import os
os.environ.setdefault("SECRET_KEY", "test-secret-key-exactly-32-chars!!")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/mobius_test/test.db")
os.environ.setdefault("DATA_DIR", "/tmp/mobius_test")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:5173")

from app.theme import inject_theme_into_html, extract_imports, _enforce_readability


def test_extract_imports_splits_imports_from_css():
  css = (
    "@import url('https://fonts.googleapis.com/css2?family=Poppins');\n"
    "@import url(\"https://fonts.googleapis.com/css2?family=Fira+Code\");\n"
    ":root { --font: 'Poppins', sans-serif; }\n"
  )
  imports, remaining = extract_imports(css)
  assert imports == [
    "https://fonts.googleapis.com/css2?family=Poppins",
    "https://fonts.googleapis.com/css2?family=Fira+Code",
  ]
  assert "@import" not in remaining
  assert "--font" in remaining


def test_extract_imports_no_imports():
  css = ":root { --bg: #fff; }"
  imports, remaining = extract_imports(css)
  assert imports == []
  assert remaining == css


def test_inject_theme_adds_link_tags_for_imports(tmp_path):
  theme_css = (
    "@import url('https://fonts.googleapis.com/css2?family=Poppins');\n"
    ":root { --font: 'Poppins', sans-serif; }\n"
  )
  shared = tmp_path / "shared"
  shared.mkdir()
  (shared / "theme.css").write_text(theme_css)

  html = '<html><head><title>Test</title></head><body style="margin:0;background:#0c0f14"></body></html>'
  result = inject_theme_into_html(html, str(tmp_path))

  assert '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Poppins">' in result
  assert "@import" not in result
  assert "--font" in result


def test_enforce_readability_strips_backdrop_filter():
  css = """\
.sidenav {
  background: #14181f;
  backdrop-filter: blur(8px);
  border: 1px solid #252b36;
}
.modal { backdrop-filter: blur(10px) saturate(120%); }
"""
  out = _enforce_readability(css)
  assert "backdrop-filter" not in out
  assert "background: #14181f" in out
  assert "border: 1px solid #252b36" in out


def test_enforce_readability_strips_webkit_backdrop_filter():
  css = ".chrome { -webkit-backdrop-filter: blur(8px); color: red; }"
  out = _enforce_readability(css)
  assert "backdrop-filter" not in out
  assert "color: red" in out


def test_enforce_readability_does_not_eat_custom_prop_filter():
  """`--my-filter: blur(...)` is a custom-property definition, NOT
  a `filter:` declaration. Stripping it would corrupt the variable
  and any rules that read it."""
  css = ":root { --my-filter: blur(4px); }\n.hero { backdrop-filter: var(--my-filter); }"
  out = _enforce_readability(css)
  # The custom property is preserved.
  assert "--my-filter: blur(4px)" in out
  # The actual backdrop-filter usage IS stripped.
  assert "backdrop-filter: var" not in out


def test_enforce_readability_strips_filter_blur_only():
  css = """\
.hero { filter: blur(4px); }
.swatch { filter: hue-rotate(-12deg); }
.mandala { filter: grayscale(60%) blur(2px); }
"""
  out = _enforce_readability(css)
  # filter: blur(...) gone
  assert "filter: blur" not in out
  # filter: grayscale(60%) blur(2px) also gone (any line containing blur())
  assert "blur(" not in out
  # but hue-rotate (no blur) preserved
  assert "filter: hue-rotate" in out


def test_enforce_readability_clamps_low_alpha_surfaces():
  css = """\
:root {
  --bg: rgba(10, 12, 18, 0.6);
  --surface: rgba(20, 60, 38, 0.78);
  --surface2: rgba(28, 78, 50, 0.88);
  --border: rgba(50, 60, 80, 0.4);
}
"""
  out = _enforce_readability(css)
  # readable surfaces forced opaque
  assert "--bg: rgba(10, 12, 18, 1)" in out
  assert "--surface: rgba(20, 60, 38, 1)" in out
  assert "--surface2: rgba(28, 78, 50, 1)" in out
  # non-surface variables untouched (border alpha is fine to be partial)
  assert "--border: rgba(50, 60, 80, 0.4)" in out


