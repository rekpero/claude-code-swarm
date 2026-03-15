import { useQuery } from '@tanstack/react-query'
import { getMetrics } from '../api/client'

export function useMetrics(wsId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ['metrics', wsId],
    queryFn: () => getMetrics(wsId),
    enabled,
    refetchInterval: 3000,
    staleTime: 0,
  })
}
