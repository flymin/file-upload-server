FILES_SCRIPT = r"""async function deleteFile(fileId) {
  const confirmed = await openConfirmDialog('Delete this file now?', 'Delete');
  if (!confirmed) return;
  await fetchJson('/web/api/files/' + encodeURIComponent(fileId), { method: 'DELETE' });
  await refreshFiles();
}

async function refreshFiles(options) {
  const opts = options || {};
  if (filesRefreshInFlight) {
    if (!opts.silent) filesRefreshQueued = true;
    return;
  }
  const status = document.getElementById('files-status');
  const list = document.getElementById('files-list');
  const button = document.getElementById('refresh-files-btn');
  filesRefreshInFlight = true;
  if (button) button.disabled = true;
  status.textContent = opts.silent ? 'Auto-refreshing…' : 'Refreshing…';
  if (!opts.silent || !list.innerHTML) {
    list.innerHTML = '<div class="empty">Loading…</div>';
  }
  try {
    const files = await fetchJson('/web/api/files');
    status.textContent = files.length ? ('Loaded ' + files.length + ' file(s). Updated ' + formatRefreshTime() + '.') : 'No files. Updated ' + formatRefreshTime() + '.';
    if (!files.length) {
      list.innerHTML = '<div class="empty">No files available.</div>';
      return;
    }
    list.innerHTML = files.map((item) => {
      const downloadUrl = '/web/api/files/' + encodeURIComponent(item.file_id) + '/download';
      return '<div class="item">'
        + '<div class="item-top">'
        + '<div><div class="item-title">' + escapeHtml(item.original_name) + '</div>'
        + '<div class="item-meta">Uploaded: ' + escapeHtml(formatDate(item.created_at)) + '</div></div>'
        + '<div class="item-actions">'
        + '<a class="button-like secondary" href="' + downloadUrl + '">Download</a>'
        + '<button type="button" class="danger" data-action="delete-file" data-file-id="' + escapeHtml(item.file_id) + '">Delete</button>'
        + '</div>'
        + '</div>'
        + '<div class="file-meta">'
        + '<div>Size: ' + escapeHtml(formatBytes(item.size)) + '</div>'
        + '<div>Type: ' + escapeHtml(item.content_type || 'application/octet-stream') + '</div>'
        + '<div>Delete on: ' + escapeHtml(formatDate(item.expires_at)) + '</div>'
        + '<div>File ID: ' + escapeHtml(item.file_id) + '</div>'
        + '</div>'
        + '</div>';
    }).join('');
  } catch (err) {
    status.textContent = 'Refresh failed: ' + err.message;
    if (!list.innerHTML || !opts.silent) list.innerHTML = '<div class="empty">Failed to load files.</div>';
  } finally {
    filesRefreshInFlight = false;
    if (button) button.disabled = false;
    if (filesRefreshQueued) {
      filesRefreshQueued = false;
      refreshFiles();
    }
  }
}

function refreshVisibleLists(options) {
  if (document.hidden) return;
  const opts = options || {};
  if (activeTabName === 'files') {
    refreshFiles(opts);
  } else {
    refreshClipboard(opts);
  }
}

function startAutoRefresh() {
  if (autoRefreshTimer) window.clearInterval(autoRefreshTimer);
  autoRefreshTimer = window.setInterval(() => {
    refreshVisibleLists({ silent: true });
  }, AUTO_REFRESH_MS);
}

window.addEventListener('DOMContentLoaded', async () => {
  document.getElementById('save-clipboard-btn').addEventListener('click', saveClipboard);
  document.getElementById('file-input').addEventListener('change', handleFileSelection);
  document.getElementById('start-upload-btn').addEventListener('click', startSelectedUploads);
  document.getElementById('clear-upload-selection-btn').addEventListener('click', clearSelectedFiles);
  document.getElementById('refresh-files-btn').addEventListener('click', refreshFiles);
  document.getElementById('refresh-clipboard-btn').addEventListener('click', refreshClipboard);
  document.querySelectorAll('[data-tab]').forEach((button) => {
    button.addEventListener('click', () => switchTab(button.dataset.tab || 'clipboard'));
  });
  document.getElementById('confirm-modal-cancel').addEventListener('click', () => closeConfirmDialog(false));
  document.getElementById('confirm-modal-confirm').addEventListener('click', () => closeConfirmDialog(true));
  document.getElementById('confirm-modal').addEventListener('click', (event) => {
    if (event.target.id === 'confirm-modal') closeConfirmDialog(false);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && confirmModalState) closeConfirmDialog(false);
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refreshVisibleLists({ silent: true });
  });
  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-action]');
    if (!button) return;

    const action = button.dataset.action;
    if (action === 'copy-current') {
      await copyCurrentInput(button);
      return;
    }
    if (action === 'clear-current') {
      clearCurrentInput();
      return;
    }
    if (action === 'fill-clipboard') {
      fillClipboardItem(button.dataset.itemId || '');
      return;
    }
    if (action === 'copy-clipboard') {
      await copyClipboardItem(button.dataset.itemId || '', button);
      return;
    }
    if (action === 'delete-clipboard') {
      await deleteClipboardItem(button.dataset.itemId || '');
      return;
    }
    if (action === 'toggle-clipboard') {
      toggleClipboardExpand(button.dataset.itemId || '');
      return;
    }
    if (action === 'delete-file') {
      await deleteFile(button.dataset.fileId || '');
    }
  });
  renderPendingSelection();
  await refreshClipboard();
  await refreshFiles();
  startAutoRefresh();
});
"""
