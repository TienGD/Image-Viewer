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

const exportButton = document.getElementById('exportButton');
const exportFormat = document.getElementById('exportFormat');

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

function handleSliderInput(e, textElement, suffix) {
	textElement.textContent = `${e.target.value}${suffix}`;
	clearTimeout(timeoutId);
	timeoutId = setTimeout(() => {
		sendToBackend();
	}, 40);
}

zoomSlider.addEventListener('input', (e) => handleSliderInput(e, zoomValue, '%'));
rotateSlider.addEventListener('input', (e) => handleSliderInput(e, rotateValue, '°'));
cropSlider.addEventListener('input', (e) => handleSliderInput(e, cropValue, '%'));

// --- 5. GỬI YÊU CẦU PREVIEW LÊN BACKEND ---
async function sendToBackend() {
	if (!currentFile) return;

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
				imgEl.src = imageUrl;
				imgEl.style.opacity = '1';
			} else {
				afterPreview.innerHTML = `<img src="${imageUrl}" style="max-width: 100%; max-height: 100%; border-radius: 8px;">`;
			}
		} else {
			console.error('Lỗi xử lý từ Backend!');
		}
	} catch (error) {
		if (error.name === 'AbortError') {
			return;
		}
		console.error('Lỗi kết nối:', error);
	}
}

