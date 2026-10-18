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





// ===========================================================================
// --- PHÂN VÙNG 10: ĐẾM HẠT & PHÂN ĐOẠN WATERSHED (PARTICLE COUNTING) ---
// ===========================================================================
//
// Nguyên tắc: JS chỉ thu thập tham số từ UI và gọi API Python.
// Toàn bộ logic xử lý ảnh, Watershed, Distance Transform, đo lường
// hình thái → thực hiện hoàn toàn ở backend (app.py, Phân vùng 5).
// ===========================================================================

// --- 10.1. KẾT NỐI CÁC PHẦN TỬ GIAO DIỆN PARTICLE COUNTING ---
const btnRunWatershed   = document.getElementById('btnRunWatershed');
const btnResetWatershed = document.getElementById('btnResetWatershed');
const btnExportDataCsv  = document.getElementById('btnExportDataCsv');

const wsMethodSelect    = document.getElementById('wsMethodSelect');
const wsThresholdSlider = document.getElementById('wsThresholdSlider');
const wsThresholdVal    = document.getElementById('wsThresholdVal');
const wsDistanceSlider  = document.getElementById('wsDistanceSlider');
const wsDistanceVal     = document.getElementById('wsDistanceVal');
const wsMinAreaSlider   = document.getElementById('wsMinAreaSlider');
const wsMinAreaVal      = document.getElementById('wsMinAreaVal');

const chkShowBoundary   = document.getElementById('chkShowBoundary');
const chkShowCentroid   = document.getElementById('chkShowCentroid');
const chkShowId         = document.getElementById('chkShowId');
const chkColorMap       = document.getElementById('chkColorMap');

const metricTotalCount  = document.getElementById('metricTotalCount');
const metricAvgArea     = document.getElementById('metricAvgArea');
const metricCoverage    = document.getElementById('metricCoverage');
const metricCircularity = document.getElementById('metricCircularity');

const particleTableBody = document.getElementById('particleTableBody');
const particleDataCount = document.getElementById('particleDataCount');

let lastParticleFile   = null;
let lastParticleParams = null;
let particleAbortCtrl  = null;

// --- 10.2. ĐẶT LẠI GIÁ TRỊ MẶC ĐỊNH (RESET WATERSHED) ---
function resetWatershedParams() {
	if (wsMethodSelect)    wsMethodSelect.value    = 'otsu';
	if (wsThresholdSlider) { wsThresholdSlider.value = 128;  document.getElementById('wsThresholdVal').textContent = '128'; }
	if (wsDistanceSlider)  { wsDistanceSlider.value  = 0.45; document.getElementById('wsDistanceVal').textContent  = '0.45'; }
	if (wsMinAreaSlider)   { wsMinAreaSlider.value   = 20;   document.getElementById('wsMinAreaVal').textContent   = '20 px\u00B2'; }
	if (chkShowBoundary)   chkShowBoundary.checked  = true;
	if (chkShowCentroid)   chkShowCentroid.checked  = true;
	if (chkShowId)         chkShowId.checked        = true;
	if (chkColorMap)       chkColorMap.checked      = false;
	showToast('\uD83D\uDD04 Đã đặt lại tham số Watershed về mặc định.');
}

// --- 10.3. CẬP NHẬT TRẠNG THÁI NÚT KHI ĐANG PHÂN TÍCH ---
function setWatershedRunning(isRunning) {
	if (!btnRunWatershed) return;
	if (isRunning) {
		btnRunWatershed.disabled = true;
		btnRunWatershed.innerHTML =
			'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="animation:wspin 1s linear infinite"><circle cx="12" cy="12" r="10" stroke-dasharray="31.4" stroke-dashoffset="10"/></svg>' +
			'<span>Đang phân tích Watershed...</span>';
	} else {
		btnRunWatershed.disabled = false;
		btnRunWatershed.innerHTML =
			'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>' +
			'<span>Thực hiện đếm hạt (Watershed)</span>';
	}
}

