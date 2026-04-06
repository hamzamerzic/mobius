import os
os.environ.setdefault("SECRET_KEY", "test-secret-key-exactly-32-chars!!")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/mobius_test/test.db")
os.environ.setdefault("DATA_DIR", "/tmp/mobius_test")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:5173")

from app.theme import inject_theme_into_html, extract_imports


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


def test_inject_theme_no_imports_no_link_tags(tmp_path):
  theme_css = ":root { --bg: #1a1a1a; }"
  shared = tmp_path / "shared"
  shared.mkdir()
  (shared / "theme.css").write_text(theme_css)

  html = '<html><head><title>Test</title></head><body style="margin:0;background:#0c0f14"></body></html>'
  result = inject_theme_into_html(html, str(tmp_path))

  assert '<link rel="stylesheet"' not in result
  assert "--bg" in result
