"""Backend registration for PicoKVM."""

from __future__ import annotations

from glassbox.backend_registry import BackendRegistration
from glassbox.effector import Effector
from glassbox.effectors.picokvm.config import PicoKVMEffectorConfig
from glassbox.effectors.picokvm.effector import PicoKVMEffector


def _picokvm_effector_factory(*, cfg, coordinate_space: str, **kwargs) -> Effector:
    _ = cfg
    return PicoKVMEffector(
        config=PicoKVMEffectorConfig(),
        coordinate_space=coordinate_space,
        **kwargs,
    )


def picokvm_effector_registration() -> BackendRegistration[Effector]:
    return BackendRegistration(name="picokvm", factory=_picokvm_effector_factory)
