"""Computer-use verification helpers."""

from glassbox.verification.diff import (
    FrameDiff,
    SceneDiff,
    compute_frame_diff,
    compute_scene_diff,
)
from glassbox.verification.golden import VerifierGoldenCase, iter_golden_cases
from glassbox.verification.probe_ingest import (
    golden_case_from_action,
    load_actions,
    write_golden_case,
)
from glassbox.verification.registry import (
    DEFAULT_REGISTRY,
    VerifierRegistration,
    VerifierRegistry,
    builtin_verifier_registrations,
)
from glassbox.verification.verifiers import SemanticOutcome, VerifierInput

__all__ = [
    "DEFAULT_REGISTRY",
    "FrameDiff",
    "SceneDiff",
    "SemanticOutcome",
    "VerifierGoldenCase",
    "VerifierInput",
    "VerifierRegistration",
    "VerifierRegistry",
    "builtin_verifier_registrations",
    "compute_frame_diff",
    "compute_scene_diff",
    "golden_case_from_action",
    "iter_golden_cases",
    "load_actions",
    "write_golden_case",
]
