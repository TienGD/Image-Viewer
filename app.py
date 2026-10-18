from fastapi import FastAPI, Request, File, UploadFile, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response, FileResponse, JSONResponse
import cv2
import numpy as np
from pathlib import Path
from collections import OrderedDict
import hashlib
import json
import shutil
from datetime import datetime
import uuid
import urllib.parse
import unicodedata
import re
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Cho phép kết nối CORS từ môi trường Visual Studio Code (Live Server, Live Preview, cổng 5500, 3000,...)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = BASE_DIR / "saved_sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# Gắn thư mục tĩnh và templates
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR /"templates")

# Cache lưu trữ ảnh gốc đã decode trong RAM (tối đa 10 ảnh gần nhất để tránh tràn RAM)
class ImageCache:
    def __init__(self, max_size=10):
        self.cache = OrderedDict()
        self.max_size = max_size

    def get(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def set(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

image_cache = ImageCache(max_size=10)

# --- ROUTE 1: HIỂN THỊ GIAO DIỆN ---
@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


# --- HÀM XỬ LÝ BIẾN ĐỔI ẢNH CHUNG (CROP, ROTATE, ZOOM) ---
def apply_transformations(img: np.ndarray, crop: int, rotate: int, zoom: int) -> np.ndarray:
    # 1. XỬ LÝ CROP (Cắt ảnh)
    # crop_value là tỷ lệ % cắt viền (từ 0% đến 30%)
    if crop > 0:
        h, w = img.shape[:2]
        crop_percent = min(max(int(crop), 0), 30) / 100.0
        pad_y = int(h * crop_percent)
        pad_x = int(w * crop_percent)
        y1, y2 = pad_y, h - pad_y
        x1, x2 = pad_x, w - pad_x
        if y2 > y1 and x2 > x1:
            img = img[y1:y2, x1:x2]

    # 2. XỬ LÝ ROTATE (Xoay ảnh)
    # rotate là góc xoay tính theo độ (từ -180 đến 180 độ)
    if rotate % 360 != 0:
        h, w = img.shape[:2]
        rad = np.deg2rad(rotate)
        cos_a = np.cos(rad)
        sin_a = np.sin(rad)
        cos_abs = np.abs(cos_a)
        sin_abs = np.abs(sin_a)
        new_w = int(np.round(h * sin_abs + w * cos_abs))
        new_h = int(np.round(h * cos_abs + w * sin_abs))
        cx = (w - 1) / 2.0
        cy = (h - 1) / 2.0
        new_cx = (new_w - 1) / 2.0
        new_cy = (new_h - 1) / 2.0
        x_lin = np.arange(new_w, dtype=np.float32) - new_cx
        y_lin = np.arange(new_h, dtype=np.float32) - new_cy
        x_src = np.round((cos_a * x_lin)[None, :] + (sin_a * y_lin)[:, None] + cx).astype(np.int32)
        y_src = np.round((-sin_a * x_lin)[None, :] + (cos_a * y_lin)[:, None] + cy).astype(np.int32)
        valid_mask = (x_src >= 0) & (x_src < w) & (y_src >= 0) & (y_src < h)
        rotated_img = np.zeros((new_h, new_w, 3), dtype=np.uint8)
        rotated_img[valid_mask] = img[y_src[valid_mask], x_src[valid_mask]]
        img = rotated_img

    # 3. XỬ LÝ ZOOM (Thu phóng ảnh)
    # zoom_value tính theo % (ví dụ 150 là x1.5 kích thước)
    if zoom != 100 and zoom > 0:
        h, w = img.shape[:2]
        scale = zoom / 100.0
        new_w = int(w * scale)
        new_h = int(h * scale)
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        if scale > 1.0:
            start_y = (new_h - h) // 2
            start_x = (new_w - w) // 2
            img = resized[start_y : start_y + h, start_x : start_x + w]
        else:
            img = np.zeros((h, w, 3), dtype=np.uint8)
            start_y = (h - new_h) // 2
            start_x = (w - new_w) // 2
            img[start_y : start_y + new_h, start_x : start_x + new_w] = resized

    return img


# --- ROUTE 2: API XỬ LÝ ẢNH PREVIEW (TỐI ƯU TỐC ĐỘ, MAX 1080PX) ---
@app.post("/api/process-image")
async def process_image(
    file: UploadFile = File(...),
    zoom: int = Form(...),
    rotate: int = Form(...),
    crop: int = Form(...)
):
    # ==========================================
    # PHÂN VÙNG 1: ĐỌC DỮ LIỆU ẢNH ĐẦU VÀO & CACHE
    # ==========================================
    image_bytes = await file.read()
    file_hash = hashlib.md5(image_bytes).hexdigest()
    
    # Kiểm tra nếu ảnh preview đã được decode trước đó trong cache
    cached_img = image_cache.get(file_hash)
    if cached_img is not None:
        img = cached_img.copy()
    else:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return Response(content="File không hợp lệ!", status_code=400)
            
        # Giới hạn kích thước preview tối đa 1080px để đảm bảo phản hồi tức thì
        max_dim = max(img.shape[:2])
        if max_dim > 1080:
            scale_factor = 1080.0 / max_dim
            new_w = int(img.shape[1] * scale_factor)
            new_h = int(img.shape[0] * scale_factor)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
            
        image_cache.set(file_hash, img)
        img = img.copy()
    
    # ==========================================
    # PHÂN VÙNG 2: ÁP DỤNG BIẾN ĐỔI (CROP -> ROTATE -> ZOOM)
    # ==========================================
    img = apply_transformations(img, crop=crop, rotate=rotate, zoom=zoom)
    
    # ==========================================
    # PHÂN VÙNG 3: TRẢ ẢNH VỀ CHO FRONTEND
    # ==========================================
    # Mã hóa ma trận ảnh (img) thành JPEG chất lượng 85 để truyền siêu tốc
    success, encoded_image = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not success:
        return Response(content="Lỗi khi xuất ảnh!", status_code=500)
    
    return Response(content=encoded_image.tobytes(), media_type="image/jpeg")


# --- ROUTE 3: API XUẤT ẢNH CHẤT LƯỢNG CAO (FULL RESOLUTION) ---
@app.post("/api/export-image")
async def export_image(
    file: UploadFile = File(...),
    zoom: int = Form(...),
    rotate: int = Form(...),
    crop: int = Form(...),
    format: str = Form("jpg")
):
    # Đọc dữ liệu ảnh gốc trực tiếp (không giảm kích thước)
    image_bytes = await file.read()
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is None:
        return Response(content="File không hợp lệ!", status_code=400)

    # Áp dụng các biến đổi trực tiếp trên ảnh gốc với đầy đủ độ phân giải
    processed_img = apply_transformations(img, crop=crop, rotate=rotate, zoom=zoom)

    # Xác định định dạng xuất và thiết lập thông số mã hóa chất lượng cao
    fmt = format.lower().strip()
    if fmt in ["jpg", "jpeg"]:
        ext = "jpg"
        media_type = "image/jpeg"
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 95]
    elif fmt == "png":
        ext = "png"
        media_type = "image/png"
        encode_params = [cv2.IMWRITE_PNG_COMPRESSION, 3]
    else:
        ext = "jpg"
        media_type = "image/jpeg"
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 95]

    success, encoded_image = cv2.imencode(f".{ext}", processed_img, encode_params)
    if not success:
        return Response(content="Lỗi khi xuất ảnh!", status_code=500)

    original_stem = Path(file.filename or "image").stem
    
    # Tạo tên file ASCII an toàn làm fallback cho các client HTTP cũ
    ascii_stem = unicodedata.normalize('NFKD', original_stem).encode('ascii', 'ignore').decode('ascii')
    ascii_stem = re.sub(r'[^a-zA-Z0-9_\-]', '_', ascii_stem).strip('_')
    if not ascii_stem:
        ascii_stem = "image"
    ascii_filename = f"{ascii_stem}_edited.{ext}"
    
    # Chuẩn RFC 5987 / RFC 6266 hỗ trợ đầy đủ Unicode (tiếng Việt có dấu)
    utf8_filename = urllib.parse.quote(f"{original_stem}_edited.{ext}")

    headers = {
        "Content-Disposition": f'attachment; filename="{ascii_filename}"; filename*=utf-8\'\'{utf8_filename}',
        "Access-Control-Expose-Headers": "Content-Disposition"
    }
    return Response(content=encoded_image.tobytes(), media_type=media_type, headers=headers)


