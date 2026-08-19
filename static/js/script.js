// --- 1. KẾT NỐI VỚI CÁC THÀNH PHẦN TRÊN GIAO DIỆN ---
const mediaInput = document.getElementById('mediaInput');
const beforePreview = document.getElementById('beforePreview');
const afterPreview = document.getElementById('afterPreview');

const zoomSlider = document.getElementById('zoomSlider');
const zoomValue = document.getElementById('zoomValue');

const rotateSlider = document.getElementById('rotateSlider');
const rotateValue = document.getElementById('rotateValue');

const cropSlider = document.getElementById('cropSlider');
const cropValue = document.getElementById('cropValue');

let currentFile = null; // Biến lưu trữ file ảnh đang tải lên

// --- 2. XỬ LÝ SỰ KIỆN CHỌN FILE (SHOW ẢNH BEFORE) ---
mediaInput.addEventListener('change', function (event) {
	const file = event.target.files[0];
	if (file) {
		currentFile = file;

		// Đọc file và hiển thị lên khung Before
		const reader = new FileReader();
		reader.onload = function (e) {
			beforePreview.innerHTML = `<img src="${e.target.result}" style="max-width: 100%; max-height: 100%; border-radius: 8px;">`;
			// Khi vừa tải ảnh lên, tự động gửi yêu cầu xử lý gốc sang khung After
			sendToBackend();
		};
		reader.readAsDataURL(file);
	}
});

// --- 3. CẬP NHẬT GIAO DIỆN THANH TRƯỢT (SLIDERS) ---
zoomSlider.addEventListener('input', (e) => (zoomValue.textContent = `${e.target.value}%`));
rotateSlider.addEventListener('input', (e) => (rotateValue.textContent = `${e.target.value}°`));
cropSlider.addEventListener('input', (e) => (cropValue.textContent = `${e.target.value}%`));

// --- 4. GỬI YÊU CẦU XỬ LÝ LÊN BACKEND (KHI KÉO SLIDER XONG) ---
// Dùng sự kiện 'change' thay vì 'input' để tránh gửi dữ liệu liên tục khi đang kéo dở
zoomSlider.addEventListener('change', sendToBackend);
rotateSlider.addEventListener('change', sendToBackend);
cropSlider.addEventListener('change', sendToBackend);

async function sendToBackend() {
	if (!currentFile) return;

	// Hiển thị trạng thái đang load (Tùy chọn)
	afterPreview.innerHTML = 'Đang xử lý...';

	// Đóng gói dữ liệu gửi đi (File ảnh + Các thông số)
	const formData = new FormData();
	formData.append('file', currentFile);
	formData.append('zoom', zoomSlider.value);
	formData.append('rotate', rotateSlider.value);
	formData.append('crop', cropSlider.value);

	try {
		// Gửi API đến Backend FastAPI
		const response = await fetch('/api/process-image', {
			method: 'POST',
			body: formData,
		});

		if (response.ok) {
			// Nhận ảnh đã xử lý dưới dạng Blob và hiển thị lên khung After
			const blob = await response.blob();
			const imageUrl = URL.createObjectURL(blob);
			afterPreview.innerHTML = `<img src="${imageUrl}" style="max-width: 100%; max-height: 100%; border-radius: 8px;">`;
		} else {
			afterPreview.innerHTML = 'Lỗi xử lý từ Backend!';
		}
	} catch (error) {
		console.error('Lỗi kết nối:', error);
		afterPreview.innerHTML = 'Lỗi kết nối server!';
	}
}
