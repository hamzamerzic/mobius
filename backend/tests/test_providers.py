"""Tests for provider event parsing (providers.py)."""

import json

from app.providers import ClaudeProvider


def _assistant_event(blocks):
  return json.dumps({"type": "assistant", "message": {"content": blocks}})


def _stream_event(content_block_start):
  return json.dumps({
    "type": "stream_event",
    "event": {
      "type": "content_block_start",
      "content_block": content_block_start,
    },
  })


provider = ClaudeProvider()


def test_ask_user_question_emits_question_event():
  line = _assistant_event([{
    "type": "tool_use",
    "name": "AskUserQuestion",
    "id": "toolu_1",
    "input": {
      "questions": [{
        "question": "Color?",
        "header": "Prefs",
        "multiSelect": False,
        "options": [
          {"label": "Red", "description": "warm"},
          {"label": "Blue", "description": "cool"},
        ],
      }],
    },
  }])
  result = provider.parse_line(line)
  assert len(result) == 1
  assert result[0]["type"] == "question"
  assert result[0]["questions"][0]["question"] == "Color?"


def test_ask_user_question_suppresses_tool_start():
  line = _stream_event({
    "type": "tool_use",
    "name": "AskUserQuestion",
    "id": "toolu_1",
    "input": {},
  })
  result = provider.parse_line(line)
  assert result is None


def test_normal_tool_emits_tool_start():
  line = _stream_event({
    "type": "tool_use",
    "name": "Bash",
    "id": "toolu_2",
    "input": {},
  })
  result = provider.parse_line(line)
  assert result["type"] == "tool_start"
  assert result["tool"] == "Bash"


def test_normal_tool_emits_tool_input():
  line = _assistant_event([{
    "type": "tool_use",
    "name": "Bash",
    "id": "toolu_3",
    "input": {"command": "ls -la"},
  }])
  result = provider.parse_line(line)
  assert len(result) == 1
  assert result[0]["type"] == "tool_input"
  assert result[0]["tool"] == "Bash"


def test_mixed_tools_separate_correctly():
  line = _assistant_event([
    {
      "type": "tool_use",
      "name": "AskUserQuestion",
      "id": "toolu_1",
      "input": {
        "questions": [{"question": "Name?", "options": [
          {"label": "A"}, {"label": "B"},
        ]}],
      },
    },
    {
      "type": "tool_use",
      "name": "Bash",
      "id": "toolu_2",
      "input": {"command": "echo hi"},
    },
  ])
  result = provider.parse_line(line)
  assert len(result) == 2
  assert result[0]["type"] == "question"
  assert result[1]["type"] == "tool_input"


def test_post_question_suppression():
  """Simulates the chat.py broadcast loop: after a question event,
  text, tool_output, and tool_end must be suppressed."""
  events = [
    {"type": "text", "content": "Before the question."},
    {"type": "question", "questions": [{"question": "Color?"}]},
    {"type": "tool_output", "content": "Answer questions?"},
    {"type": "tool_end"},
    {"type": "text", "content": "I've asked the question above."},
  ]
  published = []
  suppress_text = False
  for event in events:
    event_type = event.get("type")
    if event_type == "question":
      suppress_text = True
    if suppress_text and event_type in ("text", "tool_output", "tool_end"):
      continue
    published.append(event)

  assert len(published) == 2
  assert published[0] == {"type": "text", "content": "Before the question."}
  assert published[1]["type"] == "question"
