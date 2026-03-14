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
  return useQuery({
    queryKey: ['agent-logs', agentId, since],
    queryFn: () => getAgentLogs(agentId, since),
    refetchInterval,
    staleTime: 0,
  })
}
