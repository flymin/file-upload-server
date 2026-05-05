COMMON_SCRIPT = r"""const pendingFiles = [];
let clipboardItemsCache = [];
let confirmModalState = null;
let activeTabName = 'clipboard';
let clipboardRefreshInFlight = false;
let filesRefreshInFlight = false;
let clipboardRefreshQueued = false;
let filesRefreshQueued = false;
let autoRefreshTimer = null;

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatBytes(value) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = Number(value || 0);
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  if (index === 0) return Math.round(size) + ' ' + units[index];
  return size.toFixed(1) + ' ' + units[index];
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatRefreshTime() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

async function fetchJson(url, options) {
  const response = await fetch(url, options || {});
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_err) { data = null; }
  if (!response.ok) {
    const detail = data && data.detail ? data.detail : text || response.statusText;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

function openConfirmDialog(message, confirmLabel) {
  const overlay = document.getElementById('confirm-modal');
  const messageEl = document.getElementById('confirm-modal-message');
  const confirmButton = document.getElementById('confirm-modal-confirm');
  const cancelButton = document.getElementById('confirm-modal-cancel');

  if (!overlay || !messageEl || !confirmButton || !cancelButton) {
    return Promise.resolve(false);
  }

  messageEl.textContent = message || 'Are you sure?';
  confirmButton.textContent = confirmLabel || 'Delete';
  overlay.classList.add('open');
  overlay.setAttribute('aria-hidden', 'false');

  return new Promise((resolve) => {
    confirmModalState = { resolve };
  });
}

function closeConfirmDialog(confirmed) {
  const overlay = document.getElementById('confirm-modal');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
  }
  if (confirmModalState && typeof confirmModalState.resolve === 'function') {
    confirmModalState.resolve(Boolean(confirmed));
  }
  confirmModalState = null;
}

function switchTab(tabName) {
  const isClipboard = tabName !== 'files';
  activeTabName = isClipboard ? 'clipboard' : 'files';
  document.getElementById('tab-clipboard').classList.toggle('active', isClipboard);
  document.getElementById('tab-files').classList.toggle('active', !isClipboard);
  document.getElementById('panel-clipboard').classList.toggle('active', isClipboard);
  document.getElementById('panel-files').classList.toggle('active', !isClipboard);
  if (isClipboard) {
    refreshClipboard({ silent: true });
  } else {
    refreshFiles({ silent: true });
  }
}

function flashButtonText(button, nextText, durationMs) {
  if (!button) return;
  const originalText = button.dataset.originalText || button.textContent || '';
  if (!button.dataset.originalText) button.dataset.originalText = originalText;
  if (button.__flashTimer) window.clearTimeout(button.__flashTimer);
  button.textContent = nextText;
  button.__flashTimer = window.setTimeout(() => {
    button.textContent = button.dataset.originalText || originalText;
    button.__flashTimer = null;
  }, durationMs || 1200);
}

"""
