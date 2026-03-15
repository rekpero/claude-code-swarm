import { useQuery } from '@tanstack/react-query'
import { getPRs } from '../api/client'

export function usePRs(wsId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ['prs', wsId],
    queryFn: () => getPRs(wsId),
    enabled,
    refetchInterval: 5000,
    staleTime: 0,
  })
}
