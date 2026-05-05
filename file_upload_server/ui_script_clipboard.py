CLIPBOARD_SCRIPT = r"""function getClipboardItem(itemId) {
  return clipboardItemsCache.find((item) => String(item.id) === String(itemId));
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const helper = document.createElement('textarea');
  helper.value = text;
  helper.setAttribute('readonly', 'readonly');
  helper.style.position = 'fixed';
  helper.style.opacity = '0';
  document.body.appendChild(helper);
  helper.focus();
  helper.select();
  const ok = document.execCommand('copy');
  document.body.removeChild(helper);
  if (!ok) throw new Error('Copy failed');
}

function shouldCollapseText(text) {
  const value = String(text || '');
  const newlineCount = (value.match(/\n/g) || []).length;
  return value.length > 180 || newlineCount >= 3;
}

function toggleClipboardExpand(id) {
  const content = document.getElementById('clipboard-text-' + id);
  const toggle = document.getElementById('clipboard-toggle-' + id);
  if (!content || !toggle) return;
  const collapsed = content.classList.toggle('collapsed');
  toggle.textContent = collapsed ? 'Expand' : 'Collapse';
}

async function refreshClipboard(options) {
  const opts = options || {};
  if (clipboardRefreshInFlight) {
    if (!opts.silent) clipboardRefreshQueued = true;
    return;
  }
  const list = document.getElementById('clipboard-list');
  const status = document.getElementById('clipboard-list-status');
  const button = document.getElementById('refresh-clipboard-btn');
  clipboardRefreshInFlight = true;
  if (button) button.disabled = true;
  if (status) status.textContent = opts.silent ? 'Auto-refreshing…' : 'Refreshing…';
  if (!opts.silent || !list.innerHTML) {
    list.innerHTML = '<div class="empty">Loading…</div>';
  }
  try {
    const items = await fetchJson('/web/api/clipboard/items');
    clipboardItemsCache = Array.isArray(items) ? items : [];
    if (!clipboardItemsCache.length) {
      list.innerHTML = '<div class="empty">No saved text yet.</div>';
      if (status) status.textContent = 'No saved text. Updated ' + formatRefreshTime() + '.';
      return;
    }
    list.innerHTML = clipboardItemsCache.map((item) => {
      const text = String(item.text || '');
      const needsCollapse = shouldCollapseText(text);
      const textHtml = escapeHtml(text).replace(/\n/g, '<br>');
      return '<div class="item">'
        + '<div class="item-top">'
        + '<div></div>'
        + '<div class="item-actions">'
        + '<button type="button" class="secondary" data-action="fill-clipboard" data-item-id="' + escapeHtml(item.id) + '">Fill</button>'
        + '<button type="button" class="secondary" data-action="copy-clipboard" data-item-id="' + escapeHtml(item.id) + '">Copy</button>'
        + '<button type="button" class="danger" data-action="delete-clipboard" data-item-id="' + escapeHtml(item.id) + '">Delete</button>'
        + '</div></div>'
        + '<div id="clipboard-text-' + escapeHtml(item.id) + '" class="text-preview' + (needsCollapse ? ' collapsed' : '') + '">' + textHtml + '</div>'
        + (needsCollapse
            ? '<div class="text-toggle"><button type="button" class="link-button" id="clipboard-toggle-' + escapeHtml(item.id) + '" data-action="toggle-clipboard" data-item-id="' + escapeHtml(item.id) + '">Expand</button></div>'
            : '')
        + '<div class="item-meta">Updated: ' + escapeHtml(formatDate(item.updated_at)) + '</div>'
        + '</div>';
    }).join('');
    if (status) status.textContent = 'Loaded ' + clipboardItemsCache.length + ' saved text(s). Updated ' + formatRefreshTime() + '.';
  } catch (err) {
    if (status) status.textContent = 'Refresh failed: ' + err.message;
    if (!list.innerHTML || !opts.silent) list.innerHTML = '<div class="empty">Failed to load saved texts.</div>';
  } finally {
    clipboardRefreshInFlight = false;
    if (button) button.disabled = false;
    if (clipboardRefreshQueued) {
      clipboardRefreshQueued = false;
      refreshClipboard();
    }
  }
}

async function saveClipboard() {
  const button = document.getElementById('save-clipboard-btn');
  const status = document.getElementById('clipboard-status');
  const text = document.getElementById('clipboard-input').value;
  button.disabled = true;
  status.textContent = 'Saving…';
  try {
    await fetchJson('/web/api/clipboard/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    status.textContent = 'Saved.';
    document.getElementById('clipboard-input').value = '';
    await refreshClipboard();
  } catch (err) {
    status.textContent = 'Save failed: ' + err.message;
  } finally {
    button.disabled = false;
  }
}

function fillClipboardItem(id) {
  const item = getClipboardItem(id);
  if (!item) return;
  const input = document.getElementById('clipboard-input');
  const status = document.getElementById('clipboard-status');
  input.value = item.text || '';
  input.focus();
  if (status) status.textContent = 'Filled into input.';
}

function clearCurrentInput() {
  const input = document.getElementById('clipboard-input');
  const status = document.getElementById('clipboard-status');
  input.value = '';
  input.focus();
  if (status) status.textContent = 'Input cleared.';
}

async function copyCurrentInput(button) {
  const input = document.getElementById('clipboard-input');
  await copyTextToClipboard(input.value || '');
  flashButtonText(button || document.getElementById('copy-current-btn'), 'Copied!');
}

async function copyClipboardItem(id, button) {
  const item = getClipboardItem(id);
  if (!item) return;
  await copyTextToClipboard(item.text || '');
  flashButtonText(button, 'Copied!');
}

async function deleteClipboardItem(id) {
  const confirmed = await openConfirmDialog('Delete this saved text?', 'Delete');
  if (!confirmed) return;
  await fetchJson('/web/api/clipboard/items/' + encodeURIComponent(id), { method: 'DELETE' });
  await refreshClipboard();
}

"""