def test_enforce_readability_clamps_modern_color_syntax():
  """CSS Color 4 syntax: rgb(R G B / A) — clamp when A < 0.9."""
  css = """\
:root {
  --bg: rgb(10 12 18 / 0.6);
  --surface: rgb(20 60 38 / 0.78);
  --surface2: rgb(28 78 50 / 95%);
}
"""
  out = _enforce_readability(css)
  assert "--bg: rgb(10 12 18 / 1)" in out
  assert "--surface: rgb(20 60 38 / 1)" in out
  # 95% >= 90% threshold — left alone.
  assert "--surface2: rgb(28 78 50 / 95%)" in out


def test_enforce_readability_preserves_high_alpha_surfaces():
  """Themes that already use alpha >= 0.9 stay untouched."""
  css = ":root { --surface: rgba(20, 60, 38, 0.95); --surface2: rgba(28, 78, 50, 1); }"
  out = _enforce_readability(css)
  assert "--surface: rgba(20, 60, 38, 0.95)" in out
  assert "--surface2: rgba(28, 78, 50, 1)" in out


def test_enforce_readability_forces_root_overlays_behind_content():
  """A theme that puts `position: fixed; inset: 0` overlays on
  body/html pseudo-elements without pushing them behind the UI
  gets auto-corrected: pointer-events: none + z-index: -1 are
  appended so the overlay can't sit on top of chat."""
  css = """\
body::before {
  content: '';
  position: fixed;
  inset: 0;
  background: rgba(212, 164, 55, 0.5);
  z-index: 10;
}
.foo { color: red; }
"""
  out = _enforce_readability(css)
  # The overlay rule gets pushed behind.
  assert "z-index: -1" in out
  assert "pointer-events: none" in out
  # Original positive z-index stripped.
  assert "z-index: 10" not in out
  # Unrelated rule untouched.
  assert ".foo { color: red; }" in out


def test_enforce_readability_strips_unscoped_focus_rules():
  """A theme that tries to set `input:focus-visible` or
  `textarea:focus` globally (no parent class) would clobber the
  shell's own focus styling. Scoped rules are left alone."""
  css = """\
input:focus-visible { outline: 2px solid red; }
textarea:focus { border-color: red; }
.my-theme input:focus { background: yellow; }
.chat__input { color: green; }
"""
  out = _enforce_readability(css)
  assert "input:focus-visible" not in out
  assert "textarea:focus" not in out
  # Scoped selector preserved.
  assert ".my-theme input:focus" in out
  # Unrelated chat rule preserved.
  assert ".chat__input { color: green; }" in out


def test_enforce_readability_injects_missing_core_vars():
  """If the agent's theme defines only a few variables, missing
  core variables get filled in from DEFAULT_THEME so the shell
  doesn't fall back to invisible hardcoded literals like #111."""
  css = ":root { --accent: #ff00aa; }"
  out = _enforce_readability(css)
  # Original kept.
  assert "--accent: #ff00aa" in out
  # Critical missing ones injected.
  assert "--bg:" in out
  assert "--text:" in out
  assert "--surface:" in out


def test_enforce_readability_skips_var_injection_when_all_present():
  """When the theme defines all core variables, no injection
  block is appended (no spurious diff)."""
  css = """\
:root {
  --bg: #000;
  --surface: #111;
  --surface2: #222;
  --text: #fff;
  --muted: #999;
  --accent: #f0f;
  --accent-hover: #faf;
  --accent-dim: rgba(255, 0, 255, 0.1);
  --border: #333;
  --border-light: #444;
  --danger: #f00;
  --green: #0f0;
  --font: sans-serif;
  --mono: monospace;
}
"""
  out = _enforce_readability(css)
  assert "injected defaults" not in out


def test_enforce_readability_keeps_animations_and_ornaments():
  """Pseudo-element ornaments, animations, fonts, colors all preserved."""
  css = """\
body::before {
  content: '';
  position: fixed;
  background-image: url('data:image/svg+xml;utf8,<svg/>');
  opacity: 0.2;
  animation: drift 60s linear infinite;
}
@keyframes drift { from { transform: rotate(0); } to { transform: rotate(360deg); } }
"""
  out = _enforce_readability(css)
  # ornaments + animations preserved — only blur/low-alpha surfaces are touched.
  assert "body::before" in out
  assert "opacity: 0.2" in out
  assert "@keyframes drift" in out


