import { useEffect, useRef, useState } from 'react'
import { useAgentLogs } from '../../hooks/useAgents'
import { Spinner } from '../ui/Spinner'

const MAX_DISPLAY = 500

function eventStyle(eventType) {
  switch (eventType) {
    case 'assistant': return 'text-[var(--text)]'
    case 'tool_use': return 'text-[var(--text-dim)]'
    case 'tool_result': return 'text-[var(--blue)]'
    case 'error': return 'text-[var(--red)]'
    case 'result': return 'text-[var(--accent)]'
    default: return 'text-[var(--text-dim)]'
  }
}

function formatEvent(event) {
  try {
    const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data
    if (!data) return event.event_type

    if (event.event_type === 'assistant') {
      const content = data.message?.content
      if (Array.isArray(content)) {
        return content.map((c) => c.text || c.input && JSON.stringify(c.input) || '').filter(Boolean).join(' ')
      }
    }
    if (event.event_type === 'tool_use') {
      return `[tool] ${data.name || ''} ${data.input ? JSON.stringify(data.input).slice(0, 120) : ''}`
    }
    if (event.event_type === 'result') {
      return `[result] ${data.result != null ? data.result : JSON.stringify(data).slice(0, 120)}`
    }
    return JSON.stringify(data).slice(0, 200)
  } catch {
    return event.event_type
  }
}

export function AgentLogViewer({ agentId, isRunning }) {
  const bottomRef = useRef(null)
  const [allEvents, setAllEvents] = useState([])

  const { data, isLoading, cursorRef } = useAgentLogs(agentId, { refetchInterval: isRunning ? 3000 : false })

  // Declared before the agentId effect so it runs first in the same effects flush.
  // When the user switches agents, TanStack Query immediately returns stale cached
  // data for the new agent (staleTime=0), causing both effects to fire together.
  // By running this effect first, it may advance cursorRef to the stale last-event
  // ID — but the agentId effect below always resets cursorRef.current = 0 afterward,
  // so the last write wins before the background refetch's queryFn fires.
  useEffect(() => {
    if (data?.events?.length > 0) {
      setAllEvents(prev => {
        const existingIds = new Set(prev.map(e => e.id))
        const newEvents = data.events.filter(e => !existingIds.has(e.id))
        return newEvents.length > 0 ? [...prev, ...newEvents] : prev
      })
      cursorRef.current = data.events[data.events.length - 1].id
    }
  }, [data])

  useEffect(() => {
    setAllEvents([])
    // Reset cursor here (in addition to the render-body guard in useAgentLogs) so
    // this effect runs after the data effect above in the same flush, guaranteeing
    // cursorRef.current === 0 when the background refetch's queryFn fires.
    cursorRef.current = 0
  }, [agentId])

  // Auto-scroll only for running agents
  useEffect(() => {
    if (isRunning && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [allEvents, isRunning])

  const displayEvents = allEvents.slice(-MAX_DISPLAY)

  if (isLoading && allEvents.length === 0) {
    return (
      <div className="flex items-center justify-center py-4">
        <Spinner size={14} />
      </div>
    )
  }

  return (
    <div className="overflow-y-auto max-h-[300px] bg-[var(--bg)] rounded-md p-3 text-[11px] font-mono">
      {displayEvents.length === 0 ? (
        <span className="text-[var(--text-dim)]">No log events yet...</span>
      ) : (
        displayEvents.map((event) => (
          <div key={event.id} className={`py-0.5 leading-relaxed ${eventStyle(event.event_type)}`}>
            <span className="text-[var(--text-dim)] mr-2 select-none">›</span>
            {formatEvent(event)}
          </div>
        ))
      )}
      <div ref={bottomRef} />
    </div>
  )
}
