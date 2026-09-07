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

const saveButton = document.getElementById('saveButton');
const historyButton = document.getElementById('historyButton');
const exportButton = document.getElementById('exportButton');
const exportFormat = document.getElementById('exportFormat');

const sessionsModal = document.getElementById('sessionsModal');
const closeModalBtn = document.getElementById('closeModalBtn');
const sessionsList = document.getElementById('sessionsList');
const sessionCountBadge = document.getElementById('sessionCountBadge');
const toastNotification = document.getElementById('toastNotification');

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

// --- 6. HỖ TRỢ TOAST THÔNG BÁO ---
function showToast(message, duration = 3000) {
	if (!toastNotification) return;
	toastNotification.textContent = message;
	toastNotification.classList.add('show');
	setTimeout(() => {
		toastNotification.classList.remove('show');
	}, duration);
}

// --- 7. XỬ LÝ LƯU PHIÊN LÀM VIỆC VÀO MÁY CHỦ (SAVE SESSION) ---
async function saveSession() {
	if (!currentFile) {
		alert('Vui lòng tải ảnh lên trước khi lưu phiên làm việc!');
		return;
	}

	const originalBtnText = saveButton.textContent;
	saveButton.disabled = true;
	saveButton.textContent = 'Saving...';

	const formData = new FormData();
	formData.append('file', currentFile);
	formData.append('zoom', zoomSlider.value);
	formData.append('rotate', rotateSlider.value);
	formData.append('crop', cropSlider.value);

	try {
		const response = await fetch('/api/save-session', {
			method: 'POST',
			body: formData,
		});

		if (!response.ok) {
			throw new Error('Lỗi từ server khi lưu phiên!');
		}

		const result = await response.json();
		showToast('✓ Đã lưu phiên làm việc vào máy chủ!');
	} catch (error) {
		console.error('Lỗi khi lưu phiên:', error);
		alert('Có lỗi xảy ra trong quá trình lưu phiên làm việc!');
	} finally {
		saveButton.disabled = false;
		saveButton.textContent = originalBtnText;
	}
}

// --- 8. XỬ LÝ XUẤT ẢNH TẢI VỀ MÁY (EXPORT FILE) ---
async function downloadProcessedImage(targetFormat, triggerBtn, loadingText) {
	if (!currentFile) {
		alert('Vui lòng tải ảnh lên trước khi thực hiện!');
		return;
	}

	const originalBtnText = triggerBtn.textContent;
	triggerBtn.disabled = true;
	triggerBtn.textContent = loadingText;

	const formData = new FormData();
	formData.append('file', currentFile);
	formData.append('zoom', zoomSlider.value);
	formData.append('rotate', rotateSlider.value);
	formData.append('crop', cropSlider.value);
	formData.append('format', targetFormat);

	try {
		const response = await fetch('/api/export-image', {
			method: 'POST',
			body: formData,
		});

		if (!response.ok) {
			let errorDetail = 'Lỗi từ server khi xuất ảnh!';
			try {
				const errorText = await response.text();
				if (errorText) errorDetail = errorText;
			} catch (_) {}
			throw new Error(errorDetail);
		}

		// Lấy tên file từ header Content-Disposition (ưu tiên chuẩn RFC 5987 / UTF-8 tiếng Việt)
		let filename = '';
		const disposition = response.headers.get('Content-Disposition');
		if (disposition) {
			const utf8Match = disposition.match(/filename\*=utf-8''([^;]+)/i);
			if (utf8Match && utf8Match[1]) {
				filename = decodeURIComponent(utf8Match[1]);
			} else {
				const matches = disposition.match(/filename="?([^";]+)"?/);
				if (matches && matches[1]) {
					filename = matches[1];
				}
			}
		}
		if (!filename) {
			const dotIndex = currentFile.name.lastIndexOf('.');
			const originalName = dotIndex !== -1 ? currentFile.name.substring(0, dotIndex) : currentFile.name;
			filename = `${originalName}_edited.${targetFormat}`;
		}

		const blob = await response.blob();
		const downloadUrl = window.URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = downloadUrl;
		a.download = filename;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		window.URL.revokeObjectURL(downloadUrl);
		showToast(`✓ Đã xuất file: ${filename}`);
	} catch (error) {
		console.error('Lỗi khi tải file:', error);
		alert(`Có lỗi xảy ra trong quá trình xuất ảnh: ${error.message || 'Vui lòng thử lại!'}`);
	} finally {
		triggerBtn.disabled = false;
		triggerBtn.textContent = originalBtnText;
	}
}

// --- 9. QUẢN LÝ LỊCH SỬ PHIÊN LÀM VIỆC (MODAL & RESTORE) ---
let cachedSessions = [];

function openModal() {
	if (sessionsModal) {
		sessionsModal.classList.add('active');
		fetchAndRenderSessions();
	}
}

function closeModal() {
	if (sessionsModal) {
		sessionsModal.classList.remove('active');
	}
}

function escapeHtml(str) {
	if (!str) return '';
	return String(str)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#039;');
}