// --- 10.4. HIỂN THỊ ẢNH KẾT QUẢ WATERSHED VÀO PANEL "AFTER" ---
function renderWatershedImages(resultB64) {
	if (!afterPreview || !resultB64) return;
	var resultSrc = 'data:image/jpeg;base64,' + resultB64;
	var imgEl = afterPreview.querySelector('img');
	if (imgEl) {
		imgEl.src = resultSrc;
	} else {
		afterPreview.classList.remove('empty');
		afterPreview.innerHTML = '<img src="' + resultSrc + '" style="max-width:100%;max-height:100%;border-radius:8px;">';
	}
}

// --- 10.5. HIỂN THỊ CÁC CHỈ SỐ TỔNG HỢP VÀO METRIC CARDS ---
function renderMetricCards(data) {
	if (metricTotalCount)  metricTotalCount.textContent  = data.total_count;
	if (metricAvgArea)     metricAvgArea.textContent     = data.avg_area.toLocaleString('vi-VN') + ' px\u00B2';
	if (metricCoverage)    metricCoverage.textContent    = data.coverage_pct + '%';
	if (metricCircularity) metricCircularity.textContent = data.avg_circularity.toFixed(3);
}

// --- 10.6. RENDER BẢNG DỮ LIỆU TỪNG HẠT (NHẬN DỮ LIỆU TỪ PYTHON) ---
function renderParticleTable(particles) {
	if (!particleTableBody) return;
	if (!particles || particles.length === 0) {
		particleTableBody.innerHTML =
			'<tr class="table-placeholder-row"><td colspan="7">' +
			'<div class="table-empty-box">' +
			'<span class="empty-table-icon">\u26A0\uFE0F</span>' +
			'<div class="empty-table-text">Không phát hiện được hạt nào</div>' +
			'<div class="empty-table-sub">Hãy thử giảm <strong>Min Area</strong>, thay đổi <strong>Phương pháp phân ngưỡng</strong> hoặc giảm <strong>Distance Factor</strong>.</div>' +
			'</div></td></tr>';
		if (particleDataCount) particleDataCount.textContent = '0 kết quả';
		return;
	}
	particleTableBody.innerHTML = particles.map(function(p) {
		return '<tr>' +
			'<td><strong>#' + p.id + '</strong></td>' +
			'<td>' + p.cx + '</td>' +
			'<td>' + p.cy + '</td>' +
			'<td>' + p.area_px.toLocaleString('vi-VN') + '</td>' +
			'<td>' + p.perimeter_px + '</td>' +
			'<td>' + p.equiv_diameter_px + '</td>' +
			'<td>' + p.circularity.toFixed(3) + '</td>' +
			'</tr>';
	}).join('');
	if (particleDataCount) particleDataCount.textContent = particles.length + ' hạt / tế bào';
}

// --- 10.7. HÀM CHÍNH: GỌI API /api/particle-count (MỌI XỬ LÝ Ở PYTHON) ---
async function runWatershed() {
	if (!currentFile) {
		showToast('\u26A0\uFE0F Vui lòng tải ảnh lên trước khi thực hiện đếm hạt!');
		return;
	}
	if (particleAbortCtrl) particleAbortCtrl.abort();
	particleAbortCtrl = new AbortController();
	setWatershedRunning(true);

	var formData = new FormData();
	formData.append('file',            currentFile);
	formData.append('method',          wsMethodSelect    ? wsMethodSelect.value    : 'otsu');
	formData.append('threshold',       wsThresholdSlider ? wsThresholdSlider.value : '128');
	formData.append('distance_factor', wsDistanceSlider  ? wsDistanceSlider.value  : '0.45');
	formData.append('min_area',        wsMinAreaSlider   ? wsMinAreaSlider.value   : '20');
	formData.append('show_boundary',   (chkShowBoundary && chkShowBoundary.checked)  ? 'true' : 'false');
	formData.append('show_centroid',   (chkShowCentroid && chkShowCentroid.checked)  ? 'true' : 'false');
	formData.append('show_id',         (chkShowId       && chkShowId.checked)        ? 'true' : 'false');
	formData.append('color_map',       (chkColorMap     && chkColorMap.checked)      ? 'true' : 'false');

	lastParticleFile   = currentFile;
	lastParticleParams = {
		method         : wsMethodSelect    ? wsMethodSelect.value    : 'otsu',
		threshold      : wsThresholdSlider ? wsThresholdSlider.value : '128',
		distance_factor: wsDistanceSlider  ? wsDistanceSlider.value  : '0.45',
		min_area       : wsMinAreaSlider   ? wsMinAreaSlider.value   : '20',
	};

	try {
		var response = await fetch('/api/particle-count', {
			method: 'POST',
			body  : formData,
			signal: particleAbortCtrl.signal,
		});
		if (!response.ok) {
			var errMsg = 'L\u1ED7i server (' + response.status + ')';
			try { var errJson = await response.json(); errMsg = errJson.detail || errMsg; } catch (_) {}
			throw new Error(errMsg);
		}
		var data = await response.json();
		if (data.status !== 'success') throw new Error('Phân tích thất bại. Vui lòng thử lại!');

		renderWatershedImages(data.result_image_b64);
		renderMetricCards(data);
		renderParticleTable(data.particles);
		showToast('\u2713 Phát hiện ' + data.total_count + ' hạt/tế bào | Coverage: ' + data.coverage_pct + '%');
	} catch (error) {
		if (error.name === 'AbortError') return;
		console.error('Lỗi khi phân tích Watershed:', error);
		showToast('\u274C Lỗi: ' + (error.message || 'Không thể kết nối backend!'));
	} finally {
		setWatershedRunning(false);
	}
}

