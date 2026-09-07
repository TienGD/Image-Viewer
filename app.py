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

app = FastAPI()
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)