async function fetchAndRenderSessions() {
	if (!sessionsList) return;
	sessionsList.innerHTML = '<div style="text-align: center; padding: 20px; color: var(--text-soft);">Đang tải danh sách phiên...</div>';

	try {
		const response = await fetch('/api/sessions');
		if (!response.ok) throw new Error('Không thể tải danh sách phiên!');
		const data = await response.json();
		cachedSessions = data.sessions || [];

		if (sessionCountBadge) {
			sessionCountBadge.textContent = cachedSessions.length;
		}

		if (cachedSessions.length === 0) {
			sessionsList.innerHTML = `
				<div class="sessions-empty">
					<span class="sessions-empty-icon">📂</span>
					<p>Chưa có phiên làm việc nào được lưu.</p>
					<small style="color: var(--text-soft);">Bấm nút <strong>Save</strong> để lưu phiên chỉnh sửa hiện tại.</small>
				</div>
			`;
			return;
		}

		sessionsList.innerHTML = cachedSessions.map((session) => {
			const safeFilename = escapeHtml(session.filename);
			const safeDate = escapeHtml(session.created_at_display || session.created_at);
			const safeId = escapeHtml(session.id);
			return `
				<div class="session-item" id="session-card-${safeId}">
					<img class="session-thumb" src="/api/sessions/${safeId}/thumbnail" alt="thumbnail" loading="lazy" />
					<div class="session-info">
						<div class="session-filename" title="${safeFilename}">${safeFilename}</div>
						<div class="session-date">${safeDate}</div>
						<div class="session-badges">
							<span class="param-badge">Zoom: ${session.zoom}%</span>
							<span class="param-badge">Rotate: ${session.rotate}°</span>
							<span class="param-badge">Crop: ${session.crop}%</span>
						</div>
					</div>
					<div class="session-actions">
						<button class="session-btn session-load-btn" onclick="restoreSession('${safeId}')">Load</button>
						<button class="session-btn session-delete-btn" onclick="deleteSession('${safeId}')">Delete</button>
					</div>
				</div>
			`;
		}).join('');
	} catch (error) {
		console.error('Lỗi khi tải danh sách phiên:', error);
		sessionsList.innerHTML = '<div style="color: #ef4444; text-align: center; padding: 20px;">Lỗi khi tải danh sách phiên làm việc!</div>';
	}
}

async function restoreSession(sessionId) {
	const session = cachedSessions.find((s) => s.id === sessionId);
	if (!session) return;

	try {
		showToast('Đang khôi phục phiên làm việc...');
		const response = await fetch(`/api/sessions/${sessionId}/original`);
		if (!response.ok) throw new Error('Không thể tải ảnh gốc của phiên!');

		const blob = await response.blob();
		const restoredFile = new File([blob], session.filename, { type: blob.type || 'image/png' });
		currentFile = restoredFile;

		// Khôi phục giá trị các thanh trượt
		zoomSlider.value = session.zoom;
		zoomValue.textContent = `${session.zoom}%`;

		rotateSlider.value = session.rotate;
		rotateValue.textContent = `${session.rotate}°`;

		cropSlider.value = session.crop;
		cropValue.textContent = `${session.crop}%`;

		// Hiển thị Before Preview nhanh bằng URL.createObjectURL
		const objectUrl = URL.createObjectURL(restoredFile);
		beforePreview.innerHTML = `<img src="${objectUrl}" style="max-width: 100%; max-height: 100%; border-radius: 8px;">`;
		afterPreview.innerHTML = '';
		sendToBackend();

		// Xóa giá trị input file để có thể chọn lại file cùng tên nếu muốn
		if (mediaInput) mediaInput.value = '';

		closeModal();
		showToast(`✓ Đã khôi phục phiên: ${session.filename}`);
	} catch (error) {
		console.error('Lỗi khi khôi phục phiên:', error);
		alert(`Có lỗi xảy ra khi khôi phục phiên: ${error.message || 'Vui lòng thử lại!'}`);
	}
}

async function deleteSession(sessionId) {
	if (!confirm('Bạn có chắc chắn muốn xóa phiên làm việc này khỏi máy chủ?')) {
		return;
	}

	try {
		const response = await fetch(`/api/sessions/${sessionId}`, {
			method: 'DELETE',
		});
		if (!response.ok) throw new Error('Không thể xóa phiên làm việc!');

		showToast('Đã xóa phiên làm việc.');
		fetchAndRenderSessions();
	} catch (error) {
		console.error('Lỗi khi xóa phiên:', error);
		alert('Có lỗi xảy ra khi xóa phiên làm việc!');
	}
}

// Đưa hàm vào window scope để các nút onclick trong HTML luôn gọi được
window.restoreSession = restoreSession;
window.deleteSession = deleteSession;

// Gắn sự kiện giao diện
if (saveButton) {
	saveButton.addEventListener('click', saveSession);
}

if (historyButton) {
	historyButton.addEventListener('click', openModal);
}

if (closeModalBtn) {
	closeModalBtn.addEventListener('click', closeModal);
}

if (sessionsModal) {
	sessionsModal.addEventListener('click', (e) => {
		if (e.target === sessionsModal) {
			closeModal();
		}
	});
}

if (exportButton) {
	exportButton.addEventListener('click', () => {
		const format = exportFormat ? exportFormat.value : 'jpg';
		downloadProcessedImage(format, exportButton, 'Exporting...');
	});
}



