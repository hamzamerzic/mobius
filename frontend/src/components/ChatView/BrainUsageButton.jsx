import { chatQueries, settingsQueries } from '../../hooks/queries.js'
import BrainUsageIcon from './BrainUsageIcon.jsx'
import { mostConstrainedRemainingPercent } from '../SettingsView/providerUsage.js'
import { contextUsedPercent, usedPercentFromRemaining } from './brainUsage.js'

const PROVIDER_LABELS = {
  claude: 'Claude',
  codex: 'Codex',
  mobius: 'Möbius',
}

export default function BrainUsageButton({
  children,
  usageEnabled = true,
  chatId = null,
  provider = null,
  providerSessionId = null,
}) {
  const providerUsageQuery = settingsQueries.providerUsage.useQuery(provider, {
    enabled: usageEnabled && Boolean(provider),
  })
  const contextUsageQuery = chatQueries.currentUsage.useQuery(
    chatId,
    provider,
    providerSessionId,
    { enabled: usageEnabled },
  )
  const remainingPercent = providerUsageQuery.isLoading
    ? null
    : mostConstrainedRemainingPercent(providerUsageQuery.data)
  const leftPercent = usedPercentFromRemaining(remainingPercent)
  const rightPercent = contextUsageQuery.isLoading
    ? null
    : contextUsedPercent(contextUsageQuery.data)
  const providerLabel = PROVIDER_LABELS[provider] || 'Current model'

  const usageSummary = [
    leftPercent === null
      ? `${providerLabel} allowance used: unknown`
      : `${providerLabel} allowance used: ${Math.round(leftPercent)}%`,
    rightPercent === null
      ? 'Context used: unknown'
      : `Context used: ${Math.round(rightPercent)}%; ${Math.round(100 - rightPercent)}% remains before compaction`,
  ].join(' · ')

  return children({
    icon: <BrainUsageIcon leftPercent={leftPercent} rightPercent={rightPercent} />,
    ariaLabel: `Chat options. ${usageSummary}`,
    providerUsage: {
      provider,
      providerLabel,
      usedPercent: leftPercent,
      contextUsedPercent: rightPercent,
    },
  })
}
