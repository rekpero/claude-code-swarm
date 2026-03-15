import { useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getAgents, getAgentLogs } from '../api/client'

export function useAgents(wsId, { limit = 20, offset = 0, enabled = true } = {}) {
  return useQuery({
    queryKey: ['agents', wsId, limit, offset],
    queryFn: () => getAgents(wsId, limit, offset),
    enabled,
    refetchInterval: 3000,
    staleTime: 0,
  })
}

export function useAgentLogs(agentId, { since = 0, refetchInterval = 3000 } = {}) {
  const cursorRef = useRef(since)
  const prevAgentIdRef = useRef(agentId)

  // Reset cursor synchronously during render when agentId changes.
  // TanStack Query v5 schedules its initial fetch via scheduleMicrotask, which
  // runs before React's useEffect callbacks (posted as MessageChannel macrotasks
  // after paint). A useEffect-based reset therefore executes too late — queryFn
  // would read the stale cursor from the previous agent, silently skipping all
  // earlier events for the new agent. Resetting here (in the render body, guarded
  // by prevAgentIdRef so it fires only once per agentId change) guarantees
  // cursorRef.current === 0 when queryFn is invoked for the new agent.
  // This also prevents AgentLogViewer's useEffect([data]) — which fires after
  // useEffect([agentId]) and can overwrite a useEffect-based reset with stale
  // cached cursor values — from causing the first fetch to use a wrong cursor.
  //
  // NOTE (React concurrent-mode): Mutating refs during the render body violates
  // the strict render-purity contract. Under concurrent rendering, this block may
  // execute more than once for the same agentId transition. This is safe here
  // because: (a) refs are not observable by React's scheduler and cannot cause
  // re-renders, (b) the prevAgentIdRef guard makes the assignment idempotent —
  // repeated executions produce the same result (cursor reset to 0), and (c) the
  // assignment must happen before the TanStack Query microtask to avoid the stale
  // cursor problem described above.  Any future restructuring should preserve this
  // ordering guarantee (e.g. by capturing agentId as a closure in queryFn and
  // resetting cursorRef there when it detects an agentId change).
  if (prevAgentIdRef.current !== agentId) {
    prevAgentIdRef.current = agentId
    cursorRef.current = 0
  }

  const query = useQuery({
    queryKey: ['agent-logs', agentId],
    queryFn: () => {
      const cursor = cursorRef.current
      return getAgentLogs(agentId, cursor)
    },
    enabled: !!agentId,
    refetchInterval,
    staleTime: 0,
  })

  return { ...query, cursorRef }
}
