// ===========================================================================
// IMAGE VIEWER IUH — FRONTEND CONTROLLER
// Toàn bộ xử lý ảnh (Watershed, Distance Transform, đo lường) nằm ở backend.
// Frontend chỉ thu thập tham số, gọi API và render kết quả.
// ===========================================================================

'use strict';

const $ = (id) => document.getElementById(id);

// --- 1. KẾT NỐI CÁC THÀNH PHẦN GIAO DIỆN -----------------------------------

const mediaInput = $('mediaInput');
const beforePreview = $('beforePreview');
const afterPreview = $('afterPreview');
const sourceMeta = $('sourceMeta');

const zoomSlider = $('zoomSlider');
const zoomValue = $('zoomValue');
const rotateSlider = $('rotateSlider');
const rotateValue = $('rotateValue');
const cropSlider = $('cropSlider');
const cropValue = $('cropValue');
const btnResetTransform = $('btnResetTransform');

const saveButton = $('saveButton');
const historyButton = $('historyButton');
const exportButton = $('exportButton');
const exportFormat = $('exportFormat');

const sessionsModal = $('sessionsModal');
const closeModalBtn = $('closeModalBtn');
const sessionsList = $('sessionsList');
const sessionCountBadge = $('sessionCountBadge');
const toastNotification = $('toastNotification');

const workspaceStatus = $('workspaceStatus');
const afterViewToggle = $('afterViewToggle');
const afterViewLabel = $('afterViewLabel');
const afterLiveIndicator = $('afterLiveIndicator');
const afterLiveLabel = $('afterLiveLabel');
const distanceLegend = $('distanceLegend');
const analysisMeta = $('analysisMeta');
const analysisChip = $('analysisChip');
const analysisStatus = $('analysisStatus');
const pipelineStatus = $('pipelineStatus');

const btnRunWatershed = $('btnRunWatershed');
const btnResetWatershed = $('btnResetWatershed');
const btnExportDataCsv = $('btnExportDataCsv');

const wsMethodSelect = $('wsMethodSelect');
const wsMethodHint = $('wsMethodHint');
const wsThresholdItem = $('wsThresholdItem');
const wsThresholdSlider = $('wsThresholdSlider');
const wsThresholdVal = $('wsThresholdVal');
const wsDistanceSlider = $('wsDistanceSlider');
const wsDistanceVal = $('wsDistanceVal');
const wsMinAreaSlider = $('wsMinAreaSlider');
const wsMinAreaVal = $('wsMinAreaVal');

const chkShowBoundary = $('chkShowBoundary');
const chkShowCentroid = $('chkShowCentroid');
const chkShowId = $('chkShowId');
const chkColorMap = $('chkColorMap');

const metricTotalCount = $('metricTotalCount');
const metricAvgArea = $('metricAvgArea');
const metricCoverage = $('metricCoverage');
const metricCircularity = $('metricCircularity');

const particleTableBody = $('particleTableBody');
const particleDataCount = $('particleDataCount');
const tabParticle = $('tabParticle');

const numberFormatter = new Intl.NumberFormat('vi-VN', {
	maximumFractionDigits: 2,
});

const TABLE_EMPTY_HTML = `
	<tr class="table-placeholder-row">
		<td colspan="7">
			<div class="table-empty-box">
				<span class="empty-table-icon">🔬</span>
				<div class="empty-table-text">Chưa có dữ liệu đếm hạt</div>
				<div class="empty-table-sub">
					Vui lòng tải ảnh và nhấn nút <strong>"Thực hiện đếm hạt"</strong> để hệ thống phân đoạn vi phân và xuất bảng số liệu.
				</div>
			</div>
		</td>
	</tr>`;

const AFTER_EMPTY_HTML = `
	<div class="empty-placeholder">
		<span class="empty-icon">🔬</span>
		<div class="empty-title">Kết quả biến đổi &amp; phân đoạn</div>
		<div class="empty-sub">Ảnh sau khi căn chỉnh hoặc đếm hạt vi phân sẽ hiển thị tại đây.</div>
		<span class="empty-hint">Watershed segmentation</span>
	</div>`;

const state = {
	currentFile: null,
	previewAbort: null,
	previewTimer: null,
	particleAbort: null,
	particleFile: null,
	particleParams: null,
	watershedImages: null,
	activeAfterView: 'transform',
	afterObjectUrl: null,
	beforeObjectUrl: null,
	isAnalyzing: false,
	cachedSessions: [],
};

// --- 2. TIỆN ÍCH HIỂN THỊ ---------------------------------------------------

