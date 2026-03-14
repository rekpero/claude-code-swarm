import { ExternalLink, RefreshCw, Inbox } from 'lucide-react'
import { IssueStatusBadge } from './IssueStatusBadge'
import { EmptyState } from '../ui/EmptyState'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { useIssues, useUpdateIssueStatus } from '../../hooks/useIssues'
import { useWorkspaceContext } from '../../context/WorkspaceContext'
import { formatDistanceToNow } from 'date-fns'

export function IssueQueue() {
  const { selectedWorkspaceId } = useWorkspaceContext()
  const { data, isLoading } = useIssues(selectedWorkspaceId)
  const { mutate: updateStatus, isPending: isUpdating } = useUpdateIssueStatus(selectedWorkspaceId)

  const issues = data?.issues || []

  return (
    <div className="px-5 py-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold">
          Issue Queue
          {issues.length > 0 && (
            <span className="ml-2 text-[var(--text-dim)] font-normal text-xs">({issues.length})</span>
          )}
        </h2>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : issues.length === 0 ? (
        <EmptyState icon={Inbox} message="No issues tracked" description="Issues will appear here once labeled and picked up by the orchestrator" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[var(--border)] text-[var(--text-dim)] text-[10px] uppercase tracking-wide">
                <th className="text-left py-2 pr-3 font-medium w-12">#</th>
                <th className="text-left py-2 pr-3 font-medium">Title</th>
                <th className="text-left py-2 pr-3 font-medium w-28">Status</th>
                <th className="text-left py-2 pr-3 font-medium w-16">Attempts</th>
                <th className="text-left py-2 pr-3 font-medium w-16">PR</th>
                <th className="text-left py-2 pr-3 font-medium w-28">Updated</th>
                <th className="w-16" />
              </tr>
            </thead>
            <tbody>
              {issues.map((issue) => (
                <tr
                  key={`${issue.workspace_id}-${issue.issue_number}`}
                  className="border-b border-[var(--border)] hover:bg-white/[0.02] transition-colors"
                >
                  <td className="py-2.5 pr-3 text-[var(--text-dim)]">
                    {issue.issue_number}
                  </td>
                  <td className="py-2.5 pr-3 max-w-[300px]">
                    <a
                      href={`https://github.com/${issue.github_repo}/issues/${issue.issue_number}`}
                      target="_blank"
                      rel="noreferrer"
                      className="hover:text-[var(--accent)] transition-colors flex items-center gap-1 truncate"
                    >
                      <span className="truncate">{issue.title || `Issue #${issue.issue_number}`}</span>
                      <ExternalLink size={10} className="flex-shrink-0 opacity-50" />
                    </a>
                  </td>
                  <td className="py-2.5 pr-3">
                    <IssueStatusBadge status={issue.status} />
                  </td>
                  <td className="py-2.5 pr-3 text-[var(--text-dim)]">
                    {issue.attempts ?? 0}
                  </td>
                  <td className="py-2.5 pr-3">
                    {issue.pr_number ? (
                      <a
                        href={`https://github.com/${issue.github_repo}/pull/${issue.pr_number}`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[var(--blue)] hover:underline"
                      >
                        #{issue.pr_number}
                      </a>
                    ) : (
                      <span className="text-[var(--text-dim)]">—</span>
                    )}
                  </td>
                  <td className="py-2.5 pr-3 text-[var(--text-dim)]">
                    {issue.updated_at
                      ? formatDistanceToNow(new Date(issue.updated_at), { addSuffix: true })
                      : '—'}
                  </td>
                  <td className="py-2.5">
                    {issue.status === 'needs_human' && (
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={isUpdating}
                        onClick={() =>
                          updateStatus({ issueNumber: issue.issue_number, status: 'pending' })
                        }
                        title="Retry this issue"
                      >
                        <RefreshCw size={10} />
                        Retry
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
