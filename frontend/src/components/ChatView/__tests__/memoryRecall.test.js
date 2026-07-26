import test from 'node:test'
import assert from 'node:assert/strict'

import {
  MAX_RECALLED_NOTES,
  messageRecall,
  noteHref,
  noteLabel,
  safeNoteId,
} from '../memoryRecall.js'

const note = (id, extra = {}) => ({
  id,
  path: `notes/${id}.md`,
  title: id.replace(/-/g, ' '),
  ...extra,
})

const toolBlock = recall => ({ type: 'tool', tool: 'Bash', recall })

test('a turn that never consulted Memory yields no row at all', () => {
  assert.equal(messageRecall([{ type: 'text', content: 'hi' }]), null)
  assert.equal(messageRecall([{ type: 'tool', tool: 'Bash' }]), null)
  assert.equal(messageRecall([]), null)
  assert.equal(messageRecall(null), null)
})

test('a lookup that found nothing is reported, not silently dropped', () => {
  // The distinction this whole row exists for: an owner must be able to tell a
  // gap in their memory from an agent that ignored it.
  const recall = messageRecall([toolBlock({ status: 'empty' })])
  assert.deepEqual(recall, { notes: [], empty: true })
})

test('an in-flight lookup is a live beat, not yet a citation', () => {
  assert.equal(messageRecall([toolBlock({ status: 'searching' })]), null)
})

test('recalled notes are collected in first-seen order', () => {
  const recall = messageRecall([
    toolBlock({ status: 'hit', notes: [note('alpha'), note('beta')] }),
  ])
  assert.deepEqual(recall.notes.map(n => n.id), ['alpha', 'beta'])
  assert.equal(recall.empty, false)
})

test('the same note recalled twice in a turn is cited once', () => {
  const recall = messageRecall([
    toolBlock({ status: 'hit', notes: [note('alpha')] }),
    toolBlock({ status: 'hit', notes: [note('alpha'), note('beta')] }),
  ])
  assert.deepEqual(recall.notes.map(n => n.id), ['alpha', 'beta'])
})

test('one empty probe does not erase what another lookup remembered', () => {
  const recall = messageRecall([
    toolBlock({ status: 'empty' }),
    toolBlock({ status: 'hit', notes: [note('alpha')] }),
  ])
  assert.deepEqual(recall.notes.map(n => n.id), ['alpha'])
  assert.equal(recall.empty, false, 'the turn did remember something')
})

test('compacted activity carries citations so they survive a reload', () => {
  // _compact_activity_run rolls recall onto the activity summary for exactly
  // this reason: the individual tool blocks are folded away on read.
  const recall = messageRecall([
    { type: 'activity', recall: { status: 'hit', notes: [note('alpha')] } },
  ])
  assert.deepEqual(recall.notes.map(n => n.id), ['alpha'])
})

test('a lookup whose output could not be parsed still counts as looking', () => {
  const recall = messageRecall([toolBlock({ status: 'hit', notes: [] })])
  assert.deepEqual(recall, { notes: [], empty: false },
    'no notes to cite, but no false "nothing relevant" claim either')
})

test('citations are bounded so one turn cannot flood the transcript', () => {
  const many = Array.from({ length: 40 }, (_, i) => note(`note-${i}`))
  const recall = messageRecall([toolBlock({ status: 'hit', notes: many })])
  assert.equal(recall.notes.length, MAX_RECALLED_NOTES)
})

test('only a well-formed note id may build a deep link', () => {
  assert.equal(safeNoteId('theme-variables-are-shared'), 'theme-variables-are-shared')
  assert.equal(safeNoteId('../../etc/passwd'), '')
  assert.equal(safeNoteId('notes/alpha'), '')
  assert.equal(safeNoteId('a b'), '')
  assert.equal(safeNoteId(''), '')
  assert.equal(safeNoteId(null), '')
  assert.equal(safeNoteId('x'.repeat(200)), '')
})

test('a note links into the Memory app through the shell intent contract', () => {
  assert.equal(
    noteHref({ id: 'theme-variables-are-shared' }),
    '/shell/?app=memory&intent=note%3Atheme-variables-are-shared',
  )
  assert.equal(noteHref({ id: '../evil' }), '',
    'an unsafe id yields no link rather than an unsafe one')
})

test('a note without a title still reads as words, never blank', () => {
  assert.equal(noteLabel({ id: 'x', title: 'Real Title' }), 'Real Title')
  // A large tool output is carved head+tail, which can drop the titled section
  // lines; the id is the fallback and must not surface raw dashes.
  assert.equal(noteLabel({ id: 'theme-variables-are-shared' }), 'theme variables are shared')
  assert.equal(noteLabel({ id: '../evil' }), '')
})

test('a malformed note is skipped without dropping its siblings', () => {
  const recall = messageRecall([
    toolBlock({
      status: 'hit',
      notes: [{ id: '../evil', path: 'notes/evil.md' }, note('alpha'), null],
    }),
  ])
  assert.deepEqual(recall.notes.map(n => n.id), ['alpha'])
})
