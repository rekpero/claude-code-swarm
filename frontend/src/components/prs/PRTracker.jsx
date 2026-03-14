import { GitPullRequest } from 'lucide-react'
import { ReviewThreads } from './ReviewThreads'
import { Badge } from '../ui/Badge'
import { EmptyState } from '../ui/EmptyState'
import { Spinner } from '../ui/Spinner'
import { usePRs } from '../../hooks/usePRs'
import { useWorkspaceContext } from '../../context/WorkspaceContext'

function PRStatusBadge({ status }) {
  const MAP = {
    open: { variant: 'blue', label: 'Open' },
    merged: { variant: 'purple', label: 'Merged' },
    closed: { variant: 'dim', label: 'Closed' },
    pending_fix: { variant: 'yellow', label: 'Pending Fix' },
    needs_human: { variant: 'red', label: 'Needs Human' },
  }
  const { variant, label } = MAP[status] || { variant: 'dim', label: status }
  return <Badge variant={variant}>{label}</Badge>
}

export function PRTracker() {
  const { selectedWorkspaceId } = useWorkspaceContext()
  const { data, isLoading } = usePRs(selectedWorkspaceId)

  const prs = data?.prs || []

  return (
    <div className="px-5 py-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold">
          PR Tracker
          {prs.length > 0 && (
            <span className="ml-2 text-[var(--text-dim)] font-normal text-xs">({prs.length})</span>
          )}
        </h2>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : prs.length === 0 ? (
        <EmptyState icon={GitPullRequest} message="No PRs tracked" description="PRs created by agents will appear here" />
      ) : (
        <div className="flex flex-col gap-2">
          {prs.map((pr) => (
            <div
              key={pr.pr_number}
              className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <a
                  href={`https://github.com/${pr.github_repo}/pull/${pr.pr_number}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[var(--blue)] text-sm hover:underline font-medium"
                >
                  PR #{pr.pr_number}
                </a>
                <PRStatusBadge status={pr.latest_status} />
                <Badge variant="dim">
                  {pr.iterations} iteration{pr.iterations !== 1 ? 's' : ''}
                </Badge>
                {pr.total_comments > 0 && (
                  <Badge variant="yellow">
                    {pr.total_comments} comment{pr.total_comments !== 1 ? 's' : ''}
                  </Badge>
                )}
              </div>
              <ReviewThreads threads={pr.review_threads} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
