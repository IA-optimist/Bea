# Bea Consolidation Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize Bea without adding features: lock the legal and packaging truth, make security fail-closed, make CI honest, govern self-improvement, and prove quality with reproducible evaluation.

**Architecture:** Treat this as a consolidation program, not a feature program. The repo should converge on a small set of explicit contracts: one license, one packaging story, one auth model, one import boundary rule, one self-improvement policy, one provider abstraction, one sandbox model, one evaluation harness, and one canonical product surface. Anything that weakens proof, portability, or security stays out.

**Tech Stack:** Python, FastAPI, pytest, ruff, mypy, importlinter or AST checks, Docker, GitHub Actions, OpenTelemetry, LangGraph or Temporal, existing Bea kernel and self-improvement modules.

**Operating system lens:** Kernel as policy and scheduling core, missions as processes, tools as syscalls, memory as persistent state, MCP plugins as drivers, self-improvement as controlled updates, and the harness as the equivalent of a perf + safety test suite.

**Component mapping:**

- **Béa Kernel**: policy/safety core. Owns routing policy, approval policy, memory access rules, and the safety envelope that other layers must obey.
- **`kernel/` hardening**: kernel-internal policy engine. Owns permissions, budgets in euros/tokens, and automodification rules in an OPA/Rego-style declarative model.
- **Scheduler**: isolated orchestration service. Owns timing, retries, cadence, and cooldowns; it must not make policy decisions.
- **Orchestrateur durable**: mission state machine. Can be LangGraph or Temporal, but must support human-in-the-loop checkpoints, retries, and replay after failure.
- **Mission runtime**: process layer. Starts, pauses, resumes, and records mission state transitions, with recovery state preserved across crashes.
- **Agents**: user-space workers. Each agent has identity, capabilities, quotas, and isolated memory; they request services through policy-controlled calls, never direct privilege.
- **Tooling layer**: syscall surface. Executes bounded actions and must remain under kernel policy.
- **Sandbox**: disposable execution envelope. One throwaway container per task, allowlisted egress only, ephemeral secrets, and a killswitch that can terminate the task without leaving residual trust.
- **Memory layer**: 4-level persistent state.
  - `working`: short-lived scratch context tied to a mission.
  - `episodic`: event history and mission outcomes.
  - `semantic`: distilled facts, lessons, and durable knowledge.
  - `procedural`: reusable routines, policies, and learned behaviors.
  - Every write carries provenance, every tier has an explicit forgetting policy, and secrets are redacted before persistence.
- **Tools via MCP**: manifest-driven driver layer. Each tool ships with a schema for I/O, explicit permissions, cost, and side effects; the manifest is what the kernel authorizes.
- **Filesystem**: restricted system resource. Accessible only through policy-gated calls, never as an implicit free-for-all from agents.
- **Device drivers**: hardware/system adapters. They expose bounded capabilities through manifests or kernel hooks and remain subject to the same policy, quota, and provenance checks as MCP tools.
- **`dmesg` / system logs**: privileged diagnostics stream. Read through controlled observability hooks, never as an unfiltered raw shell surface for agents.
- **Observability**: telemetry plane. Uses OpenTelemetry plus immutable audit logs and deterministic replay so every mission can be reconstructed and reviewed.
- **App store**: ecosystem distribution layer. Publishes signed, versioned capabilities with provenance, policy metadata, and review gates before installation.
- **Self-improvement**: update mechanism. Can propose and stage changes, but cannot escape policy or provenance checks.
- **Harness**: boot-time and regression verification. Proves that policy, safety, and portability still hold after change.

---

### Task 1: Lock the repo truth, license, and packaging

**Files:**
- Modify: `LICENSE`
- Modify: `README.md`
- Create: `pyproject.toml`
- Modify: `.gitignore`
- Modify: `CONTRIBUTING.md`
- Modify: `docs/STATUS.md`

- [ ] **Step 1: Decide the license model and apply it consistently**
  - Pick one license path for the repo, then write the canonical `LICENSE` text and align the README wording with it.
  - If the project stays closed, say so directly. If it goes open, use MIT consistently and remove mixed signals.

- [ ] **Step 2: Add first-class packaging metadata**
  - Create `pyproject.toml` with PEP 621 metadata, project name, versioning policy, test/lint entrypoints, and build configuration.
  - Keep SemVer explicit and start from a `0.x` release line until the public API is frozen.

- [ ] **Step 3: Clean repo hygiene**
  - Remove personal artifacts and machine-local files from the tracked tree.
  - Ignore generated state such as `.env.agents`, local audit outputs, and transient workflow files.

- [ ] **Step 4: Align contributor instructions**
  - Update `CONTRIBUTING.md` and the status doc so release, packaging, and license expectations are obvious before anyone ships changes.

