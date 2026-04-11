"""AI provider adapters.

Each provider knows how to:
  1. Build the CLI command for a chat message.
  2. Set up the subprocess environment (auth config, etc.).
  3. Parse a line of CLI stdout into an SSE event dict, or None to skip.

The chat module calls these to stay provider-agnostic.  Adding a new
provider means writing a new class here and registering it in PROVIDERS.
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _load_agent_settings(data_dir: str) -> dict:
  """Loads agent settings from /data/shared/agent-settings.json."""
  path = Path(data_dir) / "shared" / "agent-settings.json"
  if path.exists():
    try:
      return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
      pass
  return {}


def _skill_path() -> Path | None:
  """Returns the path to the agent skill file, or None if not found."""
  candidates = [
    Path("/app/skill/agent-skill.md"),
    Path(__file__).parent.parent.parent / "skill" / "agent-skill.md",
  ]
  return next((p for p in candidates if p.exists()), None)


@dataclass
class ProviderResult:
  """Everything the chat module needs to spawn a provider subprocess."""
  cmd: list[str]
  env: dict[str, str]


def _summarize_input(tool: str, inp: dict) -> str:
  """Returns a short human-readable summary of a tool's input."""
  if tool == "Bash":
    return inp.get("command", "")
  elif tool in ("Read", "Glob"):
    return inp.get("file_path", "") or inp.get("pattern", "")
  elif tool in ("Write", "Edit"):
    return inp.get("file_path", "")
  elif tool == "Grep":
    return inp.get("pattern", "")
  return str(inp)[:200] if inp else ""


class BaseProvider:
  """Interface that all providers implement."""

  # Display name shown in the setup wizard.
  name: str = ""
  # CLI command name (used to check if the CLI is installed).
  cli_cmd: str = ""
  # Subdirectory under /data/cli-auth/ where credentials are stored.
  auth_dir: str = ""

  def build(
    self,
    user_message: str,
    session_id: str | None,
    base_env: dict[str, str],
    data_dir: str,
  ) -> ProviderResult:
    """Returns the command and env for the subprocess."""
    raise NotImplementedError

  def parse_line(self, line: str) -> Optional[dict]:
    """Parses one stdout line into an SSE event dict, or None."""
    raise NotImplementedError


