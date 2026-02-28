import logging
from pathlib import Path

from orchestrator.config import GITHUB_REPO, SKILLS_ENABLED, TARGET_REPO_PATH

logger = logging.getLogger(__name__)


def _discover_installed_skills() -> list[str]:
    """Discover skills installed in the target repo and globally."""
    skills: list[str] = []

    # Check target repo .claude/skills/
    repo_skills = TARGET_REPO_PATH / ".claude" / "skills"
    if repo_skills.is_dir():
        for entry in repo_skills.iterdir():
            if entry.is_dir() or entry.is_symlink():
                skill_md = entry / "SKILL.md" if entry.is_dir() else Path(entry.resolve()) / "SKILL.md"
                if entry.is_symlink() or skill_md.exists():
                    skills.append(entry.name)

    # Check global ~/.claude/skills/
    global_skills = Path.home() / ".claude" / "skills"
    if global_skills.is_dir():
        for entry in global_skills.iterdir():
            if (entry.is_dir() or entry.is_symlink()) and entry.name not in skills:
                skills.append(entry.name)

    return sorted(skills)


def _skills_block() -> str:
    """Return the skills hint if skills are enabled, empty string otherwise."""
    if not SKILLS_ENABLED:
        return ""

    skills = _discover_installed_skills()
    if not skills:
        return ""

    skill_list = ", ".join(skills)
    return f"""
Skills: You have access to Claude Code skills via the Skill tool. Installed skills: {skill_list}.
If the issue plan or review comments mention using a specific skill (e.g. "use the frontend-design skill"),
invoke it with the Skill tool. You can also use relevant skills proactively when the task
matches their domain."""


def build_implement_prompt(issue_number: int) -> str:
    owner, repo = GITHUB_REPO.split("/", 1)
    skills = _skills_block()
    return f"""Read the AGENT.md file at the root of this repository FIRST and follow every guideline strictly.

Your task: Implement the feature or fix described in issue #{issue_number}.
{skills}
Step 1 — Read the implementation plan:
Run `gh issue view {issue_number}` to read the full issue description.
The issue body contains a DETAILED IMPLEMENTATION PLAN. This is your complete spec.
Read it carefully — it describes exactly what to build, which files to modify,
what approach to take, and any edge cases to handle.

Step 2 — Implement:
Follow the plan in the issue body step by step.
Follow AGENT.md coding standards for all code you write.

Step 3 — Test:
Run the project's test suite to verify your changes work.
If tests fail, fix the issues and re-run tests until they pass.

Step 4 — Commit and push:
Stage your changes and commit with a descriptive message referencing #{issue_number}.
Push the branch: `git push -u origin fix/issue-{issue_number}`

Step 5 — Create PR:
Create a PR: `gh pr create --title "Fix #{issue_number}: <concise title>" --body "Closes #{issue_number}\\n\\n<summary of what was implemented based on the plan>"`

Important:
- The issue body IS the plan. Follow it precisely.
- Do NOT modify files unrelated to what the plan specifies.
- If the plan is unclear or something seems wrong, create the PR as a draft and note your questions in the PR body.
- Always run tests before creating the PR."""


def _format_unresolved_threads(threads: list[dict]) -> str:
    """Format pre-fetched unresolved threads into a readable block for the prompt."""
    if not threads:
        return "No unresolved review threads found."
    lines = []
    for i, thread in enumerate(threads, 1):
        path = thread.get("path", "unknown")
        line_num = thread.get("line")
        location = f"{path}:{line_num}" if line_num else path
        lines.append(f"--- Thread {i}: {location} ---")
        for comment in thread.get("comments", []):
            author = comment.get("author", "unknown")
            body = comment.get("body", "").strip()
            lines.append(f"  [{author}]: {body}")
        lines.append("")
    return "\n".join(lines)


def build_fix_review_prompt(pr_number: int, unresolved_threads: list[dict] | None = None) -> str:
    owner, repo = GITHUB_REPO.split("/", 1)

    skills = _skills_block()

    if unresolved_threads is not None:
        # Pre-fetched threads — embed directly in prompt
        thread_count = len(unresolved_threads)
        threads_block = _format_unresolved_threads(unresolved_threads)
        return f"""Read the AGENT.md file at the root of this repository FIRST and follow every guideline strictly.

Your task: Fix all UNRESOLVED review comments on PR #{pr_number}.
{skills}
There are {thread_count} unresolved review thread(s). Here are the details:

{threads_block}

Steps:
1. Read and understand each unresolved thread above.
2. For each thread, open the referenced file and implement the requested fix.
3. Run the project's test suite to verify your changes.
4. If tests fail, fix the issues and re-run tests.
5. Commit all fixes with message: "fix: address review comments on PR #{pr_number}"
6. Push to the existing branch.

Important:
- Fix EVERY unresolved thread listed above — do not skip any.
- Do NOT modify files unrelated to the review comments.
- If a comment is unclear, add a reply comment asking for clarification using `gh pr comment`."""
    else:
        # Fallback — agent must fetch comments itself
        return f"""Read the AGENT.md file at the root of this repository FIRST and follow every guideline strictly.

Your task: Fix all UNRESOLVED review comments on PR #{pr_number}.
{skills}
Steps:
1. Run `gh pr view {pr_number} --comments` to see the PR description and all comments.
2. Run `gh api repos/{owner}/{repo}/pulls/{pr_number}/comments` to get all inline review comment details.
3. For each review comment, understand the issue and implement the fix.
4. Run the project's test suite to verify your changes.
5. If tests fail, fix the issues and re-run tests.
6. Commit all fixes with message: "fix: address review comments on PR #{pr_number}"
7. Push to the existing branch.

Important:
- Address EVERY review comment — do not skip any.
- Do NOT modify files unrelated to the review comments.
- If a comment is unclear, add a reply comment asking for clarification using `gh pr comment`."""


