import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getIssues, updateIssueStatus } from '../api/client'

export function useIssues(wsId) {
  return useQuery({
    queryKey: ['issues', wsId],
    queryFn: () => getIssues(wsId),
    refetchInterval: 5000,
    staleTime: 0,
  })
}

export function useUpdateIssueStatus(wsId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ issueNumber, status }) => updateIssueStatus(issueNumber, status, wsId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['issues', wsId] })
    },
  })
}
