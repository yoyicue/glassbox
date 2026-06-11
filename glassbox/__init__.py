"""glassbox — the agent runtime framework

Chains perception → cognition → effector into a main loop, and provides
pytest fixtures so walkthrough cases can get started in one line.
`glassbox.phone.Phone` is the unified facade walkthrough scripts call.

Subpackages:
    perception   AVFFrameSource (HDMI grab) / StaticFrameSource (png test
                 source) / letterbox crop / wait_stable + frame_diff
    cognition    Box/UIElement/Scene schema (base) · AppleVisionOCR ·
                 HeuristicTyper (Layer 2 typing) · vlm_kimi (Layer 3 VLM
                 Set-of-Mark) · icon_detect / som / whitebox / asset_match ·
                 text_match (OCR label normalization)
    memory       ScreenMemory UTG — screen graph, element keys, signatures
    obs          recorder / replay / kimi_cache — frame recording + replay
    ios          iOS primitives — scene classification, foreground recovery,
                 safe-area geometry, no-progress detection, SpringBoard

Top-level modules:
    phone        Phone — perception+cognition+effector+profile+obs facade
    effector     PicoKVMEffector / NoOp / Mock
    profile      App profile schema + registry (Tier 1+ white-box hints)
    config       env-driven runtime config
"""


def _load_dotenv_once() -> None:
    """Automatically load a .env on `import glassbox` (API keys and other
    sensitive config).

    Resolution order: the package-root .env wins — in a repo checkout that is
    the repo root (template in .env.example). On a wheel install the "package
    root" is site-packages, where no .env can sensibly live, so fall back to
    the current working directory's .env — but only when it actually carries
    GLASSBOX_ keys, so an unrelated project's .env is never hoovered up. If
    python-dotenv is missing or no .env is found, this silently skips — real
    environment variables still take effect.
    """
    try:
        from pathlib import Path

        from dotenv import load_dotenv
    except ImportError:
        return
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        return
    cwd_env = Path.cwd() / ".env"
    try:
        if cwd_env.is_file() and "GLASSBOX_" in cwd_env.read_text(
            encoding="utf-8", errors="ignore"
        ):
            load_dotenv(cwd_env)
    except OSError:
        pass


_load_dotenv_once()


# 必须在 _load_dotenv_once() 之后导入,确保子模块 import 期就能读到 .env
from glassbox.perception.source import (  # noqa: E402
    AVFFrameSource,
    Frame,
    list_avfoundation_devices,
)
from glassbox.perception.static import StaticFrameSource  # noqa: E402

__all__ = [
    "AVFFrameSource",
    "Frame",
    "StaticFrameSource",
    "list_avfoundation_devices",
]
