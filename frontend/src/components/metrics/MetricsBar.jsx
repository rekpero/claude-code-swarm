import { MetricCard } from './MetricCard'
import { useMetrics } from '../../hooks/useMetrics'
import { useWorkspaceContext } from '../../context/WorkspaceContext'

export function MetricsBar() {
  const { selectedWorkspaceId } = useWorkspaceContext()
  const { data, isLoading } = useMetrics(selectedWorkspaceId)

  const m = data || {}
  const hibernating = m.hibernation?.hibernating
  // When the swarm is hibernating, the per-agent `rate_limited` count is 0
  // (paused agents are marked `hibernated`), so show the paused state directly
  // \u2014 otherwise the card reads 0 and hides the reason nothing is progressing.
  const rateLimitedValue = isLoading
    ? '\u2014'
    : hibernating
      ? 'PAUSED'
      : (m.rate_limited ?? 0)
  const cards = [
    { label: 'Resolved', value: isLoading ? '\u2014' : (m.resolved ?? 0), color: 'green' },
    { label: 'In Queue', value: isLoading ? '\u2014' : (m.pending ?? 0), color: 'text' },
    { label: 'In Progress', value: isLoading ? '\u2014' : (m.in_progress ?? 0), color: 'accent' },
    { label: 'PRs Open', value: isLoading ? '\u2014' : (m.prs_open ?? 0), color: 'blue' },
    { label: 'Needs Human', value: isLoading ? '\u2014' : (m.needs_human ?? 0), color: 'red' },
    { label: 'Rate Limited', value: rateLimitedValue, color: 'yellow' },
    { label: 'Avg Turns', value: isLoading ? '\u2014' : (m.avg_turns != null ? m.avg_turns.toFixed(1) : '0.0'), color: 'text' },
  ]

  return (
    <div className="grid grid-cols-4 md:grid-cols-7 gap-2 px-6 py-4 bg-[var(--bg)]">
      {cards.map((card) => (
        <MetricCard key={card.label} {...card} />
      ))}
    </div>
  )
}
