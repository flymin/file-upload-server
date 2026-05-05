STYLES = """    :root {
      color-scheme: light;
      --bg: #f4f7fb;
      --card: #ffffff;
      --line: #dbe4f0;
      --text: #0f172a;
      --muted: #475569;
      --accent: #2563eb;
      --accent-soft: #dbeafe;
      --danger: #dc2626;
      --success: #16a34a;
      --shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #eff6ff 0%, var(--bg) 180px);
      color: var(--text);
    }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .shell { max-width: 1160px; margin: 0 auto; padding: 24px; }
    .topbar {
      display: flex; gap: 16px; align-items: center; justify-content: space-between;
      padding: 18px 22px; border: 1px solid var(--line); border-radius: 20px;
      background: rgba(255,255,255,0.82); backdrop-filter: blur(10px); box-shadow: var(--shadow);
      margin-bottom: 22px;
    }
    .brand { display: flex; align-items: center; gap: 14px; }
    .brand-icon { width: 46px; height: 46px; border-radius: 14px; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.4); }
    .brand h1 { margin: 0; font-size: 20px; }
    .brand p { margin: 4px 0 0; color: var(--muted); font-size: 13px; }
    .grid { display: grid; grid-template-columns: 1.05fr 1.2fr; gap: 22px; }
    .stack { display: flex; flex-direction: column; gap: 22px; }
    .tab-strip {
      display: flex; gap: 8px; margin: -6px 0 18px; flex-wrap: wrap;
      border-bottom: 1px solid var(--line); padding: 0 6px;
    }
    .tab-button {
      background: transparent; color: var(--muted); border: 1px solid transparent;
      border-bottom: 0; border-radius: 14px 14px 0 0; padding: 12px 18px;
      margin-bottom: -1px; font-weight: 700;
    }
    .tab-button:hover { background: #eef4ff; color: var(--text); }
    .tab-button.active {
      background: var(--card); color: var(--text); border-color: var(--line);
      box-shadow: 0 -4px 14px rgba(37, 99, 235, 0.06);
    }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }
    .card { background: var(--card); border: 1px solid var(--line); border-radius: 20px; box-shadow: var(--shadow); padding: 22px; }
    .card h2 { margin: 0 0 10px; font-size: 19px; }
    .section-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
    .section-header h2 { margin: 0; }
    .muted { color: var(--muted); font-size: 14px; }
    textarea, input[type="text"], input[type="password"] {
      width: 100%; border: 1px solid #cbd5e1; border-radius: 14px; padding: 14px 16px;
      font: inherit; color: var(--text); background: #fff;
    }
    textarea { min-height: 160px; resize: vertical; }
    .row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
    button, .button-like {
      border: 0; border-radius: 12px; padding: 11px 16px; font: inherit; cursor: pointer;
      background: var(--accent); color: #fff; font-weight: 600;
    }
    button.secondary, .button-like.secondary { background: #e2e8f0; color: #0f172a; }
    button.danger { background: var(--danger); }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    .list { display: flex; flex-direction: column; gap: 12px; }
    .item { border: 1px solid var(--line); border-radius: 16px; padding: 14px 16px; background: #f8fbff; }
    .item-top { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
    .item-title { font-weight: 700; word-break: break-word; }
    .item-meta { margin-top: 6px; color: var(--muted); font-size: 13px; line-height: 1.5; word-break: break-word; }
    .item-actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .text-preview { margin-top: 8px; color: var(--text); font-size: 14px; line-height: 1.55; word-break: break-word; white-space: normal; }
    .text-preview.collapsed {
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .text-toggle { margin-top: 8px; }
    .link-button { background: transparent; color: var(--accent); padding: 0; border: 0; font-weight: 600; cursor: pointer; }
    .link-button:hover { text-decoration: underline; }
    .empty { color: var(--muted); padding: 10px 0; }
    .notice { margin-top: 12px; font-size: 14px; color: var(--muted); }
    .modal-overlay {
      position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45);
      display: none; align-items: center; justify-content: center; padding: 24px; z-index: 1000;
    }
    .modal-overlay.open { display: flex; }
    .modal-card {
      width: min(100%, 440px); background: var(--card); border: 1px solid var(--line);
      border-radius: 20px; box-shadow: 0 24px 60px rgba(15, 23, 42, 0.22); padding: 22px;
    }
    .modal-card h3 { margin: 0 0 8px; font-size: 20px; }
    .modal-card p { margin: 0; color: var(--muted); line-height: 1.6; }
    .modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
    .status-pill {
      display: inline-flex; align-items: center; gap: 8px; border-radius: 999px; padding: 8px 12px;
      background: var(--accent-soft); color: #1d4ed8; font-size: 13px; font-weight: 700;
    }
    .upload-drop {
      border: 1.5px dashed #93c5fd; border-radius: 18px; padding: 18px; background: #f8fbff;
    }
    .upload-drop input[type="file"] { width: 100%; }
    .progress-bar { width: 100%; height: 10px; border-radius: 999px; background: #dbeafe; overflow: hidden; margin-top: 10px; }
    .progress-fill { height: 100%; width: 0%; background: linear-gradient(90deg, #2563eb, #60a5fa); }
    .file-meta { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 14px; margin-top: 8px; font-size: 13px; color: var(--muted); }
    .login-card { max-width: 460px; margin: 64px auto 0; }
    .error { color: var(--danger); font-size: 14px; margin: 10px 0 0; }
    .success { color: var(--success); }
    code { background: #eff6ff; border-radius: 8px; padding: 2px 6px; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } .topbar { flex-direction: column; align-items: start; } .file-meta { grid-template-columns: 1fr; } }
"""