function formatBytes(bytes) {
	if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB'];
	const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
	const value = bytes / Math.pow(1024, index);
	return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function showToast(message, duration = 3600) {
	if (!toastNotification) return;
	toastNotification.textContent = message;
	toastNotification.classList.add('show');
	window.clearTimeout(showToast._timer);
	showToast._timer = window.setTimeout(() => {
		toastNotification.classList.remove('show');
	}, duration);
}

function setButtonBusy(button, busy, busyLabel = 'Đang xử lý...') {
	if (!button) return;
	if (busy) {
		if (!button.dataset.idleHtml) {
			button.dataset.idleHtml = button.innerHTML;
		}
		button.disabled = true;
		button.classList.add('is-busy');
		button.innerHTML =
			`<span class="btn-spinner" aria-hidden="true"></span><span>${busyLabel}</span>`;
	} else {
		button.disabled = false;
		button.classList.remove('is-busy');
		if (button.dataset.idleHtml) {
			button.innerHTML = button.dataset.idleHtml;
			delete button.dataset.idleHtml;
		}
	}
}

function setWorkspaceStatus(stateName, text) {
	if (!workspaceStatus) return;
	workspaceStatus.dataset.state = stateName;
	workspaceStatus.innerHTML = `<span class="status-dot"></span> ${text}`;
}

function setPipelineStatus(stateName, text) {
	if (!pipelineStatus) return;
	pipelineStatus.dataset.state = stateName;
	pipelineStatus.innerHTML = `<span></span> ${text}`;
}

function setAnalysisStatus(stateName, text) {
	if (!analysisStatus) return;
	analysisStatus.dataset.state = stateName;
	const textEl = analysisStatus.querySelector('.analysis-status-text');
	if (textEl) textEl.textContent = text;
}

function setAfterIndicator(stateName, text) {
	if (!afterLiveIndicator) return;
	afterLiveIndicator.dataset.state = stateName;
	if (afterLiveLabel) afterLiveLabel.textContent = text;
}

function setResultChip(stateName, text) {
	if (!analysisChip) return;
	analysisChip.dataset.state = stateName;
	analysisChip.textContent = text;
}

function updateRangeFill(input) {
	if (!input) return;
	const min = Number.parseFloat(input.min || '0');
	const max = Number.parseFloat(input.max || '100');
	const value = Number.parseFloat(input.value || '0');
	const percent = max > min ? ((value - min) / (max - min)) * 100 : 0;
	input.style.setProperty('--fill', `${Math.max(0, Math.min(100, percent))}%`);
}

function refreshAllRangeFills() {
	document.querySelectorAll('input[type="range"]').forEach(updateRangeFill);
}

function setBeforeImage(src, { objectUrl = false } = {}) {
	if (!beforePreview) return;
	if (state.beforeObjectUrl) {
		URL.revokeObjectURL(state.beforeObjectUrl);
		state.beforeObjectUrl = null;
	}
	if (objectUrl) state.beforeObjectUrl = src;

	beforePreview.classList.remove('empty');
	beforePreview.innerHTML = '';
	const img = document.createElement('img');
	img.src = src;
	img.alt = 'Ảnh gốc được chọn';
	img.decoding = 'async';
	beforePreview.appendChild(img);
}

function setAfterImage(src, { objectUrl = false, alt = 'Kết quả phân tích' } = {}) {
	if (!afterPreview) return;
	if (state.afterObjectUrl) {
		URL.revokeObjectURL(state.afterObjectUrl);
		state.afterObjectUrl = null;
	}
	if (objectUrl) state.afterObjectUrl = src;

	afterPreview.classList.remove('empty', 'is-processing');
	afterPreview.innerHTML = '';
	const img = document.createElement('img');
	img.src = src;
	img.alt = alt;
	img.decoding = 'async';
	afterPreview.appendChild(img);
}

function setAfterPlaceholder(icon, title, sub, hint = 'Watershed segmentation') {
	if (!afterPreview) return;
	afterPreview.classList.add('empty');
	afterPreview.classList.remove('is-processing');
	afterPreview.innerHTML = `
		<div class="empty-placeholder">
			<span class="empty-icon">${icon}</span>
			<div class="empty-title">${title}</div>
			<div class="empty-sub">${sub}</div>
			<span class="empty-hint">${hint}</span>
		</div>`;
}

function resetAnalysisUI() {
	state.watershedImages = null;
	state.particleFile = null;
	state.particleParams = null;
	state.activeAfterView = 'transform';

	if (afterViewToggle) afterViewToggle.hidden = true;
	if (distanceLegend) distanceLegend.hidden = true;
	if (afterViewLabel) afterViewLabel.textContent = 'Watershed · Distance Transform';
	setAfterIndicator('ready', 'Ready');
	setResultChip('idle', 'Idle');
	setAnalysisStatus('idle', 'Chưa phân tích');
	setPipelineStatus('idle', 'Chờ ảnh');

	if (analysisMeta) analysisMeta.textContent = 'Chưa có dữ liệu phân tích';
	if (metricTotalCount) metricTotalCount.textContent = '--';
	if (metricAvgArea) metricAvgArea.textContent = '--';
	if (metricCoverage) metricCoverage.textContent = '--';
	if (metricCircularity) metricCircularity.textContent = '--';
	if (particleDataCount) particleDataCount.textContent = '0 kết quả';
	if (particleTableBody) particleTableBody.innerHTML = TABLE_EMPTY_HTML;
}

// --- 3. TẢI ẢNH & PREVIEW BIẾN ĐỔI ----------------------------------------

function handleFile(file) {
	if (!file) return;

	const looksLikeImage =
		(file.type && file.type.startsWith('image/')) ||
		/\.(jpe?g|png|webp|bmp|gif|tiff?)$/i.test(file.name || '');
	if (!looksLikeImage) {
		showToast('⚠️ File không phải ảnh. Vui lòng chọn JPG, PNG, WEBP hoặc BMP.');
		return;
	}

	// Hủy yêu cầu cũ nếu người dùng chọn ảnh mới
	if (state.previewAbort) {
		state.previewAbort.abort();
		state.previewAbort = null;
	}
	if (state.particleAbort) {
		state.particleAbort.abort();
		state.particleAbort = null;
	}
	if (state.isAnalyzing) setWatershedRunning(false);

	state.currentFile = file;
	resetAnalysisUI();
	setWorkspaceStatus('ready', 'Sẵn sàng');
	if (sourceMeta) {
		sourceMeta.textContent = `${file.name || 'Ảnh'} · ${formatBytes(file.size)}`;
	}

	const reader = new FileReader();
	reader.onload = (event) => {
		setBeforeImage(event.target.result);
		sendToBackend();
	};
	reader.onerror = () => {
		showToast('❌ Không thể đọc file ảnh này.');
	};
	reader.readAsDataURL(file);

	// Cho phép chọn lại đúng file vừa chọn ở lần sau
	mediaInput.value = '';
}

if (mediaInput) {
	mediaInput.addEventListener('change', (event) => {
		handleFile(event.target.files && event.target.files[0]);
	});
}

if (beforePreview) {
	// Kéo thả ảnh vào khung Before
	['dragenter', 'dragover'].forEach((eventName) => {
		beforePreview.addEventListener(eventName, (event) => {
			event.preventDefault();
			event.stopPropagation();
			beforePreview.classList.add('is-dragover');
		});
	});

	['dragleave', 'drop'].forEach((eventName) => {
		beforePreview.addEventListener(eventName, (event) => {
			event.preventDefault();
			event.stopPropagation();
			beforePreview.classList.remove('is-dragover');
		});
	});

	beforePreview.addEventListener('drop', (event) => {
		const file = event.dataTransfer && event.dataTransfer.files
			? event.dataTransfer.files[0]
			: null;
		if (file) handleFile(file);
	});

	// Bấm vào khung trống để mở hộp chọn file
	beforePreview.addEventListener('click', () => {
		if (beforePreview.classList.contains('empty') && mediaInput) {
			mediaInput.click();
		}
	});

	beforePreview.addEventListener('keydown', (event) => {
		if ((event.key === 'Enter' || event.key === ' ') && beforePreview.classList.contains('empty')) {
			event.preventDefault();
			if (mediaInput) mediaInput.click();
		}
	});
}

// Ngăn trình duyệt mở ảnh khi người dùng kéo thả ra ngoài khung
['dragover', 'drop'].forEach((eventName) => {
	document.addEventListener(eventName, (event) => {
		if (event.target !== beforePreview && !beforePreview?.contains(event.target)) {
			event.preventDefault();
		}
	});
});

let previewTimeoutId = null;

function handleSliderInput(input, valueElement, suffix) {
	if (valueElement) valueElement.textContent = `${input.value}${suffix}`;
	updateRangeFill(input);
	window.clearTimeout(previewTimeoutId);
	previewTimeoutId = window.setTimeout(() => {
		sendToBackend();
	}, 140);
}

if (zoomSlider) {
	zoomSlider.addEventListener('input', () => handleSliderInput(zoomSlider, zoomValue, '%'));
}
if (rotateSlider) {
	rotateSlider.addEventListener('input', () => handleSliderInput(rotateSlider, rotateValue, '°'));
}
if (cropSlider) {
	cropSlider.addEventListener('input', () => handleSliderInput(cropSlider, cropValue, '%'));
}

async function sendToBackend() {
	if (!state.currentFile) return;

	if (state.previewAbort) state.previewAbort.abort();
	const controller = new AbortController();
	state.previewAbort = controller;

	const formData = new FormData();
	formData.append('file', state.currentFile);
	formData.append('zoom', zoomSlider ? zoomSlider.value : '100');
	formData.append('rotate', rotateSlider ? rotateSlider.value : '0');
	formData.append('crop', cropSlider ? cropSlider.value : '0');

	if (afterPreview) afterPreview.classList.add('is-processing');
	if (!state.isAnalyzing) setWorkspaceStatus('running', 'Đang cập nhật preview');

	try {
		const response = await fetch('/api/process-image', {
			method: 'POST',
			body: formData,
			signal: controller.signal,
		});

		if (!response.ok) {
			throw new Error(`Không thể tạo preview (${response.status}).`);
		}

		const blob = await response.blob();
		const imageUrl = URL.createObjectURL(blob);
		setAfterImage(imageUrl, { objectUrl: true, alt: 'Ảnh sau biến đổi' });
		state.activeAfterView = 'transform';
		updateAfterViewButtons(null);
		if (distanceLegend) distanceLegend.hidden = true;
		if (afterViewLabel) afterViewLabel.textContent = 'Ảnh biến đổi · Preview';
		setAfterIndicator('ready', 'Preview');
		setResultChip('idle', 'Preview');
		if (!state.isAnalyzing) setWorkspaceStatus('ready', 'Sẵn sàng');
	} catch (error) {
		if (error.name === 'AbortError') return;
		if (state.previewAbort !== controller) return;
		console.error('Lỗi preview:', error);
		if (afterPreview) afterPreview.classList.remove('is-processing');
		if (!state.isAnalyzing) setWorkspaceStatus('error', 'Lỗi preview');
		showToast(`❌ ${error.message || 'Không thể kết nối backend.'}`);
	} finally {
		if (state.previewAbort === controller) {
			if (afterPreview) afterPreview.classList.remove('is-processing');
			state.previewAbort = null;
		}
	}
}

if (btnResetTransform) {
	btnResetTransform.addEventListener('click', () => {
		if (zoomSlider) zoomSlider.value = '100';
		if (rotateSlider) rotateSlider.value = '0';
		if (cropSlider) cropSlider.value = '0';
		if (zoomValue) zoomValue.textContent = '100%';
		if (rotateValue) rotateValue.textContent = '0°';
		if (cropValue) cropValue.textContent = '0%';
		refreshAllRangeFills();
		showToast('↺ Đã đặt lại Zoom / Rotate / Crop.');
		sendToBackend();
	});
}

// --- 4. LƯU PHIÊN & XUẤT ẢNH ----------------------------------------------

async function saveSession() {
	if (!state.currentFile) {
		showToast('⚠️ Vui lòng tải ảnh lên trước khi lưu phiên.');
		return;
	}

	setButtonBusy(saveButton, true, 'Đang lưu...');
	const formData = new FormData();
	formData.append('file', state.currentFile);
	formData.append('zoom', zoomSlider ? zoomSlider.value : '100');
	formData.append('rotate', rotateSlider ? rotateSlider.value : '0');
	formData.append('crop', cropSlider ? cropSlider.value : '0');

	try {
		const response = await fetch('/api/save-session', {
			method: 'POST',
			body: formData,
		});
		if (!response.ok) throw new Error('Server không lưu được phiên.');
		await response.json();
		showToast('✓ Đã lưu phiên làm việc vào máy chủ.');
	} catch (error) {
		console.error('Lỗi lưu phiên:', error);
		showToast(`❌ ${error.message || 'Có lỗi khi lưu phiên.'}`);
	} finally {
		setButtonBusy(saveButton, false);
	}
}

async function downloadProcessedImage(targetFormat, triggerBtn) {
	if (!state.currentFile) {
		showToast('⚠️ Vui lòng tải ảnh lên trước khi xuất file.');
		return;
	}

	setButtonBusy(triggerBtn, true, 'Đang xuất...');
	const formData = new FormData();
	formData.append('file', state.currentFile);
	formData.append('zoom', zoomSlider ? zoomSlider.value : '100');
	formData.append('rotate', rotateSlider ? rotateSlider.value : '0');
	formData.append('crop', cropSlider ? cropSlider.value : '0');
	formData.append('format', targetFormat);

	try {
		const response = await fetch('/api/export-image', {
			method: 'POST',
			body: formData,
		});
		if (!response.ok) {
			const errorText = await response.text().catch(() => '');
			throw new Error(errorText || 'Server không xuất được ảnh.');
		}

		let filename = '';
		const disposition = response.headers.get('Content-Disposition');
		if (disposition) {
			const utf8Match = disposition.match(/filename\*=utf-8''([^;]+)/i);
			if (utf8Match && utf8Match[1]) {
				filename = decodeURIComponent(utf8Match[1]);
			} else {
				const asciiMatch = disposition.match(/filename="?([^";]+)"?/);
				if (asciiMatch && asciiMatch[1]) filename = asciiMatch[1];
			}
		}
		if (!filename) {
			const dotIndex = state.currentFile.name.lastIndexOf('.');
			const stem = dotIndex !== -1
				? state.currentFile.name.substring(0, dotIndex)
				: state.currentFile.name;
			filename = `${stem}_edited.${targetFormat}`;
		}

		const blob = await response.blob();
		const downloadUrl = URL.createObjectURL(blob);
		const anchor = document.createElement('a');
		anchor.href = downloadUrl;
		anchor.download = filename;
		document.body.appendChild(anchor);
		anchor.click();
		document.body.removeChild(anchor);
		URL.revokeObjectURL(downloadUrl);
		showToast(`✓ Đã xuất file: ${filename}`);
	} catch (error) {
		console.error('Lỗi xuất ảnh:', error);
		showToast(`❌ ${error.message || 'Có lỗi khi xuất ảnh.'}`);
	} finally {
		setButtonBusy(triggerBtn, false);
	}
}

