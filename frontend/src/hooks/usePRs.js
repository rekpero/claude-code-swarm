import { useQuery } from '@tanstack/react-query'
import { getPRs } from '../api/client'

export function usePRs(wsId) {
  return useQuery({
    queryKey: ['prs', wsId],
    queryFn: () => getPRs(wsId),
    refetchInterval: 5000,
    staleTime: 0,
  })
}
