/* Render an edit tool's changed files as immediately visible diffs. */

import DiffView from '../DiffView/DiffView.jsx'
import './ToolEditPreview.css'

function FileStat({ file }) {
  return (
    <span
      className="chat__tool-diff-stat"
      role="img"
      aria-label={`${file.insertions || 0} additions, ${file.deletions || 0} deletions`}
    >
      <span className="chat__tool-diff-add">+{file.insertions || 0}</span>
      <span className="chat__tool-diff-delete">−{file.deletions || 0}</span>
    </span>
  )
}

export default function ToolEditPreview({ preview }) {
  if (!preview?.files?.length) return null
  return (
    <div className={`chat__tool-section chat__tool-diff-section${
      preview.relative ? ' chat__tool-diff-section--relative' : ''
    }`}>
      <span className="chat__tool-section-label">Changes</span>
      <div className="chat__tool-diff-files">
        {preview.files.map((file, index) => (
          <div className="chat__tool-diff-file" key={`${file.path}-${index}`}>
            <div className="chat__tool-diff-head">
              <code title={file.path}>{file.path || 'Unknown file'}</code>
              <FileStat file={file} />
            </div>
            <div className="chat__tool-diff-scroll">
              <DiffView file={file} />
            </div>
          </div>
        ))}
      </div>
      {preview.relative && (
        <span className="chat__tool-output-more">
          Preview is based on the edited selection.
        </span>
      )}
      {preview.truncated && (
        <span className="chat__tool-output-more">
          Diff preview truncated.
        </span>
      )}
    </div>
  )
}
