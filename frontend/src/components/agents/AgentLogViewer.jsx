import { useEffect, useRef, useState } from 'react'
import { useAgentLogs } from '../../hooks/useAgents'
import { Spinner } from '../ui/Spinner'

const MAX_DISPLAY = 500

function eventTypeClass(eventType) {
  switch (eventType) {
    case 'assistant': return 'text-[var(--accent)]'
    case 'tool_use': return 'text-[var(--yellow)]'
    case 'tool_result': return 'text-[var(--text-muted)]'
    case 'result': return 'text-[var(--green)]'
    case 'error': return 'text-[var(--red)]'
    case 'system': return 'text-[var(--blue)]'
    case 'user': return 'text-[var(--text-muted)]'
    case 'rate_limit_event': return 'text-[var(--yellow)]'
    default: return 'text-[var(--text-muted)]'
  }
}

function formatLogTime(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

function formatToolUse(b) {
  const tool = b.name || 'unknown'
  const input = b.input || {}
  if (tool === 'Bash') return `$ ${(input.command || '').substring(0, 120)}`
  if (tool === 'Read') return `Read ${input.file_path || '?'}`
  if (tool === 'Edit' || tool === 'Write') return `${tool} ${input.file_path || '?'}`
  if (tool === 'Grep') return `Grep "${input.pattern || ''}"`
  if (tool === 'Glob') return `Glob ${input.pattern || ''}`
  if (tool === 'Skill') return `Skill: ${input.skill || '?'}`
  if (tool === 'WebSearch') return `WebSearch: ${input.query || '?'}`
  if (tool === 'WebFetch') return `WebFetch: ${input.url || '?'}`
  if (tool === 'Agent') return `Agent: ${input.description || '?'}`
  return `${tool}`
}

function tryParseEventData(raw, eventType) {
  try {
    const d = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (eventType === 'assistant' || d?.type === 'assistant') {
      const blocks = d.message?.content || []
      const parts = []
      for (const b of blocks) {
        if (b.type === 'text' && b.text) parts.push(b.text)
        else if (b.type === 'tool_use') parts.push(formatToolUse(b))
        else if (b.type === 'thinking' && b.thinking) parts.push('(thinking) ' + b.thinking)
        else if (typeof b === 'string') parts.push(b)
      }
      return parts.join(' ') || null
    }
    if (eventType === 'user' || d?.type === 'user') return null
    if (eventType === 'tool_use' || d?.type === 'tool_use') {
      const tool = d.tool || d.name || 'unknown'
      const input = d.input || {}
      if (tool === 'Bash') return `$ ${input.command || ''}`
      if (tool === 'Read') return `Read ${input.file_path || '?'}`
      if (tool === 'Edit' || tool === 'Write') return `${tool} ${input.file_path || '?'}`
      if (tool === 'Grep') return `Grep "${input.pattern || ''}"`
      if (tool === 'Glob') return `Glob ${input.pattern || ''}`
      if (tool === 'WebSearch') return `WebSearch: ${input.query || '?'}`
      if (tool === 'WebFetch') return `WebFetch: ${input.url || '?'}`
      if (tool === 'Agent') return `Agent: ${input.description || '?'}`
      return `${tool}: ${JSON.stringify(input)}`
    }
    if (eventType === 'tool_result' || d?.type === 'tool_result') return null
    if (eventType === 'result' || d?.type === 'result') {
      const r = d.result
      if (typeof r === 'string') return r
      if (r && typeof r === 'object') return JSON.stringify(r)
      return 'Agent finished'
    }
    if (eventType === 'error' || d?.type === 'error') {
      const err = d.error
      if (typeof err === 'string') return err
      if (err && err.message) return err.message
      return 'Error occurred'
    }
    if (eventType === 'system' || d?.type === 'system') {
      if (d.subtype === 'init') return `Session started in ${d.cwd || '?'}`
      return d.message || d.text || null
    }
    if (eventType === 'rate_limit_event') return 'Rate limit event'
    return null
  } catch {
    return raw || null
  }
}

export function AgentLogViewer({ agentId, isRunning }) {
  const containerRef = useRef(null)
  const [allEvents, setAllEvents] = useState([])
  // Track the agentId for which the cursor was last reset so the data effect
  // can guard against overwriting the reset with stale cached data.
  const cursorAgentIdRef = useRef(agentId)

  const { data, isLoading, cursorRef } = useAgentLogs(agentId, { refetchInterval: isRunning ? 3000 : false })

  useEffect(() => {
    cursorAgentIdRef.current = agentId
    setAllEvents([])
    cursorRef.current = 0
  }, [agentId, cursorRef])

  useEffect(() => {
    // Guard the entire update with the agentId check to prevent stale cached
    // events from a previous agent being appended before the reset effect runs.
    if (data?.events?.length > 0 && cursorAgentIdRef.current === agentId) {
      const newCursor = data.events[data.events.length - 1].id
      setAllEvents(prev => {
        const existingIds = new Set(prev.map(e => e.id))
        const newEvents = data.events.filter(e => !existingIds.has(e.id))
        if (newEvents.length === 0) return prev
        return [...prev, ...newEvents]
      })
      // Update cursor outside the state updater: React may invoke updater
      // functions more than once in StrictMode/concurrent mode, which would
      // advance the cursor even when the state update is ultimately discarded.
      cursorRef.current = newCursor
    }
  }, [data, cursorRef, agentId])

  // Only auto-scroll if the user is already near the bottom (within 50px).
  // This prevents hijacking the scroll when the user is reading earlier logs.
  useEffect(() => {
    const el = containerRef.current
    if (!isRunning || !el) return
    const nearBottom = (el.scrollHeight - el.scrollTop - el.clientHeight) < 50
    if (nearBottom) {
      el.scrollTop = el.scrollHeight
    }
  }, [allEvents, isRunning])

  const displayEvents = allEvents.slice(-MAX_DISPLAY)

  if (isLoading && allEvents.length === 0) {
    return (
      <div className="flex items-center justify-center py-4">
        <Spinner size={12} />
      </div>
    )
  }

  const formattedEvents = displayEvents
    .map((event) => {
      const summary = tryParseEventData(event.event_data, event.event_type)
      if (!summary) return null
      return { ...event, summary }
    })
    .filter(Boolean)

  return (
    <div ref={containerRef} className="overflow-y-auto max-h-[500px] bg-[var(--bg)] border border-[var(--border-subtle)] rounded-md p-3 text-[10px] font-mono leading-relaxed">
      {formattedEvents.length === 0 ? (
        <span className="text-[var(--text-muted)]">Waiting for events...</span>
      ) : (
        formattedEvents.map((event) => (
          <div key={event.id} className="py-0.5 text-[var(--text-dim)] break-words">
            <span className="text-[var(--text-muted)] mr-2 tabular-nums">{formatLogTime(event.timestamp)}</span>
            <span className={`mr-2 font-semibold ${eventTypeClass(event.event_type)}`}>
              {event.event_type}
            </span>
            <span className="text-[var(--text-dim)]">{event.summary}</span>
          </div>
        ))
      )}
    </div>
  )
}
