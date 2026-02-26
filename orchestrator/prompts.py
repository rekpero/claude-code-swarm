from orchestrator.config import GITHUB_REPO


def build_implement_prompt(issue_number: int) -> str:
    owner, repo = GITHUB_REPO.split("/", 1)
    return f"""Read the AGENT.md file at the root of this repository FIRST and follow every guideline strictly.

Your task: Implement the feature or fix described in issue #{issue_number}.

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


def build_fix_review_prompt(pr_number: int) -> str:
    owner, repo = GITHUB_REPO.split("/", 1)
    return f"""Read the AGENT.md file at the root of this repository FIRST and follow every guideline strictly.

Your task: Fix all review comments on PR #{pr_number}.

Steps:
1. Run `gh pr view {pr_number} --comments` to see the PR description and all comments.
2. Run `gh api repos/{owner}/{repo}/pulls/{pr_number}/comments` to get all inline review comments.
3. For each review comment, understand the issue and implement the fix.
4. Run the project's test suite to verify your changes.
5. If tests fail, fix the issues and re-run tests.
6. Commit all fixes with message: "fix: address review comments on PR #{pr_number}"
7. Push to the existing branch.

Important:
- Address EVERY comment — do not skip any.
- Do NOT modify files unrelated to the review comments.
- If a comment is unclear, add a reply comment asking for clarification using `gh pr comment`."""
