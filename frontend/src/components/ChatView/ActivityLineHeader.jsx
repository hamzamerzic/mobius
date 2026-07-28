import { forwardRef } from 'react'
import {
  Dot,
  EditPencil,
  FileDocument,
  Globe,
  ImageSquare,
  Search,
  Sparkle,
  Tasks,
  Terminal,
} from '@openai/apps-sdk-ui/components/Icon'

// Every activity line uses the same fixed-width glyph lane. Tool kinds select
// their matching glyph; reasoning has its own mark so a thinking-only stretch
// remains visibly part of the activity system instead of becoming bare text.
const ACTIVITY_ICONS = {
  reasoning: Sparkle,
  terminal: Terminal,
  files: FileDocument,
  search: Search,
  edit: EditPencil,
  web: Globe,
  plan: Tasks,
  image: ImageSquare,
}

export function ActivityTypeIcon({ kind }) {
  const Icon = ACTIVITY_ICONS[kind] || Dot
  return <Icon width={13} height={13} />
}

const ActivityLineHeader = forwardRef(function ActivityLineHeader({
  text,
  displayState,
  iconKind,
  interactive = false,
  open = false,
  ariaLabel,
  controlsId,
  onToggle,
  count = null,
  reserveInteractiveGeometry = false,
}, ref) {
  const Header = interactive ? 'button' : 'div'

  return (
    <Header
      ref={ref}
      type={interactive ? 'button' : undefined}
      className={
        `chat__activity-header${interactive ? '' : ' chat__activity-header--static'}`
        + (reserveInteractiveGeometry
            ? ' chat__activity-header--reserve-interactive'
            : '')
      }
      onClick={interactive ? onToggle : undefined}
      aria-expanded={interactive ? open : undefined}
      aria-controls={interactive ? controlsId : undefined}
      aria-label={ariaLabel}
      role={interactive ? undefined : 'status'}
    >
      <span
        className="chat__activity-icon"
        data-activity-kind={iconKind}
        aria-hidden="true"
      >
        <ActivityTypeIcon kind={iconKind} />
      </span>
      <span className="chat__activity-label">
        <span className="chat__activity-label-text">{text}</span>
        {displayState === 'running' && (
          <span className="chat__activity-label-sweep" aria-hidden="true">{text}</span>
        )}
      </span>
      {count && (
        // A delegating turn's helper rollup ("2 running · 1 done") — the header
        // owns it so it reads at a glance without expanding the line.
        <span className="chat__activity-count">{count}</span>
      )}
    </Header>
  )
})

export default ActivityLineHeader