// --- 5. QUẢN LÝ PHIÊN LÀM VIỆC --------------------------------------------

function escapeHtml(value) {
	if (value === null || value === undefined) return '';
	return String(value)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#039;');
}

function openModal() {
	if (!sessionsModal) return;
	sessionsModal.classList.add('active');
	document.body.classList.add('modal-open');
	fetchAndRenderSessions();
	if (closeModalBtn) closeModalBtn.focus();
}

function closeModal() {
	if (!sessionsModal) return;
	sessionsModal.classList.remove('active');
	document.body.classList.remove('modal-open');
}

async function fetchAndRenderSessions() {
	if (!sessionsList) return;
	sessionsList.innerHTML = '<div class="sessions-empty"><p>Đang tải danh sách phiên...</p></div>';

	try {
		const response = await fetch('/api/sessions');
		if (!response.ok) throw new Error('Không thể tải danh sách phiên.');
		const data = await response.json();
		state.cachedSessions = data.sessions || [];

		if (sessionCountBadge) sessionCountBadge.textContent = state.cachedSessions.length;

		if (state.cachedSessions.length === 0) {
			sessionsList.innerHTML = `
				<div class="sessions-empty">
					<span class="sessions-empty-icon">📂</span>
					<p>Chưa có phiên làm việc nào được lưu.</p>
					<small>Bấm nút <strong>Lưu phiên</strong> để lưu phiên chỉnh sửa hiện tại.</small>
				</div>`;
			return;
		}

		sessionsList.innerHTML = state.cachedSessions
			.map((session) => {
				const safeFilename = escapeHtml(session.filename || 'Ảnh không tên');
				const safeDate = escapeHtml(session.created_at_display || session.created_at || '');
				const safeId = escapeHtml(session.id);
				return `
					<div class="session-item" id="session-card-${safeId}">
						<img class="session-thumb" src="/api/sessions/${safeId}/thumbnail" alt="Thumbnail phiên ${safeFilename}" loading="lazy" />
						<div class="session-info">
							<div class="session-filename" title="${safeFilename}">${safeFilename}</div>
							<div class="session-date">${safeDate}</div>
							<div class="session-badges">
								<span class="param-badge">Zoom: ${escapeHtml(session.zoom)}%</span>
								<span class="param-badge">Rotate: ${escapeHtml(session.rotate)}°</span>
								<span class="param-badge">Crop: ${escapeHtml(session.crop)}%</span>
							</div>
						</div>
						<div class="session-actions">
							<button type="button" class="session-btn session-load-btn" onclick="restoreSession('${safeId}')">Load</button>
							<button type="button" class="session-btn session-delete-btn" onclick="deleteSession('${safeId}')">Delete</button>
						</div>
					</div>`;
			})
			.join('');
	} catch (error) {
		console.error('Lỗi tải sessions:', error);
		sessionsList.innerHTML =
			'<div class="sessions-empty" style="color:#be123c;"><p>Không thể tải danh sách phiên làm việc.</p></div>';
	}
}

