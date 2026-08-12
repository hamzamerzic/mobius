import FileText from 'lucide-react/dist/esm/icons/file-text.mjs'
import FolderKanban from 'lucide-react/dist/esm/icons/folder-kanban.mjs'
import PanelsTopLeft from 'lucide-react/dist/esm/icons/panels-top-left.mjs'
import Sigma from 'lucide-react/dist/esm/icons/sigma.mjs'
import Table2 from 'lucide-react/dist/esm/icons/table-2.mjs'

function projectTypeWords(value) {
  if (!value) return ''
  if (typeof value === 'string') return value.toLowerCase()
  return [
    value.project_type,
    value.key,
    value.name,
    value.template?.key,
    value.template?.name,
  ].filter(Boolean).join(' ').toLowerCase()
}

export function projectTypeKind(value) {
  const words = projectTypeWords(value)
  if (/latex|\.tex\b|paper/.test(words)) return 'latex'
  if (/web|site|html/.test(words)) return 'web'
  if (/sheet|table|csv/.test(words)) return 'sheet'
  if (/document|docs|markdown|writing/.test(words)) return 'document'
  return 'blank'
}

export function defaultProjectName(template) {
  const name = String(template?.name || '').trim()
  if (!name || projectTypeKind(template) === 'blank') return 'Untitled project'
  return `Untitled ${name.toLowerCase()}`
}

export default function ProjectTypeIcon({ value, size = 20, ...props }) {
  const kind = projectTypeKind(value)
  if (kind === 'latex') return <Sigma size={size} {...props} />
  if (kind === 'web') return <PanelsTopLeft size={size} {...props} />
  if (kind === 'sheet') return <Table2 size={size} {...props} />
  if (kind === 'document') return <FileText size={size} {...props} />
  return <FolderKanban size={size} {...props} />
}
