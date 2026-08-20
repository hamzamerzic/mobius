/** Canonical render snapshots for detecting the first visible post-answer change. */

function stableSerialize(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) {
    return `[${value.map(stableSerialize).join(',')}]`
  }
  return `{${Object.keys(value).sort().map(key => (
    `${JSON.stringify(key)}:${stableSerialize(value[key])}`
  )).join(',')}}`
}

function renderableQuestionItem(item) {
  if (item?.type !== 'question') return item
  const {
    answers: _answers,
    absorbedTool: _absorbedTool,
    absorbedToolUseId: _absorbedToolUseId,
    ...renderable
  } = item
  return renderable
}

/** Snapshot only state that can make the assistant surface visibly change.
 * Answer controls and the absorbed raw question-tool lifecycle are excluded:
 * they settle the submitted card but are not the agent's continuation. */
export function questionResponseActivitySnapshot(items) {
  const renderableItems = Array.isArray(items)
    ? items.map(renderableQuestionItem)
    : []
  return stableSerialize(renderableItems)
}

export function questionResponseActivityChanged(snapshot, items) {
  return typeof snapshot === 'string'
    && snapshot !== questionResponseActivitySnapshot(items)
}