async function restoreSession(sessionId) {
	const session = state.cachedSessions.find((item) => item.id === sessionId);
	if (!session) return;

	try {
		showToast('Đang khôi phục phiên làm việc...');
		const response = await fetch(`/api/sessions/${sessionId}/original`);
		if (!response.ok) throw new Error('Không thể tải ảnh gốc của phiên.');

		const blob = await response.blob();
		const restoredFile = new File([blob], session.filename || 'restored-image.png', {
			type: blob.type || 'image/png',
		});

		state.currentFile = restoredFile;
		resetAnalysisUI();

		if (zoomSlider) zoomSlider.value = session.zoom;
		if (zoomValue) zoomValue.textContent = `${session.zoom}%`;

		if (rotateSlider) rotateSlider.value = session.rotate;
		if (rotateValue) rotateValue.textContent = `${session.rotate}°`;

		if (cropSlider) cropSlider.value = session.crop;
		if (cropValue) cropValue.textContent = `${session.crop}%`;

		refreshAllRangeFills();

		if (sourceMeta) {
			sourceMeta.textContent = `${restoredFile.name} · ${formatBytes(restoredFile.size)}`;
		}

		const reader = new FileReader();
		reader.onload = (event) => {
			setBeforeImage(event.target.result);
			afterPreview.innerHTML = AFTER_EMPTY_HTML;
			afterPreview.classList.add('empty');
			sendToBackend();
		};
		reader.readAsDataURL(restoredFile);

		if (mediaInput) mediaInput.value = '';
		closeModal();
		showToast(`✓ Đã khôi phục phiên: ${session.filename}`);
	} catch (error) {
		console.error('Lỗi khôi phục phiên:', error);
		showToast(`❌ ${error.message || 'Không thể khôi phục phiên.'}`);
	}
}

