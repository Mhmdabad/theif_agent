# Contributing

Development conventions for this repository. The rulebook grades **how** the
project was built, not only the finished artefact: the grader reads the repo to
reconstruct the working method, so the history is part of the submission.

## Branch per feature

`main` is always stable and always green. No direct pushes.

```bash
git checkout main && git pull --ff-only origin main
git checkout -b issue-<N>-<short-slug>
# work, commit
git push -u origin issue-<N>-<short-slug>
gh pr create --base main
```

Branch names carry the issue number so a branch, a PR and a task are one thing:
`issue-4-config-scaffold`, `issue-8-boardstate-model`.

**Merge to `main` only when stable** — CI green and the acceptance criteria in
the issue actually met, not merely coded.

## One issue, one branch, one PR

Every task in [`docs/TODO.md`](docs/TODO.md) has a GitHub issue, labelled by
build stage (`stage-0` … `stage-7`, `league`, `submission`, `final-checklist`).
Work one at a time and close it with `Closes #N` in the commit or PR body.

If a task turns out to be already satisfied by earlier work, close it with
**evidence** — the commit that did it plus verification output. Do not open an
empty PR to make the process look tidy.

## Build in stage order

Stages are layered deliberately: each runs end to end before the next is laid on
top, so at any moment the space of possible faults is confined to the newest
layer. Do not start stage *n+1* before every gate in stage *n* is met.

Skipping ahead to cryptography or the cloud does not save time — a fault in an
upper layer hides behind instability in the layer beneath it.

## Pull requests

A PR body should say **what** changed, **why now**, what was **verified**, and
what is deliberately **out of scope** with the issue that covers it. Reviews
state what was actually checked. "LGTM" is not a review.

Squash merge, and delete the branch.

## Quality gates

CI runs on every push and pull request. Reproduce locally before pushing:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov --cov-report=term-missing
```

The coverage floor lives in `[tool.coverage.report].fail_under` in
`pyproject.toml` — the workflow carries no hard-coded number that could diverge
from config.

Keep modules short (~150 lines) so responsibilities stay separated.

## Commits

Imperative subject, a body explaining **why** rather than restating the diff,
and `Closes #N` where it settles an issue.

Commits are authored by the team. Do not add co-author trailers for tooling.

## Never commit secrets

`credentials.json`, `token.json`, `*.env` and any API key are gitignored and
must stay that way — **including** in a private repository. A secret pushed even
once is permanently compromised: removing it from the current tree is not
enough, it remains in history and the credentials must be rotated in the Google
Cloud console.

Per-match config files and match logs are deliberately **not** ignored: Appendix F
mandatory rule 4 requires each match's config to be committed, and logs are the
evidence the Replay App verifies.

## The two repositories

This team submits two repos — [COP](https://github.com/Mhmdabad/police_agent)
and [THIEF](https://github.com/Mhmdabad/theif_agent). They share no code at
runtime and must never share live state: separate processes, separate config
directories. Sharing memory or importing a common module holding live state
**disqualifies the solution** even if the game works.

Shared logic is therefore **duplicated deliberately** in both repos rather than
extracted into a package both import. When changing shared behaviour — the rules
engine, scent model, crypto, protocol — apply the same change to both, in the
same shape, and say so in the PR.

`scripts/check_shared_drift.py` enforces that in CI: it clones the sibling,
normalises the package name, and fails if any module in its `SHARED` manifest
differs. Two consequences worth knowing before you start:

- **Paired branches are compared against each other.** A shared change has to
  land in both repos, and until it has, each side's branch disagrees with the
  other's `main`. So the check first looks for a sibling branch with the *same
  name* and compares against that; it falls back to `main` when there is none.
  Give both PRs the same branch name and the gate stays green throughout,
  without either side being exempted. `--no-pair` forces a `main` comparison.
  Pairing does not weaken anything: two same-named branches that disagree
  still fail.
- **A new module must be added to `SHARED` or to `DIVERGENT`,** with a reason
  in the latter case. A module in neither is unchecked, and unchecked is how
  every drift so far got in.
