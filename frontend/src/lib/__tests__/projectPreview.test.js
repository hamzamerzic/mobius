import test from 'node:test'
import assert from 'node:assert/strict'

import {
  projectPreviewSandbox,
  safeProjectHtmlDocument,
} from '../projectPreview.js'

test('project HTML preview injects a deny-by-default CSP into the document head', () => {
  const result = safeProjectHtmlDocument('<html><head><title>Site</title></head><body /></html>')
  assert.match(result, /^<meta http-equiv="Content-Security-Policy"/)
  assert.match(result, /default-src 'none'/)
  assert.match(result, /form-action 'none'/)
  assert.match(result, /base-uri 'none'/)
  assert.doesNotMatch(result, /script-src/)
})

test('project preview policy precedes resources placed before a malformed head', () => {
  const remoteImage = '<img src="https://tracker.invalid/pixel"><head><title>Late head</title>'
  const result = safeProjectHtmlDocument(remoteImage)

  assert.equal(result.indexOf('Content-Security-Policy') < result.indexOf(remoteImage), true)
  assert.match(result, /^<meta http-equiv="Content-Security-Policy"/)
})

test('project HTML preview grants no iframe sandbox capabilities', () => {
  assert.equal(projectPreviewSandbox(), '')
})
