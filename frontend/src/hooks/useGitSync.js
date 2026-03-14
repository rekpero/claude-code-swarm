import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getGitStatus, gitPull } from '../api/client'

export function useGitSync(wsId) {
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: ['git-sync', wsId],
    queryFn: () => getGitStatus(wsId),
    enabled: !!wsId,
    refetchInterval: 30000,
    staleTime: 10000,
  })

  const pull = useMutation({
    mutationFn: () => gitPull(wsId),
    onSuccess: (data) => {
      queryClient.setQueryData(['git-sync', wsId], {
        synced: data.synced,
        local_sha: data.local_sha,
        remote_sha: data.remote_sha,
        behind: data.behind,
        ahead: data.ahead,
      })
    },
  })

  return { ...query, pull }
}
