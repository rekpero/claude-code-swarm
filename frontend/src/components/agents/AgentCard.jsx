import { useState, useEffect } from 'react'
import { ChevronDown, ChevronUp, ExternalLink } from 'lucide-react'
import { AgentStatusBadge } from './AgentStatusBadge'
import { AgentLogViewer } from './AgentLogViewer'
import { formatDuration, intervalToDuration } from 'date-fns'

function ElapsedTime({ startedAt, status }) {
  const [elapsed, setElapsed] = useState('')

  useEffect(() => {
    if (!startedAt) return
    const update = () => {
      const start = new Date(startedAt)
      const now = new Date()
      const dur = intervalToDuration({ start, end: now })
      const parts = []
      if (dur.hours) parts.push(`${dur.hours}h`)
      if (dur.minutes) parts.push(`${dur.minutes}m`)
      parts.push(`${dur.seconds ?? 0}s`)
      setElapsed(parts.join(' '))
    }
    update()
    let t
    if (status === 'running') {
      t = setInterval(update, 1000)
    }
    return () => clearInterval(t)
  }, [startedAt, status])

  return <span className="text-[var(--text-dim)] text-[11px]">{elapsed}</span>
}

export function AgentCard({ agent }) {
  const [expanded, setExpanded] = useState(false)
  const isRunning = agent.status === 'running'

  return (
    <div
      className={`rounded-lg border bg-[var(--surface)] overflow-hidden transition-all duration-200 ${
        isRunning ? 'border-[rgba(108,92,231,0.5)] shadow-[0_0_0_1px_rgba(108,92,231,0.1)]' : 'border-[var(--border)]'
      }`}
    >
      {/* Top bar accent for running agents */}
      {isRunning && (
        <div className="h-0.5 bg-gradient-to-r from-[var(--accent)] to-[var(--blue)]" />
      )}

      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-white/[0.02] transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <AgentStatusBadge status={agent.status} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            {agent.issue_number && (
              <a
                href="#"
                onClick={(e) => { e.preventDefault(); e.stopPropagation() }}
                className="text-[var(--blue)] text-xs hover:underline"
              >
                #{agent.issue_number}
              </a>
            )}
            <span className="text-xs text-[var(--text)] truncate">
              {agent.branch || `agent-${agent.agent_id?.slice(0, 8)}`}
            </span>
          </div>
          <div className="text-[10px] text-[var(--text-dim)] font-mono truncate mt-0.5">
            {agent.agent_id}
          </div>
        </div>

        <div className="flex items-center gap-4 flex-shrink-0">
          <ElapsedTime startedAt={agent.started_at} status={agent.status} />
          <span className="text-[11px] text-[var(--text-dim)]">
            {agent.turns_used ?? 0}
            {agent.max_turns ? `/${agent.max_turns}` : ''} turns
          </span>
          <div className="text-[var(--text-dim)]">
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>
        </div>
      </div>

      {expanded && (
        <div className="px-4 pb-4">
          <AgentLogViewer agentId={agent.agent_id} isRunning={isRunning} />
        </div>
      )}
    </div>
  )
}