def build_resume_implement_prompt(issue_number: int) -> str:
    skills = _skills_block()
    return f"""Read the AGENT.md file at the root of this repository FIRST and follow every guideline strictly.

Your task: CONTINUE implementing the feature or fix described in issue #{issue_number}.
{skills}
IMPORTANT CONTEXT: A previous agent was working on this issue but was interrupted by a
rate limit. The worktree has been preserved with all its in-progress work. You must
pick up where the previous agent left off — do NOT start from scratch.

Step 1 — Assess current state:
Run `git log --oneline -10` to see what commits have been made.
Run `git diff` and `git diff --cached` to see any uncommitted changes.
Run `gh issue view {issue_number}` to read the full implementation plan.

Step 2 — Determine what's left to do:
Compare the implementation plan with what's already been done.
Only implement the remaining parts that haven't been completed yet.

Step 3 — Continue implementation:
Pick up from where the previous agent stopped.
Follow AGENT.md coding standards for all code you write.

Step 4 — Test:
Run the project's test suite to verify all changes work.
If tests fail, fix the issues and re-run tests until they pass.

Step 5 — Commit and push:
Stage your changes and commit with a descriptive message referencing #{issue_number}.
Push the branch: `git push -u origin fix/issue-{issue_number}`

Step 6 — Create PR (if one doesn't exist yet):
Check first: `gh pr list --head fix/issue-{issue_number}`
If no PR exists, create one: `gh pr create --title "Fix #{issue_number}: <concise title>" --body "Closes #{issue_number}\\n\\n<summary of what was implemented>"`
If a PR already exists, just push — the PR will update automatically.

Important:
- Do NOT redo work that's already been completed.
- Check git log and file state before making any changes.
- The issue body IS the plan. Follow it precisely for remaining work."""


def build_resume_fix_review_prompt(pr_number: int, unresolved_threads: list[dict] | None = None) -> str:
    owner, repo = GITHUB_REPO.split("/", 1)
    skills = _skills_block()

    if unresolved_threads is not None:
        thread_count = len(unresolved_threads)
        threads_block = _format_unresolved_threads(unresolved_threads)
        return f"""Read the AGENT.md file at the root of this repository FIRST and follow every guideline strictly.

Your task: CONTINUE fixing review comments on PR #{pr_number}.
{skills}
IMPORTANT CONTEXT: A previous agent was working on fixing review comments but was
interrupted by a rate limit. The worktree has been preserved with all its in-progress
work. You must pick up where the previous agent left off — do NOT start from scratch.

There are {thread_count} unresolved review thread(s) remaining. Here are the details:

{threads_block}

Steps:
1. Run `git log --oneline -10` and `git diff` to see what's already been done.
2. For each unresolved thread listed above, check if it has already been addressed by the previous agent. Only fix the remaining ones.
3. Run the project's test suite to verify your changes.
4. If tests fail, fix the issues and re-run tests.
5. Commit all fixes with message: "fix: address review comments on PR #{pr_number}"
6. Push to the existing branch.

Important:
- Do NOT redo fixes that are already committed.
- Address every REMAINING unresolved thread listed above — do not skip any.
- Do NOT modify files unrelated to the review comments."""
    else:
        return f"""Read the AGENT.md file at the root of this repository FIRST and follow every guideline strictly.

Your task: CONTINUE fixing review comments on PR #{pr_number}.
{skills}
IMPORTANT CONTEXT: A previous agent was working on fixing review comments but was
interrupted by a rate limit. The worktree has been preserved with all its in-progress
work. You must pick up where the previous agent left off — do NOT start from scratch.

Steps:
1. Run `git log --oneline -10` and `git diff` to see what's already been done.
2. Run `gh pr view {pr_number} --comments` to see all PR comments.
3. Run `gh api repos/{owner}/{repo}/pulls/{pr_number}/comments` to get inline review comment details.
4. For each review comment, check if it has already been addressed by the previous agent. Only fix the remaining ones.
5. Run the project's test suite to verify your changes.
6. If tests fail, fix the issues and re-run tests.
7. Commit all fixes with message: "fix: address review comments on PR #{pr_number}"
8. Push to the existing branch.

Important:
- Do NOT redo fixes that are already committed.
- Address every REMAINING review comment — do not skip any.
- Do NOT modify files unrelated to the review comments."""
