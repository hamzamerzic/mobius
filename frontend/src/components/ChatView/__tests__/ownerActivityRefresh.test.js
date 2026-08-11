import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import assert from 'node:assert/strict'

const chatView = readFileSync(new URL('../ChatView.jsx', import.meta.url), 'utf8')
const paneChatView = readFileSync(
  new URL('../../Shell/PaneChatView.jsx', import.meta.url),
  'utf8',
)

function slice(source, fromNeedle, toNeedle) {
  const from = source.indexOf(fromNeedle)
  assert.ok(from >= 0, `expected to find ${fromNeedle}`)
  const to = source.indexOf(toNeedle, from)
  assert.ok(to > from, `expected to find ${toNeedle} after ${fromNeedle}`)
  return source.slice(from, to)
}

test('the pane projects ordinary activity but refreshes server truth once for the first title', () => {
  assert.match(paneChatView, /onOwnerActivity=\{handleOwnerActivity\}/)
  assert.match(paneChatView, /markChatOwnerActivity\(chatId\)/)
  const firstMessage = slice(
    paneChatView,
    'const handleFirstMessage = useCallback',
    'const handleOwnerActivity = useCallback',
  )
  assert.match(firstMessage, /refreshChats\(\)/,
    'the first committed message must replace New chat with the server title')
  const ordinaryActivity = slice(
    paneChatView,
    'const handleOwnerActivity = useCallback',
    'const handleMessageStart = useCallback',
  )
  assert.doesNotMatch(ordinaryActivity, /refreshChats/,
    'later owner activity must not fetch and reconcile the complete drawer list')
  assert.match(paneChatView, /if \(continues !== undefined\) \{[\s\S]*?refreshApps\(\)[\s\S]*?loadTheme\(\)/,
    'an idle activation 204 must not reconcile unrelated app and theme state')
  assert.doesNotMatch(paneChatView, /onQuestionAnswered/,
    'question answers must not keep a one-off parallel projection callback')
  assert.match(chatView, /const onOwnerActivityRef = useRef\(onOwnerActivity\)/)
})

test('an accepted mid-turn queue or direct steer refreshes drawer recency', () => {
  const queuePath = slice(
    chatView,
    'const result = await queueRequest',
    '// Race: server said "started" though we expected queued.',
  )
  assert.match(
    queuePath,
    /if \(result\?\.status === 'queued' \|\| result\?\.status === 'steered'\) \{[\s\S]*?onOwnerActivityRef\.current\?\.\(\)/,
    'accepted owner activity behind an existing run must not wait for run-end',
  )
  const duplicate = slice(
    queuePath,
    "if (result?.status === 'duplicate') {",
    "if (result?.status === 'queued') {",
  )
  assert.doesNotMatch(duplicate, /onOwnerActivityRef/,
    'a duplicate acknowledgement must not manufacture new recency')
})

test('duplicate and queued acceptance retire New Chat before every early return', () => {
  const fresh = slice(
    chatView,
    '// FRESH SEND PATH: no active turn, no queue.',
    'const doSendSilent = useCallback',
  )
  const accepted = fresh.indexOf('acknowledgeFirstMessageAccepted()')
  const duplicate = fresh.indexOf("if (result?.status === 'duplicate') {")
  const queued = fresh.indexOf("if (result?.status === 'queued') {")
  assert.ok(accepted >= 0 && duplicate > accepted,
    'duplicate acceptance must publish the first-message boundary before its early return')
  assert.ok(queued > accepted,
    'queued acceptance must publish the first-message boundary before either queued return')
  assert.equal(fresh.match(/acknowledgeFirstMessageAccepted\(\)/g)?.length, 1,
    'all successful fresh-send statuses share one exactly-once boundary')
  assert.match(chatView,
    /const acknowledgeFirstMessageAccepted = useCallback\(\(\) => \{[\s\S]*?if \(hadMessagesRef\.current\) return false[\s\S]*?hadMessagesRef\.current = true[\s\S]*?onFirstMessageRef\.current\?\.\(\)/,
    'the shared boundary itself must remain idempotent')

  const queuePath = slice(
    chatView,
    'const result = await queueRequest',
    '// Race: server said "started" though we expected queued.',
  )
  const queueAccepted = queuePath.indexOf('acknowledgeFirstMessageAccepted()')
  const queueDuplicate = queuePath.indexOf("if (result?.status === 'duplicate') {")
  const queueQueued = queuePath.indexOf("if (result?.status === 'queued') {")
  assert.ok(queueAccepted >= 0
      && queueDuplicate > queueAccepted
      && queueQueued > queueAccepted,
    'every accepted queue result must cross the first-message boundary before returning')
})

test('a deferred steer refreshes again at its authoritative transcript cut', () => {
  const cut = slice(
    chatView,
    'onSteeredIntoTurn: ({',
    '// System run activity is a structured sequence',
  )
  const commit = cut.indexOf('commitMessages(prev => insertMessageBatchByTs')
  const refresh = cut.indexOf('onOwnerActivityRef.current?.()')
  assert.ok(commit >= 0 && refresh > commit,
    'drawer refresh must follow the committed steer event, not predict its cut')
})

test('fast-forward exposes durable enqueue recency while the cut settles', () => {
  const fastForward = slice(
    chatView,
    'async function steerRowsImpl(steerRowsList) {',
    '// STEER (fast-forward): inject the queued messages into the LIVE turn',
  )
  const accepted = slice(
    fastForward,
    "if (result?.status === 'steered') {",
    "if (result?.status !== 'steered') {",
  )
  assert.match(accepted, /onOwnerActivityRef\.current\?\.\(\)/)
})

test('question answers share the same owner-activity refresh boundary', () => {
  const answerPath = slice(
    chatView,
    'const doSendSilent = useCallback',
    'function handleSubmit(e)',
  )
  const response = answerPath.indexOf('const response = await streamSend')
  const refresh = answerPath.indexOf('onOwnerActivityRef.current?.()')
  assert.ok(response >= 0 && refresh > response,
    'a question answer refresh belongs after its successful write')
})
