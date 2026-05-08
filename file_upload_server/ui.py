import html
import json

from .config import SETTINGS
from .pwa import APP_NAME, THEME_COLOR
from .ui_scripts import render_app_script
from .ui_styles import STYLES


FAVICON_DATA_URI = "/favicon.svg"
APP_ICON_URL = "/icon-192.png"




def render_page(title: str, body: str) -> str:
    title_safe = html.escape(title)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="theme-color" content="{THEME_COLOR}" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-title" content="{APP_NAME}" />
  <meta name="apple-mobile-web-app-status-bar-style" content="default" />
  <title>{title_safe}</title>
  <link rel="manifest" href="/manifest.webmanifest" />
  <link rel="icon" type="image/svg+xml" href="{FAVICON_DATA_URI}" />
  <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
  <style>
{STYLES}
  </style>
</head>
<body>
  <div class="shell">{body}</div>
</body>
</html>
"""


def render_home_page() -> str:
    body = f"""
<div class="topbar">
  <div class="brand">
    <img class="brand-icon" src="{APP_ICON_URL}" alt="favicon" />
    <div>
      <h1>File Upload Server</h1>
    </div>
  </div>
  <a class="button-like" href="/login">Login</a>
</div>
<div class="card">
  <h2>Running</h2>
</div>
"""
    return render_page("File Upload Server", body)


def render_login_page(next_url: str, error: str = "") -> str:
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    body = f"""
<div class="card login-card">
  <div class="brand" style="margin-bottom:18px;">
    <img class="brand-icon" src="{APP_ICON_URL}" alt="favicon" />
    <div>
      <h1>Login</h1>
    </div>
  </div>
  <form method="post" action="/login">
    <input type="hidden" name="next" value="{html.escape(next_url)}" />
    <div class="stack" style="gap:12px;">
      <div>
        <div class="muted" style="margin-bottom:8px;">Username</div>
        <input type="text" name="username" autocomplete="username" required />
      </div>
      <div>
        <div class="muted" style="margin-bottom:8px;">Password</div>
        <input type="password" name="password" autocomplete="current-password" required />
      </div>
      <button type="submit">Login</button>
    </div>
    {error_html}
  </form>
</div>
"""
    return render_page("Login", body)


def render_app_page(username: str) -> str:
    user = SETTINGS["users"][username]
    username_js = json.dumps(username)
    display_name = html.escape(user.get("display_name") or username)
    retention_days = SETTINGS["web_file_retention_days"]
    parallelism = SETTINGS["web_upload_parallelism"]
    body = f"""
<div class="topbar">
  <div class="brand">
    <img class="brand-icon" src="{APP_ICON_URL}" alt="favicon" />
    <div>
      <h1>{display_name}</h1>
      <p>Private clipboard + private files. Web uploads auto-expire after {retention_days} days.</p>
    </div>
  </div>
  <div class="row">
    <span class="status-pill">Logged in as {html.escape(username)}</span>
    <a class="button-like secondary" href="/logout">Logout</a>
  </div>
</div>
<div class="tab-strip">
  <button id="tab-clipboard" type="button" class="tab-button active" data-tab="clipboard">Clipboard</button>
  <button id="tab-files" type="button" class="tab-button" data-tab="files">Files</button>
</div>
<div id="panel-clipboard" class="tab-panel active">
  <div class="stack">
    <section class="card">
      <h2>Clipboard</h2>
      <p class="muted">Saved per user. Same text will be de-duplicated and bumped to the top.</p>
      <textarea id="clipboard-input" placeholder="Paste or type text here..."></textarea>
      <div class="row" style="margin-top:12px;">
        <button id="save-clipboard-btn" type="button">Save text</button>
        <button id="copy-current-btn" type="button" class="secondary" data-action="copy-current">Copy input</button>
        <button id="clear-current-btn" type="button" class="secondary" data-action="clear-current">Clear input</button>
        <span class="notice" id="clipboard-status"></span>
      </div>
    </section>
    <section class="card">
      <div class="section-header">
        <h2>Saved texts</h2>
        <button id="refresh-clipboard-btn" type="button" class="secondary">Refresh</button>
      </div>
      <p class="muted">Auto-refreshes while this page is open.</p>
      <div class="row" style="margin-bottom:12px;">
        <span class="notice" id="clipboard-list-status"></span>
      </div>
      <div id="clipboard-list" class="list"></div>
    </section>
  </div>
</div>
<div id="panel-files" class="tab-panel">
  <div class="stack">
    <section class="card">
      <h2>File upload</h2>
      <p class="muted">Chunked + parallel + resumable. Files live in your own upload directory and do not mix with token API uploads.</p>
      <div class="upload-drop">
        <input id="file-input" type="file" multiple />
        <div class="row" style="margin-top:12px;">
          <button id="start-upload-btn" type="button" disabled>Upload selected files</button>
          <button id="clear-upload-selection-btn" type="button" class="secondary" disabled>Clear selection</button>
          <span class="notice" id="upload-selection-status">No files selected.</span>
        </div>
        <div id="selected-files-summary" class="notice" style="margin-top:10px;"></div>
        <div class="notice">Chunk size is chosen automatically based on file size. Current browser parallelism: {parallelism}.</div>
      </div>
      <div id="upload-jobs" class="list" style="margin-top:14px;"></div>
    </section>
    <section class="card">
      <div class="section-header">
        <h2>Your files</h2>
        <button id="refresh-files-btn" type="button" class="secondary">Refresh</button>
      </div>
      <p class="muted">File list refresh triggers cleanup of expired files. Downloads are served as complete files with HTTP range support.</p>
      <div class="row" style="margin-bottom:12px;">
        <span class="notice" id="files-status"></span>
      </div>
      <div id="files-list" class="list"></div>
    </section>
  </div>
</div>
<div id="confirm-modal" class="modal-overlay" aria-hidden="true">
  <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="confirm-modal-title">
    <h3 id="confirm-modal-title">Confirm delete</h3>
    <p id="confirm-modal-message">Are you sure?</p>
    <div class="modal-actions">
      <button id="confirm-modal-cancel" type="button" class="secondary">Cancel</button>
      <button id="confirm-modal-confirm" type="button" class="danger">Delete</button>
    </div>
  </div>
</div>
<script>
{render_app_script(username_js, parallelism)}
</script>
"""
    return render_page("Workspace", body)


# ─── Routes: page + auth ─────────────────────────────────────────────────────
