"""Small CLI helpers for selecting crawl policies."""

from __future__ import annotations

import os

from glassbox.config import AgentConfig
from glassbox.crawl_policies import DEFAULT_CRAWL_POLICY_REGISTRY


def _make_crawl_policy(name: str):
    return DEFAULT_CRAWL_POLICY_REGISTRY.create(name)


def _resolve_crawl_policy_name(
    bundle_id: str | None,
    *,
    explicit_policy: str | None,
    cfg: AgentConfig,
) -> str:
    if explicit_policy:
        return explicit_policy
    env_policy = os.environ.get("GLASSBOX_CRAWL_POLICY")
    if env_policy:
        return env_policy
    if cfg.crawl_policy != "generic":
        return cfg.crawl_policy
    if bundle_id == "com.apple.Preferences":
        return "ios_settings"
    return "generic"