class ClaudeProvider(BaseProvider):
  """Claude Code CLI (claude -p --output-format stream-json)."""

  name = "Claude Code"
  cli_cmd = "claude"
  auth_dir = "claude"

  def build(self, user_message, session_id, base_env, data_dir, chat_id=None):
    cmd = [
      "claude",
      "-p",
      "--output-format", "stream-json",
      "--verbose",
      "--include-partial-messages",
      "--dangerously-skip-permissions",
    ]
    if session_id:
      cmd += ["--resume", session_id]
    else:
      skill = _skill_path()
      if skill:
        cmd += ["--system-prompt-file", str(skill)]

    # The agent uses agent-browser (installed in the image) via Bash for
    # screenshots and interactive testing — no MCP browser tools needed.

    # Load user-configurable settings (model, effort).
    agent_settings = _load_agent_settings(data_dir)
    if agent_settings.get("model"):
      cmd += ["--model", agent_settings["model"]]
    if agent_settings.get("effort"):
      cmd += ["--effort", agent_settings["effort"]]

    # Message is a positional argument — always last.  The "--" terminates
    # option parsing so the agent doesn't confuse it with a flag value.
    cmd += ["--", user_message]

    env = dict(base_env)
    creds = Path(data_dir) / "cli-auth" / "claude" / ".credentials.json"
    if creds.exists():
      env["CLAUDE_CONFIG_DIR"] = str(creds.parent)

    # Per-chat agent-browser session.  Every agent-browser invocation
    # in this subprocess picks up AGENT_BROWSER_SESSION via env, so
    # each chat gets its own isolated Chrome instance and they don't
    # fight over the "default" session when building in parallel.
    # The session is torn down by chat.py in the finally block.
    if chat_id:
      env["AGENT_BROWSER_SESSION"] = f"chat-{chat_id}"

    return ProviderResult(cmd=cmd, env=env)

  def _parse_stream_event(self, event: dict):
    """Handles stream_event — text deltas and tool block starts."""
    inner = event.get("event", {})
    inner_type = inner.get("type")
    if inner_type == "content_block_delta":
      delta = inner.get("delta", {})
      if delta.get("type") == "text_delta" and delta.get("text"):
        return {"type": "text", "content": delta["text"]}
    # Emit tool_start as soon as the content block begins streaming,
    # not from the assistant event.  This handles max_tokens truncation
    # where the assistant event is never sent.
    elif inner_type == "content_block_start":
      block = inner.get("content_block", {})
      if block.get("type") == "tool_use":
        return {
          "type": "tool_start",
          "tool": block.get("name", ""),
          "input": "",
        }
    return None

  def _parse_tool_event(self, event: dict):
    """Handles assistant events — backfills tool input summaries."""
    # Tool starts are emitted from content_block_start (earlier, handles
    # max_tokens truncation).  The assistant event arrives later with the
    # full input, so we emit tool_input events to backfill the summaries.
    results = []
    for block in event.get("message", {}).get("content", []):
      if block.get("type") == "tool_use":
        inp = block.get("input", {})
        summary = _summarize_input(block.get("name", ""), inp)
        if summary:
          results.append({
            "type": "tool_input",
            "tool": block.get("name", ""),
            "input": summary,
          })
    return results if results else None

  def _parse_user_event(self, event: dict):
    """Handles user events — tool results and tool_end markers."""
    # Tool results come as user messages.  The shape varies:
    # sometimes a top-level tool_use_result dict, sometimes
    # content blocks inside message.content.
    results = []
    output = ""

    result_data = event.get("tool_use_result")
    if isinstance(result_data, dict):
      stdout = result_data.get("stdout", "")
      stderr = result_data.get("stderr", "")
      output = (stdout + ("\n" + stderr if stderr else "")).strip()
    elif isinstance(result_data, str):
      output = result_data.strip()
    else:
      # Try content blocks.
      for block in event.get("message", {}).get("content", []):
        if (isinstance(block, dict)
            and block.get("type") == "tool_result"):
          content = block.get("content", "")
          if isinstance(content, str):
            output = content.strip()

    if output:
      results.append({"type": "tool_output", "content": output})
    results.append({"type": "tool_end"})
    return results

  def _parse_result_event(self, event: dict):
    """Handles result events — final cost info or error."""
    if event.get("is_error"):
      msg = event.get("result", "Unknown error.")
      # Surface a friendly message for auth failures so the user
      # knows where to fix it instead of seeing a raw CLI error.
      lower = msg.lower() if isinstance(msg, str) else ""
      if any(k in lower for k in ("auth", "login", "credential",
                                   "not logged", "sign in")):
        msg += (
          "\n\nOpen Settings and reconnect under AI provider."
        )
      return {"type": "error", "message": msg}
    return {
      "type": "done",
      "cost_usd": event.get("total_cost_usd", 0),
    }

  def parse_line(self, line: str) -> list[dict]:
    """Parse one line of Claude CLI JSON output into agent events.

    The Claude CLI emits several event shapes on stdout:
      - {"type": "stream_event", ...} → text tokens during streaming
      - {"type": "assistant", ...} → tool_use blocks (end of turn)
      - {"type": "user", ...} → tool results
      - {"type": "result", ...} → session ID and final cost/usage

    Returns a list of normalized dicts, a single dict, or None.
    """
    try:
      event = json.loads(line)
    except json.JSONDecodeError:
      return None

    event_type = event.get("type")

    if event_type == "stream_event":
      return self._parse_stream_event(event)
    elif event_type == "assistant":
      return self._parse_tool_event(event)
    elif event_type == "user":
      return self._parse_user_event(event)
    elif event_type == "result":
      return self._parse_result_event(event)

    return None


# Registry of available providers, keyed by ID.
PROVIDERS: dict[str, BaseProvider] = {
  "claude": ClaudeProvider(),
}

# The default provider when none is configured.
DEFAULT_PROVIDER = "claude"


def get_provider(provider_id: str | None = None) -> BaseProvider:
  """Returns a provider by ID, falling back to the default."""
  return PROVIDERS.get(provider_id or DEFAULT_PROVIDER, PROVIDERS[DEFAULT_PROVIDER])


def detect_available() -> list[str]:
  """Returns IDs of providers whose CLI tool is installed."""
  return [pid for pid, p in PROVIDERS.items() if shutil.which(p.cli_cmd)]
