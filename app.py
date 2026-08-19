from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response
import cv2
import numpy as np

app = FastAPI()

# Gắn thư mục tĩnh và templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

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
    # PHÂN VÙNG 1: ĐỌC DỮ LIỆU ẢNH ĐẦU VÀO
    # ==========================================
    image_bytes = await file.read()
    
    # Chuyển chuỗi bytes thành mảng numpy 1 chiều
    nparr = np.frombuffer(image_bytes, np.uint8)
    
    # Giải mã mảng 1 chiều thành ma trận ảnh OpenCV (img)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # Kiểm tra nếu file gửi lên không phải là ảnh hợp lệ
    if img is None:
        return Response(content="File không hợp lệ!", status_code=400)
    
    
    # ==========================================
    # PHÂN VÙNG 2: XỬ LÝ CROP (Cắt ảnh)
    # ==========================================
    # crop_value là tỷ lệ % cắt viền (từ 0% đến 30%)
    
    # [CODE CROP CỦA BẠN Ở ĐÂY]
    
    
    # ==========================================
    # PHÂN VÙNG 3: XỬ LÝ ROTATE (Xoay ảnh)
    # ==========================================
    # rotate_value là góc xoay (từ 0 đến 360 độ)
    
    # [CODE XOAY CỦA BẠN Ở ĐÂY]
    
    
    # ==========================================
    # PHÂN VÙNG 4: XỬ LÝ ZOOM (Thu phóng ảnh)
    # ==========================================
    # zoom_value tính theo % (ví dụ 150 là x1.5 kích thước)
    
    # [CODE THU PHÓNG CỦA BẠN Ở ĐÂY]
    
    
    # ==========================================
    # PHÂN VÙNG 5: TRẢ ẢNH VỀ CHO FRONTEND
    # ==========================================
    # Mã hóa ma trận ảnh (img) ngược lại thành định dạng JPEG
    success, encoded_image = cv2.imencode('.jpg', img)
    
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