- [ ] **Step 5: Verify the packaging story**
  - Run `python -m build`, install the wheel from `dist/`, and confirm the repo still imports and starts from the packaged artifact.

### Task 2: Make security fail-closed and explicit

**Files:**
- Modify: `api/routes/*.py`
- Modify: `api/_deps.py`
- Modify: `api/auth.py`
- Modify: `api/middleware.py`
- Modify: `config/settings.py`
- Create: `tests/security/test_auth_coverage.py`
- Create: `tests/security/test_public_route_allowlist.py`
- Create: `docs/security/threat_model_merge.md`

- [ ] **Step 1: Remove fail-open auth fallbacks**
  - Delete every `_auth = None` style fallback in route modules.
  - Make missing auth dependencies crash early in tests and fail deployment rather than silently downgrading security.

- [ ] **Step 2: Require secrets outside tests**
  - Ensure production and local non-test paths reject missing secrets.
  - Keep test-only overrides explicit and isolated so a missing secret cannot turn into a permissive default.

- [ ] **Step 3: Prove route coverage mechanically**
  - Add a test that enumerates protected routes and checks that each one has an explicit auth path.
  - Keep a small allowlist for public routes and verify that the allowlist is the only exception set.

- [ ] **Step 4: Replace silent exception swallowing in security code**
  - Convert `except Exception: pass` in security-sensitive code paths to structured logging plus a fail-closed response.
  - Only keep silent handling where a crash would clearly be worse and the code path is already non-security-critical.

- [ ] **Step 5: Write the merge-mode threat model**
  - Document the threat model for merge mode and `AUTO_APPROVE_MEDIUM`, including prompt injection, secret exposure, and accidental destructive actions.
  - Capture the review rules for critical actions, payments, and other irreversible operations.

