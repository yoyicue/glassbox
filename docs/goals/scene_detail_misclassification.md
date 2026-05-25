# Goal — Self-improving Settings navigation → general GUI agent (P4-P6)

Status: **P1-P3 shipped & live-validated; this doc is now the forward roadmap
(P4-P6).** The original bug — `classify_ios_scene` mislabeling real Settings
detail pages as `springboard`/`unknown` — is fixed and proven on the live rig.
What remains is the forward-looking work: learn from real runs, then generalize
beyond Settings.

## Foundation already shipped (do not redo)

- **P1 semantic fallback** (`glassbox/ios/scene.py`) — Settings-detail veto
  before `springboard`/`unknown`, structural+language-aware cues, recovery safety
  belt. Back/Up affordance treated as strong detail evidence.
- **P2 transition prior + gated VLM verifier** — a verified `settings.tap_row`
  gives the next changed screen a strong `settings_detail` prior; opt-in VLM only
  for conflicts/low-confidence, cached + budgeted; `classification_source`
  recorded (`frame`/`semantic`/`transition`/`vlm`).
- **P3 graph-authoritative model** (`graph_state.py`, the
  `docs/design/screen_state_fsm.md` design realized) — the UTG is authority for
  ambiguous scene kind, root coverage (successful root→detail edges), and inert
  rows (self-loop no-progress). Coverage stays honest (graph only unions into
  visited; misses still reported). Live: en-HK honest 15/17, `verify_report`
  exit 0. The P3b root→root false-credit was found and fixed via live runs.

## P4 — Self-Improving Settings Navigation

- Mine real crawl traces for classifier conflicts, recovery loops, VLM
  disagreement, graph over/under-splitting, and new unseen page types.
- Generate small human-review labeling packs; turn approved labels into
  fixtures/golden tests.
- Allow learned or VLM-distilled classifiers to replace the P1 scoring fallback,
  while deterministic safety gates remain authoritative.
- Produce policy suggestions (aliases, blocked patterns, inert-row evidence), but
  require tests/review before shipping them.

## P5 — General GUI World Model

- Generalize from Settings to app-agnostic GUI state, controls, action effects,
  preconditions, recovery paths, and side-effect risk.
- Learn action-effect records from every run: `state + action + expected effect
  + observed state + verifier result + risk`.
- Introduce a formal risk taxonomy (`observe-only`, `navigation`, `idempotent`,
  `reversible`, `setting-changing`, `destructive`, `auth/payment/privacy`,
  `unknown`) and constrain planners to task-allowed risk.
- Transfer common GUI patterns across apps: list rows, details, tab bars, modals,
  forms, search, permission dialogs, and destructive confirmations.

## P6 — Verifiable GUI Agent Runtime

- Express tasks as declarative contracts with allowed risk, forbidden effects,
  success criteria, time/VLM budgets, and required artifacts.
- Make each agent step auditable: observation hash, policy authorization,
  predicted effect, action, actual effect, verifier result, recovery, artifact.
- Split specialized agents for perception, navigation, safety, recovery, QA, and
  review over a shared audited state store.
- Run continuous evaluation across offline fixtures, replay traces, simulator
  runs, real-device canaries, cost/latency regression, and unsafe-near-miss
  checks.
- Keep self-improvement human-governed: automatic fixture mining and candidate
  repairs are allowed; silent deployment of learned policy is not.

## Constraints (carried from P1-P3)

- Deterministic safety gates stay authoritative; learned/VLM components advise,
  never override safety.
- Read-only: learn only from the crawl's legitimate actions, never speculative
  taps. Back-chevron detection keeps the status-bar-clock guard.
- Honesty: any learned classification/coverage records source + evidence and
  stays reportable; never hide a real failure as inert/known.
- Cold-start must degrade exactly to the single-frame behavior on an empty graph.
