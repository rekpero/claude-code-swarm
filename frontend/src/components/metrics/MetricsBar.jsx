import { MetricCard } from './MetricCard'
import { useMetrics } from '../../hooks/useMetrics'
import { useWorkspaceContext } from '../../context/WorkspaceContext'

export function MetricsBar() {
  const { selectedWorkspaceId } = useWorkspaceContext()
  const { data, isLoading } = useMetrics(selectedWorkspaceId)

  const m = data || {}
  const cards = [
    { label: 'Resolved', value: isLoading ? '—' : (m.resolved ?? 0), color: 'green' },
    { label: 'In Queue', value: isLoading ? '—' : (m.pending ?? 0), color: 'text' },
    { label: 'In Progress', value: isLoading ? '—' : (m.in_progress ?? 0), color: 'accent' },
    { label: 'PRs Open', value: isLoading ? '—' : (m.prs_open ?? 0), color: 'blue' },
    { label: 'Needs Human', value: isLoading ? '—' : (m.needs_human ?? 0), color: 'red' },
    { label: 'Rate Limited', value: isLoading ? '—' : (m.rate_limited ?? 0), color: 'yellow' },
    { label: 'Avg Turns', value: isLoading ? '—' : (m.avg_turns != null ? m.avg_turns.toFixed(1) : '0.0'), color: 'text' },
  ]

  return (
    <div className="grid grid-cols-4 md:grid-cols-7 gap-3 px-5 py-4">
      {cards.map((card) => (
        <MetricCard key={card.label} {...card} />
      ))}
    </div>
  )
}
