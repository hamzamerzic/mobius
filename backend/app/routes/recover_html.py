"""HTML/CSS templates for the recovery page.

Separated from recover.py so route logic and markup are easier to
maintain independently.
"""

import html

_STYLE = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: var(--font, system-ui, -apple-system, sans-serif);
    background: var(--bg, #0c0f14); color: var(--text, #d4d4d8);
    min-height: 100vh; display: flex;
    align-items: center; justify-content: center;
    padding: 16px;
  }
  .card {
    background: var(--surface, #14181f); border: 1px solid var(--border, #252b36);
    border-radius: 12px; padding: 32px; max-width: 440px; width: 100%;
  }
  h1 { font-size: 20px; margin-bottom: 4px; }
  .sub { color: var(--muted, #52525b); font-size: 14px; margin-bottom: 24px; }
  label { display: block; font-size: 13px; color: var(--muted, #52525b); margin-bottom: 4px; }
  input {
    width: 100%; padding: 10px 12px; font-size: 14px;
    background: var(--bg, #0c0f14); border: 1px solid var(--border, #252b36);
    border-radius: 6px; color: var(--text, #d4d4d8); margin-bottom: 12px;
    outline: none;
  }
  input:focus { border-color: var(--accent, #a78bfa); }
  .btn {
    display: inline-block; padding: 10px 20px; font-size: 14px;
    border: none; border-radius: 6px; cursor: pointer;
    color: #fff; text-decoration: none; text-align: center;
    width: 100%;
  }
  .btn-primary { background: var(--accent, #a78bfa); }
  .btn-primary:hover { background: var(--accent-hover, #c4b5fd); }
  .btn-warn { background: #dc2626; }
  .btn-warn:hover { background: #b91c1c; }
  .btn-outline {
    background: transparent; border: 1px solid var(--border, #252b36);
    color: var(--text, #d4d4d8);
  }
  .btn-outline:hover { background: var(--surface2, #1a1f28); }
  .error { color: var(--danger, #f87171); font-size: 13px; margin-bottom: 12px; }
  .msg {
    background: rgba(110, 231, 183, 0.08);
    border: 1px solid var(--green, #6ee7b7);
    color: var(--green, #6ee7b7);
    font-size: 14px; font-weight: 500;
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 18px;
    display: flex; align-items: flex-start; gap: 10px;
  }
  .msg::before {
    content: "\\2713"; font-size: 16px; font-weight: 700; flex: 0 0 auto;
  }
  .actions { display: flex; flex-direction: column; gap: 10px; }
  .section { margin-bottom: 20px; }
  .section-title { font-size: 13px; color: var(--muted, #52525b); margin-bottom: 8px; }
  hr { border: none; border-top: 1px solid var(--border, #252b36); margin: 20px 0; }
  .recommended {
    background: var(--accent-dim, rgba(167,139,250,0.08));
    border: 1px solid var(--accent, #a78bfa);
    border-radius: 10px; padding: 16px; margin-bottom: 20px;
  }
  .recommended .label {
    font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase; color: var(--accent, #a78bfa); margin-bottom: 8px;
  }
  .recommended .desc {
    font-size: 13px; color: var(--muted, #52525b); margin-bottom: 12px;
  }
"""


def login_html(error: str = "") -> str:
  """Returns the recovery login page HTML."""
  error_html = (
    f'<p class="error">{html.escape(error)}</p>' if error else ""
  )
  return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Möbius Recovery</title>
  <style>{_STYLE}</style>
</head>
<body>
  <div class="card">
    <h1>&#8734; Recovery</h1>
    <p class="sub">Log in to access recovery tools.</p>
    {error_html}
    <form method="POST" action="/recover/auth">
      <label for="username">Username</label>
      <input id="username" name="username" required autofocus>
      <label for="password">Password</label>
      <input id="password" name="password" type="password" required>
      <button class="btn btn-primary" type="submit">Log in</button>
    </form>
  </div>
</body>
</html>"""


_CONFIRM_RESTORE = (
  "Restore the interface from the original image?"
  " Your chats and mini-apps will not be affected."
)
_CONFIRM_APPS = (
  "Delete all mini-apps? Your data files will remain."
)
_CONFIRM_AUTH = (
  "Reset CLI auth? You will need to sign in again."
)
_CONFIRM_FACTORY = (
  "FACTORY RESET: This deletes your account, all apps,"
  " CLI credentials, and theme — but preserves chat history."
  " Are you sure?"
)


def dashboard_html(msg: str = "") -> str:
  """Returns the recovery dashboard page HTML."""
  msg_html = (
    f'<p class="msg">{html.escape(msg)}</p>' if msg else ""
  )
  return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Möbius Recovery</title>
  <style>{_STYLE}</style>
</head>
<body>
  <div class="card">
    <h1>&#8734; Recovery</h1>
    <p class="sub">Restore a working state. Your chats and data are safe.</p>
    {msg_html}

    <div class="recommended">
      <p class="label">&#10003; Recommended</p>
      <p class="desc">Resets the interface to its original state. Chats, mini-apps, and settings are untouched.</p>
      <form method="POST" action="/recover/action"
            onsubmit="return confirm('{_CONFIRM_RESTORE}')">
        <input type="hidden" name="action" value="restore_shell">
        <button class="btn btn-primary" type="submit">
          Restore interface
        </button>
      </form>
    </div>

    <div class="section">
      <p class="section-title">Other safe actions</p>
      <div class="actions">
        <form method="POST" action="/recover/action">
          <input type="hidden" name="action" value="download_backup">
          <button class="btn btn-outline" type="submit">
            Download backup (.zip)
          </button>
          <p style="font-size:12px;color:#94a3b8;margin-top:6px;">Backup includes CLI auth credentials. Store the backup file securely.</p>
        </form>
        <form method="POST" action="/recover/action">
          <input type="hidden" name="action" value="reset_chat">
          <button class="btn btn-outline" type="submit">
            Reset chat log
          </button>
        </form>
      </div>
    </div>

    <hr>

    <div class="section">
      <p class="section-title">Destructive actions</p>
      <div class="actions">
        <form method="POST" action="/recover/action"
              onsubmit="return confirm('{_CONFIRM_APPS}')">
          <input type="hidden" name="action" value="reset_apps">
          <button class="btn btn-warn" type="submit">
            Reset all mini-apps
          </button>
        </form>
        <form method="POST" action="/recover/action"
              onsubmit="return confirm('{_CONFIRM_AUTH}')">
          <input type="hidden" name="action" value="reset_settings">
          <button class="btn btn-warn" type="submit">
            Reset CLI auth
          </button>
        </form>
        <form method="POST" action="/recover/action"
              onsubmit="return confirm('{_CONFIRM_FACTORY}')">
          <input type="hidden" name="action" value="factory_reset">
          <button class="btn btn-warn" type="submit">
            Factory reset
          </button>
        </form>
      </div>
    </div>

    <hr>
    <a href="/" class="btn btn-outline" style="margin-top: 4px;">
      &larr; Back to app
    </a>
  </div>
</body>
</html>"""
