import test from 'node:test'
import assert from 'node:assert/strict'

import {
  questionResponseActivityChanged,
  questionResponseActivitySnapshot,
} from '../questionResponseActivity.js'

const question = {
  type: 'question',
  question_id: 'q-1',
  questions: [{ question: 'Continue?' }],
  absorbedTool: 'AskUserQuestion',
  absorbedToolUseId: 'tool-1',
}

test('answer controls and raw question-tool settlement are not response activity', () => {
  const snapshot = questionResponseActivitySnapshot([
    { type: 'text', content: 'Before' },
    question,
  ])
  assert.equal(questionResponseActivityChanged(snapshot, [
    { type: 'text', content: 'Before' },
    { ...question, answers: { Continue: 'Yes' } },
  ]), false)
  assert.equal(questionResponseActivityChanged(snapshot, [
    { type: 'text', content: 'Before' },
    {
      type: 'question',
      question_id: 'q-1',
      questions: [{ question: 'Continue?' }],
      answers: { Continue: 'Yes' },
    },
  ]), false)
})

test('text, thinking, tool, and error changes are response activity', () => {
  const items = [{ type: 'text', content: 'Before' }, question]
  const snapshot = questionResponseActivitySnapshot(items)
  for (const activity of [
    { type: 'text', content: 'After' },
    { type: 'thinking', content: 'Working' },
    { type: 'tool', tool: 'Bash', status: 'running' },
    { type: 'error', message: 'Stopped' },
  ]) {
    assert.equal(questionResponseActivityChanged(
      snapshot,
      [...items, activity],
    ), true)
  }
})

test('catch-up object key order cannot manufacture response activity', () => {
  const snapshot = questionResponseActivitySnapshot([
    { type: 'text', content: 'Before', source: { url: 'u', title: 't' } },
    question,
  ])
  assert.equal(questionResponseActivityChanged(snapshot, [
    { source: { title: 't', url: 'u' }, content: 'Before', type: 'text' },
    {
      questions: [{ question: 'Continue?' }],
      question_id: 'q-1',
      type: 'question',
      answers: { Continue: 'Yes' },
    },
  ]), false)
})

test('a catch-up snapshot containing post-answer content is response activity', () => {
  const snapshot = questionResponseActivitySnapshot([
    { type: 'text', content: 'Before' },
    question,
  ])
  assert.equal(questionResponseActivityChanged(snapshot, [
    { type: 'text', content: 'Before' },
    { ...question, answers: { Continue: 'Yes' } },
    { type: 'text', content: 'After reconnect' },
  ]), true)
})
