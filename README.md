# 🔬 Image Viewer IUH — Watershed Cell Analysis Studio

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![OpenCV](https://img.shields.io/badge/OpenCV-5.0%2B-5C3EE8.svg?logo=opencv&logoColor=white)](https://opencv.org/)
[![NumPy](https://img.shields.io/badge/NumPy-2.0%2B-013243.svg?logo=numpy&logoColor=white)](https://numpy.org/)
[![Matplotlib](https://img.shields.io/badge/Matplotlib-3.8%2B-11557c.svg)](https://matplotlib.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Ứng dụng web chuyên sâu phục vụ **xử lý ảnh vi học, phân đoạn tế bào/mẫu hạt bằng thuật toán Watershed & Distance Transform**, tích hợp công cụ căn chỉnh hình ảnh thời gian thực, quản lý phiên làm việc và xuất báo cáo khoa học.

---

## 🌟 Tính Năng Nổi Bật

### 1. ⚙️ Căn Chỉnh & Biến Đổi Ảnh (Image Transformation)
* **Thu phóng (Zoom):** Tùy chỉnh linh hoạt từ $50\%$ đến $200\%$.
* **Xoay tự do (Rotate):** Góc quay từ $-180^\circ$ đến $+180^\circ$ với thuật toán nội suy bilinear giữ nguyên tâm ảnh.
* **Cắt viền (Crop/Scale):** Cắt bỏ phần viền thừa $0\%$ đến $30\%$.
* **Preview thời gian thực:** Tối ưu hóa kích thước tối đa 1080px kết hợp bộ nhớ đệm RAM (`ImageCache`) để đạt tốc độ phản hồi tức thì.
* **Xuất ảnh chất lượng cao (Export):** Xuất toàn vẹn độ phân giải ảnh gốc sang định dạng **JPG (Quality 95)** hoặc **PNG (Compression level 3)**.

---

### 2. 🧮 Phân Đoạn Watershed & Đếm Hạt Tự Động (Particle Counting)
Pipeline học thuật hoàn chỉnh được tự cài đặt tối ưu hóa bằng NumPy (không phụ thuộc hoàn toàn vào blackbox OpenCV):
1. **Grayscale conversion:** Chuyển đổi chuẩn màu ITU-R BT.601 ($Y = 0.299R + 0.587G + 0.114B$).
2. **Khử nhiễu & Nhị phân hóa (Binarization):**
   * *Tự động Otsu (Otsu Threshold)*: Cực đại hóa phương sai giữa hai lớp.
   * *Ngưỡng thích nghi (Adaptive Gaussian)*: Tự động điều chỉnh theo từng cửa sổ cục bộ $11 \times 11$, hỗ trợ tinh chỉnh hằng số bù ngưỡng $C$ từ $-10 \to +10$ (mặc định $C = 2$).
   * *Ngưỡng tam giác (Triangle Method)*: Phù hợp cho phổ histogram bị lệch.
   * *Tùy chỉnh thủ công (Manual)*: Cho phép người dùng kéo slider từ $1 \to 254$.
   * *Auto-correct polarity*: Tự nhận diện và chuẩn hóa vật thể sáng trên nền tối hoặc ngược lại.
3. **Làm sạch hình thái học (Morphological Opening):** Loại bỏ cặn mẫu và chấm nhiễu nhỏ.
4. **Euclidean Distance Transform (EDT):** Tự cài đặt thuật toán separable parabolic lower-envelope $O(N)$ (Felzenszwalb & Huttenlocher).
5. **Marker-based Watershed:** Tự cài đặt thuật toán Meyer Flooding với hàng đợi phân cấp 256 mức (hierarchical bucket queue) và Connected Components RLE + Union-Find 8 hướng.
6. **Đo lường thông số hình thái học từng hạt:**
   * Tọa độ tâm ($C_x, C_y$).
   * Diện tích ($Area\text{ }px^2$).
   * Chu vi ($Perimeter\text{ }px$).
   * Đường kính tương đương ($D_{equiv} = 2\sqrt{A / \pi}$).
   * Độ tròn ($Circularity = 4\pi A / P^2$, đạt $1.0$ với hình tròn hoàn hảo).

---

### 3. 📊 Phổ Phân Bố Mức Xám & Bản Đồ Nhiệt Ngưỡng Cục Bộ (Adaptive Heatmap)
* **Bản đồ nhiệt ngưỡng cục bộ $T(x,y)$ (Heatmap khi chọn Adaptive Gaussian):**
  * Thể hiện trực quan sự biến thiên của mặt phẳng ngưỡng cục bộ $T(x,y) = \text{Mean}_{11 \times 11} - 2$ trên toàn không gian 2D của bức ảnh.
  * 🔴 **Vùng màu nóng (Đỏ/Vàng):** Mức ngưỡng được nâng cao tại những vùng ảnh có cường độ sáng mạnh/bị chói, ngăn ngừa cháy sáng.
  * 🔵 **Vùng màu lạnh (Xanh lam/Xanh lục):** Mức ngưỡng được chủ động hạ thấp tại vùng đổ bóng hoặc thiếu sáng sâu, bóc tách cấu trúc ẩn trong tối.
  * Chứng minh mặt phẳng ngưỡng thích nghi bám sát địa hình độ sáng thực tế thay vì dùng ngưỡng phẳng cứng nhắc.
* **Biểu đồ phổ mức xám & Đối chiếu ngưỡng (Histogram khi chọn Otsu, Triangle, Manual):**
* Vẽ biểu đồ phổ tần suất 256 mức xám ($0 \to 255$) bằng backend phi đồ họa `Agg` an toàn luồng.
* **Đối chiếu trực quan các phương pháp ngưỡng (Otsu, Triangle, Manual):**
  * 🔵 **Ngưỡng Otsu:** Tối ưu tự động toàn cục.
  * 🟣 **Ngưỡng Triangle:** Hình học tam giác cho ảnh lệch phổ.
  * 🔴 **Ngưỡng Manual:** Giá trị thiết lập thủ công.
  * *Làm nổi bật nét liền và ký hiệu `[Đang dùng]` cho phương pháp đang được chọn.*
* **Chế độ xem đa góc độ:**
  * `Toàn ảnh`: Thống kê toàn bộ pixel ảnh đầu vào.
  * `Vùng hạt`: Thống kê riêng các pixel thuộc các hạt tế bào đã phân đoạn.
  * `Hạt & Nền`: So sánh trực quan sự phân tách cường độ giữa hạt và nền mẫu.
* Thanh thống kê Footer chi tiết: Tổng pixel, Mức xám TB $\mu$, Trung vị $\text{Med}$, Độ lệch chuẩn $\sigma$, khoảng $[\text{Min}, \text{Max}]$ và nút tải ảnh biểu đồ PNG độ phân giải cao.

---

### 4. 📁 Quản Lý Phiên (Sessions) & Xuất Dữ Liệu
* **Lưu phiên làm việc:** Lưu ảnh gốc, ảnh thumbnail và toàn bộ thông số biến đổi vào thư mục `saved_sessions/`.
* **Lịch sử phiên (History Modal):** Duyệt danh sách, khôi phục trạng thái làm việc chỉ với 1 click hoặc xóa phiên cũ.
* **Xuất file báo cáo:**
  * Tải ảnh kết quả biến đổi (JPG/PNG).
  * Tải biểu đồ phổ mức xám Matplotlib (PNG).
  * Xuất bảng dữ liệu số đo hình thái toàn bộ hạt ra định dạng **CSV chuẩn UTF-8 with BOM** (tương thích hoàn hảo với Microsoft Excel).

---

## 🛠️ Công Nghệ Sử Dụng

| Thành phần | Công nghệ / Thư viện | Vai trò |
| :--- | :--- | :--- |
| **Backend** | Python 3.10+, FastAPI, Uvicorn | Web API bất đồng bộ, hiệu năng cao |
| **Xử lý ảnh** | OpenCV, NumPy, Matplotlib | Pipeline phân tích, Distance Transform, Watershed, Histogram |
| **Frontend** | HTML5, CSS3 hiện đại, Vanilla JavaScript | Giao diện Responsive, Dark/Light Studio Theme, không phụ thuộc framework nặng |
| **Template Engine** | Jinja2 | Render giao diện ban đầu |

---

## 📂 Cấu Trúc Thư Mục

```text
Image-Viewer/
├── app.py                      # FastAPI server & toàn bộ pipeline xử lý ảnh
├── requirements.txt            # Danh sách thư viện phụ thuộc
├── saved_sessions/             # Thư mục lưu trữ các phiên làm việc (ảnh gốc + metadata JSON)
├── static/
│   ├── css/
│   │   └── style.css           # Toàn bộ CSS phong cách UI studio hiện đại
│   └── js/
│       └── script.js           # Bộ điều khiển Frontend, tương tác API và render
└── templates/
    └── index.html              # Giao diện chính của ứng dụng
```

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy Ứng Dụng

### 1. Yêu cầu hệ thống
* Python 3.10 trở lên.
* Trình duyệt web hiện đại (Google Chrome, Microsoft Edge, Firefox,...).

### 2. Cài đặt môi trường

```bash
# 1. Clone repository về máy
git clone https://github.com/<your-username>/Image-Viewer.git
cd Image-Viewer

# 2. Khởi tạo môi trường ảo (khuyến nghị)
python -m venv venv

# Kích hoạt trên Windows:
venv\Scripts\activate
# Kích hoạt trên Linux / macOS:
source venv/bin/activate

# 3. Cài đặt các gói phụ thuộc
pip install -r requirements.txt
```

### 3. Khởi chạy Server

```bash
python app.py
```
Hoặc khởi chạy qua Uvicorn trực tiếp:
```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Truy cập ứng dụng tại trình duyệt: **`http://127.0.0.1:8000`**

> **Mẹo tiện ích:** Nếu bạn mở dự án bằng tiện ích **Live Server** hoặc **Live Preview** trong Visual Studio Code (chạy ở cổng 5500 hoặc 3000), frontend đã được cấu hình CORS và proxy tự động chuyển tiếp request tới backend cổng 8000!

---

## 📖 Hướng Dẫn Sử Dụng Nhanh

1. **Tải ảnh:** Nhấn nút **Upload file** hoặc kéo thả ảnh trực tiếp vào khung **Ảnh gốc (Source)**.
2. **Căn chỉnh (Tab 1):** Kéo các thanh trượt `Zoom`, `Rotate`, `Crop` để tinh chỉnh khung nhìn nếu cần.
3. **Đếm hạt & Phân tích tế bào (Tab 2):**
   * Chọn phương pháp phân ngưỡng (`Otsu`, `Adaptive Gaussian`, `Triangle`, hoặc `Manual`).
   * Điều chỉnh `Hệ số tách cụm dính` (Distance Factor) và `Diện tích tối thiểu` (Min Area).
   * Nhấn nút **Thực hiện đếm hạt** (hoặc dùng phím tắt `Ctrl + Enter`).
4. **Xem kết quả:**
   * Xem ảnh phân đoạn viền Watershed hoặc bấm chuyển tab `Distance` để xem bản đồ khoảng cách nhiệt JET.
   * Đối chiếu phổ mức xám và 4 vạch ngưỡng trên biểu đồ Matplotlib.
   * Xem bảng đo lường chi tiết và bấm **Xuất CSV** để tải số liệu về máy.

---

## ⌨️ Phím Tắt Tiện Ích

* <kbd>Ctrl</kbd> + <kbd>Enter</kbd> (hoặc <kbd>Cmd</kbd> + <kbd>Enter</kbd>): Chạy nhanh phân tích đếm hạt.
* <kbd>Esc</kbd>: Đóng cửa sổ danh sách phiên đã lưu (Saved Sessions).

---

## 📄 Bản Quyền & Giấy Phép

Phát triển bởi đội ngũ nghiên cứu & sinh viên Khoa Công nghệ Thông tin — **Đại học Công nghiệp TP.HCM (IUH)**.  
Dự án được phân phối dưới giấy phép **MIT License**.
