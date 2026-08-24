import { chatQueries, settingsQueries } from '../../hooks/queries.js'
import BrainUsageIcon from './BrainUsageIcon.jsx'
import { weeklyUsagePercent } from '../SettingsView/providerUsage.js'
import { contextTokenCounts, contextUsedPercent, formatTokenCount } from './brainUsage.js'

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
  const leftPercent = providerUsageQuery.isLoading
    ? null
    : weeklyUsagePercent(providerUsageQuery.data)
  const contextTokens = contextUsageQuery.isLoading
    ? null
    : contextTokenCounts(contextUsageQuery.data)
  const rightPercent = contextUsageQuery.isLoading
    ? null
    : contextUsedPercent(contextUsageQuery.data)
  const providerLabel = PROVIDER_LABELS[provider] || 'Current model'

  const usageSummary = [
    leftPercent === null
      ? `${providerLabel} weekly usage: unknown`
      : `${providerLabel} weekly usage: ${Math.round(leftPercent)}%`,
    contextTokens === null || rightPercent === null
      ? 'Context used: unknown'
      : `Context used: ${formatTokenCount(contextTokens.used)} of ${formatTokenCount(contextTokens.maximum)} tokens (${Math.round(rightPercent)}%); ${Math.round(100 - rightPercent)}% remains before compaction`,
  ].join(' · ')

  return children({
    icon: <BrainUsageIcon leftPercent={leftPercent} rightPercent={rightPercent} />,
    ariaLabel: `Chat options. ${usageSummary}`,
    providerUsage: {
      provider,
      providerLabel,
      weeklyUsagePercent: leftPercent,
      contextTokensUsed: contextTokens?.used ?? null,
      contextTokensMaximum: contextTokens?.maximum ?? null,
    },
  })
}
