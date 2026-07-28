import { ArrowRotateCw } from '@openai/apps-sdk-ui/components/Icon'
import MarkerCard from './MarkerCard.jsx'

export default function AutoContinuationCard({ msg }) {
  const restarted = msg?.continuation_reason === 'restart'
  const title = restarted
    ? 'Server restarted — continuing automatically'
    : 'Usage available again — continuing automatically'

  return (
    <MarkerCard
      title={title}
      icon={<ArrowRotateCw width={14} height={14} aria-hidden="true" />}
    />
  )
}
