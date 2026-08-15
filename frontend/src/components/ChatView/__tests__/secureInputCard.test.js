import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import assert from 'node:assert/strict'

const component = readFileSync(new URL('../SecureInputCard.jsx', import.meta.url), 'utf8')
const stream = readFileSync(new URL('../useStreamConnection.js', import.meta.url), 'utf8')
const backend = readFileSync(
  new URL('../../../../../backend/app/routes/secure_inputs.py', import.meta.url),
  'utf8',
)

test('secure inputs are uncontrolled and never use browser persistence', () => {
  assert.match(component, /const formRef = useRef/)
  assert.doesNotMatch(component, /value=\{|setFields|localStorage|sessionStorage|indexedDB/)
  assert.match(component, /form\.reset\(\)/)
  assert.match(component, /for \(const key of Object\.keys\(fields\)\) fields\[key\] = ''/)
})

test('secure input events contain metadata and status only', () => {
  assert.match(stream, /event\.type === 'secure_input_request'/)
  assert.match(stream, /fields: Array\.isArray\(event\.fields\)/)
  assert.doesNotMatch(stream, /event\.values|event\.secrets/)
  assert.doesNotMatch(stream, /item\.type !== 'secure_input'/)
  assert.doesNotMatch(stream, /item\.type === 'secure_input'[\s\S]{0,180}item\.status/)
  assert.match(component, /secure-card__receipt-lock/)
  assert.match(component, /Receipt saved · entered values omitted/)
  assert.doesNotMatch(component, /Memory only/)
})

test('secret-bearing request parsing avoids schema reflection', () => {
  assert.match(backend, /await request\.json\(\)/)
  assert.match(backend, /Invalid secure input submission\./)
  assert.doesNotMatch(backend, /BaseModel|response_model/)
})

test('reveal is visibly distinct and needs explicit confirmation', () => {
  assert.match(component, /secure-card--reveal/)
  assert.match(component, /Reveal for this turn/)
  assert.match(component, /reveal_confirmed/)
  assert.match(component, /sent to the AI provider/)
})