async function deleteSession(sessionId) {
	if (!window.confirm('Bạn có chắc chắn muốn xóa phiên làm việc này khỏi máy chủ?')) return;

	try {
		const response = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
		if (!response.ok) throw new Error('Không thể xóa phiên làm việc.');
		showToast('Đã xóa phiên làm việc.');
		fetchAndRenderSessions();
	} catch (error) {
		console.error('Lỗi xóa phiên:', error);
		showToast(`❌ ${error.message || 'Có lỗi khi xóa phiên.'}`);
	}
}

window.restoreSession = restoreSession;
window.deleteSession = deleteSession;

if (saveButton) saveButton.addEventListener('click', saveSession);
if (historyButton) historyButton.addEventListener('click', openModal);
if (closeModalBtn) closeModalBtn.addEventListener('click', closeModal);
if (sessionsModal) {
	sessionsModal.addEventListener('click', (event) => {
		if (event.target === sessionsModal) closeModal();
	});
}
if (exportButton) {
	exportButton.addEventListener('click', () => {
		const format = exportFormat ? exportFormat.value : 'jpg';
		downloadProcessedImage(format, exportButton);
	});
}

// --- 6. WATERSHED — THAM SỐ & ĐIỀU KHIỂN ----------------------------------

const METHOD_HINTS = {
	otsu: 'Otsu tự động tìm ngưỡng tối ưu cho ảnh nền sáng, vật thể tối.',
	adaptive: 'Phù hợp ảnh chiếu sáng không đều — ngưỡng được tính theo từng vùng 11×11.',
	triangle: 'Tốt cho histogram lệch, ảnh có ít vật thể trên nền lớn.',
	manual: 'Dùng giá trị ngưỡng cố định bên dưới. Kéo slider để tinh chỉnh.',
};