### Task 3: Make CI honest and enforce architecture boundaries

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/validate_local.py`
- Modify: `pytest.ini`
- Modify: `ruff.toml`
- Modify: `pyproject.toml`
- Create: `.importlinter`
- Create: `tests/architecture/test_kernel_import_boundaries.py`

- [ ] **Step 1: Turn lint and typing into blocking gates**
  - Make `ruff check` blocking.
  - Make `mypy --strict` blocking for `kernel/`, `executor/`, and `api/auth`.
  - Keep coverage minimums blocking instead of advisory.

- [ ] **Step 2: Quarantine stale tests**
  - Move the ~170 obsolete tests behind a quarantine marker or a dedicated non-blocking lane.
  - Keep the blocking suite small, relevant, and stable.

- [ ] **Step 3: Enforce the kernel import rule mechanically**
  - Add importlinter or AST-based CI checks to guarantee that `kernel/` does not import upward into `core/`, `api/`, `agents/`, or tool layers.
  - Make the rule fail CI, not just docs.

- [ ] **Step 4: Keep local validation identical to CI**
  - Ensure `scripts/validate_local.py` runs the same checks, in the same order, with the same thresholds as CI.

### Task 4: Govern self-improvement instead of trusting it

**Files:**
- Modify: `core/improvement_daemon.py`
- Modify: `core/self_improvement/promotion_pipeline.py`
- Modify: `kernel/improvement/gate.py`
- Modify: `.github/workflows/ci.yml`
- Create: `tests/self_improvement/test_pr_only_policy.py`
- Create: `tests/self_improvement/test_patch_signing.py`
- Create: `docs/security/self_improvement_policy.md`

- [ ] **Step 1: Make PR-only the default**
  - Self-improvement should propose a branch, run tests, and request human review by default.
  - Automerge stays disabled by default, with explicit handling for critical code areas.

- [ ] **Step 2: Block sensitive areas from automerge**
  - Never automerge changes touching `kernel/`, auth, executor, secrets, payments, or CI.
  - Require a human decision even if the benchmark looks good.

- [ ] **Step 3: Add canary plus rollback**
  - Gate automatic changes with a canary run and a measurable rollback condition based on the harness.
  - A patch is only promoted if the harness proves it and the rollback path remains intact.

- [ ] **Step 4: Sign auto-applied patches**
  - Add cryptographic signatures for generated patches before they are accepted by the merge path.
  - Reject unsigned or signature-mismatched patches.

- [ ] **Step 5: Make builds reproducible**
  - Pin the build inputs used by self-improvement so the same patch yields the same result in CI and on a local replay.
  - Record the build digest alongside the patch metadata.

### Task 5: Decouple providers and make execution portable

**Files:**
- Modify: `core/llm_factory.py`
- Create: `core/providers/llm_provider.py`
- Modify: `executor/desktop_env/sandbox.py`
- Modify: `scripts/run_api_local.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`

- [ ] **Step 1: Introduce a neutral provider interface**
  - Create a provider abstraction that can route to OpenAI, Anthropic, OpenRouter, Ollama, or vLLM without the critical path depending on a single vendor.
  - Keep provider-specific code behind the abstraction boundary.

- [ ] **Step 2: Remove direct Codex dependency from the critical path**
  - Ensure the runtime can fall back cleanly if a Codex-specific path is unavailable.
  - The orchestrator should degrade, not stall.

- [ ] **Step 3: Make sandbox execution task-scoped**
  - Run actions in throwaway containers or isolated workers with allowlisted network access, ephemeral filesystem state, and ephemeral secrets.
  - Add a kill switch for runaway tasks.

- [ ] **Step 4: Make the repo cross-platform**
  - Keep Windows support, but stop assuming Windows-only behavior in core validation.
  - Add Linux and Windows CI jobs for the critical path.

- [ ] **Step 5: Decide on a durable orchestrator**
  - Evaluate LangGraph or Temporal for durable mission checkpoints, resumption, and human-in-the-loop control.
  - If the homegrown engine stays, it needs the same durability guarantees.

### Task 6: Build proof, observability, and the public surface

**Files:**
- Modify: `core/observability/*`
- Modify: `core/self_improvement/benchmark_suite.py`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/API_VERSIONING.md`
- Modify: `docs/API_REFERENCE.md`
- Modify: `core/mcp/mcp_registry.py`
- Modify: `core/mcp/bea/bea_mcp_server.py`
- Modify: `plugins/plugin_registry.py`
- Modify: `beamax_app/`
- Modify: `frontend/`
- Modify: `mobile/`
- Create: `tests/eval/test_agent_harness.py`

- [ ] **Step 1: Add end-to-end observability**
  - Trace mission -> agent -> tool -> LLM with OpenTelemetry.
  - Include latency, cost, failures, and retry metadata in the trace model.

- [ ] **Step 2: Replace smoke benchmarks with reproducible evaluation**
  - Build a stable harness that can run at every PR and every self-improvement cycle.
  - Use frozen tasks, deterministic scoring, and diff-based pass/fail output instead of internal thresholds alone.

- [ ] **Step 3: Freeze API v1**
  - Define the stable surface, mark the excess surface as deprecated, and stop adding new endpoints to the legacy path.
  - Version public contracts before the next growth phase.

- [ ] **Step 4: Add signed and versioned MCP tooling**
  - Make the plugin/tool registry carry signatures, versions, and provenance.
  - Expose Bea as an MCP server so external agents can use it as a process, not a pile of internal modules.

- [ ] **Step 5: Choose the canonical product surfaces**
  - Keep Flutter as the canonical mobile path if the repo still wants one authoritative app.
  - Reduce the React / React Native surface if it is not the primary product.

- [ ] **Step 6: Split out HexStrike v2 if it still drags the core**
  - Move the pentest toolchain to its own repo if its lifecycle, risk profile, or dependency set keeps contaminating the main kernel.

---

## Sprint 3 — Agent codeur compétitif (Semaines 5–6)

**Objectif :** Béa résout une issue GitHub de bout en bout, proprement, via un worktree isolé, un patch testé, une PR et un rollback si nécessaire.

| Chantier | Objectif | Agent |
|---|---|---|
| Repo-map (tree-sitter) | Index symboles + graphe d'imports + ranking pertinence + budget tokens façon Aider | Codex |
| Worktree-per-task | Chaque mission code = git worktree isolé → tests → diff/PR. Jamais de modif directe sur main | Claude Code |
| Boucle test/lint/fix | L'agent itère jusqu'à CI verte avant de proposer la PR | Cursor |
| Éval v1 | Ajouter un sous-ensemble type SWE-bench-lite au harness | Kilo Code |

**Gate S3 :** Béa prend une issue simple → worktree → patch → tests verts → PR, avec rollback. Score d'éval mesuré et publié en interne.

### Definition of Done

- Un issue GitHub simple peut être transformée en worktree isolé.
- Le repo-map permet de localiser les symboles pertinents et les imports dépendants.
- L'agent applique un patch, lance lint/tests, puis itère jusqu'à une CI locale verte.
- La PR est générée avec un diff propre et un score d'éval reproductible.
- Un rollback worktree/patch est disponible si le score ou les tests régressent.

---

## Execution Order

1. Lock truth and packaging.
2. Close security and policy gaps.
3. Make CI and import boundaries real.
4. Govern self-improvement with review, signatures, and rollback.
5. Decouple providers and sandbox execution.
6. Prove quality with observability, evaluation, and a stable public surface.

## Definition of Done

- One license path is chosen and documented everywhere.
- Security is fail-closed by default.
- CI blocks on the rules that matter.
- Self-improvement cannot silently merge risky changes.
- The runtime does not depend on one vendor or one platform.
- The repo has a reproducible evaluation story.
- Public contracts are versioned and narrow.
