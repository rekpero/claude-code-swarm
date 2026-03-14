import { useEffect, useRef } from 'react'
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

  // Reset cursor in an effect to avoid mutating refs during render, which
  // violates React's render-purity contract and breaks under StrictMode's
  // double-render (the second pass would see prevAgentIdRef already updated
  // and skip the reset). TanStack Query's queryFn is called after effects run,
  // so the cursor is guaranteed to be 0 before the first fetch for the new agent.
  useEffect(() => {
    prevAgentIdRef.current = agentId
    cursorRef.current = 0
  }, [agentId])

  const query = useQuery({
    queryKey: ['agent-logs', agentId],
    queryFn: () => getAgentLogs(agentId, cursorRef.current),
    refetchInterval,
    staleTime: 0,
  })

  return { ...query, cursorRef }
}