function syncMethodUI() {
	if (!wsMethodSelect) return;
	const method = wsMethodSelect.value || 'otsu';
	const isManual = method === 'manual';

	if (wsMethodHint) {
		wsMethodHint.textContent = METHOD_HINTS[method] || METHOD_HINTS.otsu;
	}
	if (wsThresholdItem) {
		wsThresholdItem.classList.toggle('is-muted', !isManual);
	}
	if (wsThresholdSlider) {
		wsThresholdSlider.disabled = !isManual;
		if (!isManual) updateRangeFill(wsThresholdSlider);
	}
}

function resetWatershedParams() {
	if (wsMethodSelect) wsMethodSelect.value = 'otsu';
	if (wsThresholdSlider) wsThresholdSlider.value = '128';
	if (wsThresholdVal) wsThresholdVal.textContent = '128';
	if (wsDistanceSlider) wsDistanceSlider.value = '0.45';
	if (wsDistanceVal) wsDistanceVal.textContent = '0.45';
	if (wsMinAreaSlider) wsMinAreaSlider.value = '20';
	if (wsMinAreaVal) wsMinAreaVal.textContent = '20 px²';
	if (chkShowBoundary) chkShowBoundary.checked = true;
	if (chkShowCentroid) chkShowCentroid.checked = true;
	if (chkShowId) chkShowId.checked = true;
	if (chkColorMap) chkColorMap.checked = false;
	syncMethodUI();
	refreshAllRangeFills();
	showToast('↺ Đã đặt lại tham số Watershed về mặc định.');
}

function collectParticleParams() {
	const method = wsMethodSelect ? wsMethodSelect.value : 'otsu';
	return {
		method,
		threshold: wsThresholdSlider ? wsThresholdSlider.value : '128',
		distance_factor: wsDistanceSlider ? wsDistanceSlider.value : '0.45',
		min_area: wsMinAreaSlider ? wsMinAreaSlider.value : '20',
		show_boundary: chkShowBoundary ? chkShowBoundary.checked : true,
		show_centroid: chkShowCentroid ? chkShowCentroid.checked : true,
		show_id: chkShowId ? chkShowId.checked : true,
		color_map: chkColorMap ? chkColorMap.checked : false,
	};
}

function updateAfterViewButtons(activeView) {
	document.querySelectorAll('[data-after-view]').forEach((button) => {
		const isActive = button.dataset.afterView === activeView;
		button.classList.toggle('is-active', isActive);
		button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
	});
}

function showAfterView(view) {
	if (!state.watershedImages) return;
	const base64 = view === 'distance'
		? state.watershedImages.distance
		: state.watershedImages.result;
	if (!base64) return;

	state.activeAfterView = view;
	setAfterImage(`data:image/jpeg;base64,${base64}`, {
		alt: view === 'distance' ? 'Bản đồ Distance Transform' : 'Kết quả phân đoạn Watershed',
	});
	updateAfterViewButtons(view);
	if (distanceLegend) distanceLegend.hidden = view !== 'distance';
	if (afterViewLabel) {
		afterViewLabel.textContent = view === 'distance'
			? 'Distance Transform · Bản đồ khoảng cách'
			: 'Watershed · Viền phân đoạn & #ID';
	}
	setAfterIndicator('ready', view === 'distance' ? 'Distance' : 'Watershed');
}

