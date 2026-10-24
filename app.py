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
import base64
import csv
import io
import time
from array import array
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

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
# HÀM TIỆN ÍCH 5.0: GIẢI MÃ & CHUẨN HÓA KÍCH THƯỚC ẢNH ĐẦU VÀO
# ---------------------------------------------------------------------------
def _decode_image_bytes(
    image_bytes: bytes,
    max_dim: int = 1600
) -> np.ndarray:
    """
    Giải mã bytes ảnh thành ma trận BGR và giới hạn cạnh dài.

    Việc giới hạn kích thước giúp:
      - Distance Transform + Watershed chạy ổn định trên ảnh lớn.
      - Base64 trả về không quá nặng, giao diện phản hồi nhanh.
      - Giữ nguyên tỷ lệ khung hình (resize bằng INTER_AREA).
    """
    if not image_bytes:
        raise ValueError("File ảnh rỗng. Vui lòng chọn ảnh khác.")

    nparr = np.frombuffer(image_bytes, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise ValueError("File ảnh không hợp lệ hoặc định dạng chưa được hỗ trợ.")

    h, w = img_bgr.shape[:2]
    long_side = max(h, w)
    if max_dim and long_side > max_dim:
        scale = float(max_dim) / float(long_side)
        new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
        img_bgr = cv2.resize(img_bgr, new_size, interpolation=cv2.INTER_AREA)

    return np.ascontiguousarray(img_bgr)


def _to_grayscale(img_bgr: np.ndarray) -> np.ndarray:
    """
    Chuyển BGR → grayscale bằng công thức BT.601, cài đặt trực tiếp
    bằng NumPy (không gọi cv2.cvtColor).

        Y = 0.114·B + 0.587·G + 0.299·R
    """
    b = img_bgr[:, :, 0].astype(np.float32, copy=False)
    g = img_bgr[:, :, 1].astype(np.float32, copy=False)
    r = img_bgr[:, :, 2].astype(np.float32, copy=False)
    return np.clip(
        0.114 * b + 0.587 * g + 0.299 * r, 0.0, 255.0
    ).astype(np.uint8)


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
    method = (method or "otsu").strip().lower()
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
    white_ratio = float(np.count_nonzero(binary)) / float(binary.size)
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


# ===========================================================================
# 5C-1 — EUCLIDEAN DISTANCE TRANSFORM (TỰ CÀI ĐẶT TỪ ĐẦU)
# ===========================================================================
#
# Mục tiêu: với mỗi pixel foreground, tính khoảng cách Euclid tới pixel
# background gần nhất. Công thức:
#
#       D(x, y) = min_{b ∈ Background} sqrt((x - bx)² + (y - by)²)
#
# Không dùng cv2.distanceTransform. Thuật toán dưới đây dựa trên ý tưởng
# "distance transform of sampled functions" của Felzenszwalb & Huttenlocher:
# một phép EDT 2-D được tách thành hai phép EDT 1-D liên tiếp (separable).
# ===========================================================================


def _edt_1d_squared(f: np.ndarray) -> np.ndarray:
    """
    EDT 1-D chính xác trên miền bình phương khoảng cách.

    Bài toán:
        d(q) = min_p ( (q - p)² + f(p) )

    Mỗi vị trí p được xem như một parabol:
        y(q) = (q - p)² + f(p)

    Đường bao dưới (lower envelope) của tất cả parabol chính là d(q).
    Thuật toán duy trì:
        v[k] — vị trí parabol đại diện trên envelope
        z[k] — hoành độ giao điểm giữa parabol k-1 và parabol k

    Mỗi parabol được đưa vào / loại khỏi envelope tối đa một lần,
    nên độ phức tạp là O(n) thay vì O(n²) nếu duyệt mọi cặp (p, q).

    Tham số:
        f : mảng 1-D float, chi phí tại mỗi vị trí.

    Trả về:
        d : mảng 1-D float, giá trị bình phương khoảng cách nhỏ nhất.
    """
    n = int(f.size)
    if n == 0:
        return np.empty(0, dtype=np.float64)

    d = np.empty(n, dtype=np.float64)
    fl = f.astype(np.float64, copy=False).tolist()
    v = [0] * n
    z = [0.0] * (n + 1)

    k = 0
    v[0] = 0
    z[0] = -np.inf
    z[1] = np.inf

    for q in range(1, n):
        fq = fl[q]
        q2 = q * q

        # Hoành độ giao điểm giữa parabol mới (q) và parabol v[k].
        s = (
            (fq + q2) - (fl[v[k]] + v[k] * v[k])
        ) / (2.0 * q - 2.0 * v[k])

        # Nếu giao điểm nằm bên trái giao điểm cuối cùng thì parabol v[k]
        # không còn nằm trên envelope → loại nó ra.
        while s <= z[k]:
            k -= 1
            s = (
                (fq + q2) - (fl[v[k]] + v[k] * v[k])
            ) / (2.0 * q - 2.0 * v[k])

        k += 1
        v[k] = q
        z[k] = s
        z[k + 1] = np.inf

    # Truy vấn envelope tại từng q.
    k = 0
    for q in range(n):
        while z[k + 1] < q:
            k += 1
        dq = q - v[k]
        d[q] = dq * dq + fl[v[k]]

    return d


def _euclidean_distance_transform(mask: np.ndarray) -> np.ndarray:
    """
    EDT 2-D chính xác bằng phương pháp separable (tự cài đặt).

    Quy trình:
        1. Chọn hướng: đặt số cột <= số hàng để vòng lặp Python ở pass 2
           có ít lần lặp nhất.
        2. Pass ngang (vectorized):
           Với mỗi hàng, tìm khoảng cách bình phương tới background gần
           nhất bằng hai lượt quét:
               - maximum.accumulate cho vị trí background bên trái
               - minimum.accumulate cho vị trí background bên phải
           Không cần vòng lặp Python cho từng pixel.
        3. Pass dọc:
           Mỗi cột là một bài toán EDT 1-D tổng quát, giải bằng
           lower-envelope parabol ở _edt_1d_squared.
        4. Lấy căn bậc hai, gán background = 0.

    Kết quả là khoảng cách Euclid chính xác (sai số chỉ do làm tròn
    float), khác với cv2.distanceTransform(DIST_L2, mask=5) vốn dùng
    xấp xỉ 5×5.

    Tham số:
        mask : mảng bool H×W, True = foreground.

    Trả về:
        dist : float32 H×W, khoảng cách tới background gần nhất.
    """
    fg = np.asarray(mask, dtype=bool)
    if fg.ndim != 2:
        raise ValueError("mask phải là mảng 2 chiều.")

    # Không có foreground, hoặc foreground phủ kín ảnh → không có biên nền.
    if fg.size == 0 or not fg.any() or not (~fg).any():
        return np.zeros(fg.shape, dtype=np.float32)

    transposed = fg.shape[1] > fg.shape[0]
    work = fg.T if transposed else fg
    _h, w = work.shape
    inf = 1.0e20

    # ------------------------------------------------------------------
    # PASS 1 — khoảng cách ngang tới background gần nhất trên từng hàng
    # ------------------------------------------------------------------
    idx = np.arange(w, dtype=np.float64)
    is_bg = ~work

    # Vị trí background gần nhất bên trái (hoặc -1 nếu không có).
    left = np.maximum.accumulate(
        np.where(is_bg, idx, -1.0), axis=1
    )
    # Vị trí background gần nhất bên phải (hoặc w nếu không có).
    right = np.minimum.accumulate(
        np.where(is_bg, idx, float(w))[:, ::-1], axis=1
    )[:, ::-1]

    d_left = np.where(left >= 0.0, idx - left, inf)
    d_right = np.where(right < w, right - idx, inf)
    row_sq = np.minimum(d_left, d_right) ** 2

    # ------------------------------------------------------------------
    # PASS 2 — lower envelope dọc cho từng cột
    # ------------------------------------------------------------------
    col_sq = np.empty_like(row_sq)
    for x in range(w):
        col_sq[:, x] = _edt_1d_squared(row_sq[:, x])

    dist = np.sqrt(col_sq)
    if transposed:
        dist = dist.T

    # Background không có ý nghĩa khoảng cách → trả về 0.
    dist[~fg] = 0.0
    return dist.astype(np.float32, copy=False)


def _dilate_cross(mask: np.ndarray, iterations: int = 1) -> np.ndarray:
    """
    Phép giãn nhị phân với phần tử cấu trúc chữ thập 3×3 (tự cài đặt).

    Kernel tương đương cv2.getStructuringElement(MORPH_ELLIPSE, (3, 3)):
        [[0, 1, 0],
         [1, 1, 1],
         [0, 1, 0]]

    Mỗi vòng lặp mở rộng vùng foreground thêm 1 pixel theo 4 hướng.
    Lặp `iterations` lần → bán kính Manhattan = iterations.

    Tham số:
        mask       : mảng bool H×W.
        iterations : số lần giãn.

    Trả về:
        mảng bool H×W sau khi giãn.
    """
    out = np.asarray(mask, dtype=bool).copy()
    for _ in range(max(0, int(iterations))):
        prev = out
        out = prev.copy()
        out[1:, :] |= prev[:-1, :]
        out[:-1, :] |= prev[1:, :]
        out[:, 1:] |= prev[:, :-1]
        out[:, :-1] |= prev[:, 1:]
    return out


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

    Ghi chú thuật toán:
        - EDT được cài đặt từ đầu bằng phương pháp separable
          (xem _euclidean_distance_transform), không dùng
          cv2.distanceTransform.
        - Phép giãn sure_bg dùng _dilate_cross (NumPy), không dùng
          cv2.dilate.
        - Các phép trừ / ngưỡng đều vectorized bằng NumPy.
    """
    foreground = cleaned_binary > 0

    # ------------------------------------------------------------------
    # (1) EDT chính xác: khoảng cách Euclid từ mỗi pixel vật thể tới nền.
    # ------------------------------------------------------------------
    dist_raw = _euclidean_distance_transform(foreground)

    # Chuẩn hóa về [0, 1] để hiển thị và so sánh.
    dist_max = float(dist_raw.max()) if dist_raw.size else 0.0
    if dist_max > 0:
        dist_map = (dist_raw / dist_max).astype(np.float32, copy=False)
    else:
        dist_map = dist_raw.copy()

    # ------------------------------------------------------------------
    # (2) Ngưỡng tâm hạt: giữ pixel có khoảng cách > factor × max.
    #     Đây là các "hạt giống" (seeds) cho Watershed.
    # ------------------------------------------------------------------
    distance_factor = float(np.clip(distance_factor, 0.05, 0.95))
    if dist_max > 0:
        sure_fg = np.where(
            dist_raw > (distance_factor * dist_max), 255, 0
        ).astype(np.uint8)
    else:
        sure_fg = np.zeros_like(cleaned_binary, dtype=np.uint8)

    # ------------------------------------------------------------------
    # (3) Background chắc chắn = giãn vật thể 3 pixel theo hình chữ thập.
    # ------------------------------------------------------------------
    sure_bg = (
        _dilate_cross(foreground, iterations=3).astype(np.uint8) * 255
    )

    # ------------------------------------------------------------------
    # (4) Unknown = sure_bg \ sure_fg — vùng Watershed sẽ phân xử.
    # ------------------------------------------------------------------
    unknown = ((sure_bg > 0) & (sure_fg == 0)).astype(np.uint8) * 255

    return dist_map, sure_fg, sure_bg, unknown


# ===========================================================================
# 5D-1 — CONNECTED COMPONENTS LABELING (TỰ CÀI ĐẶT)
# ===========================================================================
def _connected_components_rle(mask: np.ndarray):
    """
    Gán nhãn thành phần liên thông 8-hướng bằng Run-Length Encoding
    (RLE) + Union-Find, tự cài đặt — không dùng cv2.connectedComponents.

    Ý tưởng:
        1. Mỗi hàng ảnh được nén thành các "run" [start, end) gồm các
           pixel foreground liên tiếp.
        2. Hai run ở hai hàng kề nhau được nối nếu chúng giao nhau hoặc
           chạm chéo (8-liên thông).
        3. Union-Find gộp nhãn tạm của các run thuộc cùng thành phần.
        4. Đổi root của Union-Find thành nhãn tuần tự 1..N và tô lại ảnh.

    Vì số run thường nhỏ hơn rất nhiều so với số pixel, thuật toán nhanh
    và ít tốn bộ nhớ hơn BFS từng pixel.

    Tham số:
        mask : mảng bool H×W (True = foreground).

    Trả về:
        (num_components, labels)
        - num_components : số thành phần (không tính nền).
        - labels         : int32 H×W; 0 = nền, 1..N = thành phần.
    """
    fg = np.asarray(mask, dtype=bool)
    if fg.ndim != 2:
        raise ValueError("mask phải là mảng 2 chiều.")

    h, w = fg.shape
    parent = []

    def find(x: int) -> int:
        """Tìm root với path compression (lặp, tránh đệ quy sâu)."""
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        """Gộp hai tập; root nhỏ hơn làm root để kết quả ổn định."""
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if ra < rb:
            parent[rb] = ra
        else:
            parent[ra] = rb

    rows = []
    prev_runs = []

    for y in range(h):
        row = fg[y]

        # Tìm các run [start, end) bằng đạo hàm trên hàng đã padding 0.
        padded = np.empty(w + 2, dtype=np.int8)
        padded[0] = 0
        padded[-1] = 0
        padded[1:-1] = row
        diff = np.diff(padded)
        starts = np.flatnonzero(diff == 1).tolist()
        ends = np.flatnonzero(diff == -1).tolist()

        runs = []
        j = 0
        prev_n = len(prev_runs)

        for s, e in zip(starts, ends):
            label = len(parent)
            parent.append(label)

            # Bỏ các run hàng trước nằm hoàn toàn bên trái.
            # Điều kiện < s (không phải <= s) giữ lại trường hợp chạm chéo
            # 8-liên thông: prev kết thúc tại s-1 và run mới bắt đầu tại s.
            while j < prev_n and prev_runs[j][1] < s:
                j += 1

            # Nối với mọi run hàng trước còn giao / chạm run hiện tại.
            # Với 8-liên thông, run trước được phép bắt đầu đúng tại e
            # (pixel cuối của run hiện tại và pixel đầu của run trước
            # nằm chéo nhau) → dùng <= e, không phải < e.
            k = j
            while k < prev_n and prev_runs[k][0] <= e:
                union(label, prev_runs[k][2])
                k += 1

            runs.append((s, e, label))

        rows.append(runs)
        prev_runs = runs

    if not parent:
        return 0, np.zeros((h, w), dtype=np.int32)

    # Nén root → nhãn 1..N theo thứ tự quét.
    root_to_label = {}
    labels = np.zeros((h, w), dtype=np.int32)

    for y, runs in enumerate(rows):
        for s, e, label in runs:
            root = find(label)
            out_label = root_to_label.get(root)
            if out_label is None:
                out_label = len(root_to_label) + 1
                root_to_label[root] = out_label
            labels[y, s:e] = out_label

    return len(root_to_label), labels


# ===========================================================================
# 5D-2 — GRADIENT MAGNITUDE (SOBEL TỰ CÀI ĐẶT)
# ===========================================================================
def _sobel_gradient_magnitude(gray: np.ndarray) -> np.ndarray:
    """
    Tính gradient magnitude bằng Sobel 3×3, cài đặt trực tiếp bằng NumPy.

    Quy trình:
        1. Làm mượt Gaussian 3×3 với kernel 1-2-1 (separable):
               [1 2 1]
               [2 4 2] / 16
               [1 2 1]
        2. Tích chập với Sobel X và Sobel Y:
               Gx = [[-1, 0, 1],      Gy = [[-1, -2, -1],
                     [-2, 0, 2],            [ 0,  0,  0],
                     [-1, 0, 1]]             [ 1,  2,  1]]
        3. |G| = sqrt(Gx² + Gy²), chuẩn hóa về 0..255.

    Gradient càng lớn = cạnh càng mạnh. Watershed sẽ ưu tiên mở rộng
    vào vùng gradient nhỏ (vùng phẳng) trước.

    Tham số:
        gray : ảnh xám uint8 H×W.

    Trả về:
        gradient : uint8 H×W, 0..255.
    """
    g = gray.astype(np.float32, copy=False)
    p = np.pad(g, 1, mode="edge")

    # Gaussian 3×3 (1-2-1) — viết tường minh để thấy rõ kernel.
    smooth = (
        p[:-2, :-2] + 2.0 * p[:-2, 1:-1] + p[:-2, 2:]
        + 2.0 * p[1:-1, :-2] + 4.0 * p[1:-1, 1:-1] + 2.0 * p[1:-1, 2:]
        + p[2:, :-2] + 2.0 * p[2:, 1:-1] + p[2:, 2:]
    ) / 16.0

    q = np.pad(smooth, 1, mode="edge")

    gx = (
        q[:-2, 2:] + 2.0 * q[1:-1, 2:] + q[2:, 2:]
        - q[:-2, :-2] - 2.0 * q[1:-1, :-2] - q[2:, :-2]
    )
    gy = (
        q[2:, :-2] + 2.0 * q[2:, 1:-1] + q[2:, 2:]
        - q[:-2, :-2] - 2.0 * q[:-2, 1:-1] - q[:-2, 2:]
    )

    # Sobel có tổng trọng số 4 theo mỗi trục → chia 4 để về thang 0..255.
    magnitude = np.hypot(gx, gy) * 0.25
    return np.clip(magnitude, 0.0, 255.0).astype(np.uint8)


# ===========================================================================
# 5D-3 — MARKER-BASED WATERSHED (MEYER FLOODING TỰ CÀI ĐẶT)
# ===========================================================================
def _watershed_flood(
    gradient: np.ndarray,
    markers: np.ndarray
) -> np.ndarray:
    """
    Marker-based Watershed theo thuật toán flooding của Meyer, tự cài đặt.

    Nguyên lý:
        - Mỗi marker (label > 0) là một "hồ" đã có nước.
        - Pixel unknown (label = 0) được đưa vào hàng đợi ưu tiên theo
          gradient magnitude.
        - Luôn xử lý pixel có gradient nhỏ nhất trước: nước lan qua
          vùng phẳng trước, chậm lại ở cạnh mạnh.
        - Khi hai nhãn khác nhau gặp nhau, tạo đường phân thủy.

    Hàng đợi phân cấp (hierarchical queue):
        - Gradient được lượng tử hóa thành 256 mức 0..255.
        - buckets[level] là một array('i') chứa flat-index của pixel.
        - heads[level] là con trỏ đọc đầu hàng.
        - Mỗi pixel được enqueue đúng một lần → tổng chi phí queue O(N),
          không có log(N) như heapq.
        - Nếu trong lúc xử lý mức `current` phát hiện neighbor có mức
          thấp hơn, thuật toán quay lại mức thấp hơn ngay để giữ đúng
          thứ tự ưu tiên.

    Tạo đường biên:
        Sau khi flood, duyệt các cặp pixel kề nhau. Nếu hai nhãn khác
        nhau, đặt pixel biên về phía có gradient lớn hơn. Cách này cho
        đường watershed mảnh 1 pixel và bám sát cạnh thật.

    Tham số:
        gradient : uint8 H×W, gradient magnitude.
        markers  : int32 H×W; 0 = unknown, 1 = background, >=2 = seed.

    Trả về:
        labels : int32 H×W; -1 = đường phân thủy, 1 = background,
                 >=2 = vùng hạt.
    """
    labels = np.asarray(markers, dtype=np.int32).copy()
    if labels.ndim != 2:
        raise ValueError("markers phải là mảng 2 chiều.")

    h, w = labels.shape
    if h == 0 or w == 0:
        return labels

    wp = w + 2

    # Padding viền -1 để không cần kiểm tra biên trong vòng lặp nóng.
    labels_pad = np.pad(labels, 1, mode="constant", constant_values=-1)
    grad_pad = np.pad(
        np.asarray(gradient, dtype=np.uint8), 1, mode="edge"
    )

    lf = labels_pad.ravel()
    gf = grad_pad.ravel()

    # ------------------------------------------------------------------
    # Khởi tạo frontier: unknown pixel kề với ít nhất một marker.
    # Vectorized bằng bốn phép shift.
    # ------------------------------------------------------------------
    unknown = labels == 0
    labeled = labels > 0
    adjacent = np.zeros_like(unknown)
    adjacent[1:, :] |= labeled[:-1, :]
    adjacent[:-1, :] |= labeled[1:, :]
    adjacent[:, 1:] |= labeled[:, :-1]
    adjacent[:, :-1] |= labeled[:, 1:]
    frontier = np.flatnonzero((unknown & adjacent).ravel())

    buckets = [array("i") for _ in range(256)]
    heads = [0] * 256
    queued = np.zeros(lf.size, dtype=bool)

    if frontier.size:
        ys, xs = np.divmod(frontier, w)
        padded_indices = (ys + 1) * wp + (xs + 1)
        for pidx in padded_indices.tolist():
            level = int(gf[pidx])
            queued[pidx] = True
            buckets[level].append(pidx)

    # Mức thấp nhất đang có phần tử.
    current = 0
    while current < 256 and heads[current] >= len(buckets[current]):
        current += 1

    offsets = (-wp, wp, -1, 1)

    while current < 256:
        bucket = buckets[current]
        switched = False

        while heads[current] < len(bucket):
            idx = bucket[heads[current]]
            heads[current] += 1

            if lf[idx] != 0:
                continue

            # Chọn nhãn của neighbor đã có nhãn và có gradient nhỏ nhất.
            # Tie-break bằng label nhỏ hơn để kết quả ổn định.
            best_label = 0
            best_grad = 256
            for off in offsets:
                nidx = idx + off
                nl = int(lf[nidx])
                if nl > 0:
                    ng = int(gf[nidx])
                    if ng < best_grad or (
                        ng == best_grad
                        and (best_label == 0 or nl < best_label)
                    ):
                        best_grad = ng
                        best_label = nl

            if best_label == 0:
                # Không còn neighbor có nhãn (trường hợp phòng vệ).
                continue

            lf[idx] = best_label

            # Mở rộng sang 4 neighbor chưa có nhãn.
            lower_level = 256
            for off in offsets:
                nidx = idx + off
                if lf[nidx] == 0 and not queued[nidx]:
                    queued[nidx] = True
                    level = int(gf[nidx])
                    buckets[level].append(nidx)
                    if level < lower_level:
                        lower_level = level

            # Hierarchical queue: nếu có pixel ưu tiên thấp hơn, quay lại.
            if lower_level < current:
                current = lower_level
                switched = True
                break

        if switched:
            continue

        current += 1
        while current < 256 and heads[current] >= len(buckets[current]):
            current += 1

    labels = labels_pad[1:-1, 1:-1].copy()

    # Vùng unknown còn sót (không tiếp cận được seed) → coi là nền.
    labels[labels == 0] = 1

    # ------------------------------------------------------------------
    # Hậu xử lý: tạo đường phân thủy 1 pixel.
    # Với mỗi cặp kề nhau khác nhãn, chọn phía có gradient lớn hơn.
    # ------------------------------------------------------------------
    boundary = np.zeros((h, w), dtype=bool)

    diff = labels[:, 1:] != labels[:, :-1]
    choose_right = diff & (gradient[:, 1:] >= gradient[:, :-1])
    choose_left = diff & ~choose_right
    boundary[:, 1:] |= choose_right
    boundary[:, :-1] |= choose_left

    diff = labels[1:, :] != labels[:-1, :]
    choose_bottom = diff & (gradient[1:, :] >= gradient[:-1, :])
    choose_top = diff & ~choose_bottom
    boundary[1:, :] |= choose_bottom
    boundary[:-1, :] |= choose_top

    labels[boundary] = -1
    return labels


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
        img_bgr : Ảnh màu BGR (dùng để tính gradient magnitude).
        sure_fg : Vùng foreground chắc chắn (uint8).
        unknown : Vùng không xác định (uint8).

    Trả về:
        markers   : Ma trận int32 chứa nhãn phân đoạn
                    (0=unknown, -1=boundary, 1=background, >1=region).
        num_labels: Số thành phần seed + 1 (background).

    Ghi chú thuật toán:
        - Connected Components 8-hướng dùng RLE + Union-Find tự cài đặt,
          không gọi cv2.connectedComponents.
        - Gradient dùng Sobel 3×3 tự cài đặt.
        - Watershed dùng Meyer flooding với hierarchical queue tự cài đặt,
          không gọi cv2.watershed.
    """
    # ------------------------------------------------------------------
    # (1) Gradient magnitude của ảnh xám — "địa hình" cho watershed.
    # ------------------------------------------------------------------
    gray = _to_grayscale(img_bgr)
    gradient = _sobel_gradient_magnitude(gray)

    # ------------------------------------------------------------------
    # (2) Connected Components trên sure_fg → marker cho từng hạt.
    #     labels: 0 = nền, 1..N = các thành phần sure_fg.
    # ------------------------------------------------------------------
    num_components, components = _connected_components_rle(sure_fg > 0)

    # Dịch label +1 để background (0) trở thành 1; các hạt thành 2..N+1.
    markers = components + 1

    # Vùng unknown = 0 để watershed quyết định.
    markers[unknown == 255] = 0

    # ------------------------------------------------------------------
    # (3) Flooding: lan nhãn vào vùng unknown theo thứ tự gradient.
    # ------------------------------------------------------------------
    markers = _watershed_flood(gradient, markers)

    return markers, num_components + 1


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
    if markers.ndim != 2 or markers.size == 0:
        return particles

    # ------------------------------------------------------------------
    # BƯỚC 1 — THỐNG KÊ VECTORIZED BẰNG NUMPY
    # Thay vì tạo mask H×W cho từng label (O(số_hạt × số_pixel)), ta chỉ
    # duyệt các pixel foreground đúng một lần rồi dùng bincount/reduceat.
    # ------------------------------------------------------------------
    h, w = markers.shape
    flat = markers.ravel()
    foreground = np.flatnonzero(flat > 1)  # bỏ 0 (unknown), -1 (viền), 1 (nền)
    if foreground.size == 0:
        return particles

    fg_labels = flat[foreground]
    labels, inverse, counts = np.unique(
        fg_labels, return_inverse=True, return_counts=True
    )

    ys = (foreground // w).astype(np.int64, copy=False)
    xs = (foreground % w).astype(np.int64, copy=False)

    # Tổng tọa độ để tính centroid từng label
    sum_x = np.bincount(inverse, weights=xs, minlength=labels.size)
    sum_y = np.bincount(inverse, weights=ys, minlength=labels.size)

    # Bounding box từng label: sắp xếp theo inverse rồi reduceat
    order = np.argsort(inverse, kind="stable")
    inverse_sorted = inverse[order]
    starts = np.searchsorted(inverse_sorted, np.arange(labels.size), side="left")
    min_y = np.minimum.reduceat(ys[order], starts)
    max_y = np.maximum.reduceat(ys[order], starts)
    min_x = np.minimum.reduceat(xs[order], starts)
    max_x = np.maximum.reduceat(xs[order], starts)

    # ------------------------------------------------------------------
    # BƯỚC 2 — CONTOUR CỤC BỘ ĐỂ TÍNH CHU VI
    # Chỉ cắt vùng bounding box (nhỏ hơn nhiều so với toàn ảnh) và thêm
    # 1px viền để cv2.findContours xử lý đúng hạt chạm biên crop.
    # ------------------------------------------------------------------
    for idx, label in enumerate(labels):
        area = int(counts[idx])
        if area < min_area:
            continue

        y0 = int(min_y[idx])
        x0 = int(min_x[idx])
        y1 = int(max_y[idx]) + 1
        x1 = int(max_x[idx]) + 1

        local_mask = (markers[y0:y1, x0:x1] == label).astype(np.uint8) * 255
        local_mask = cv2.copyMakeBorder(
            local_mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0
        )

        contours, _ = cv2.findContours(
            local_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            continue
        cnt = max(contours, key=cv2.contourArea)
        perimeter = float(cv2.arcLength(cnt, closed=True))

        # Centroid vectorized; fallback về tâm bounding box nếu cần
        cx = round(float(sum_x[idx]) / area, 1)
        cy = round(float(sum_y[idx]) / area, 1)

        equiv_diameter = round(2 * np.sqrt(area / np.pi), 2)

        if perimeter > 0:
            # Circularity lý thuyết ≤ 1; contour pixel hóa có thể nhích > 1
            # với hạt rất nhỏ nên clip lại cho dữ liệu hiển thị hợp lý.
            circularity = round(
                float(np.clip(4 * np.pi * area / (perimeter ** 2), 0.0, 1.0)),
                4,
            )
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
        Phải dùng p["ws_label"] (label gốc do Watershed gán)
        để tra cứu đúng vùng trong ma trận markers.
        KHÔNG dùng (i + 2) vì particles đã được sort lại theo diện tích
        → thứ tự index i không còn tương ứng với label trong markers nữa.
    """
    output = img_bgr.copy()

    rng = np.random.default_rng(seed=42)
    # Tạo bảng màu ngẫu nhiên ổn định: seed cố định → màu không đổi mỗi lần gọi.
    # Palette được tra một lần bằng NumPy indexing thay vì tạo mask cho từng hạt.
    max_label = int(markers.max(initial=1)) + 1
    palette = rng.integers(70, 235, size=(max_label + 1, 3), dtype=np.uint8)

    # --- (1) TÔ MÀU TỪNG VÙNG HẠT ---
    if color_map and particles:
        particle_labels = np.fromiter(
            (p["ws_label"] for p in particles),
            dtype=np.int32,
            count=len(particles),
        )
        color_mask = np.isin(markers, particle_labels)
        mapped_colors = palette[np.clip(markers, 0, max_label)]
        output[color_mask] = (
            output[color_mask].astype(np.float32) * 0.45
            + mapped_colors[color_mask].astype(np.float32) * 0.55
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
    Chuyển bản đồ khoảng cách (float32, 0→1) thành ảnh màu JET.

    Colormap JET được cài đặt trực tiếp bằng NumPy (nội suy tuyến tính
    giữa các mốc màu), không dùng cv2.applyColorMap.

    Các mốc JET:
        0.000 → navy   (0.0, 0.0, 0.5)
        0.125 → blue   (0.0, 0.0, 1.0)
        0.375 → cyan   (0.0, 1.0, 1.0)
        0.625 → yellow (1.0, 1.0, 0.0)
        0.875 → red    (1.0, 0.0, 0.0)
        1.000 → dark red (0.5, 0.0, 0.0)

    Màu NÓNG (đỏ/vàng) = xa nền nhất = tâm hạt.
    Màu LẠNH (xanh đậm) = gần nền nhất = rìa hạt.
    """
    x = np.clip(np.asarray(dist_map, dtype=np.float32), 0.0, 1.0)

    positions = np.array(
        [0.0, 0.125, 0.375, 0.625, 0.875, 1.0], dtype=np.float32
    )
    red = np.array(
        [0.0, 0.0, 0.0, 1.0, 1.0, 0.5], dtype=np.float32
    )
    green = np.array(
        [0.0, 0.0, 1.0, 1.0, 0.0, 0.0], dtype=np.float32
    )
    blue = np.array(
        [0.5, 1.0, 1.0, 0.0, 0.0, 0.0], dtype=np.float32
    )

    r = np.interp(x, positions, red).astype(np.float32)
    g = np.interp(x, positions, green).astype(np.float32)
    b = np.interp(x, positions, blue).astype(np.float32)

    # OpenCV / cv2.imencode dùng thứ tự BGR.
    bgr = np.stack((b, g, r), axis=-1)
    return np.clip(bgr * 255.0, 0.0, 255.0).astype(np.uint8)


# ---------------------------------------------------------------------------
# HÀM TIỆN ÍCH 5H: PIPELINE PHÂN ĐOẠN DÙNG CHUNG
# ---------------------------------------------------------------------------
def _segment_particles(
    img_bgr: np.ndarray,
    method: str = "otsu",
    threshold: int = 128,
    distance_factor: float = 0.45,
    min_area: int = 20,
):
    """
    Chạy pipeline: Grayscale → Binarize → Opening → Distance Transform
    → Watershed → Measurements.

    Tách riêng để API JSON và API CSV dùng cùng một logic, tránh lệch số liệu.

    Ghi chú về việc "tự cài đặt":
        - Distance Transform: _euclidean_distance_transform (separable EDT).
        - Connected Components: _connected_components_rle (RLE + Union-Find).
        - Gradient: _sobel_gradient_magnitude (Sobel + Gaussian 3×3).
        - Watershed: _watershed_flood (Meyer hierarchical queue).
        - Các phép ngưỡng / thống kê / bbox / tô màu: NumPy vectorized.
        OpenCV chỉ còn được dùng cho I/O ảnh và các bước tiền xử lý
        (Gaussian blur, threshold, morphology) ở giai đoạn binarization.
    """
    method = (method or "otsu").strip().lower()
    if method not in {"otsu", "adaptive", "triangle", "manual"}:
        method = "otsu"

    threshold = int(np.clip(threshold, 1, 254))
    distance_factor = float(np.clip(distance_factor, 0.05, 0.95))
    min_area = max(1, int(min_area))

    gray = _to_grayscale(img_bgr)
    binary = _binarize(gray, method=method, manual_threshold=threshold)
    cleaned = _morphological_clean(binary)

    dist_map, sure_fg, _sure_bg, unknown = _distance_transform(
        cleaned, distance_factor=distance_factor
    )
    markers, _num_labels = _watershed_segment(
        img_bgr.copy(), sure_fg, unknown
    )
    particles = _measure_particles(markers, min_area=min_area)

    return markers, particles, dist_map


# ---------------------------------------------------------------------------
# HÀM TIỆN ÍCH 5I: PHÂN TÍCH MỘT ẢNH & ĐÓNG GÓI KẾT QUẢ JSON
# ---------------------------------------------------------------------------
def _analyze_particle_image(
    image_bytes: bytes,
    method: str,
    threshold: int,
    distance_factor: float,
    min_area: int,
    show_boundary: bool,
    show_centroid: bool,
    show_id: bool,
    color_map: bool,
) -> dict:
    """Chạy toàn bộ pipeline 5A và trả về dict sẵn sàng cho JSONResponse."""
    started_at = time.perf_counter()

    # 5-I — Đọc & decode ảnh (giới hạn 1600px để phản hồi ổn định)
    img_bgr = _decode_image_bytes(image_bytes, max_dim=1600)
    total_pixels = int(img_bgr.shape[0] * img_bgr.shape[1])

    # 5-II → 5-V — Tiền xử lý, Distance Transform, Watershed, đo lường
    markers, particles, dist_map = _segment_particles(
        img_bgr,
        method=method,
        threshold=threshold,
        distance_factor=distance_factor,
        min_area=min_area,
    )

    # 5-VI — Vẽ viền/tâm/#ID + bản đồ khoảng cách
    result_img = _draw_results(
        img_bgr,
        markers,
        particles,
        show_boundary=show_boundary,
        show_centroid=show_centroid,
        show_id=show_id,
        color_map=color_map,
    )
    dist_img_colored = _render_distance_map(dist_map)

    # 5-VII — Mã hóa base64
    ok_result, result_encoded = cv2.imencode(
        ".jpg", result_img, [cv2.IMWRITE_JPEG_QUALITY, 88]
    )
    ok_dist, dist_encoded = cv2.imencode(
        ".jpg", dist_img_colored, [cv2.IMWRITE_JPEG_QUALITY, 85]
    )
    if not ok_result or not ok_dist:
        raise ValueError("Không thể mã hóa ảnh kết quả.")

    result_b64 = base64.b64encode(result_encoded.tobytes()).decode("utf-8")
    dist_b64 = base64.b64encode(dist_encoded.tobytes()).decode("utf-8")

    # 5-VIII — Chỉ số tổng hợp
    total_count = len(particles)
    if total_count > 0:
        total_area = int(sum(p["area_px"] for p in particles))
        avg_area = round(total_area / total_count, 2)
        coverage_pct = round(min(total_area / max(total_pixels, 1) * 100.0, 100.0), 2)
        avg_circularity = round(
            sum(p["circularity"] for p in particles) / total_count, 4
        )
    else:
        total_area = 0
        avg_area = 0.0
        coverage_pct = 0.0
        avg_circularity = 0.0

    # Không trả ws_label nội bộ ra ngoài
    particles_json = [
        {k: v for k, v in p.items() if k != "ws_label"}
        for p in particles
    ]

    processing_ms = round((time.perf_counter() - started_at) * 1000.0, 1)

    return {
        "total_count": total_count,
        "avg_area": avg_area,
        "coverage_pct": coverage_pct,
        "avg_circularity": avg_circularity,
        "total_area_px": total_area,
        "result_image_b64": result_b64,
        "dist_image_b64": dist_b64,
        "particles": particles_json,
        "image_width": int(img_bgr.shape[1]),
        "image_height": int(img_bgr.shape[0]),
        "processing_ms": processing_ms,
        "method": (method or "otsu").strip().lower(),
        "threshold": int(np.clip(threshold, 1, 254)),
        "distance_factor": round(float(np.clip(distance_factor, 0.05, 0.95)), 2),
        "min_area": max(1, int(min_area)),
    }


def _build_particle_csv(
    image_bytes: bytes,
    method: str,
    threshold: int,
    distance_factor: float,
    min_area: int,
) -> bytes:
    """Chạy cùng pipeline 5A rồi đóng gói bảng đo lường thành CSV UTF-8."""
    img_bgr = _decode_image_bytes(image_bytes, max_dim=1600)
    _markers, particles, _dist_map = _segment_particles(
        img_bgr,
        method=method,
        threshold=threshold,
        distance_factor=distance_factor,
        min_area=min_area,
    )

    output_csv = io.StringIO()
    writer = csv.writer(output_csv)
    writer.writerow([
        "#ID", "Tam_X(px)", "Tam_Y(px)",
        "Dien_tich(px2)", "Chu_vi(px)",
        "Duong_kinh_tuong_duong(px)", "Do_tron(0-1)",
    ])
    for p in particles:
        writer.writerow([
            p["id"], p["cx"], p["cy"],
            p["area_px"], p["perimeter_px"],
            p["equiv_diameter_px"], p["circularity"],
        ])

    return output_csv.getvalue().encode("utf-8-sig")  # BOM cho Excel tiếng Việt


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
    # =========================================================
    # PHÂN VÙNG 5-I: ĐỌC & DECODE ẢNH ĐẦU VÀO
    # =========================================================
    image_bytes = await file.read()

    # =========================================================
    # PHÂN VÙNG 5-II → 5-VIII: CHẠY PIPELINE TRONG THREADPOOL
    # =========================================================
    # Distance Transform + Watershed là tác vụ CPU-bound. Đưa vào
    # threadpool để không chặn event loop của FastAPI (các request
    # preview/export khác vẫn được phục vụ song song).
    try:
        result = await run_in_threadpool(
            _analyze_particle_image,
            image_bytes,
            method,
            threshold,
            distance_factor,
            min_area,
            show_boundary,
            show_centroid,
            show_id,
            color_map,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(content={"status": "success", **result})


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

    Dùng chung pipeline và giới hạn 1600px với /api/particle-count để số
    liệu CSV khớp chính xác với kết quả đang hiển thị trên giao diện.
    """
    image_bytes = await file.read()
    try:
        csv_bytes = await run_in_threadpool(
            _build_particle_csv,
            image_bytes,
            method,
            threshold,
            distance_factor,
            min_area,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
