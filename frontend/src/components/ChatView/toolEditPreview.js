/* Parse the bounded provider-neutral diff carried by edit tool blocks. */

import { parseUnifiedDiff } from '../DiffView/parseUnifiedDiff.js'

export function toolEditPreview(value) {
  if (!value || typeof value !== 'object' || typeof value.diff !== 'string') {
    return null
  }
  const relative = value.relative === true
  const parsedFiles = parseUnifiedDiff(value.diff)
  const files = relative
    ? parsedFiles.map(file => ({
        ...file,
        hunks: file.hunks.map((hunk, index) => ({
          ...hunk,
          header: `Changed selection${file.hunks.length > 1 ? ` ${index + 1}` : ''}`,
        })),
      }))
    : parsedFiles
  if (files.length === 0) return null
  return {
    files,
    relative,
    truncated: value.truncated === true,
  }
}