function setWatershedRunning(isRunning) {
	state.isAnalyzing = isRunning;
	setButtonBusy(btnRunWatershed, isRunning, 'Đang phân tích...');
	if (btnResetWatershed) btnResetWatershed.disabled = isRunning;

	if (isRunning) {
		if (afterPreview) afterPreview.classList.add('is-processing');
		setWorkspaceStatus('running', 'Đang phân tích');
		setPipelineStatus('running', 'Đang xử lý...');
		setAnalysisStatus('running', 'Đang phân tích...');
		setAfterIndicator('busy', 'Analyzing');
		setResultChip('running', 'Đang chạy');
	} else {
		if (afterPreview) afterPreview.classList.remove('is-processing');
	}
}

function renderMetricCards(data) {
	if (metricTotalCount) metricTotalCount.textContent = numberFormatter.format(data.total_count || 0);
	if (metricAvgArea) metricAvgArea.textContent = numberFormatter.format(data.avg_area || 0);
	if (metricCoverage) {
		metricCoverage.textContent = `${numberFormatter.format(data.coverage_pct || 0)}%`;
	}
	if (metricCircularity) {
		const value = Number(data.avg_circularity || 0);
		metricCircularity.textContent = value.toFixed(3);
	}
}

function renderParticleTable(particles) {
	if (!particleTableBody) return;

	if (!particles || particles.length === 0) {
		particleTableBody.innerHTML = `
			<tr class="table-placeholder-row">
				<td colspan="7">
					<div class="table-empty-box">
						<span class="empty-table-icon">⚠️</span>
						<div class="empty-table-text">Không phát hiện được hạt nào</div>
						<div class="empty-table-sub">Hãy thử giảm <strong>Min Area</strong>, đổi <strong>phương pháp phân ngưỡng</strong> hoặc giảm <strong>Distance Factor</strong>.</div>
					</div>
				</td>
			</tr>`;
		if (particleDataCount) particleDataCount.textContent = '0 kết quả';
		return;
	}

	particleTableBody.innerHTML = particles
		.map((particle) => `
			<tr>
				<td>#${particle.id}</td>
				<td>${numberFormatter.format(particle.cx)}</td>
				<td>${numberFormatter.format(particle.cy)}</td>
				<td>${numberFormatter.format(particle.area_px)}</td>
				<td>${numberFormatter.format(particle.perimeter_px)}</td>
				<td>${numberFormatter.format(particle.equiv_diameter_px)}</td>
				<td>${Number(particle.circularity || 0).toFixed(3)}</td>
			</tr>`)
		.join('');

	if (particleDataCount) {
		particleDataCount.textContent = `${particles.length} hạt / tế bào`;
	}
}

async function runWatershed() {
	if (!state.currentFile) {
		showToast('⚠️ Vui lòng tải ảnh lên trước khi thực hiện đếm hạt.');
		return;
	}

	if (state.particleAbort) state.particleAbort.abort();
	const controller = new AbortController();
	state.particleAbort = controller;

	const fileAtRequest = state.currentFile;
	const params = collectParticleParams();

	const formData = new FormData();
	formData.append('file', fileAtRequest);
	formData.append('method', params.method);
	formData.append('threshold', params.threshold);
	formData.append('distance_factor', params.distance_factor);
	formData.append('min_area', params.min_area);
	formData.append('show_boundary', params.show_boundary ? 'true' : 'false');
	formData.append('show_centroid', params.show_centroid ? 'true' : 'false');
	formData.append('show_id', params.show_id ? 'true' : 'false');
	formData.append('color_map', params.color_map ? 'true' : 'false');

	setWatershedRunning(true);

	try {
		const response = await fetch('/api/particle-count', {
			method: 'POST',
			body: formData,
			signal: controller.signal,
		});

		if (!response.ok) {
			let message = `Lỗi server (${response.status})`;
			try {
				const errorJson = await response.json();
				message = errorJson.detail || message;
			} catch (_) {
				// Giữ message mặc định khi response không phải JSON
			}
			throw new Error(message);
		}

		const data = await response.json();
		if (data.status !== 'success') {
			throw new Error('Phân tích thất bại. Vui lòng thử lại.');
		}
		if (state.particleAbort !== controller) return;

		state.watershedImages = {
			result: data.result_image_b64,
			distance: data.dist_image_b64,
		};
		state.particleFile = fileAtRequest;
		state.particleParams = {
			method: params.method,
			threshold: params.threshold,
			distance_factor: params.distance_factor,
			min_area: params.min_area,
		};

		if (afterViewToggle) afterViewToggle.hidden = false;
		showAfterView('result');

		renderMetricCards(data);
		renderParticleTable(data.particles);

		if (analysisMeta) {
			const methodLabel = (data.method || params.method || 'otsu').toUpperCase();
			analysisMeta.textContent =
				`${data.image_width}×${data.image_height}px · ${data.processing_ms} ms · ${methodLabel}`;
		}

		setResultChip('success', 'Hoàn tất');
		setAnalysisStatus('success', `Đã phân tích ${data.total_count} hạt`);
		setPipelineStatus('success', `Hoàn tất · ${data.total_count} hạt`);
		setWorkspaceStatus('ready', 'Sẵn sàng');

		showToast(
			`✓ Phát hiện ${data.total_count} hạt/tế bào | Coverage: ${data.coverage_pct}%`
		);
	} catch (error) {
		if (error.name === 'AbortError') return;
		if (state.particleAbort !== controller) return;
		console.error('Lỗi phân tích Watershed:', error);
		setResultChip('error', 'Lỗi');
		setAnalysisStatus('error', 'Phân tích thất bại');
		setPipelineStatus('error', 'Lỗi xử lý');
		setAfterIndicator('error', 'Failed');
		setWorkspaceStatus('error', 'Lỗi phân tích');
		showToast(`❌ ${error.message || 'Không thể kết nối backend.'}`);
	} finally {
		if (state.particleAbort === controller) {
			state.particleAbort = null;
			setWatershedRunning(false);
		}
	}
}

