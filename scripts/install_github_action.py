#!/usr/bin/env python3
"""Install the Claude PR-review pipeline into a target repository.

Copies the reusable core + manual wrapper into the target's .github/workflows/,
substituting the chosen auth (OAuth for personal, API key for enterprise) and CI
workflow name; seeds .claude/memory/review-learnings/; sets the auth secret via
gh; prints the automatic-job snippet to paste into the target's CI. Never commits
or pushes.
"""
from __future__ import annotations
import argparse, subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
GA = REPO_DIR / "github-action"
SRC_CORE = GA / "claude-review-core.yml"
SRC_WRAPPER = GA / "claude-code-review.yml"
SRC_SNIPPET = GA / "claude-review-automatic.snippet.yml"

AUTH = {
    "oauth": ("claude_code_oauth_token", "CLAUDE_CODE_OAUTH_TOKEN"),
    "apikey": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
}
LEARN_README = (
    "# Review learnings\n\nDurable, likely-to-recur findings the Claude PR reviewer "
    "records here (kind: regression | security | architecture). Future reviews read "
    "these and check new diffs against them. One file per learning.\n"
)

def _subst(text: str, auth: str, ci_workflow_name: str) -> str:
    # Template default is OAuth; rewrite to API key when requested.
    if auth == "apikey":
        text = text.replace("claude_code_oauth_token", "anthropic_api_key")
        text = text.replace("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
    if ci_workflow_name != "CI":
        text = text.replace('select(.name == "CI")', f'select(.name == "{ci_workflow_name}")')
    return text

def _write_guarded(dst: Path, content: str, force: bool) -> bool:
    """Write content to dst unless it already exists with different content and force is False.

    Returns True if written, False if skipped due to the clobber guard.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not force:
        try:
            existing = dst.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            existing = None
        if existing != content:
            print(f"  ! {dst} exists and differs — pass --force to overwrite, skipping.")
            return False
    dst.write_text(content, encoding="utf-8")
    return True

def install_files(target: Path, auth: str, ci_workflow_name: str = "CI", force: bool = False) -> list[Path]:
    if auth not in AUTH:
        raise ValueError(f"auth must be one of {list(AUTH)}")
    written: list[Path] = []
    for src, rel in [(SRC_CORE, ".github/workflows/claude-review-core.yml"),
                     (SRC_WRAPPER, ".github/workflows/claude-code-review.yml")]:
        dst = target / rel
        if _write_guarded(dst, _subst(src.read_text(encoding="utf-8"), auth, ci_workflow_name), force):
            written.append(dst)
    learn = target / ".claude" / "memory" / "review-learnings"
    learn.mkdir(parents=True, exist_ok=True)
    if _write_guarded(learn / ".gitkeep", "", force):
        written.append(learn / ".gitkeep")
    if _write_guarded(learn / "README.md", LEARN_README, force):
        written.append(learn / "README.md")
    return written

def set_secret(repo: str, auth: str) -> int:
    secret = AUTH[auth][1]
    print(f"Setting {secret} on {repo} (gh will prompt for the value)...")
    return subprocess.call(["gh", "secret", "set", secret, "--repo", repo])

def main() -> int:
    ap = argparse.ArgumentParser(description="Install the Claude PR-review pipeline into a target repo.")
    ap.add_argument("target", help="local path to the target repo working tree")
    ap.add_argument("--auth", choices=list(AUTH), help="oauth (personal) or apikey (enterprise)")
    ap.add_argument("--repo", help="owner/name — set the auth secret there via gh")
    ap.add_argument("--ci-workflow-name", default="CI", help="name: of the target's CI workflow (default CI)")
    ap.add_argument("--skip-secret", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite existing files that differ")
    args = ap.parse_args()

    target = Path(args.target).expanduser().resolve()
    if not (target / ".git").exists():
        print(f"error: {target} is not a git working tree"); return 1
    if not SRC_CORE.exists() or not SRC_WRAPPER.exists():
        print("error: source workflows missing under github-action/"); return 1

    auth = args.auth
    if not auth:
        ans = input("Auth mode — [1] OAuth token (personal)  [2] API key (enterprise): ").strip()
        auth = "apikey" if ans == "2" else "oauth"

    for p in install_files(target, auth, args.ci_workflow_name, force=args.force):
        print(f"  wrote {p}")

    if args.skip_secret:
        print(f"\nSkipped secret. Later: gh secret set {AUTH[auth][1]} --repo <owner/name>")
    elif args.repo:
        rc = set_secret(args.repo, auth)
        if rc != 0:
            print(f"warning: gh secret set exited {rc} — the secret may not be set."); return rc
    else:
        print(f"\nNo --repo; set it yourself: gh secret set {AUTH[auth][1]} --repo <owner/name>")

    print("\nNEXT: add the automatic-review job to your CI workflow — see")
    print(f"  {SRC_SNIPPET}")
    print("Files staged in the target working tree — NOT committed or pushed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
