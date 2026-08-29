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

let currentFile = null;

// --- 2. XỬ LÝ SỰ KIỆN CHỌN FILE ---
mediaInput.addEventListener('change', function (event) {
	const file = event.target.files[0];
	if (file) {
		currentFile = file;
		const reader = new FileReader();
		reader.onload = function (e) {
			beforePreview.innerHTML = `<img src="${e.target.result}" style="max-width: 100%; max-height: 100%; border-radius: 8px;">`;

			// Xóa rỗng thẻ After để tạo lại từ đầu cho ảnh mới
			afterPreview.innerHTML = '';
			sendToBackend();
		};
		reader.readAsDataURL(file);
	}
});

// --- 3 & 4. CẬP NHẬT GIAO DIỆN VÀ GỌI API BẰNG DEBOUNCE & ABORTCONTROLLER ---
let timeoutId = null;
let currentAbortController = null;

// Hàm xử lý chung khi kéo bất kỳ thanh trượt nào
function handleSliderInput(e, textElement, suffix) {
	// 1. Cập nhật con số hiển thị ngay lập tức
	textElement.textContent = `${e.target.value}${suffix}`;

	// 2. Hủy lịch gọi cũ nếu người dùng vẫn đang kéo
	clearTimeout(timeoutId);

	// 3. Đặt lịch gọi API mới sau 40ms (phản hồi tức thì, mượt mà như 25-30 FPS)
	timeoutId = setTimeout(() => {
		sendToBackend();
	}, 40);
}

zoomSlider.addEventListener('input', (e) => handleSliderInput(e, zoomValue, '%'));
rotateSlider.addEventListener('input', (e) => handleSliderInput(e, rotateValue, '°'));
cropSlider.addEventListener('input', (e) => handleSliderInput(e, cropValue, '%'));

// --- 5. GỬI YÊU CẦU XỬ LÝ LÊN BACKEND ---
async function sendToBackend() {
	if (!currentFile) return;

	// Hủy yêu cầu HTTP đang chạy trước đó nếu có (tránh ứ đọng request)
	if (currentAbortController) {
		currentAbortController.abort();
	}
	currentAbortController = new AbortController();

	const formData = new FormData();
	formData.append('file', currentFile);
	formData.append('zoom', zoomSlider.value);
	formData.append('rotate', rotateSlider.value);
	formData.append('crop', cropSlider.value);

	try {
		const response = await fetch('/api/process-image', {
			method: 'POST',
			body: formData,
			signal: currentAbortController.signal,
		});

		if (response.ok) {
			const blob = await response.blob();
			const imageUrl = URL.createObjectURL(blob);
			let imgEl = afterPreview.querySelector('img');

			if (imgEl) {
				// CẬP NHẬT TRỰC TIẾP link ảnh mới vào thẻ cũ (không chớp nháy)
				imgEl.src = imageUrl;
				imgEl.style.opacity = '1';
			} else {
				// Nếu là lần đầu tiên chưa có thẻ <img>, tạo mới
				afterPreview.innerHTML = `<img src="${imageUrl}" style="max-width: 100%; max-height: 100%; border-radius: 8px;">`;
			}
		} else {
			console.error('Lỗi xử lý từ Backend!');
		}
	} catch (error) {
		if (error.name === 'AbortError') {
			// Request cũ bị hủy vì có thao tác kéo mới hơn - hoàn toàn bình thường
			return;
		}
		console.error('Lỗi kết nối:', error);
	}
}
