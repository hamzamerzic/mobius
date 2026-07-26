"""Memory recall citations: identification, parsing, and survival on read.

The behaviour under test is what lets an owner tell three states apart —
the turn recalled these notes / it looked and Memory had nothing / it never
looked. The third is the absence of a citation, so the tests below care as
much about what is NOT stamped as about what is.
"""

from app.chat_transcript import (
  _compact_activity_item,
  _compact_activity_run,
  _distinctive_activity,
)
from app.events import process_event
from app.memory_recall import (
  MAX_RECALL_NOTES,
  RECALL_EMPTY,
  RECALL_HIT,
  RECALL_SEARCHING,
  recall_from_command,
  recall_from_output,
)

MEMORY_CMD = 'python3 /data/apps/memory/memory_search.py "what does he prefer" "chat-1"'

# Synthetic notes. Fixtures here become a public diff, so they must never carry
# anything from a real owner's graph — a memory note is personal by definition.
HIT_OUTPUT = """Relevant memories:
- Apps render in a sandboxed frame: Each mini-app runs isolated. [notes/apps-render-in-a-sandboxed-frame.md]
- Theme variables are shared: Colors come from one stylesheet. [notes/theme-variables-are-shared.md]
FILES: notes/apps-render-in-a-sandboxed-frame.md, notes/theme-variables-are-shared.md"""


# --- identification -------------------------------------------------------

def test_a_memory_search_command_is_identified_as_a_lookup():
  assert recall_from_command(MEMORY_CMD) == {"status": RECALL_SEARCHING}


def test_a_command_merely_mentioning_memory_search_is_not_a_lookup():
  # Identification gates everything downstream, so a false positive here would
  # mint citations from an unrelated command's output.
  # Every one of these is an ordinary thing to do WHILE working on Memory, and
  # each names the script without running it.
  assert recall_from_command("grep -rn memory_search.py /data/platform") is None
  assert recall_from_command("cat /data/apps/memory/memory_search.py") is None
  assert recall_from_command("wc -l memory_search.py") is None
  assert recall_from_command("ls -la /data/apps/memory/memory_search.py") is None
  assert recall_from_command("vim memory_search.py") is None
  assert recall_from_command("python3 -m py_compile app/memory_search.py") is None
  assert recall_from_command("echo memory_search.python") is None
  assert recall_from_command("ls /data/apps/memory/") is None
  assert recall_from_command("") is None
  assert recall_from_command(None) is None


def test_the_script_is_recognized_however_it_is_invoked():
  assert recall_from_command("memory_search.py 'q'") is not None
  assert recall_from_command('cd /x && python3 ./memory_search.py "q"') is not None
  assert recall_from_command('python3 -u "/a/b/memory_search.py" "q"') is not None
  assert recall_from_command('MEMORY_READER_PROVIDER=none python3 /a/memory_search.py "q"') is not None
  assert recall_from_command('/usr/bin/python3.12 /a/memory_search.py "q"') is not None


# --- parsing --------------------------------------------------------------

def test_a_successful_lookup_cites_the_notes_it_opened():
  recall = recall_from_output(HIT_OUTPUT)
  assert recall["status"] == RECALL_HIT
  assert [note["id"] for note in recall["notes"]] == [
    "apps-render-in-a-sandboxed-frame", "theme-variables-are-shared",
  ]
  assert recall["notes"][0]["title"] == "Apps render in a sandboxed frame"
  assert recall["notes"][0]["excerpt"] == "Each mini-app runs isolated."


def test_a_lookup_that_found_nothing_says_so():
  assert recall_from_output("No relevant memories.") == {"status": RECALL_EMPTY}


def test_a_carved_output_keeps_every_citation_and_falls_back_on_titles():
  # A full lookup exceeds the inline threshold and is reduced to head+tail, so
  # the titled section lines in the middle can be lost. The FILES: line is
  # authoritative and sits in the tail, so the citation SET must survive whole.
  carved = "Relevant memories:\n- A: b [notes/a.md]\n…\nFILES: notes/a.md, notes/z.md"
  recall = recall_from_output(carved)
  assert [note["id"] for note in recall["notes"]] == ["a", "z"]
  assert recall["notes"][1]["title"] == "z", "a title-less note still reads"


def test_an_unreadable_body_never_claims_nothing_was_found():
  # "Nothing relevant" is a strong claim about the owner's memory. Only the
  # app's own marker may make it; anything else degrades to a note-less beat.
  for body in ("", "   ", "some unrelated text", "Traceback (most recent call last):"):
    recall = recall_from_output(body)
    assert recall["status"] == RECALL_HIT
    assert recall["notes"] == []


def test_a_citation_path_may_not_escape_the_graph():
  recall = recall_from_output(
    "FILES: ../../etc/passwd, /abs/x.md, notes/../secret.md, notes/ok.md"
  )
  assert [note["path"] for note in recall["notes"]] == ["notes/ok.md"]


