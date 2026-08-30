from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response
import cv2
import numpy as np
from pathlib import Path
from collections import OrderedDict
import hashlib

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
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

# --- ROUTE 2: API XỬ LÝ ẢNH (NHẬN TỪ JAVASCRIPT) ---
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
    
    # Kiểm tra nếu ảnh gốc đã được decode trước đó trong cache
    cached_img = image_cache.get(file_hash)
    if cached_img is not None:
        img = cached_img.copy()
    else:
        # Chuyển chuỗi bytes thành mảng numpy 1 chiều
        nparr = np.frombuffer(image_bytes, np.uint8)
        
        # Giải mã mảng 1 chiều thành ma trận ảnh OpenCV (img)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Kiểm tra nếu file gửi lên không phải là ảnh hợp lệ
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
    # PHÂN VÙNG 2: XỬ LÝ CROP (Cắt ảnh)
    # ==========================================
    # crop_value là tỷ lệ % cắt viền (từ 0% đến 30%)
    if crop > 0:
        h, w = img.shape[:2]
        
        # 1. Giới hạn tỷ lệ cắt an toàn trong khoảng [0%, 30%] và đổi sang hệ số thập phân
        crop_percent = min(max(int(crop), 0), 30) / 100.0
        
        # 2. Tính số pixel cần cắt bỏ đều ở 4 phía (trên/dưới/trái/phải)
        pad_y = int(h * crop_percent)
        pad_x = int(w * crop_percent)
        
        # 3. Xác định tọa độ biên cắt trung tâm
        y1, y2 = pad_y, h - pad_y
        x1, x2 = pad_x, w - pad_x
        
        # 4. Cắt lấy vùng ảnh trung tâm bằng kỹ thuật NumPy Slicing
        if y2 > y1 and x2 > x1:
            img = img[y1:y2, x1:x2]
    
    # ==========================================
    # PHÂN VÙNG 3: XỬ LÝ ROTATE (Xoay ảnh)
    # ==========================================
    # rotate là góc xoay tính theo độ (từ -180 đến 180 độ)
    # rotate > 0: xoay theo chiều kim đồng hồ (sang phải)
    # rotate < 0: xoay ngược chiều kim đồng hồ (sang trái)
    if rotate % 360 != 0:
        h, w = img.shape[:2]
        
        # 1. Đổi góc sang radian và tính sin, cos
        rad = np.deg2rad(rotate)
        cos_a = np.cos(rad)
        sin_a = np.sin(rad)
        
        # 2. Tính kích thước khung hình mới để ảnh không bị cắt góc
        cos_abs = np.abs(cos_a)
        sin_abs = np.abs(sin_a)
        new_w = int(np.round(h * sin_abs + w * cos_abs))
        new_h = int(np.round(h * cos_abs + w * sin_abs))
        
        # 3. Xác định tọa độ tâm của ảnh cũ và ảnh mới
        cx = (w - 1) / 2.0
        cy = (h - 1) / 2.0
        new_cx = (new_w - 1) / 2.0
        new_cy = (new_h - 1) / 2.0
        
        # 4. Tối ưu hóa Broadcasting 1D (tránh tạo mảng 2D khổng lồ bằng np.indices)
        x_lin = np.arange(new_w, dtype=np.float32) - new_cx
        y_lin = np.arange(new_h, dtype=np.float32) - new_cy
        
        # 5. Ánh xạ ngược (Inverse Mapping) với cơ chế Broadcasting
        x_src = np.round((cos_a * x_lin)[None, :] + (sin_a * y_lin)[:, None] + cx).astype(np.int32)
        y_src = np.round((-sin_a * x_lin)[None, :] + (cos_a * y_lin)[:, None] + cy).astype(np.int32)
        
        # 6. Lọc các pixel có tọa độ hợp lệ nằm trong phạm vi ảnh gốc
        valid_mask = (x_src >= 0) & (x_src < w) & (y_src >= 0) & (y_src < h)
        
        # 7. Khởi tạo ảnh mới với nền đen và gán giá trị các pixel hợp lệ
        rotated_img = np.zeros((new_h, new_w, 3), dtype=np.uint8)
        rotated_img[valid_mask] = img[y_src[valid_mask], x_src[valid_mask]]
        img = rotated_img
    
    
    # ==========================================
    # PHÂN VÙNG 4: XỬ LÝ ZOOM (Thu phóng ảnh)
    # ==========================================
    # zoom_value tính theo % (ví dụ 150 là x1.5 kích thước)
    if zoom != 100 and zoom > 0:
            h, w = img.shape[:2]
            scale = zoom / 100.0
            
            # 1. Phóng to / Thu nhỏ ảnh
            new_w = int(w * scale)
            new_h = int(h * scale)
            resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            
            if scale > 1.0:
                # 2a. Nếu phóng to: Cắt lấy phần trung tâm bằng đúng kích thước gốc
                start_y = (new_h - h) // 2
                start_x = (new_w - w) // 2
                img = resized[start_y : start_y + h, start_x : start_x + w]
            else:
                # 2b. Nếu thu nhỏ: Đặt ảnh nhỏ vào giữa một khung nền đen bằng kích thước gốc
                img = np.zeros((h, w, 3), dtype=np.uint8)
                start_y = (h - new_h) // 2
                start_x = (w - new_w) // 2
                img[start_y : start_y + new_h, start_x : start_x + new_w] = resized
    
    
    # ==========================================
    # PHÂN VÙNG 5: TRẢ ẢNH VỀ CHO FRONTEND
    # ==========================================
    # Mã hóa ma trận ảnh (img) ngược lại thành định dạng JPEG (chất lượng 85 để truyền siêu tốc)
    success, encoded_image = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    
    # Nếu có lỗi trong quá trình mã hóa ảnh
    if not success:
        return Response(content="Lỗi khi xuất ảnh!", status_code=500)
    
    # Chuyển đối tượng ảnh đã mã hóa thành chuỗi bytes
    processed_image_bytes = encoded_image.tobytes()
    
    # Trả về trình duyệt
    return Response(content=processed_image_bytes, media_type="image/jpeg")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)