# =======================================================
# --- ROUTE 4: CÁC API QUẢN LÝ PHIÊN LÀM VIỆC (SESSIONS) ---
# =======================================================

@app.post("/api/save-session")
async def save_session(
    file: UploadFile = File(...),
    zoom: int = Form(...),
    rotate: int = Form(...),
    crop: int = Form(...)
):
    image_bytes = await file.read()
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return JSONResponse(status_code=400, content={"error": "File không hợp lệ!"})
    
    # 1. Tạo session_id theo timestamp và chuỗi ngẫu nhiên
    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    short_id = uuid.uuid4().hex[:6]
    session_id = f"session_{timestamp_str}_{short_id}"
    
    session_path = SESSIONS_DIR / session_id
    session_path.mkdir(parents=True, exist_ok=True)
    
    # 2. Lưu file ảnh gốc nguyên bản
    original_filename = file.filename or "image.png"
    ext = Path(original_filename).suffix.lower()
    if not ext:
        ext = ".png"
    original_save_name = f"original{ext}"
    original_file_path = session_path / original_save_name
    with open(original_file_path, "wb") as f:
        f.write(image_bytes)
        
    # 3. Tạo ảnh thumbnail/preview đã xử lý theo các thông số hiện tại
    processed_img = apply_transformations(img, crop=crop, rotate=rotate, zoom=zoom)
    thumb_max = max(processed_img.shape[:2])
    thumb_scale = min(1.0, 400.0 / thumb_max) if thumb_max > 0 else 1.0
    thumb_w = int(processed_img.shape[1] * thumb_scale)
    thumb_h = int(processed_img.shape[0] * thumb_scale)
    thumb_img = cv2.resize(processed_img, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
    
    preview_file_path = session_path / "preview.jpg"
    cv2.imwrite(str(preview_file_path), thumb_img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    
    # 4. Ghi thông tin metadata vào session.json
    metadata = {
        "id": session_id,
        "filename": original_filename,
        "created_at": now.isoformat(),
        "created_at_display": now.strftime("%d/%m/%Y %H:%M:%S"),
        "zoom": zoom,
        "rotate": rotate,
        "crop": crop,
        "original_file": original_save_name,
        "preview_file": "preview.jpg"
    }
    
    with open(session_path / "session.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
        
    return JSONResponse(status_code=200, content={"status": "success", "session": metadata})


@app.get("/api/sessions")
async def get_sessions():
    sessions = []
    if SESSIONS_DIR.exists():
        for session_folder in SESSIONS_DIR.iterdir():
            if session_folder.is_dir():
                json_file = session_folder / "session.json"
                if json_file.exists():
                    try:
                        with open(json_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            sessions.append(data)
                    except Exception:
                        pass
    # Sắp xếp mới nhất lên đầu
    sessions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return JSONResponse(content={"sessions": sessions})


@app.get("/api/sessions/{session_id}/thumbnail")
async def get_session_thumbnail(session_id: str):
    if not re.match(r"^session_[a-zA-Z0-9_]+$", session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")
    preview_path = SESSIONS_DIR / session_id / "preview.jpg"
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(preview_path, media_type="image/jpeg")


@app.get("/api/sessions/{session_id}/original")
async def get_session_original(session_id: str):
    if not re.match(r"^session_[a-zA-Z0-9_]+$", session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")
    session_folder = SESSIONS_DIR / session_id
    json_file = session_folder / "session.json"
    if not json_file.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    original_file = session_folder / data.get("original_file", "original.png")
    if not original_file.exists():
        raise HTTPException(status_code=404, detail="Original file not found")
    
    ext = original_file.suffix.lower()
    media_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    media_type = media_type_map.get(ext, "application/octet-stream")
    return FileResponse(
        original_file,
        media_type=media_type,
        filename=data.get("filename", original_file.name)
    )


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    if not re.match(r"^session_[a-zA-Z0-9_]+$", session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")
    session_folder = SESSIONS_DIR / session_id
    if not session_folder.exists() or not session_folder.is_dir():
        raise HTTPException(status_code=404, detail="Session not found")
    
    shutil.rmtree(session_folder, ignore_errors=True)
    return JSONResponse(content={"status": "success", "message": f"Session {session_id} deleted"})


# ===========================================================================
# --- PHÂN VÙNG 5: ĐẾM HẠT & PHÂN ĐOẠN WATERSHED (PARTICLE COUNTING) ---
# ===========================================================================
#
# Quy trình xử lý chuẩn học thuật:
#   Grayscale → Gaussian Blur → Binarization → Morphological Opening (denoising)
#   → Distance Transform → Threshold Foreground → Watershed Segmentation
#   → Đo lường hình thái (contour analysis) → Trả kết quả ảnh + JSON
#
# Hai kỹ thuật triển khai:
#   (A) Distance Transform: chuyển ảnh nhị phân thành bản đồ khoảng cách,
#       giúp tìm tâm hạt, tách hạt dính, đánh giá hình dạng.
#   (B) Watershed: phân đoạn vùng dựa trên markers từ Distance Transform,
#       vẽ viền vi phân, trả về số liệu từng vùng tế bào/hạt.
# ===========================================================================


# ---------------------------------------------------------------------------
# HÀM TIỆN ÍCH 5A: TIỀN XỬ LÝ & BINARIZATION (PHÂN NGƯỠNG NHỊ PHÂN)
# ---------------------------------------------------------------------------
def _binarize(
    gray: np.ndarray,
    method: str,
    manual_threshold: int
) -> np.ndarray:
    """
    Chuyển ảnh xám (grayscale) thành ảnh nhị phân chuẩn Watershed:
        Vật thể = TRẮNG (255),  Nền = ĐEN (0)

    Quy trình đúng theo pipeline Watershed:
        Bước 1 — Gaussian Blur để khử nhiễu.
        Bước 2 — Phân ngưỡng nhị phân.
        Bước 3 — AUTO-CORRECT hướng sáng/tối:
            ┌─ Brightfield microscopy: vật thể TỐI trên nền SÁNG
            │     → THRESH_BINARY_INV: tối→trắng(255), sáng→đen(0)  ✓
            └─ Fluorescence microscopy: vật thể SÁNG trên nền TỐI
                  → THRESH_BINARY_INV sẽ cho kết quả ngược (nền trắng)
                  → Phát hiện bằng white_ratio > 0.70 rồi đảo ngược ✓

    Điều này đảm bảo Distance Transform luôn tính trên vật thể (trắng),
    tạo "ngọn đồi" đúng vị trí — không phải trên nền.

    Tham số:
        gray            : Ảnh xám 8-bit (H×W).
        method          : 'otsu' | 'adaptive' | 'triangle' | 'manual'
        manual_threshold: Giá trị ngưỡng (1–254), chỉ dùng khi method='manual'.

    Trả về:
        binary: Ảnh nhị phân (0/255), VẬT THỂ = TRẮNG, NỀN = ĐEN.
    """
    blurred = cv2.GaussianBlur(gray, (5, 5), sigmaX=1)

    if method == "otsu":
        # Otsu tự động tìm ngưỡng tối ưu phân tách 2 lớp histogram
        # THRESH_BINARY_INV: vật thể tối → trắng (chuẩn brightfield)
        _, binary = cv2.threshold(
            blurred, 0, 255,
            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
    elif method == "adaptive":
        # Adaptive Gaussian: xử lý ảnh có chiếu sáng không đồng đều
        # Mỗi vùng nhỏ tự tính ngưỡng riêng → tốt cho tiêu bản không đồng nhất
        binary = cv2.adaptiveThreshold(
            blurred, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 11, 2
        )
    elif method == "triangle":
        # Triangle: tốt cho ảnh có histogram lệch (skewed)
        # Ví dụ: ảnh với nhiều nền và ít vật thể nhỏ
        _, binary = cv2.threshold(
            blurred, 0, 255,
            cv2.THRESH_BINARY_INV + cv2.THRESH_TRIANGLE
        )
    else:  # "manual"
        thresh_val = max(1, min(254, int(manual_threshold)))
        _, binary = cv2.threshold(
            blurred, thresh_val, 255,
            cv2.THRESH_BINARY_INV
        )

    # -----------------------------------------------------------------------
    # AUTO-CORRECT: Đảm bảo VẬT THỂ = TRẮNG, NỀN = ĐEN
    # -----------------------------------------------------------------------
    # Lý do cần bước này:
    #   - Ảnh fluorescence (vật thể sáng, nền tối): THRESH_BINARY_INV
    #     sẽ tạo ra ảnh mà NỀN = trắng, VẬT THỂ = đen → sai!
    #   - Distance Transform tính khoảng cách từ pixel TRẮNG tới nền ĐEN.
    #     Nếu nền là trắng → "ngọn đồi" xuất hiện trên nền, không phải hạt.
    # Heuristic: nếu > 70% pixel là trắng → nền đang là trắng → đảo lại.
    white_ratio = cv2.countNonZero(binary) / float(binary.size)
    if white_ratio > 0.70:
        binary = cv2.bitwise_not(binary)

    return binary


# ---------------------------------------------------------------------------
# HÀM TIỆN ÍCH 5B: LÀM SẠCH NHỊ PHÂN (MORPHOLOGICAL OPENING)
# ---------------------------------------------------------------------------
def _morphological_clean(binary: np.ndarray) -> np.ndarray:
    """
    Áp dụng Morphological Opening để loại bỏ nhiễu nhỏ và cặn mẫu.
    Opening = Erosion → Dilation (giữ lại cấu trúc lớn, xóa chấm nhỏ).
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    opening = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=2)
    return opening


# ---------------------------------------------------------------------------
# HÀM TIỆN ÍCH 5C: DISTANCE TRANSFORM & TÌM VÙNG FOREGROUND CHẮC CHẮN
# ---------------------------------------------------------------------------
def _distance_transform(
    cleaned_binary: np.ndarray,
    distance_factor: float
):
    """
    Thực hiện Distance Transform rồi ngưỡng hóa để tìm:
      - dist_map : Bản đồ khoảng cách chuẩn hóa (float32, 0.0→1.0).
                   Mỗi pixel sáng = khoảng cách tới nền gần nhất.
      - sure_fg  : Vùng chắc chắn là foreground (tâm hạt) sau threshold.
      - sure_bg  : Vùng chắc chắn là background (dilated binary).
      - unknown  : Vùng không chắc → nơi Watershed sẽ phân tách.

    Tham số:
        cleaned_binary : Ảnh nhị phân sạch (0/255).
        distance_factor: Hệ số ngưỡng (0.1→0.9). Càng cao → càng ít tâm
                         → phân đoạn chặt hơn nhưng dễ bỏ sót hạt nhỏ.
    """
    # Distance Transform: DIST_L2 = khoảng cách Euclidean
    dist_map_raw = cv2.distanceTransform(cleaned_binary, cv2.DIST_L2, 5)

    # Chuẩn hóa về [0, 1] để hiển thị và so sánh
    dist_max = dist_map_raw.max()
    if dist_max > 0:
        dist_map = dist_map_raw / dist_max
    else:
        dist_map = dist_map_raw.copy()

    # Threshold foreground bằng distance_factor × giá trị cực đại
    _, sure_fg = cv2.threshold(
        dist_map_raw,
        distance_factor * dist_max,
        255, cv2.THRESH_BINARY
    )
    sure_fg = np.uint8(sure_fg)

    # Dilate binary để lấy vùng background chắc chắn
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    sure_bg = cv2.dilate(cleaned_binary, kernel, iterations=3)

    # Vùng không chắc = background - foreground
    unknown = cv2.subtract(sure_bg, sure_fg)

    return dist_map, sure_fg, sure_bg, unknown


# ---------------------------------------------------------------------------
# HÀM TIỆN ÍCH 5D: WATERSHED SEGMENTATION & TẠO MARKERS
# ---------------------------------------------------------------------------
def _watershed_segment(
    img_bgr: np.ndarray,
    sure_fg: np.ndarray,
    unknown: np.ndarray
):
    """
    Gán markers và chạy Watershed algorithm.

    Tham số:
        img_bgr : Ảnh màu BGR (input cho cv2.watershed).
        sure_fg : Vùng foreground chắc chắn (uint8).
        unknown : Vùng không xác định (uint8).

    Trả về:
        markers   : Ma trận int32 chứa nhãn phân đoạn
                    (0=unknown, -1=boundary, 1=background, >1=region).
        num_labels: Số nhãn từ connectedComponents (bao gồm background).
    """
    # Connected Components trên sure_fg → gán nhãn ban đầu
    num_labels, markers = cv2.connectedComponents(sure_fg)

    # Tăng tất cả labels lên 1 để background=0 thành background=1
    markers = markers + 1

    # Đặt vùng unknown = 0 (Watershed sẽ quyết định)
    markers[unknown == 255] = 0

    # Watershed: điền vào vùng 0, tạo boundary = -1
    markers = cv2.watershed(img_bgr, markers)

    return markers, num_labels


# ---------------------------------------------------------------------------
# HÀM TIỆN ÍCH 5E: ĐO LƯỜNG HÌNH THÁI TỪNG VÙNG (PARTICLE MEASUREMENTS)
# ---------------------------------------------------------------------------
def _measure_particles(
    markers: np.ndarray,
    min_area: int
) -> list:
    """
    Trích xuất số liệu hình thái học từ từng vùng phân đoạn:
      - Diện tích (area_px)
      - Chu vi (perimeter_px) — dùng contour
      - Tọa độ tâm (cx, cy) — moments
      - Đường kính tương đương (equiv_diameter_px) = 2 × sqrt(area/π)
      - Độ tròn (circularity) = 4π × area / perimeter²  (=1 với hình tròn hoàn hảo)

    Tham số:
        markers  : Ma trận nhãn Watershed (int32).
        min_area : Lọc bỏ các vùng < min_area px² (nhiễu, cặn mẫu).
    """
    particles = []
    unique_labels = np.unique(markers)

    # Label 0 = unknown, -1 = boundary, 1 = background → bỏ qua
    valid_labels = [lb for lb in unique_labels if lb > 1]

    for label in valid_labels:
        mask = np.zeros(markers.shape, dtype=np.uint8)
        mask[markers == label] = 255

        area = int(cv2.countNonZero(mask))
        if area < min_area:
            continue

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        cnt = max(contours, key=cv2.contourArea)

        perimeter = float(cv2.arcLength(cnt, closed=True))

        M = cv2.moments(mask)
        if M["m00"] > 0:
            cx = round(M["m10"] / M["m00"], 1)
            cy = round(M["m01"] / M["m00"], 1)
        else:
            x, y, w, h = cv2.boundingRect(cnt)
            cx = round(x + w / 2.0, 1)
            cy = round(y + h / 2.0, 1)

        equiv_diameter = round(2 * np.sqrt(area / np.pi), 2)

        if perimeter > 0:
            circularity = round(4 * np.pi * area / (perimeter ** 2), 4)
        else:
            circularity = 0.0

        particles.append({
            "id"                : int(label - 1),  # ID tạm thời (sẽ gán lại sau khi sort)
            "ws_label"          : int(label),       # ← Label gốc từ Watershed, dùng để map màu
            "cx"                : cx,
            "cy"                : cy,
            "area_px"           : area,
            "perimeter_px"      : round(perimeter, 2),
            "equiv_diameter_px" : equiv_diameter,
            "circularity"       : circularity,
        })

    # Sắp xếp theo diện tích giảm dần rồi gán lại ID từ 1
    particles.sort(key=lambda p: p["area_px"], reverse=True)
    for i, p in enumerate(particles):
        p["id"] = i + 1

    return particles


# ---------------------------------------------------------------------------
# HÀM TIỆN ÍCH 5F: VẼ KẾT QUẢ LÊN ẢNH MÀU
# ---------------------------------------------------------------------------
def _draw_results(
    img_bgr: np.ndarray,
    markers: np.ndarray,
    particles: list,
    show_boundary: bool,
    show_centroid: bool,
    show_id: bool,
    color_map: bool,
) -> np.ndarray:
    """
    Vẽ đường viền Watershed, tâm hạt, mã số, màu sắc lên bản sao ảnh gốc.

    Quy ước màu kết quả:
        - Đường viền Watershed (boundary): màu đỏ-cam [0, 80, 255] (BGR)
          → Đây là đường cắt chính xác giữa các vật thể dính nhau
        - Tâm hạt (centroid): chấm xanh lá
        - #ID: số trắng có bóng đen

    Lưu ý kỹ thuật:
        Phải dùng p["ws_label"] (label gốc từ Watershed / connectedComponents)
        để tra cứu đúng vùng trong ma trận markers.
        KHÔNG dùng (i + 2) vì particles đã được sort lại theo diện tích
        → thứ tự index i không còn tương ứng với label trong markers nữa.
    """
    output = img_bgr.copy()

    rng = np.random.default_rng(seed=42)
    # Tạo bảng màu ngẫu nhiên ổn định: seed cố định → màu không đổi mỗi lần gọi
    max_label = max((p["ws_label"] for p in particles), default=2) + 2
    colors = rng.integers(60, 220, size=(max_label, 3)).tolist()

    # --- (1) TÔ MÀU TỪNG VÙNG HẠT ---
    # Dùng p["ws_label"] để tra đúng vùng trong ma trận markers
    if color_map:
        for p in particles:
            ws_lbl = p["ws_label"]
            mask_color = markers == ws_lbl
            if not mask_color.any():
                continue
            color_bgr = np.array(colors[ws_lbl % len(colors)], dtype=np.float64)
            output[mask_color] = (
                output[mask_color].astype(np.float64) * 0.45 + color_bgr * 0.55
            ).clip(0, 255).astype(np.uint8)

    # --- (2) VẼ ĐƯỜNG VIỀN WATERSHED (markers == -1) ---
    # Đây là điểm mấu chốt: đường viền = nơi "nước" từ hai lõi gặp nhau
    # → Tách chính xác hai hạt dính nhau
    if show_boundary:
        boundary_mask = markers == -1
        output[boundary_mask] = [0, 80, 255]   # Màu đỏ-cam nổi bật (BGR)

    # --- (3) VẼ TÂM HẠT VÀ #ID ---
    font = cv2.FONT_HERSHEY_SIMPLEX
    for p in particles:
        cx_int = int(round(p["cx"]))
        cy_int = int(round(p["cy"]))

        if show_centroid:
            cv2.circle(output, (cx_int, cy_int), 3, (0, 255, 180), -1)    # Chấm đặc xanh lá
            cv2.circle(output, (cx_int, cy_int), 5, (0, 140, 100), 1)     # Vòng viền đậm hơn

        if show_id:
            label_text = str(p["id"])
            font_scale = 0.38
            thickness  = 1
            text_size  = cv2.getTextSize(label_text, font, font_scale, thickness)[0]
            tx = cx_int - text_size[0] // 2
            ty = cy_int + text_size[1] // 2
            # Bóng chữ đen để dễ đọc trên mọi màu nền
            cv2.putText(output, label_text, (tx + 1, ty + 1),
                        font, font_scale, (0, 0, 0), thickness + 1, cv2.LINE_AA)
            cv2.putText(output, label_text, (tx, ty),
                        font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)

    return output


# ---------------------------------------------------------------------------
# HÀM TIỆN ÍCH 5G: RENDER ẢNH DISTANCE TRANSFORM ĐỂ HIỂN THỊ
# ---------------------------------------------------------------------------
def _render_distance_map(dist_map: np.ndarray) -> np.ndarray:
    """
    Chuyển bản đồ khoảng cách (float32, 0→1) thành ảnh màu JET để hiển thị.
    Màu NÓNG (đỏ/vàng) = xa nền nhất = tâm hạt.
    Màu LẠNH (xanh đậm) = gần nền nhất = rìa hạt.
    """
    dist_8u = (dist_map * 255).astype(np.uint8)
    dist_color = cv2.applyColorMap(dist_8u, cv2.COLORMAP_JET)
    return dist_color


# ---------------------------------------------------------------------------
# ROUTE 5A: API CHÍNH — PHÂN TÍCH WATERSHED + DISTANCE TRANSFORM
# ---------------------------------------------------------------------------
@app.post("/api/particle-count")
async def particle_count(
    file: UploadFile = File(...),
    method: str = Form("otsu"),
    threshold: int = Form(128),
    distance_factor: float = Form(0.45),
    min_area: int = Form(20),
    show_boundary: bool = Form(True),
    show_centroid: bool = Form(True),
    show_id: bool = Form(True),
    color_map: bool = Form(False),
):
    """
    API phân tích đếm hạt / tế bào theo quy trình Watershed + Distance Transform.

    Endpoint: POST /api/particle-count

    Form fields:
        file            : File ảnh (multipart/form-data).
        method          : Phương pháp binarization ('otsu','adaptive','triangle','manual').
        threshold       : Ngưỡng thủ công khi method='manual' (1–254).
        distance_factor : Hệ số threshold trên Distance Transform (0.1–0.9).
        min_area        : Diện tích tối thiểu (px²) để tính là hạt hợp lệ.
        show_boundary   : Có vẽ viền Watershed lên ảnh không (bool).
        show_centroid   : Có đánh dấu tâm hạt không (bool).
        show_id         : Có ghi số thứ tự #ID lên hạt không (bool).
        color_map       : Có tô màu từng vùng hạt không (bool).

    Response (JSON):
        {
          "status"           : "success",
          "total_count"      : <int>,
          "avg_area"         : <float>,
          "coverage_pct"     : <float>,
          "avg_circularity"  : <float>,
          "result_image_b64" : <str>,   -- Ảnh Watershed (base64 JPEG)
          "dist_image_b64"   : <str>,   -- Ảnh Distance Transform (base64 JPEG)
          "particles"        : [ {...} ]
        }
    """
    import base64

    # =========================================================
    # PHÂN VÙNG 5-I: ĐỌC & DECODE ẢNH ĐẦU VÀO
    # =========================================================
    


    # =========================================================
    # PHÂN VÙNG 5-II: TIỀN XỬ LÝ — GRAYSCALE & BINARIZATION
    # =========================================================
   

    # =========================================================
    # PHÂN VÙNG 5-III: DISTANCE TRANSFORM
    # =========================================================
   

    # =========================================================
    # PHÂN VÙNG 5-IV: WATERSHED SEGMENTATION
    # =========================================================
   
    # =========================================================
    # PHÂN VÙNG 5-V: ĐO LƯỜNG HÌNH THÁI TỪNG HẠT
    # =========================================================
   

    # =========================================================
    # PHÂN VÙNG 5-VI: VẼ KẾT QUẢ LÊN ẢNH
    # =========================================================
    

    # =========================================================
    # PHÂN VÙNG 5-VII: MÃ HÓA ẢNH THÀNH BASE64 ĐỂ TRẢ VỀ JSON
    # =========================================================
    _, result_encoded = cv2.imencode(".jpg", result_img,  [cv2.IMWRITE_JPEG_QUALITY, 88])
    _, dist_encoded   = cv2.imencode(".jpg", dist_img_colored, [cv2.IMWRITE_JPEG_QUALITY, 85])

    result_b64 = base64.b64encode(result_encoded.tobytes()).decode("utf-8")
    dist_b64   = base64.b64encode(dist_encoded.tobytes()).decode("utf-8")

    # =========================================================
    # PHÂN VÙNG 5-VIII: TÍNH TOÁN CÁC CHỈ SỐ TỔNG HỢP
    # =========================================================
    total_count = len(particles)

    if total_count > 0:
        avg_area        = round(sum(p["area_px"]      for p in particles) / total_count, 2)
        total_area      = sum(p["area_px"] for p in particles)
        coverage_pct    = round(total_area / total_pixels * 100, 2)
        avg_circularity = round(sum(p["circularity"]  for p in particles) / total_count, 4)
    else:
        avg_area        = 0.0
        coverage_pct    = 0.0
        avg_circularity = 0.0

    # Loại bỏ trường nội bộ ws_label trước khi trả về JSON
    # (ws_label chỉ dùng nội bộ trong _draw_results, không cần thiết ở frontend)
    particles_json = [
        {k: v for k, v in p.items() if k != "ws_label"}
        for p in particles
    ]

    return JSONResponse(content={
        "status"           : "success",
        "total_count"      : total_count,
        "avg_area"         : avg_area,
        "coverage_pct"     : coverage_pct,
        "avg_circularity"  : avg_circularity,
        "result_image_b64" : result_b64,
        "dist_image_b64"   : dist_b64,
        "particles"        : particles_json,
    })


# ---------------------------------------------------------------------------
# ROUTE 5B: XUẤT CSV DỮ LIỆU ĐO LƯỜNG (PARTICLE MEASUREMENTS EXPORT)
# ---------------------------------------------------------------------------
@app.post("/api/particle-export-csv")
async def particle_export_csv(
    file: UploadFile = File(...),
    method: str = Form("otsu"),
    threshold: int = Form(128),
    distance_factor: float = Form(0.45),
    min_area: int = Form(20),
):
    """
    Chạy lại toàn bộ quy trình phân tích rồi xuất bảng số liệu dạng CSV.

    Endpoint: POST /api/particle-export-csv
    Response: file CSV (text/csv) với các cột:
        #ID, Tam_X, Tam_Y, Dien_tich_px2, Chu_vi_px, Duong_kinh_px, Do_tron
    """
    import io, csv

    image_bytes = await file.read()
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise HTTPException(status_code=400, detail="File ảnh không hợp lệ.")

    max_dim = max(img_bgr.shape[:2])
    if max_dim > 1200:
        scale = 1200.0 / max_dim
        img_bgr = cv2.resize(img_bgr,
                             (int(img_bgr.shape[1] * scale), int(img_bgr.shape[0] * scale)),
                             interpolation=cv2.INTER_AREA)

    gray    = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    binary  = _binarize(gray, method=method, manual_threshold=threshold)
    cleaned = _morphological_clean(binary)
    _, sure_fg, _, unknown = _distance_transform(cleaned, distance_factor=distance_factor)
    markers, _             = _watershed_segment(img_bgr.copy(), sure_fg, unknown)
    particles              = _measure_particles(markers, min_area=min_area)

    output_csv = io.StringIO()
    writer = csv.writer(output_csv)
    writer.writerow(["#ID", "Tam_X(px)", "Tam_Y(px)",
                     "Dien_tich(px2)", "Chu_vi(px)",
                     "Duong_kinh_tuong_duong(px)", "Do_tron(0-1)"])
    for p in particles:
        writer.writerow([
            p["id"], p["cx"], p["cy"],
            p["area_px"], p["perimeter_px"],
            p["equiv_diameter_px"], p["circularity"]
        ])

    csv_bytes = output_csv.getvalue().encode("utf-8-sig")   # BOM cho Excel tiếng Việt
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=\"particle_measurements.csv\""
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