def test_repeated_and_excessive_citations_are_bounded():
  paths = ", ".join(f"notes/n{i}.md" for i in range(40))
  recall = recall_from_output(f"FILES: notes/dup.md, notes/dup.md, {paths}")
  assert len(recall["notes"]) == MAX_RECALL_NOTES
  assert recall["notes"][0]["path"] == "notes/dup.md"
  assert len({note["path"] for note in recall["notes"]}) == len(recall["notes"])


def test_the_last_files_line_wins_after_a_head_tail_carve():
  # A carve keeps the head, so a stale FILES: from the head could linger above
  # the real one. memory_search.py always prints it last.
  recall = recall_from_output(
    "FILES: notes/stale.md\n…carved…\nRelevant memories:\nFILES: notes/real.md"
  )
  assert [note["path"] for note in recall["notes"]] == ["notes/real.md"]


# --- the block carries it through persistence ------------------------------

def _tool_blocks(recall_in, recall_out, output=HIT_OUTPUT):
  blocks: list = []
  process_event({"type": "tool_start", "tool": "Bash", "tool_use_id": "t1"}, blocks)
  event_in = {"type": "tool_input", "tool_use_id": "t1", "input": MEMORY_CMD}
  if recall_in is not None:
    event_in["recall"] = recall_in
  process_event(event_in, blocks)
  event_out = {"type": "tool_output", "tool_use_id": "t1", "content": output}
  if recall_out is not None:
    event_out["recall"] = recall_out
  process_event(event_out, blocks)
  return blocks


def test_the_lookup_marker_reaches_the_persisted_block_and_then_settles():
  blocks = _tool_blocks(
    {"status": RECALL_SEARCHING},
    {"status": RECALL_HIT, "notes": [{"id": "a", "path": "notes/a.md", "title": "A"}]},
  )
  assert blocks[0]["recall"]["status"] == RECALL_HIT
  assert blocks[0]["recall"]["notes"][0]["id"] == "a"


def test_an_ordinary_command_gains_no_recall_field():
  blocks = _tool_blocks(None, None, output="total 0\n")
  assert "recall" not in blocks[0]


# --- survival through the read-side projection -----------------------------

def test_consulting_memory_is_its_own_activity_beat():
  assert _distinctive_activity({"type": "tool", "tool": "Bash",
                                "recall": {"status": RECALL_HIT, "notes": []}})
  assert not _distinctive_activity({"type": "tool", "tool": "Bash"})


def test_the_compacted_line_still_knows_what_it_recalled():
  # Without this the beat renders live and reverts to "Ran a command" on the
  # next chat load, which is worse for trust than never having shown it.
  item = _compact_activity_item({
    "type": "tool", "tool": "Bash", "status": "done",
    "input": MEMORY_CMD,
    "recall": {"status": RECALL_HIT, "notes": [{"id": "a", "path": "notes/a.md"}]},
  })
  assert item["recall"]["notes"][0]["id"] == "a"


def test_citations_roll_up_so_a_folded_run_keeps_them():
  # _compact_activity_entries keeps only two entries per tool name, so a third
  # lookup's notes exist ONLY on the run summary.
  blocks = [
    (i, {"type": "tool", "tool": "Bash", "status": "done",
         "recall": {"status": RECALL_HIT,
                    "notes": [{"id": f"n{i}", "path": f"notes/n{i}.md"}]}})
    for i in range(3)
  ]
  run = _compact_activity_run(blocks, message_index=0)
  assert [note["id"] for note in run["recall"]["notes"]] == ["n0", "n1", "n2"]
  assert run["recall"]["status"] == RECALL_HIT


def test_a_run_with_no_lookup_carries_no_recall_key():
  blocks = [(0, {"type": "tool", "tool": "Bash", "status": "done"})]
  assert "recall" not in _compact_activity_run(blocks, message_index=0)


def test_a_remembered_note_outranks_an_empty_probe_in_the_same_run():
  blocks = [
    (0, {"type": "tool", "tool": "Bash", "status": "done",
         "recall": {"status": RECALL_EMPTY}}),
    (1, {"type": "tool", "tool": "Bash", "status": "done",
         "recall": {"status": RECALL_HIT,
                    "notes": [{"id": "a", "path": "notes/a.md"}]}}),
  ]
  run = _compact_activity_run(blocks, message_index=0)
  assert run["recall"]["status"] == RECALL_HIT
  assert [note["id"] for note in run["recall"]["notes"]] == ["a"]


def test_an_all_empty_run_still_reports_that_it_looked():
  blocks = [(0, {"type": "tool", "tool": "Bash", "status": "done",
                 "recall": {"status": RECALL_EMPTY}})]
  run = _compact_activity_run(blocks, message_index=0)
  assert run["recall"] == {"status": RECALL_EMPTY, "notes": []}
