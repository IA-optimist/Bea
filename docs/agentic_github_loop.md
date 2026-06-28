# GitHub Mission Loop — Béa v1

## Pipeline

```
GitHub Issue Created
        ↓
IssueClassifier.classify()
  → IssueKind (BUG/ENHANCEMENT/SECURITY/RESEARCH/DATA/SELF_IMPROVEMENT)
  → requires_human_approval (security/self-improvement → always True)
        ↓
GitHubMissionLoop.plan()
  → MissionPlan (steps, branch: bea/issue-<N>/<kind>)
  → SECURITY/SELF_IMPROVEMENT → status=HUMAN_REVIEW (no auto-steps)
        ↓
 [Human reviews plan]
        ↓
ACIExecutor runs steps in ACI sandbox:
  - Create worktree/branch
  - Implement (APPLY_PATCH → HIGH risk → approval required)
  - Run tests (RUN_TESTS → MEDIUM risk → warned)
  - Run linter (RUN_LINTER → LOW risk)
        ↓
GitHubMissionLoop.mark_pr_draft_created()
  → status=PR_DRAFT_CREATED
  → pr_draft=True ALWAYS
  → labels: ["pr-draft", "agentic"]
        ↓
[Human reviews PR diff + CI + verdicts]
        ↓
[Human merges] ← BÉA NEVER AUTO-MERGES
```

## Branch Naming

All branches created by the Mission Loop:
```
bea/issue-<number>/<kind>
```
Examples:
- `bea/issue-42/bug`
- `bea/issue-99/enhancement`
- `bea/issue-15/security` (human review required)

## Labels

See `agent_github/labels.py` for all 15 BEA_LABELS.

Key labels applied by the loop:
- `agentic` — issue/PR was created by Béa
- `pr-draft` — PR draft created, awaiting review
- `human-review-required` — manual review required before any action

## SOP Workflow (from configs/workflows.yaml)

```yaml
github_mission:
  steps:
    - classify → plan → branch → implement → test → review
    → pr_draft → human_gate
```

P0 verdict at any step → workflow stops, PR draft NOT created.

## Invariants

| Invariant | Where enforced |
|-----------|---------------|
| PR draft never auto-merged | `MissionPlan.pr_draft=True` always |
| SECURITY always human_review | `_ALWAYS_HUMAN` in `mission_loop.py` |
| SELF_IMPROVEMENT always human_review | `_ALWAYS_HUMAN` in `mission_loop.py` |
| Branch prefix `bea/` | `_branch_name()` static method |
| Business/financial/cyber always approved | IssueKind SECURITY gate |
