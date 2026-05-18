"""Single source of truth for the default theme.

Both the shell (index.html) and the app-frame inject theme CSS from
/data/shared/theme.css.  When no theme.css exists, this default is
used.  The shell's index.css and app-frame.html should NOT define
their own :root variables — they come from here.
"""

import re
from html import escape as html_escape
from pathlib import Path

# Matches @import url('...') or @import url("...") statements.
_IMPORT_RE = re.compile(
  r"""@import\s+url\(\s*['"]([^'"]+)['"]\s*\)\s*;[^\S\n]*\n?""",
)

DEFAULT_THEME = """\
:root {
  --bg: #0d0f14;
  --surface: #151820;
  --surface2: #1c2028;
  --border: #2a2f3a;
  --border-light: #1e2330;
  --text: #d8d8dc;
  --muted: #6b6b76;
  --accent: #8b6cf7;
  --accent-hover: #7c5ce6;
  --accent-dim: rgba(139, 108, 247, 0.12);
  --danger: #ef4444;
  --green: #059669;
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


def _escape_for_style_tag(css: str) -> str:
  """Escapes any closing </style> sequence inside CSS so it can't break
  out of a <style> block. The HTML parser ends a <style> at the first
  literal `</`, regardless of what follows; so any user-controlled CSS
  injected verbatim is a stored-XSS vector. The CSS-spec-safe rewrite
  is `<\\/` (backslash escape inside CSS strings/comments) but for
  general CSS the simpler defense is to break the closing-tag pattern
  with an HTML comment-friendly substitution that keeps the CSS
  semantically identical: replace `</` with `<\\/` inside the embedded
  block. Browsers parse `<\\/style>` as text inside the <style>, never
  as a closing tag.
  """
  return css.replace("</", "<\\/")


def _is_safe_import_url(url: str) -> bool:
  """Allow only http(s) URLs for @import — no javascript:, data:, etc."""
  return url.startswith("https://") or url.startswith("http://")


_CORE_VARS = {
  # Variables the shell relies on. If the agent's theme omits any,
  # we inject the default value so the shell never falls back to an
  # invisible-on-dark-mode hardcoded literal (e.g. `var(--fg, #111)`
  # where --fg doesn't exist).
  "--bg", "--surface", "--surface2", "--text", "--muted",
  "--accent", "--accent-hover", "--accent-dim",
  "--border", "--border-light", "--danger", "--green",
  "--font", "--mono",
}


def _enforce_readability(css: str) -> str:
  """Strip CSS declarations that cause known unreadable-theme failures.

  Agent-authored themes have repeatedly broken readability in the same
  ways:

    1. `backdrop-filter: blur(...)` on surfaces that wrap chat content —
       blurs everything behind, making text look hazy/unreadable.
    2. `filter: blur(...)` on body/html/#root — same effect at the root.
    3. `--surface` / `--surface2` / `--bg` set via `rgba(..., <0.9)` —
       semi-transparent surfaces let ornamental background patterns
       (also commonly added by agent themes) show through, muddling
       text against busy animated layers.
    4. Full-screen `position: fixed; inset: 0` pseudo-overlays on root
       elements without `pointer-events: none` AND a behind-content
       z-index — they sit ON TOP of the chat instead of behind it.
    5. Unscoped global `input:focus-visible / textarea:focus / ...`
       rules clobber the shell's own focus styling and reintroduce
       the "purple square inside the rounded form" bug.

  Plus we INJECT defaults for any core variable the agent's theme
  forgot, so `var(--fg, #111)`-style mistakes can't render text
  invisibly. The transformation stays conservative: we only strip
  the specific declarations that block readability and inject the
  variables the shell explicitly relies on. Animations, ornamental
  pseudo-elements, gradients, custom fonts — all preserved.
  """
  # 1. Strip backdrop-filter declarations entirely (including the
  #    -webkit- prefix). The property-boundary lookbehind rejects
  #    matches preceded by word OR hyphen — so `--my-backdrop-filter:`
  #    (custom property) and `-foo-backdrop-filter` (any prefix other
  #    than the explicit `-webkit-` alternation) are left alone.
  css = re.sub(
    r"(?<![\w-])(?:-webkit-)?backdrop-filter\s*:[^;{}]*;?", "", css,
    flags=re.IGNORECASE,
  )
  # 2. Strip `filter: ...blur(...)...` declarations. Other `filter`
  #    values (hue-rotate, grayscale, saturate, etc.) stay; only the
  #    blur is a readability killer. Property boundary on the left so
  #    `--my-filter: blur(...)` (custom-property name) isn't caught.
  css = re.sub(
    r"(?<![\w-])filter\s*:\s*[^;{}]*blur\s*\([^)]*\)[^;{}]*;?", "", css,
    flags=re.IGNORECASE,
  )
  # 3. Clamp the alpha channel on the readable-surface variables.
  #    Two color syntaxes:
  #      legacy:   rgba(R, G, B, A)  or  hsla(H, S, L, A)
  #      modern:   rgb(R G B / A)    or  hsl(H S L / A)
  #    Only sub-0.9 alpha gets clamped to 1; high-alpha values are
  #    left alone. Property name match is case-insensitive (mixed-
  #    case custom properties are technically legal).
  def _clamp_legacy(match: re.Match) -> str:
    name, prefix, alpha = match.group(1), match.group(2), match.group(3)
    if float(alpha) >= 0.9:
      return match.group(0)
    return f"{name}: {prefix}, 1)"
  css = re.sub(
    r"(--(?:surface|surface2|bg))\s*:\s*"
    r"(rgba\(\s*[\d.%]+\s*,\s*[\d.%]+\s*,\s*[\d.%]+|"
    r"hsla\(\s*[\d.deg]+\s*,\s*[\d.%]+\s*,\s*[\d.%]+)"
    r"\s*,\s*([\d.]+)\s*\)",
    _clamp_legacy, css, flags=re.IGNORECASE,
  )

  def _clamp_modern(match: re.Match) -> str:
    name, prefix, alpha = match.group(1), match.group(2), match.group(3)
    if float(alpha.rstrip('%')) / (100 if alpha.endswith('%') else 1) >= 0.9:
      return match.group(0)
    # `prefix` greedily consumed any whitespace before `/`, so strip
    # it before reassembling to avoid a double space in the output.
    return f"{name}: {prefix.rstrip()} / 1)"
  css = re.sub(
    r"(--(?:surface|surface2|bg))\s*:\s*"
    r"(rgba?\([^/)]+|hsla?\([^/)]+)"
    r"\s*/\s*([\d.]+%?)\s*\)",
    _clamp_modern, css, flags=re.IGNORECASE,
  )

  # 4. Strip full-screen fixed-position pseudo-overlays on root
  #    elements unless they're explicitly marked behind-content
  #    (z-index < 0 OR pointer-events: none + z-index 0). The
  #    Andalusian-paradise breakage was an agent putting animated
  #    mandalas at `position: fixed; inset: 0` over the chat.
  #
  #    Rather than parse selectors/declarations properly, we wrap
  #    the whole class of risky rules with `pointer-events: none`
  #    and force `z-index: -1` if those properties aren't already
  #    present. This preserves the visual ornament but pushes it
  #    behind the actual UI.
  css = _force_overlays_behind_content(css)

  # 5. Strip unscoped global focus rules that clobber shell styling.
  #    `input:focus-visible { outline: ... }` or
  #    `textarea:focus { ... }` at the top level (no parent class)
  #    would override the shell's deliberate focus indicators and
  #    re-introduce the "purple square" bug on the chat input.
  css = _strip_unscoped_focus_rules(css)

  # 6. Inject defaults for any core variable the agent's theme
  #    omitted, so the shell never falls back to an invisible
  #    hardcoded literal.
  css = _inject_missing_core_vars(css)

  return css


_OVERLAY_SELECTOR_RE = re.compile(
  r"((?:^|[\s,}])\s*(?:html|body|#root|\.shell)(?:::before|::after)\b)",
  re.IGNORECASE | re.MULTILINE,
)


def _force_overlays_behind_content(css: str) -> str:
  """Find rules on `html|body|#root|.shell` pseudo-elements with
  `position: fixed; inset: 0;` (or equivalent full-cover) and force
  them behind the UI. We append `pointer-events: none;` and
  `z-index: -1;` inside the rule's body so any agent-set positive
  z-index is overridden.

  We do a coarse selector match — if a rule's selector list includes
  any root-element pseudo, we touch the whole rule.
  """
  # Find each rule block: selector { body }
  result = []
  i = 0
  while i < len(css):
    # Find the next `{`. If none, append the rest and break.
    brace = css.find("{", i)
    if brace == -1:
      result.append(css[i:])
      break
    selector = css[i:brace]
    # Find matching closing brace (no nested @rules expected here —
    # @keyframes blocks have nested rules but their outer selector
    # is `@keyframes name` which doesn't match _OVERLAY_SELECTOR_RE).
    close = css.find("}", brace)
    if close == -1:
      result.append(css[i:])
      break
    body = css[brace + 1:close]
    if _OVERLAY_SELECTOR_RE.search(selector):
      # Looks like a root pseudo-element rule. Append safety
      # declarations idempotently — only if not already set to a
      # safe value.
      additions = []
      if not re.search(
        r"pointer-events\s*:\s*none", body, re.IGNORECASE,
      ):
        additions.append("  pointer-events: none;")
      # Force z-index to -1 regardless of what's there — overlays
      # should never sit above content. Strip any existing z-index
      # declaration first so the appended one wins.
      body = re.sub(
        r"z-index\s*:[^;{}]*;?", "", body, flags=re.IGNORECASE,
      )
      additions.append("  z-index: -1;")
      body = body.rstrip() + "\n" + "\n".join(additions) + "\n"
    result.append(selector + "{" + body + "}")
    i = close + 1
  return "".join(result)


_UNSCOPED_FOCUS_SELECTOR_RE = re.compile(
  # A selector list where at least one selector is a bare
  # `input` or `textarea` (optionally followed by `:focus`,
  # `:focus-visible`, `:focus-within`) with no parent class
  # selector. Conservative: only flag if the entire selector list
  # is bare element+focus.
  r"^[ \t]*(input|textarea)\s*(?::focus(?:-visible|-within)?)?"
  r"(?:\s*,\s*(?:input|textarea)\s*(?::focus(?:-visible|-within)?)?)*"
  r"\s*$",
  re.IGNORECASE,
)


def _strip_unscoped_focus_rules(css: str) -> str:
  """Remove top-level rules whose selector list is just bare
  `input` / `textarea` (with optional `:focus*`). Such rules in
  agent-authored theme.css would override the shell's intentional
  focus indicators globally — exactly the pattern that re-introduced
  the purple-square bug. Scoped rules (`.my-theme input:focus { }`)
  are preserved."""
  out = []
  i = 0
  while i < len(css):
    brace = css.find("{", i)
    if brace == -1:
      out.append(css[i:])
      break
    selector = css[i:brace]
    close = css.find("}", brace)
    if close == -1:
      out.append(css[i:])
      break
    # Find a sensible block boundary on the selector — match against
    # the part after the last `}` (or start) so a selector list
    # that's just `input:focus, textarea:focus` is detected even
    # when preceded by other rules without an explicit newline.
    last_brace = selector.rfind("}")
    sel_to_test = selector[last_brace + 1:] if last_brace >= 0 else selector
    if _UNSCOPED_FOCUS_SELECTOR_RE.match(sel_to_test.strip()):
      # Drop the whole rule. Keep anything BEFORE the matched
      # selector (so prior rules in the same chunk survive).
      preserved = selector[:last_brace + 1] if last_brace >= 0 else ""
      out.append(preserved)
      i = close + 1
      continue
    out.append(selector + "{" + css[brace + 1:close] + "}")
    i = close + 1
  return "".join(out)


def _inject_missing_core_vars(css: str) -> str:
  """For any core variable the theme didn't define, append a
  `:root { --foo: <default>; }` block at the end of the CSS so the
  shell never falls back to a hardcoded literal that might be
  invisible against the active background."""
  defined = set(re.findall(r"(--[a-zA-Z][\w-]*)\s*:", css))
  missing = _CORE_VARS - defined
  if not missing:
    return css
  # Pull defaults from DEFAULT_THEME by parsing it once.
  defaults: dict[str, str] = {}
  for line in DEFAULT_THEME.splitlines():
    m = re.match(r"\s*(--[\w-]+)\s*:\s*([^;]+);", line)
    if m:
      defaults[m.group(1)] = m.group(2).strip()
  injected = "\n".join(
    f"  {name}: {defaults[name]};"
    for name in sorted(missing)
    if name in defaults
  )
  if not injected:
    return css
  return css + (
    f"\n/* Möbius: injected defaults for variables the theme omitted */\n"
    f":root {{\n{injected}\n}}\n"
  )


def inject_theme_into_html(html: str, data_dir: str) -> str:
  """Inject the active theme CSS and background color into an HTML string.

  Replaces the </head> tag with a <style> block containing the theme CSS,
  and replaces the default #0c0f14 background color placeholder with the
  active theme's --bg color. Used by both the SPA fallback and the
  app-frame endpoint.

  Security: the theme CSS is owner-controlled via the storage API but
  the agent (running autonomously) writes it. We escape `</` sequences
  to defend against `</style><script>...` breakouts even from agent-
  authored CSS, and restrict @import URLs to http(s) schemes to block
  `javascript:` / `data:` URIs in font import declarations.

  Readability: a separate `_enforce_readability` pass strips known
  content-obscuring declarations (blur filters, low-alpha surfaces)
  that have broken agent-authored themes before. See its docstring
  for the failure modes.
  """
  css = get_theme_css(data_dir)
  bg = get_bg_color(data_dir)
  imports, css = extract_imports(css)
  safe_imports = [u for u in imports if _is_safe_import_url(u)]
  link_tags = "".join(
    f'<link rel="stylesheet" href="{html_escape(url, quote=True)}">\n'
    for url in safe_imports
  )
  css = _enforce_readability(css)
  safe_css = _escape_for_style_tag(css)
  html = html.replace(
    "</head>", f"{link_tags}<style>{safe_css}</style>\n</head>"
  )
  html = html.replace("background:#0c0f14", f"background:{bg}")
  html = html.replace('content="#0c0f14"', f'content="{bg}"')
  return html
