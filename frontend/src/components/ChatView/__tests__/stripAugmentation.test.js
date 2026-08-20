import { test } from 'node:test'
import assert from 'node:assert/strict'

import { augmentationSuffix, stripAugmentation } from '../msgText.js'

test('stripAugmentation removes hidden file manifests without gluing queued messages', () => {
  const text = [
    'first note',
    '',
    '[Files in this session:',
    '- Screenshot.png → /data/chats/chat/uploads/Screenshot.png (image/png, 1 KB)',
    ']',
    '',
    'second note',
  ].join('\n')

  assert.equal(stripAugmentation(text), 'first note\nsecond note')
})

test('stripAugmentation removes repeated file manifests without extra blank lines', () => {
  const text = [
    'first queued',
    '',
    '[Files in this session:',
    '- One.png → /data/chats/chat/uploads/One.png (image/png, 1 KB)',
    ']',
    '',
    'second queued',
    '',
    '[Files in this session:',
    '- Two.png → /data/chats/chat/uploads/Two.png (image/png, 1 KB)',
    ']',
  ].join('\n')

  assert.equal(stripAugmentation(text), 'first queued\nsecond queued')
})

test('stripAugmentation collapses duplicate trailing file manifests from steered sends', () => {
  const text = [
    'fast forward icon nit',
    '',
    '[Files in this session:',
    '- Screenshot.png → /data/chats/chat/uploads/Screenshot.png (image/png, 307 KB)',
    ']',
    '',
    '[Files in this session:',
    '- Screenshot.png → /data/chats/chat/uploads/Screenshot.png (image/png, 307 KB)',
    ']',
  ].join('\n')

  assert.equal(stripAugmentation(text), 'fast forward icon nit')
})

test('stripAugmentation removes agent experience as a paragraph boundary', () => {
  const text = 'before\n<agent_experience>hidden</agent_experience>\nafter'
  assert.equal(stripAugmentation(text), 'before\n\nafter')
})

test('augmentationSuffix returns the hidden file manifest so an edit can keep it', () => {
  const suffix = '\n\n[Files in this session:\n- One.png → /p/One.png (image/png, 1 KB)]'
  const content = 'please summarize this' + suffix
  assert.equal(augmentationSuffix(content), suffix)
  // The visible edit plus the preserved suffix reconstructs a manifest-bearing
  // message; stripping it again yields just the new visible text.
  const edited = 'summarize the attached file' + augmentationSuffix(content)
  assert.equal(stripAugmentation(edited), 'summarize the attached file')
})

test('augmentationSuffix is empty when a queued message carries no manifest', () => {
  assert.equal(augmentationSuffix('just plain queued text'), '')
  assert.equal(augmentationSuffix(''), '')
})
