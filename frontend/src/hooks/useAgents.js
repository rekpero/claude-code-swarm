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

  // Reset cursor synchronously during render when agentId changes so that
  // TanStack Query's fetch for the new query key always starts from offset 0
  // rather than the previous agent's last cursor (which would happen if we
  // relied on a useEffect to do the reset after render).
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