def test_inject_theme_no_imports_no_link_tags(tmp_path):
  theme_css = ":root { --bg: #1a1a1a; }"
  shared = tmp_path / "shared"
  shared.mkdir()
  (shared / "theme.css").write_text(theme_css)

  html = '<html><head><title>Test</title></head><body style="margin:0;background:#0c0f14"></body></html>'
  result = inject_theme_into_html(html, str(tmp_path))

  assert '<link rel="stylesheet"' not in result
  assert "--bg" in result


# /api/theme endpoint tests --------------------------------------------------
# The endpoint returns the *effective* theme — user override if present,
# DEFAULT_THEME otherwise. Lets the agent reset to defaults via DELETE on
# the storage URL without writing a complete default block in JS.

def test_api_theme_returns_default_when_no_override(client, auth):
  """No theme.css → endpoint returns DEFAULT_THEME and default --bg."""
  from app.theme import DEFAULT_THEME
  res = client.get("/api/theme", headers=auth)
  assert res.status_code == 200
  body = res.json()
  assert body["css"] == DEFAULT_THEME
  # DEFAULT_THEME has --bg: #0d0f14
  assert body["bg"] == "#0d0f14"


def test_api_theme_returns_user_override_when_present(client, auth):
  """User-written theme.css → endpoint returns it verbatim."""
  import os
  data_dir = os.environ["DATA_DIR"]
  shared = os.path.join(data_dir, "shared")
  os.makedirs(shared, exist_ok=True)
  custom = ":root { --bg: #ff0000; --accent: #00ff00; }"
  with open(os.path.join(shared, "theme.css"), "w") as f:
    f.write(custom)
  try:
    res = client.get("/api/theme", headers=auth)
    assert res.status_code == 200
    body = res.json()
    assert body["css"] == custom
    assert body["bg"] == "#ff0000"
  finally:
    os.remove(os.path.join(shared, "theme.css"))


def test_api_theme_returns_default_when_override_is_empty(client, auth):
  """Empty theme.css → endpoint falls back to DEFAULT_THEME."""
  import os
  from app.theme import DEFAULT_THEME
  data_dir = os.environ["DATA_DIR"]
  shared = os.path.join(data_dir, "shared")
  os.makedirs(shared, exist_ok=True)
  with open(os.path.join(shared, "theme.css"), "w") as f:
    f.write("")
  try:
    res = client.get("/api/theme", headers=auth)
    assert res.status_code == 200
    assert res.json()["css"] == DEFAULT_THEME
  finally:
    os.remove(os.path.join(shared, "theme.css"))


def test_api_theme_reset_via_delete(client, auth):
  """Agent's reset path: DELETE the storage URL → /api/theme returns
  defaults. End-to-end verification that the architecture works."""
  from app.theme import DEFAULT_THEME

  # Set a custom theme via the storage API.
  custom = ":root { --bg: #123456; }"
  res = client.put(
    "/api/storage/shared/theme.css",
    headers=auth,
    json={"content": custom},
  )
  assert res.status_code in (200, 201, 204)

  # Verify endpoint returns the override.
  body = client.get("/api/theme", headers=auth).json()
  assert body["css"] == custom

  # Reset by deleting.
  res = client.delete("/api/storage/shared/theme.css", headers=auth)
  assert res.status_code in (200, 204)

  # Endpoint now returns defaults.
  body = client.get("/api/theme", headers=auth).json()
  assert body["css"] == DEFAULT_THEME


def test_api_theme_requires_auth(client):
  """Unauth requests return 401 — theme isn't a public endpoint."""
  res = client.get("/api/theme")
  assert res.status_code == 401


# Security tests for inject_theme_into_html ---------------------------------

