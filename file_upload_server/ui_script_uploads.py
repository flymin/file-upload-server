UPLOADS_SCRIPT = r"""function createUploadJobCard(file) {
  const job = document.createElement('div');
  job.className = 'item';
  job.innerHTML = ''
    + '<div class="item-title">' + escapeHtml(file.name) + '</div>'
    + '<div class="file-meta">'
    + '<div>Size: ' + escapeHtml(formatBytes(file.size)) + '</div>'
    + '<div>Status: <span class="job-status">Preparing…</span></div>'
    + '<div>Uploaded: <span class="job-uploaded">0%</span></div>'
    + '<div>Chunking: <span class="job-chunking">—</span></div>'
    + '</div>'
    + '<div class="progress-bar"><div class="progress-fill"></div></div>';
  document.getElementById('upload-jobs').prepend(job);
  return job;
}

function updateJobProgress(job, percent, statusText, chunkingText) {
  job.querySelector('.progress-fill').style.width = String(Math.max(0, Math.min(100, percent))) + '%';
  job.querySelector('.job-uploaded').textContent = percent.toFixed(1) + '%';
  if (statusText) job.querySelector('.job-status').textContent = statusText;
  if (chunkingText) job.querySelector('.job-chunking').textContent = chunkingText;
}

function renderPendingSelection() {
  const startButton = document.getElementById('start-upload-btn');
  const clearButton = document.getElementById('clear-upload-selection-btn');
  const status = document.getElementById('upload-selection-status');
  const summary = document.getElementById('selected-files-summary');

  if (!pendingFiles.length) {
    startButton.disabled = true;
    clearButton.disabled = true;
    status.textContent = 'No files selected.';
    summary.textContent = '';
    return;
  }

  startButton.disabled = false;
  clearButton.disabled = false;
  const totalBytes = pendingFiles.reduce((sum, file) => sum + (file.size || 0), 0);
  status.textContent = pendingFiles.length + ' file(s) selected.';
  summary.innerHTML = pendingFiles
    .slice(0, 8)
    .map((file) => escapeHtml(file.name) + ' (' + escapeHtml(formatBytes(file.size)) + ')')
    .join('<br>');
  if (pendingFiles.length > 8) {
    summary.innerHTML += '<br>…and ' + (pendingFiles.length - 8) + ' more';
  }
  summary.innerHTML += '<br>Total: ' + escapeHtml(formatBytes(totalBytes));
}

function clearSelectedFiles() {
  pendingFiles.length = 0;
  document.getElementById('file-input').value = '';
  renderPendingSelection();
}

async function initUpload(file) {
  return fetchJson('/web/api/uploads/init', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      filename: file.name,
      size: file.size,
      content_type: file.type || 'application/octet-stream',
      last_modified_ms: file.lastModified || 0,
    }),
  });
}

async function uploadChunk(uploadId, chunkIndex, blob) {
  const response = await fetch('/web/api/uploads/' + encodeURIComponent(uploadId) + '/chunks/' + chunkIndex, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: blob,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || ('Chunk upload failed (' + response.status + ')'));
  }
  return response.json();
}

async function completeUpload(uploadId) {
  return fetchJson('/web/api/uploads/' + encodeURIComponent(uploadId) + '/complete', { method: 'POST' });
}

async function processFile(file) {
  const job = createUploadJobCard(file);
  try {
    const init = await initUpload(file);
    const uploadId = init.upload_id;
    const chunkSize = init.chunk_size;
    const totalChunks = init.total_chunks;
    const received = new Set((init.received_chunks || []).map((value) => Number(value)));
    let uploadedBytes = Number(init.received_bytes || 0);
    updateJobProgress(job, file.size ? uploadedBytes / file.size * 100 : 100, 'Uploading…', formatBytes(chunkSize) + ' × ' + totalChunks);

    const pending = [];
    for (let index = 1; index <= totalChunks; index += 1) {
      if (!received.has(index)) pending.push(index);
    }

    let cursor = 0;
    async function worker() {
      while (cursor < pending.length) {
        const current = pending[cursor];
        cursor += 1;
        const start = (current - 1) * chunkSize;
        const end = Math.min(file.size, start + chunkSize);
        const blob = file.slice(start, end);
        const result = await uploadChunk(uploadId, current, blob);
        uploadedBytes = Number(result.received_bytes || uploadedBytes + blob.size);
        const percent = file.size ? uploadedBytes / file.size * 100 : 100;
        updateJobProgress(job, percent, 'Uploading…', result.received_count + ' / ' + totalChunks + ' chunks');
      }
    }

    const workers = [];
    const workerCount = Math.max(1, Math.min(UPLOAD_PARALLELISM, pending.length || 1));
    for (let i = 0; i < workerCount; i += 1) workers.push(worker());
    await Promise.all(workers);

    const finalInfo = await completeUpload(uploadId);
    updateJobProgress(job, 100, 'Completed', 'Ready');
    const meta = job.querySelector('.file-meta');
    meta.innerHTML += '<div class="success">Expires: ' + escapeHtml(formatDate(finalInfo.expires_at)) + '</div>';
    await refreshFiles();
  } catch (err) {
    updateJobProgress(job, 0, 'Failed', err.message || 'Upload failed');
    throw err;
  }
}

function handleFileSelection(event) {
  pendingFiles.length = 0;
  for (const file of Array.from(event.target.files || [])) {
    pendingFiles.push(file);
  }
  renderPendingSelection();
}

async function startSelectedUploads() {
  if (!pendingFiles.length) return;

  const startButton = document.getElementById('start-upload-btn');
  const clearButton = document.getElementById('clear-upload-selection-btn');
  const fileInput = document.getElementById('file-input');
  const status = document.getElementById('upload-selection-status');
  const summary = document.getElementById('selected-files-summary');
  const files = pendingFiles.slice();
  let finished = false;

  startButton.disabled = true;
  clearButton.disabled = true;
  fileInput.disabled = true;
  status.textContent = 'Uploading ' + files.length + ' file(s)…';

  try {
    for (const file of files) {
      try {
        await processFile(file);
      } catch (_err) {
        // Status already rendered on the upload card.
      }
    }
    pendingFiles.length = 0;
    fileInput.value = '';
    finished = true;
  } finally {
    fileInput.disabled = false;
    if (finished) {
      startButton.disabled = true;
      clearButton.disabled = true;
      status.textContent = 'Upload finished.';
      summary.textContent = '';
    } else {
      renderPendingSelection();
    }
  }
}

"""
