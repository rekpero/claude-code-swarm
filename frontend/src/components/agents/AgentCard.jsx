import { useState, useEffect, useRef } from 'react'
import { ChevronDown, ChevronUp, Code, MessageSquare, RotateCw } from 'lucide-react'
import { AgentStatusBadge } from './AgentStatusBadge'
import { AgentLogViewer } from './AgentLogViewer'
import { restartAgent } from '../../api/client'
import { formatDuration, intervalToDuration } from 'date-fns'

const AGENT_TYPE_META = {
  implement: { label: 'Implementing Issue', icon: Code, color: 'text-[var(--accent)]' },
  fix_review: { label: 'Fixing PR Review', icon: MessageSquare, color: 'text-[var(--blue)]' },
}

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

  return <span className="text-[var(--text-muted)] text-[10px] font-mono tabular-nums">{elapsed}</span>
}

export function AgentCard({ agent, workspaceName, onRestarted }) {
  const isRunning = agent.status === 'running'
  const [expanded, setExpanded] = useState(isRunning)
  const [restarting, setRestarting] = useState(false)
  const [restartError, setRestartError] = useState(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    if (isRunning) {
      setExpanded(true)
    }
  }, [isRunning])

  return (
    <div
      className={`rounded-lg border bg-[var(--surface)] overflow-hidden transition-all duration-200 ${
        isRunning
          ? 'border-[var(--accent-border)] glow-border'
          : 'border-[var(--border)] hover:border-[var(--text-muted)]'
      }`}
    >
      {/* Running accent bar */}
      {isRunning && (
        <div className="h-px bg-gradient-to-r from-transparent via-[var(--accent)] to-transparent opacity-60" />
      )}

      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-[var(--surface-hover)] transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <AgentStatusBadge status={agent.status} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            {(() => {
              const meta = AGENT_TYPE_META[agent.agent_type]
              const TypeIcon = meta?.icon
              return meta ? (
                <span className={`flex items-center gap-1 text-[10px] font-semibold ${meta.color}`}>
                  {TypeIcon && <TypeIcon size={10} />}
                  {meta.label}
                </span>
              ) : (
                <span className="text-[10px] text-[var(--text-dim)] font-medium">
                  {agent.agent_type || 'agent'}
                </span>
              )
            })()}
            {agent.issue_number && (
              <span className="text-[var(--text-dim)] text-[10px] font-mono">
                issue #{agent.issue_number}
              </span>
            )}
            {agent.pr_number && (
              <span className="text-[var(--text-dim)] text-[10px] font-mono">
                PR #{agent.pr_number}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[9px] text-[var(--text-muted)] font-mono truncate">
              {agent.branch_name || agent.agent_id}
            </span>
            {workspaceName && (
              <span className="text-[8px] text-black bg-white/90 px-1.5 py-0.5 rounded font-medium truncate max-w-[120px]">
                {workspaceName}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-4 flex-shrink-0">
          <ElapsedTime startedAt={agent.started_at} status={agent.status} />
          <span className="text-[10px] text-[var(--text-muted)] font-mono tabular-nums">
            {agent.turns_used ?? 0}
            {agent.max_turns ? `/${agent.max_turns}` : ''} turns
          </span>
          {isRunning && (
            <div className="flex flex-col items-end gap-0.5">
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  if (restarting) return
                  setRestarting(true)
                  setRestartError(null)
                  restartAgent(agent.agent_id)
                    .then(() => { Promise.resolve(onRestarted?.()).catch(() => {}) })
                    .catch((err) => { if (mountedRef.current) setRestartError(err?.message || 'Restart failed') })
                    .finally(() => { if (mountedRef.current) setRestarting(false) })
                }}
                disabled={restarting}
                className="flex items-center gap-1 px-2 py-1 text-[9px] font-medium text-[var(--yellow)] bg-[rgba(234,179,8,0.08)] border border-[rgba(234,179,8,0.15)] rounded hover:bg-[rgba(234,179,8,0.15)] transition-colors disabled:opacity-40"
                title="Kill and restart this agent"
              >
                <RotateCw size={9} className={restarting ? 'animate-spin' : ''} />
                {restarting ? 'Restarting...' : 'Restart'}
              </button>
              {restartError && (
                <span className="text-[8px] text-[var(--red)]">{restartError}</span>
              )}
            </div>
          )}
          <div className="text-[var(--text-muted)]">
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </div>
        </div>
      </div>

      <div className="px-4 pb-4" style={{ display: expanded ? undefined : 'none' }}>
        <AgentLogViewer agentId={agent.agent_id} isRunning={isRunning} />
      </div>
    </div>
  )
}
