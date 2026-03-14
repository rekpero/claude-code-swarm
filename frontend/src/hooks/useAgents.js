import { useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getAgents, getAgentLogs } from '../api/client'

export function useAgents(wsId, { limit = 20, offset = 0 } = {}) {
  return useQuery({
    queryKey: ['agents', wsId, limit, offset],
    queryFn: () => getAgents(wsId, limit, offset),
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
  if (prevAgentIdRef.current !== agentId) {
    prevAgentIdRef.current = agentId
    cursorRef.current = 0
  }

  const query = useQuery({
    queryKey: ['agent-logs', agentId],
    queryFn: () => getAgentLogs(agentId, cursorRef.current),
    refetchInterval,
    staleTime: 0,
  })

  return { ...query, cursorRef }
}
