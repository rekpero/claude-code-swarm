import { useState } from 'react'
import { ExternalLink, RefreshCw, Inbox } from 'lucide-react'
import { IssueStatusBadge } from './IssueStatusBadge'
import { EmptyState } from '../ui/EmptyState'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { useIssues, useUpdateIssueStatus } from '../../hooks/useIssues'
import { useWorkspaceContext } from '../../context/WorkspaceContext'
import { useWorkspaces } from '../../hooks/useWorkspaces'
import { formatDistanceToNow } from 'date-fns'

const REPO_RE = /^[\w.-]+\/[\w.-]+$/
function buildGitHubUrl(repo, path) {
  if (!repo || !REPO_RE.test(repo)) return null
  const [owner, name] = repo.split('/')
  return `https://github.com/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/${path}`
}

export function IssueQueue() {
  const { selectedWorkspaceId } = useWorkspaceContext()
  const { data, isLoading } = useIssues(selectedWorkspaceId)
  const { mutate: updateStatus } = useUpdateIssueStatus(selectedWorkspaceId)
  const { data: wsData } = useWorkspaces()
  const workspaces = wsData?.workspaces || []
  const wsMap = Object.fromEntries(workspaces.map(w => [w.id, w.name || w.repo_url]))
  const wsRepoMap = Object.fromEntries(workspaces.map(w => [w.id, w.github_repo]))
  const showWorkspace = !selectedWorkspaceId
  const [retryingIssue, setRetryingIssue] = useState(null)

  const issues = data?.issues || []

  return (
    <div className="px-6 py-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-[13px] font-semibold tracking-tight">
          Issue Queue
          {issues.length > 0 && (
            <span className="ml-2 text-[var(--text-muted)] font-normal text-[11px]">({issues.length})</span>
          )}
        </h2>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Spinner />
        </div>
      ) : issues.length === 0 ? (
        <EmptyState icon={Inbox} message="No issues tracked" description="Issues will appear here once labeled and picked up by the orchestrator" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="text-left py-2.5 px-4 font-medium text-[var(--text-muted)] text-[9px] uppercase tracking-widest w-12">#</th>
                <th className="text-left py-2.5 px-4 font-medium text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Title</th>
                {showWorkspace && <th className="text-left py-2.5 px-4 font-medium text-[var(--text-muted)] text-[9px] uppercase tracking-widest w-28">Workspace</th>}
                <th className="text-left py-2.5 px-4 font-medium text-[var(--text-muted)] text-[9px] uppercase tracking-widest w-28">Status</th>
                <th className="text-left py-2.5 px-4 font-medium text-[var(--text-muted)] text-[9px] uppercase tracking-widest w-16">Tries</th>
                <th className="text-left py-2.5 px-4 font-medium text-[var(--text-muted)] text-[9px] uppercase tracking-widest w-16">PR</th>
                <th className="text-left py-2.5 px-4 font-medium text-[var(--text-muted)] text-[9px] uppercase tracking-widest w-28">Updated</th>
                <th className="w-16" />
              </tr>
            </thead>
            <tbody>
              {issues.map((issue) => (
                <tr
                  key={`${issue.workspace_id}-${issue.issue_number}`}
                  className="border-b border-[var(--border-subtle)] last:border-b-0 hover:bg-[var(--surface-hover)] transition-colors"
                >
                  <td className="py-2.5 px-4 text-[var(--text-muted)] font-mono">
                    {issue.issue_number}
                  </td>
                  <td className="py-2.5 px-4 max-w-[300px]">
                    <a
                      href={buildGitHubUrl(wsRepoMap[issue.workspace_id], `issues/${issue.issue_number}`) ?? '#'}
                      target="_blank"
                      rel="noreferrer"
                      className="hover:text-[var(--accent)] transition-colors flex items-center gap-1.5 truncate group"
                    >
                      <span className="truncate">{issue.title || `Issue #${issue.issue_number}`}</span>
                      <ExternalLink size={9} className="flex-shrink-0 opacity-0 group-hover:opacity-40 transition-opacity" />
                    </a>
                  </td>
                  {showWorkspace && (
                    <td className="py-2.5 px-4">
                      <span className="text-[8px] text-black bg-white/90 px-1.5 py-0.5 rounded font-medium truncate max-w-[120px] inline-block">
                        {wsMap[issue.workspace_id] || '\u2014'}
                      </span>
                    </td>
                  )}
                  <td className="py-2.5 px-4">
                    <IssueStatusBadge status={issue.status} />
                  </td>
                  <td className="py-2.5 px-4 text-[var(--text-muted)] font-mono">
                    {issue.attempts ?? 0}
                  </td>
                  <td className="py-2.5 px-4">
                    {issue.pr_number ? (
                      <a
                        href={buildGitHubUrl(wsRepoMap[issue.workspace_id], `pull/${issue.pr_number}`) ?? '#'}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[var(--accent)] hover:underline font-mono"
                      >
                        #{issue.pr_number}
                      </a>
                    ) : (
                      <span className="text-[var(--text-muted)]">\u2014</span>
                    )}
                  </td>
                  <td className="py-2.5 px-4 text-[var(--text-muted)] font-mono text-[10px] whitespace-nowrap">
                    {issue.updated_at
                      ? formatDistanceToNow(new Date(issue.updated_at), { addSuffix: true })
                      : '\u2014'}
                  </td>
                  <td className="py-2.5 px-4">
                    {issue.status === 'needs_human' && (
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={retryingIssue === `${issue.workspace_id}-${issue.issue_number}`}
                        onClick={() => {
                          setRetryingIssue(`${issue.workspace_id}-${issue.issue_number}`)
                          updateStatus(
                            { issueNumber: issue.issue_number, status: 'pending', workspaceId: issue.workspace_id },
                            { onSettled: () => setRetryingIssue(null) }
                          )
                        }}
                        title="Retry this issue"
                      >
                        <RefreshCw size={9} />
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
