# Config preset layer — design

Status: **design, not implemented; snapshot as of `a578f1d` (2026-06-11).**
Produced by the same 7-agent design pass as
[`phone_orchestrator_decomposition.md`](phone_orchestrator_decomposition.md);
the adversarial review verified the mechanism's key factual claims (including
the conftest-vs-pydantic `env_file` asymmetry that justifies deferring step 7)
and added five corrections, all folded in below. Owner of the "config sprawl"
finding: [`../goals/project_health_snapshot.md`](../goals/project_health_snapshot.md)
item 5 (~87 `GLASSBOX_*` env keys; ~16 raw `os.environ` readers bypassing the
pydantic-settings layer; dual `enable_vlm`/`enable_kimi` naming; no preset
entry point).

```bash
grep -rhoE 'GLASSBOX_[A-Z0-9_]+' glassbox --include='*.py' | sort -u | wc -l
grep -rnE 'os\.environ\.get|os\.getenv' glassbox --include='*.py' | wc -l
```

## 1. Mechanism

Presets are **named, committed, flat dicts of `GLASSBOX_*` env key→string
pairs** — a frozen `Preset` dataclass table in a new `glassbox/presets.py` —
applied via `os.environ.setdefault` **before runtime assembly**. Not
`model_copy` field updates, not a new pydantic settings source: writing
through process env is the only single write path that reaches all three
consumer kinds at once (AgentConfig's settings machinery, the `env_file`-less
PicoKVM config classes, and the ~16 raw `os.environ` readers — e.g. the icon
detector keys its cache off a direct env read and ignores the cfg field).

Precedence falls out by construction:

1. explicit exported env **and** the stage-1 `.env` load (already in process
   env by apply time) beat presets;
2. presets beat field defaults;
3. two selected presets disagreeing on a key is a **hard error**.

Selection: `open_phone(..., preset="rig-ipad")` or `GLASSBOX_PRESET=a,b`
(itself `GLASSBOX_`-prefixed, so the smoke suite's `_isolate_glassbox_env`
strips it automatically and test isolation is untouched).

## 2. Corrections from review (bake into implementation)

1. **No "inert for already-built Phones" claim** — per-call raw readers see
   preset writes immediately, so `apply_presets` must **fail loudly when
   called after runtime assembly** instead of documenting inertness.
2. **`GLASSBOX_PICOKVM=1` stays out of the `rig-ios-settings` preset** — in
   today's `build_full_run_env` that key is conditional on a parameter;
   folding it into the preset would silently flip the `picokvm=False` harness
   path.
3. **Floor-identity guard**: the benchmark driver stamps `vlm_enabled` from
   `args.vlm`, not resolved env — a `vlm-on` preset during a gate run would
   flip live behavior while the stamped config lies. The driver must stamp
   from resolved-after-preset state and refuse (rc 2) any preset that touches
   floor-identity keys during a floor run.
4. Golden/home-path normalization for any preset that bakes cache paths.
5. Document that presets must never be pinned in `.env` (same trap as
   `GLASSBOX_LANGUAGE` — it would flip the default for every caller including
   the smoke suite).

## 3. Steps (PR-sized)

1. **Mechanism**: `glassbox/presets.py` (table + `apply_presets()` +
   validation tests, no callers). Initial presets copied verbatim from
   today's de-facto blocks: `rig-ios-settings`, `vlm-on`, `rig-ipad`,
   `rig-iphone-zh`.
2. **Facade selection**: `open_phone(preset=...)` + `GLASSBOX_PRESET` hook,
   applied before `_ai_config()`/`get_config()`; `_ai_config`'s own logic
   untouched.
3. **Single source of truth**: `build_full_run_env` consumes the
   `rig-ios-settings` preset for its `GLASSBOX_*` setdefault lines
   (`IOS_SETTINGS_*` lines stay). *Hold until no benchmark is in flight from
   the working checkout and after the decomposition rig session.*
4. **Benchmark driver + floor-identity guard** (correction 3). *Same hold.*
5. **VLM dedup A (zero observable change)**: single resolvers on AgentConfig
   — `vlm_enabled()` (the existing tri-state: `enable_vlm` if not None else
   `enable_kimi`) and `resolved_vlm_cache_dir()` — and point
   `backend_registry`/`runtime` at them.
6. **VLM dedup B**: warn-once deprecation only when a kimi-named source is
   the *deciding* one; docs present `GLASSBOX_ENABLE_VLM` +
   `open_phone(preset="vlm-on")` as the front door.
7. **Deferred, explicitly not a prerequisite**: migrating the ~16 raw env
   readers onto cfg fields. Verified NOT behavior-preserving today — under
   the smoke suite's env-strip, a raw read returns the stripped default while
   the cfg field re-reads `.env` (the `env_file` asymmetry), so this needs
   its own characterization pass first.

## 4. Sequencing vs the decomposition

Steps 1-2 and 5-6 are offline and orthogonal — land any time. Steps 3-4
rewrite the live rig entry path (`run_full` → `build_full_run_env`): hold them
until the decomposition's rig session is done and no benchmark is running
from the checkout.
