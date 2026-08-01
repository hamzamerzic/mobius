/* Render a durable continuation event without attributing it to the owner. */

import { ArrowRotateCw } from '@openai/apps-sdk-ui/components/Icon'
import MarkerCard from './MarkerCard.jsx'

export default function ContinuationCard({ msg }) {
  const manual = msg?.continuation_reason === 'manual'
  const reason = msg?.continuation_reason
  // Automatic recovery is a durable product event, not provider prose. Keep
  // one stable label across restart and usage-limit resumes so the transcript
  // clearly records that the chat resumed itself after the old Resume action
  // disappeared with the parked turn.
  const title = manual ? 'Resumed manually' : 'Resumed automatically'
  const subtitle = !manual && reason === 'restart'
    ? 'Server restarted — continuing automatically'
    : (!manual && reason === 'usage_limit'
        ? 'Usage available again — continuing automatically'
        : undefined)

  return (
    <MarkerCard
      title={title}
      subtitle={subtitle}
      icon={<ArrowRotateCw width={14} height={14} aria-hidden="true" />}
    />
  )
}