async function exportParticleCSV() {
	if (!state.particleFile || !state.particleParams) {
		showToast('⚠️ Chưa có kết quả đếm hạt. Hãy chạy phân tích trước.');
		return;
	}

	setButtonBusy(btnExportDataCsv, true, 'Đang xuất...');
	const formData = new FormData();
	formData.append('file', state.particleFile);
	formData.append('method', state.particleParams.method);
	formData.append('threshold', state.particleParams.threshold);
	formData.append('distance_factor', state.particleParams.distance_factor);
	formData.append('min_area', state.particleParams.min_area);

	try {
		const response = await fetch('/api/particle-export-csv', {
			method: 'POST',
			body: formData,
		});
		if (!response.ok) throw new Error(`Lỗi server (${response.status}).`);

		const blob = await response.blob();
		const downloadUrl = URL.createObjectURL(blob);
		const anchor = document.createElement('a');
		anchor.href = downloadUrl;
		anchor.download = 'particle_measurements.csv';
		document.body.appendChild(anchor);
		anchor.click();
		document.body.removeChild(anchor);
		URL.revokeObjectURL(downloadUrl);
		showToast('✓ Đã xuất file CSV thành công.');
	} catch (error) {
		console.error('Lỗi xuất CSV:', error);
		showToast(`❌ Không thể xuất CSV: ${error.message || 'Vui lòng thử lại.'}`);
	} finally {
		setButtonBusy(btnExportDataCsv, false);
	}
}

// --- 7. GẮN SỰ KIỆN WATERSHED --------------------------------------------

if (btnRunWatershed) btnRunWatershed.addEventListener('click', runWatershed);
if (btnResetWatershed) btnResetWatershed.addEventListener('click', resetWatershedParams);
if (btnExportDataCsv) btnExportDataCsv.addEventListener('click', exportParticleCSV);

if (wsMethodSelect) {
	wsMethodSelect.addEventListener('change', syncMethodUI);
}

if (wsThresholdSlider) {
	wsThresholdSlider.addEventListener('input', (event) => {
		if (wsThresholdVal) wsThresholdVal.textContent = event.target.value;
		updateRangeFill(event.target);
	});
}

if (wsDistanceSlider) {
	wsDistanceSlider.addEventListener('input', (event) => {
		if (wsDistanceVal) wsDistanceVal.textContent = event.target.value;
		updateRangeFill(event.target);
	});
}

if (wsMinAreaSlider) {
	wsMinAreaSlider.addEventListener('input', (event) => {
		if (wsMinAreaVal) wsMinAreaVal.textContent = `${event.target.value} px²`;
		updateRangeFill(event.target);
	});
}

if (afterViewToggle) {
	afterViewToggle.addEventListener('click', (event) => {
		const button = event.target.closest('[data-after-view]');
		if (!button) return;
		showAfterView(button.dataset.afterView);
	});
}

// --- 8. PHÍM TẮT & KHỞI TẠO ----------------------------------------------

document.addEventListener('keydown', (event) => {
	// Ctrl/Cmd + Enter: chạy nhanh phân tích khi đang ở tab Đếm hạt
	if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
		if (sessionsModal && sessionsModal.classList.contains('active')) return;
		event.preventDefault();
		if (tabParticle) tabParticle.checked = true;
		runWatershed();
		return;
	}

	// Escape: đóng modal
	if (event.key === 'Escape' && sessionsModal && sessionsModal.classList.contains('active')) {
		closeModal();
	}
});

refreshAllRangeFills();
syncMethodUI();
resetAnalysisUI();
setWorkspaceStatus('ready', 'Sẵn sàng');
