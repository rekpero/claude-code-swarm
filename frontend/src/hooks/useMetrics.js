import { useQuery } from '@tanstack/react-query'
import { getMetrics } from '../api/client'

export function useMetrics(wsId) {
  return useQuery({
    queryKey: ['metrics', wsId],
    queryFn: () => getMetrics(wsId),
    refetchInterval: 3000,
    staleTime: 0,
  })
}
