"""Opening a PR for a meta-agent proposal.

The pure parts (`branch_name`, `build_pr_body`) are unit-tested. The real
side-effecting publisher (`GitHubPRPublisher`) is the network boundary: it
branches, applies the proposal's diff, commits, pushes, and opens a PR via
PyGithub. Its GitHub token must be a fine-grained PAT scoped to PR-write
only — no merge, no branch-protection edit, no push to a protected branch.
A leaked token must not be able to bypass the gate.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

_BRANCH_PREFIX = "meta-agent/"

_REVIEWER_CHECKLIST = """
---
## Reviewer checklist (anti-rubber-stamp)
- [ ] The hypothesis names a *root cause*, not a symptom.
- [ ] The diff is one logical change and touches only the edit surface.
- [ ] If a rubric changed, it was *tightened* — never loosened.
- [ ] If a new eval was added, the description says exactly where to wire it in.
- [ ] The predicted effect is measurable — `meta/measure.py` can check it post-merge.
- [ ] You read the *actual diff*, not just this description.
"""


@dataclass(frozen=True)
class OpenedPR:
    number: int
    url: str
    branch: str


class PRPublisher(Protocol):
    """The boundary the orchestrator depends on — real or fake."""

    def publish(self, *, branch: str, title: str, body: str, diff: str) -> OpenedPR: ...


def branch_name(signal_id: str, *, now: datetime | None = None) -> str:
    """`meta-agent/<slugified-signal-id>-<YYYYMMDD>` — namespaced so the CI gate
    can target it, dated so re-proposals of the same pattern don't collide."""
    now = now or datetime.now(UTC)
    slug = re.sub(r"[^a-z0-9]+", "-", signal_id.lower()).strip("-")
    return f"{_BRANCH_PREFIX}{slug}-{now:%Y%m%d}"


def build_pr_body(proposal_markdown: str) -> str:
    """The proposal Markdown plus a reviewer checklist — the human is the merge
    gate, and the checklist is there so they can't rubber-stamp it."""
    return proposal_markdown.rstrip() + "\n" + _REVIEWER_CHECKLIST


class GitHubPRPublisher:
    """Real publisher: git branch + apply diff + commit + push, then open a PR.

    Used by the weekly cron (v3 chunk 9). Tests inject a fake instead.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        token: str,
        repo_slug: str,
        base_branch: str = "master",
    ) -> None:
        self.repo_root = repo_root
        self._token = token
        self.repo_slug = repo_slug
        self.base_branch = base_branch

    def _git(self, *args: str, stdin: str | None = None) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repo_root), *args],
            capture_output=True,
            text=True,
            input=stdin,
            check=True,
        )
        return result.stdout

    def publish(self, *, branch: str, title: str, body: str, diff: str) -> OpenedPR:
        self._git("checkout", "-b", branch)
        # Apply the proposal's unified diff from stdin — no shell, no temp file.
        self._git("apply", "-", stdin=diff)
        self._git("add", "-A")
        self._git("commit", "-m", title)
        self._git("push", "-u", "origin", branch)
        return self._open_pull(branch=branch, title=title, body=body)

    def _open_pull(self, *, branch: str, title: str, body: str) -> OpenedPR:
        # Lazy import: PyGithub is only needed for the real PR path, so the
        # module (and every test using a fake publisher) imports without it.
        from github import Github

        repo = Github(self._token).get_repo(self.repo_slug)
        pr = repo.create_pull(title=title, body=body, head=branch, base=self.base_branch)
        return OpenedPR(number=pr.number, url=pr.html_url, branch=branch)
