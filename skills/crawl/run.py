"""Small CLI helpers for selecting crawl policies."""

from __future__ import annotations

import os

from glassbox.app_policies import DEFAULT_APP_POLICY_REGISTRY
from glassbox.config import AgentConfig
from glassbox.crawl_policies import DEFAULT_CRAWL_POLICY_REGISTRY
from glassbox.platforms import select_platform_backend


def _make_crawl_policy(name: str, *, cfg: AgentConfig | None = None):
    return DEFAULT_CRAWL_POLICY_REGISTRY.create(name, cfg=cfg)


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
    platform = select_platform_backend(cfg, bundle_id=bundle_id)
    app_policy = DEFAULT_APP_POLICY_REGISTRY.crawl_policy_for(bundle_id, platform=platform)
    if app_policy:
        return app_policy
    return "generic"