// --- 10.8. XUẤT CSV — GỌI API /api/particle-export-csv (PYTHON XỬ LÝ VÀ STREAM CSV) ---
async function exportParticleCSV() {
	if (!lastParticleFile) {
		showToast('\u26A0\uFE0F Chưa có kết quả đếm hạt. Hãy chạy phân tích trước!');
		return;
	}
	var btn = btnExportDataCsv;
	var originalHtml = btn ? btn.innerHTML : '';
	if (btn) { btn.disabled = true; btn.innerHTML = '<span>Đang xuất...</span>'; }

	var formData = new FormData();
	formData.append('file',            lastParticleFile);
	formData.append('method',          lastParticleParams.method);
	formData.append('threshold',       lastParticleParams.threshold);
	formData.append('distance_factor', lastParticleParams.distance_factor);
	formData.append('min_area',        lastParticleParams.min_area);

	try {
		var response = await fetch('/api/particle-export-csv', { method: 'POST', body: formData });
		if (!response.ok) throw new Error('L\u1ED7i server (' + response.status + ')');
		var blob        = await response.blob();
		var downloadUrl = window.URL.createObjectURL(blob);
		var a = document.createElement('a');
		a.href = downloadUrl;
		a.download = 'particle_measurements.csv';
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		window.URL.revokeObjectURL(downloadUrl);
		showToast('\u2713 Đã xuất file CSV thành công!');
	} catch (error) {
		console.error('Lỗi khi xuất CSV:', error);
		showToast('\u274C Không thể xuất CSV: ' + error.message);
	} finally {
		if (btn) { btn.disabled = false; btn.innerHTML = originalHtml; }
	}
}

// --- 10.9. GẮN SỰ KIỆN ---
if (btnRunWatershed)   btnRunWatershed.addEventListener('click',   runWatershed);
if (btnResetWatershed) btnResetWatershed.addEventListener('click', resetWatershedParams);
if (btnExportDataCsv)  btnExportDataCsv.addEventListener('click',  exportParticleCSV);

// Cập nhật giá trị hiển thị tương tác thời gian thực khi kéo thanh trượt
if (wsThresholdSlider && wsThresholdVal) {
	wsThresholdSlider.addEventListener('input', function(e) {
		wsThresholdVal.textContent = e.target.value;
	});
}

if (wsDistanceSlider && wsDistanceVal) {
	wsDistanceSlider.addEventListener('input', function(e) {
		wsDistanceVal.textContent = e.target.value;
	});
}

if (wsMinAreaSlider && wsMinAreaVal) {
	wsMinAreaSlider.addEventListener('input', function(e) {
		wsMinAreaVal.textContent = e.target.value + ' px²';
	});
}

// Inject CSS animation spinner
(function() {
	var s = document.createElement('style');
	s.textContent = '@keyframes wspin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}';
	document.head.appendChild(s);
})();