def test_inject_theme_escapes_style_breakout(tmp_path):
  """A theme.css with `</style><script>...` cannot break out of the
  <style> block. The HTML parser ends a style block on the first
  literal `</`; any user-controlled CSS containing `</style>` would
  otherwise produce sibling tags in the head, allowing script
  injection. We escape `</` to `<\\/` which the CSS parser ignores
  but the HTML parser doesn't recognize as a closing tag.

  Stored-XSS regression guard for owner-controlled theme CSS.
  """
  malicious = "</style><script>window.__pwned=1</script><style>"
  shared = tmp_path / "shared"
  shared.mkdir()
  (shared / "theme.css").write_text(malicious)

  html = '<html><head></head><body style="margin:0;background:#0c0f14"></body></html>'
  result = inject_theme_into_html(html, str(tmp_path))
  head = result.split("</head>")[0]

  # The only `</style>` in the head must be our own wrapper close —
  # anything else means the user-controlled CSS broke out.
  closes = head.count("</style>")
  assert closes == 1, f"unexpected </style> count in head: {closes}"
  # No `</script>` either: verifies the secondary close doesn't appear
  # outside <style>. (`<script>` text inside <style> is inert.)
  assert "</script>" not in head
  # Crucial: parse the head as HTML and verify no <script> tag exists.
  # Use stdlib HTMLParser; if the parser sees a <script> as a real
  # tag in the head, that's a breakout.
  from html.parser import HTMLParser

  class TagFinder(HTMLParser):
    def __init__(self):
      super().__init__()
      self.tags = []

    def handle_starttag(self, tag, attrs):
      self.tags.append(tag)

  parser = TagFinder()
  parser.feed(head + "</head>")
  assert "script" not in parser.tags, f"script tag injected: {parser.tags}"


def test_inject_theme_filters_unsafe_import_urls(tmp_path):
  """@import url('javascript:...') and data: URIs must not produce a
  <link> tag in the rendered HTML. http(s) only."""
  hostile = (
    "@import url('javascript:alert(1)');\n"
    "@import url('data:text/css,body{}');\n"
    "@import url('https://fonts.googleapis.com/css?family=Inter');\n"
    ":root { --bg: #1a1a1a; }\n"
  )
  shared = tmp_path / "shared"
  shared.mkdir()
  (shared / "theme.css").write_text(hostile)

  html = '<html><head></head><body style="margin:0;background:#0c0f14"></body></html>'
  result = inject_theme_into_html(html, str(tmp_path))

  # No <link> tag pointing at a non-http(s) URL.
  assert 'href="javascript:' not in result
  assert "href='javascript:" not in result
  assert 'href="data:' not in result
  assert "href='data:" not in result
  # The legitimate https URL DOES produce a <link> tag.
  assert 'fonts.googleapis.com' in result


def test_inject_theme_quotes_in_import_urls_dont_inject_attrs(tmp_path):
  """A `"` in a font URL must not break out of the <link href="..."> attr.
  Even if our regex captures part of the URL, html.escape() with
  quote=True ensures the value is attribute-safe."""
  # Construct a URL that includes a literal `"` followed by attribute-
  # injection-shaped text. The `extract_imports` regex's `[^'"]+` may
  # truncate such URLs — verifying the behavior either way.
  tricky = (
    "@import url('https://example.com/x.css?\"onload=alert(1)');\n"
    ":root { --bg: #abcdef; }\n"
  )
  shared = tmp_path / "shared"
  shared.mkdir()
  (shared / "theme.css").write_text(tricky)

  html = '<html><head></head><body style="margin:0;background:#0c0f14"></body></html>'
  result = inject_theme_into_html(html, str(tmp_path))

  # Critical property: any <link> tag's href attribute is properly
  # quoted. Parse the head and check.
  from html.parser import HTMLParser

  class LinkAttrChecker(HTMLParser):
    def __init__(self):
      super().__init__()
      self.bad = False

    def handle_starttag(self, tag, attrs):
      if tag == "link":
        # Any attr name not in the expected set means injection.
        for name, _ in attrs:
          if name not in ("rel", "href"):
            self.bad = True

  parser = LinkAttrChecker()
  parser.feed(result.split("</head>")[0] + "</head>")
  assert not parser.bad, "extra attributes injected into <link>"
