import { GitPullRequest } from 'lucide-react'
import { ReviewThreads } from './ReviewThreads'
import { Badge } from '../ui/Badge'
import { EmptyState } from '../ui/EmptyState'
import { Spinner } from '../ui/Spinner'
import { usePRs } from '../../hooks/usePRs'
import { useWorkspaceContext } from '../../context/WorkspaceContext'
import { useWorkspaces } from '../../hooks/useWorkspaces'

const REPO_RE = /^[\w.-]+\/[\w.-]+$/
function buildGitHubUrl(repo, section, number) {
  if (!repo || !REPO_RE.test(repo)) return null
  if (!Number.isInteger(number) || number <= 0) return null
  const [owner, name] = repo.split('/')
  return `https://github.com/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/${section}/${number}`
}

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
  const { data: wsData } = useWorkspaces()
  const workspaces = wsData?.workspaces || []
  const wsMap = Object.fromEntries(workspaces.map(w => [w.id, w.name || w.repo_url]))
  const wsRepoMap = Object.fromEntries(workspaces.map(w => [w.id, w.github_repo]))
  const showWorkspace = !selectedWorkspaceId

  const prs = data?.prs || []

  return (
    <div className="px-6 py-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-[13px] font-semibold tracking-tight">
          PR Tracker
          {prs.length > 0 && (
            <span className="ml-2 text-[var(--text-muted)] font-normal text-[11px]">({prs.length})</span>
          )}
        </h2>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Spinner />
        </div>
      ) : prs.length === 0 ? (
        <EmptyState icon={GitPullRequest} message="No PRs tracked" description="PRs created by agents will appear here" />
      ) : (
        <div className="flex flex-col gap-2">
          {prs.map((pr) => (
            <div
              key={`${pr.workspace_id}-${pr.pr_number}`}
              className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3 hover:border-[var(--text-muted)] transition-all"
            >
              <div className="flex items-center gap-3">
                <a
                  href={buildGitHubUrl(wsRepoMap[pr.workspace_id], 'pull', pr.pr_number) ?? '#'}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[var(--accent)] text-[12px] hover:underline font-semibold font-mono"
                >
                  #{pr.pr_number}
                </a>
                <PRStatusBadge status={pr.latest_status} />
                <Badge variant="dim">
                  {pr.iterations} iter{pr.iterations !== 1 ? 's' : ''}
                </Badge>
                {pr.total_comments > 0 && (
                  <Badge variant="yellow">
                    {pr.total_comments} comment{pr.total_comments !== 1 ? 's' : ''}
                  </Badge>
                )}
                {showWorkspace && wsMap[pr.workspace_id] && (
                  <span className="text-[8px] text-black bg-white/90 px-1.5 py-0.5 rounded font-medium truncate max-w-[120px] ml-auto">
                    {wsMap[pr.workspace_id]}
                  </span>
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
