"""Single source of truth for the default theme.

Both the shell (index.html) and the app-frame inject theme CSS from
/data/shared/theme.css.  When no theme.css exists, this default is
used.  The shell's index.css and app-frame.html should NOT define
their own :root variables — they come from here.
"""

import re
from pathlib import Path

# Matches @import url('...') or @import url("...") statements.
_IMPORT_RE = re.compile(
  r"""@import\s+url\(\s*['"]([^'"]+)['"]\s*\)\s*;[^\S\n]*\n?""",
)

DEFAULT_THEME = """\
:root {
  --bg: #0c0f14;
  --surface: #14181f;
  --surface2: #1a1f28;
  --border: #252b36;
  --border-light: #1c2029;
  --text: #d4d4d8;
  --muted: #52525b;
  --accent: #a78bfa;
  --accent-hover: #c4b5fd;
  --accent-dim: rgba(167, 139, 250, 0.1);
  --danger: #f87171;
  --green: #6ee7b7;
  --font: 'Inter', system-ui, -apple-system, sans-serif;
  --mono: 'JetBrains Mono', ui-monospace, 'SF Mono', monospace;
}
"""


def get_theme_css(data_dir: str) -> str:
  """Returns the active theme CSS — user override or default."""
  theme_path = Path(data_dir) / "shared" / "theme.css"
  if theme_path.exists():
    content = theme_path.read_text(encoding="utf-8").strip()
    if content:
      return content
  return DEFAULT_THEME


def extract_imports(css: str) -> tuple[list[str], str]:
  """Split @import url() lines from CSS, return (urls, remaining_css).

  Browsers ignore @import inside <style> tags in some contexts, so
  callers should convert these to <link> tags instead.
  """
  urls = _IMPORT_RE.findall(css)
  remaining = _IMPORT_RE.sub("", css)
  return urls, remaining


def get_bg_color(data_dir: str) -> str:
  """Extracts the --bg color for use in the manifest."""
  css = get_theme_css(data_dir)
  m = re.search(r"--bg:\s*(#[0-9a-fA-F]{3,8})", css)
  return m.group(1) if m else "#0c0f14"


def inject_theme_into_html(html: str, data_dir: str) -> str:
  """Inject the active theme CSS and background color into an HTML string.

  Replaces the </head> tag with a <style> block containing the theme CSS,
  and replaces the default #0c0f14 background color placeholder with the
  active theme's --bg color. Used by both the SPA fallback and the
  app-frame endpoint.
  """
  css = get_theme_css(data_dir)
  bg = get_bg_color(data_dir)
  imports, css = extract_imports(css)
  link_tags = "".join(
    f'<link rel="stylesheet" href="{url}">\n' for url in imports
  )
  html = html.replace(
    "</head>", f"{link_tags}<style>{css}</style>\n</head>"
  )
  html = html.replace("background:#0c0f14", f"background:{bg}")
  html = html.replace('content="#0c0f14"', f'content="{bg}"')
  return html
