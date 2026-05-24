"""VLM describe-scene clients backed by Kimi-compatible providers.

Two built-in providers are available (default moonshot):

  1. MoonshotAnthropicVLM (default): uses Moonshot's official Anthropic-compatible endpoint
       POST https://api.moonshot.cn/anthropic/v1/messages
       model: kimi-k2.6 (262k context, can be changed via KIMI_ANTHROPIC_MODEL)
       uses the `anthropic` SDK (already a pyproject dependency)
       measured ~8.5s/call, login screenshot labels all 6/6 elements correctly

  2. SiliconFlowVLM: uses SiliconFlow's OpenAI-compatible endpoint
       POST https://api.siliconflow.cn/v1/chat/completions
       model: Pro/moonshotai/Kimi-K2.6
       stdlib-only (urllib), measured ~20s/call (K2.6's reasoning chain is longer)

Both implement the same .chat() + .describe_scene() API, and enrich_scene works with either.

Pricing (2026-05, Moonshot official vs SF):
    Moonshot kimi-k2.6:    ¥1.10/¥6.50/¥27.00 per 1M (hit/miss/out), 262k ctx
    Moonshot v1-32k-vision: ¥5.00/¥20.00,          32k ctx (old + expensive)
    SF Pro/Kimi-K2.6:      $0.60/$2.50 per 1M ≈ ¥4.4/¥18.3

Usage (M3b):
    Layer 3 semantics — on the elements obtained from OCR + heuristic, let Kimi
    populate intent_label / scene_type / purpose. Usage:
        scene = phone.perceive()                 # Layer 1 + Layer 2
        enrich_scene(scene, frame_img, kimi)     # Layer 3

    **Do not let Kimi return click coordinates directly** in general or 2D
    screens (measured offset ~100px); only let it label known elements. The
    Settings 1D-list row-y fallback is the bounded, measured exception and still
    flows through Settings row projection before actuation.

→ call only at key decision points, not every frame
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from glassbox.cognition.base import Scene
from glassbox.cognition.base import UIElement
from glassbox.cognition.contracts import (
    DEFAULT_SCENE_CLASSIFICATION_PROJECTOR,
    SceneClassification,
    VLMRequest,
    VLMResult,
    VLMStageOutcome,
)
from glassbox.perception.source import Frame

# SiliconFlow VLM defaults
SF_URL = "https://api.siliconflow.cn/v1/chat/completions"
SF_MODEL = "Pro/moonshotai/Kimi-K2.6"

# Moonshot VLM defaults
MS_BASE_URL = "https://api.moonshot.cn/anthropic"
MS_MODEL = "kimi-k2.6"   # 262k context + vision, measured ~8.5s/call, 3-4x cheaper than v1

# legacy name compatibility
DEFAULT_URL = SF_URL
DEFAULT_MODEL = SF_MODEL


def _require_api_key(explicit: str | None, env_name: str) -> str:
    """Get the API key: explicit argument > environment variable. Neither → raise a clear error.

    The key always goes through the env (the repo-root `.env` is loaded
    automatically by the glassbox, see .env.example); it is **never hardcoded
    into source**.
    """
    key = explicit or os.environ.get(env_name)
    if not key:
        raise RuntimeError(
            f"Missing API key — set the environment variable {env_name}, "
            f"or run `cp .env.example .env` and fill the key into .env."
        )
    return key


VLMResponse = VLMResult


# ─── shared: JSON fallback parsing + describe_scene prompt construction ──
def _element_payload(el: UIElement | dict[str, Any]) -> dict[str, Any]:
    if isinstance(el, UIElement):
        return {
            "id": int(el.element_id),
            "text": el.text or "",
            "type": el.type,
            "box": [el.box.x, el.box.y, el.box.x2, el.box.y2],
        }
    return dict(el)


def _frame_png_bytes(frame: Frame) -> bytes:
    import cv2

    ok, png = cv2.imencode(".png", frame.img)
    if not ok:
        raise ValueError("failed to encode VLMRequest image as PNG")
    return png.tobytes()


def normalize_describe_scene_args(
    request: VLMRequest | None = None,
    *,
    frame_image: bytes | None = None,
    elements: list[dict[str, Any]] | None = None,
    scene_hint: str | None = None,
    system_prompt: str | None = None,
    set_of_mark: bool = False,
) -> dict[str, Any]:
    if request is not None:
        return {
            "frame_image": _frame_png_bytes(request.image),
            "elements": [_element_payload(el) for el in request.elements],
            "scene_hint": request.scene_hint,
            "system_prompt": request.system_prompt,
            "set_of_mark": request.set_of_mark,
        }
    if frame_image is None:
        raise TypeError("describe_scene requires frame_image or VLMRequest")
    if elements is None:
        raise TypeError("describe_scene requires elements or VLMRequest")
    return {
        "frame_image": frame_image,
        "elements": elements,
        "scene_hint": scene_hint,
        "system_prompt": system_prompt,
        "set_of_mark": set_of_mark,
    }


def _safe_parse_json(content: str) -> dict | None:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


class _DescribeSceneMixin:
    """A subclass only needs to implement .chat(...) to gain describe_scene capability."""

    def chat(self, **kw) -> VLMResponse:           # type: ignore[empty-body]
        raise NotImplementedError

    def describe_scene(
        self,
        request: VLMRequest | None = None,
        *,
        frame_image: bytes | None = None,
        elements: list[dict[str, Any]] | None = None,
        scene_hint: str | None = None,
        system_prompt: str | None = None,
        set_of_mark: bool = False,
    ) -> VLMResponse:
        """Feed a screenshot + already-recognized elements, let Kimi populate intent_label / scene_type.

        elements must be shaped like:
            [{"id": int, "text": str, "type": str, "box": [x1,y1,x2,y2]}, ...]

        system_prompt overrides SYSTEM_DESCRIBE — used by the prompt-tuning loop
        (scripts/vlm_autoresearch) to A/B candidate prompts against the default.

        set_of_mark draws a numbered red box for each element onto the
        screenshot, so the VLM correlates an element to its on-screen region by
        a mark it can *see* instead of mentally aligning text coordinates.
        Default off: on the (sparse) eval set it measured at parity with the
        text-only path while costing more tokens + being sensitive to box
        accuracy — opt in for dense/ambiguous scenes. See glassbox/cognition/som.py,
        docs/design/gui_understanding.md §6.1, and scripts/vlm_autoresearch.
        """
        args = normalize_describe_scene_args(
            request,
            frame_image=frame_image,
            elements=elements,
            scene_hint=scene_hint,
            system_prompt=system_prompt,
            set_of_mark=set_of_mark,
        )
        frame_image = args["frame_image"]
        elements = args["elements"]
        scene_hint = args["scene_hint"]
        system_prompt = args["system_prompt"]
        set_of_mark = args["set_of_mark"]

        summary_lines = []
        for el in elements:
            box = el.get("box") or [0, 0, 0, 0]
            summary_lines.append(
                f'  - id={el.get("id")} type={el.get("type", "text")} '
                f'text={(el.get("text") or "")[:40]!r} box={box}'
            )
        summary = "\n".join(summary_lines) if summary_lines else "  (空)"

        image = frame_image
        mark_note = ""
        if set_of_mark and elements:
            from glassbox.cognition.som import render_set_of_mark
            image = render_set_of_mark(frame_image, elements)
            mark_note = (
                "截图上已为每个元素画了红色方框 + 红色数字编号,数字 = 上面列表里的 id。"
                "请用画面上的红色编号来定位元素的实际位置(标号可能压住元素一角,"
                "元素文字以上面列表为准)。\n\n"
            )

        user_text = (
            f"图片是 iOS 手机截图。OCR + heuristic 已识别 {len(elements)} 个元素:\n"
            f"{summary}\n\n"
            f"{mark_note}"
        )
        if scene_hint:
            user_text += f"用户当前操作意图:{scene_hint}\n\n"
        user_text += (
            "请按 system 给的 schema 回填每个 id 对应的 intent_label / purpose / "
            "confidence,以及整个屏幕的 scene_type。"
        )

        return self.chat(
            system=system_prompt or SYSTEM_DESCRIBE,
            user_text=user_text,
            image=image,
            json_object=True,
        )

    def read_text_region(self, *, region_image: bytes) -> str:
        """OCR fallback (F): read the exact visible text in a cropped image.

        For a single row/control whose on-device OCR is too noisy to match any
        known label. Returns only the text — no analysis, no JSON. Empty when
        the VLM cannot read it. Slow + billed, so callers should gate this on
        a real OCR miss and cache by crop signature.
        """
        resp = self.chat(
            system=(
                "你是 OCR 引擎。只输出图片中可见的文字本身,逐字照抄,"
                "不要解释、不要加标点或修饰。看不清就输出空。"
            ),
            user_text="读出这张图里的文字,只返回文字本身。",
            image=region_image,
            json_object=False,
        )
        return (resp.raw_content or "").strip()[:64]


# ─── SiliconFlowVLM: OpenAI-compatible backend ────────────────────────
class SiliconFlowVLM(_DescribeSceneMixin):
    """OpenAI-compatible chat client, exposing only the capabilities we use."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = SF_MODEL,
        url: str = SF_URL,
        timeout: int = 180,
    ):
        self.api_key = _require_api_key(api_key, "SILICONFLOW_API_KEY")
        self.model = model
        self.url = url
        self.timeout = timeout

    def chat(
        self,
        *,
        system: str,
        user_text: str,
        image: str | bytes | None = None,
        json_object: bool = True,
        temperature: float = 0.1,
    ) -> VLMResponse:
        """A single-turn chat.

        image accepts three forms:
            - None       (text only)
            - bytes      (raw PNG/JPG bytes, automatically base64-wrapped into a data URL)
            - str URL    ("https://..." or an already-assembled data:image/...;base64,...)
        """
        user_content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        if image is not None:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": self._coerce_image_url(image)},
            })

        body: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        }
        if json_object:
            body["response_format"] = {"type": "json_object"}

        t0 = time.monotonic()
        data = self._post_json(body)
        elapsed = int((time.monotonic() - t0) * 1000)

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected VLM response structure: {data}") from e

        parsed = None
        if json_object:
            parsed = _safe_parse_json(content)

        return VLMResponse(
            raw_content=content,
            parsed=parsed,
            usage=data.get("usage", {}),
            model=data.get("model", self.model),
            elapsed_ms=elapsed,
        )

    # —— internal ——
    def _coerce_image_url(self, image: str | bytes) -> str:
        if isinstance(image, bytes):
            b64 = base64.b64encode(image).decode("ascii")
            return f"data:image/png;base64,{b64}"
        if isinstance(image, str):
            return image
        raise TypeError(f"image must be str or bytes, got {type(image)}")

    def _post_json(self, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8")[:500]
            except Exception:
                err_body = ""
            raise RuntimeError(f"Kimi HTTP {e.code}: {err_body}") from e
        return json.loads(raw)


# ─── MoonshotAnthropicVLM: Moonshot official Anthropic-compatible backend ─────
class MoonshotAnthropicVLM(_DescribeSceneMixin):
    """VLM client for the Moonshot Anthropic endpoint, using the `anthropic` SDK."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str = MS_BASE_URL,
        timeout: int = 180,
    ):
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError(
                "The `anthropic` SDK is required (already a pyproject dependency)."
            ) from e

        self.api_key = _require_api_key(api_key, "MOONSHOT_API_KEY")
        self.model = model or os.environ.get("KIMI_ANTHROPIC_MODEL") or MS_MODEL
        self.base_url = base_url
        self.timeout = timeout
        self._client = anthropic.Anthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
        )

    def chat(
        self,
        *,
        system: str,
        user_text: str,
        image: str | bytes | None = None,
        json_object: bool = True,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> VLMResponse:
        """Anthropic Messages API. The Moonshot endpoint supports a base64 source for image."""
        content_blocks: list[dict[str, Any]] = []
        if image is not None:
            if isinstance(image, bytes):
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(image).decode("ascii"),
                    },
                })
            elif isinstance(image, str):
                # the Anthropic SDK supports a URL source
                content_blocks.append({
                    "type": "image",
                    "source": {"type": "url", "url": image},
                })
            else:
                raise TypeError(f"image must be str / bytes, got {type(image)}")
        content_blocks.append({"type": "text", "text": user_text})

        t0 = time.monotonic()
        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": content_blocks}],
            )
        except Exception as e:
            raise RuntimeError(f"MoonshotAnthropicVLM chat failed: {e}") from e
        elapsed = int((time.monotonic() - t0) * 1000)

        text = "".join(
            getattr(b, "text", "") for b in message.content if getattr(b, "type", None) == "text"
        )
        parsed = _safe_parse_json(text) if json_object else None

        return VLMResponse(
            raw_content=text,
            parsed=parsed,
            usage={
                "prompt_tokens": getattr(message.usage, "input_tokens", 0),
                "completion_tokens": getattr(message.usage, "output_tokens", 0),
                "total_tokens": (
                    getattr(message.usage, "input_tokens", 0)
                    + getattr(message.usage, "output_tokens", 0)
                ),
            },
            model=getattr(message, "model", self.model),
            elapsed_ms=elapsed,
        )


# ─── factory: env VLM_BACKEND/KIMI_BACKEND=anthropic|siliconflow, default anthropic ──
def make_vlm_client(
    backend: str | None = None,
    model: str | None = None,
    **kwargs,
) -> _DescribeSceneMixin:
    """Build a client based on the backend name.

    backend: explicit argument > env `VLM_BACKEND` > env `KIMI_BACKEND` > default anthropic.
    model:   explicit argument > env `VLM_MODEL` > env `KIMI_MODEL` > each backend's own default;
             shared by both backends (SiliconFlow / Moonshot have different
             model names, leave it blank to take each default).
    endpoint is still a module constant (SF_URL / MS_BASE_URL) — provider
    domains are stable; to actually change one, use the constructor argument
    url= / base_url=.
    """
    name = (
        backend or os.environ.get("VLM_BACKEND") or os.environ.get("KIMI_BACKEND") or "anthropic"
    ).lower().strip()
    model = model or os.environ.get("VLM_MODEL") or os.environ.get("KIMI_MODEL") or None
    if model:
        kwargs.setdefault("model", model)
    if name in ("anthropic", "moonshot", "ms"):
        return MoonshotAnthropicVLM(**kwargs)
    if name in ("siliconflow", "sf", "openai"):
        return SiliconFlowVLM(**kwargs)
    raise ValueError(f"unknown VLM_BACKEND={name} (supported: anthropic / siliconflow)")


KimiResponse = VLMResponse
KimiVL = SiliconFlowVLM
KimiAnthropic = MoonshotAnthropicVLM
make_kimi_client = make_vlm_client


# ─── prompt: used by describe_scene ──────────────────────────────────
# Tuned via the autoresearch-style loop in scripts/vlm_autoresearch (v1_anchor:
# 0.804 → 1.000 on the eval set). The anchor rule (#2) fixed the main
# failure mode — Kimi paraphrasing an element into a near-synonym.
SYSTEM_DESCRIBE = """你是 iOS UI 走查助手。看截图 + 用户给的元素候选列表,
为每个元素回填**动作语义标签**,顺便提取整屏的**业务状态**。

**只返回严格 JSON**:
{
  "scene_type": "login_form | paywall | list | settings | splash | modal | onboarding | main | unknown",
  "context": "<≤80字 当前屏幕状态说明,可省略>",
  "available_intents": ["<≤8字 可执行动作短语>", "..."],
  "app_state": {
    "subscription": "subscribed | free | trial | expired | unknown",
    "auth":         "logged_in | logged_out | unknown",
    "current_view": "<≤8字 当前页中文短名>",
    "unread_count": "<整数字符串,无未读省略此 key>"
  },
  "elements": [
    {"id": <用户给的 id,不可改>,
     "intent_label": "<≤8字 动作短语,如:确认登录 / 关闭弹窗 / 选择年度套餐>",
     "purpose": "<≤20字,这个元素具体干嘛>",
     "confidence": 0.0-1.0}
  ]
}

要求:
1. 严格用用户给的 id,不要新增、删除、重排。
2. intent_label 必须是**动作短语**,且**锚定元素自身可见文字**:用「动词 + 元素原文关键词」构造,
   不要把元素文字替换成近义词或上位词。
   - 元素文字是「功能请求」→「提交功能请求」,不能写成「提交反馈」。
   - 元素文字是「使用条款」→「查看使用条款」,不能丢掉「使用」二字。
   - 元素文字是「未找到设备?」→ 保留「未找到设备」,不能泛化成「查看帮助」。
   - 元素文字本身已是动作(如「重新扫描」「恢复购买」)→ 直接用原文。
   - 始终是动作,不是描述(不要「登录按钮」这种)。
3. 看不清 / 不确定:confidence ≤ 0.5,intent_label 用空字符串。
4. 纯展示性元素(标题、温度数值、说明文字、插画 banner)不可操作 → intent_label 用空字符串。
5. 不要返回 box 坐标,也不要自创新元素。
6. context / available_intents 可选;available_intents 只列当前屏幕真实可执行的动作。
7. app_state 各 key 都可选;不确定填 "unknown" 或干脆省略。subscription
   要看页面上是否有"会员/订阅/试用/解锁/付费/限制"等线索,有"高级会员"
   "已订阅"等正向词 → "subscribed";有"获取折扣/解锁/升级"等促销 → "free"。"""

DESCRIBE_CACHE_SCHEMA_VERSION = "describe-scene-v3"


def describe_prompt_cache_key(system_prompt: str | None = None) -> str:
    """Stable key fragment for describe_scene prompt/schema cache compatibility."""
    h = hashlib.sha256()
    h.update(DESCRIBE_CACHE_SCHEMA_VERSION.encode("utf-8"))
    h.update(b"\0")
    h.update((system_prompt or SYSTEM_DESCRIBE).encode("utf-8"))
    return h.hexdigest()[:16]


def vlm_stage_outcome_from_result(result: VLMResult) -> VLMStageOutcome:
    """Derive the VLM stage's typed output from a backend response."""
    parsed = result.parsed
    if not isinstance(parsed, dict):
        return VLMStageOutcome(status="parse_error", error="invalid parsed payload")

    classification = None
    scene_type = parsed.get("scene_type")
    if isinstance(scene_type, str) and scene_type:
        classification = SceneClassification(
            semantic_scene_type=scene_type,
            confidence=1.0,
            source="vlm",
        )

    element_intents: dict[int, str] = {}
    for item in parsed.get("elements", []) or []:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        label = item.get("intent_label")
        if not isinstance(label, str):
            continue
        label = label.strip()
        if label:
            element_intents[item_id] = label[:32]

    return VLMStageOutcome(
        status="ok",
        element_intents=element_intents,
        classification=classification,
    )


# ─── enrich_scene: populate Kimi results onto the Scene ──────────────
def enrich_scene(
    scene: Scene,
    frame_image: bytes | Frame,
    client: _DescribeSceneMixin,
    *,
    scene_hint: str | None = None,
) -> Scene:
    """Run Kimi describe_scene, populate intent_label onto scene.elements and
    scene_type onto scene.scene_type. Modifies and returns the scene in place.

    If Kimi fails / returns something invalid, mark the Scene's VLM status and
    return it without applying Layer 3 labels.
    """
    raw_ids = [int(el.element_id) for el in scene.elements]
    use_request_ids = len(set(raw_ids)) != len(raw_ids)
    payload = []
    by_request_id = {}
    request_elements = []
    for index, el in enumerate(scene.elements):
        request_id = index if use_request_ids else int(el.element_id)
        payload.append({
            "id": request_id,
            "text": el.text or "",
            "type": el.type,
            "box": [el.box.x, el.box.y, el.box.x2, el.box.y2],
        })
        request_elements.append(el.model_copy(update={"element_id": request_id}))
        by_request_id[request_id] = el
    requested_ids = [int(item["id"]) for item in payload]
    scene.vlm_requested_element_ids = requested_ids
    scene.vlm_returned_element_ids = []
    scene.vlm_missing_element_ids = list(requested_ids)
    scene.vlm_intent_coverage = 0.0 if requested_ids else None
    if not payload:
        _mark_vlm(scene, "skipped_empty", scene_hint=scene_hint, client=client)
        return scene

    try:
        if isinstance(frame_image, Frame):
            try:
                resp = client.describe_scene(
                    VLMRequest(
                        image=frame_image,
                        elements=request_elements,
                        scene_hint=scene_hint,
                        system_prompt=SYSTEM_DESCRIBE,
                    )
                )
            except TypeError:
                resp = client.describe_scene(
                    frame_image=_frame_png_bytes(frame_image),
                    elements=payload,
                    scene_hint=scene_hint,
                )
        else:
            resp = client.describe_scene(
                frame_image=frame_image,
                elements=payload,
                scene_hint=scene_hint,
            )
    except Exception as e:
        _mark_vlm(scene, "error", scene_hint=scene_hint, client=client, error=str(e))
        return scene

    outcome = vlm_stage_outcome_from_result(resp)
    if outcome.status != "ok":
        _mark_vlm(
            scene,
            outcome.status,
            scene_hint=scene_hint,
            client=client,
            response=resp,
            error=outcome.error,
        )
        return scene
    parsed = resp.parsed
    assert isinstance(parsed, dict)
    _mark_vlm(scene, "ok", scene_hint=scene_hint, client=client, response=resp)

    # scene_type
    if outcome.classification is not None:
        DEFAULT_SCENE_CLASSIFICATION_PROJECTOR.project(
            scene,
            [outcome.classification],
            overwrite_scene_type=True,
        )

    context = parsed.get("context")
    if isinstance(context, str) and context.strip():
        scene.context = context.strip()[:256]

    intents = parsed.get("available_intents")
    if isinstance(intents, list):
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in intents:
            if not isinstance(item, str):
                continue
            intent = item.strip()[:32]
            if not intent or intent in seen:
                continue
            cleaned.append(intent)
            seen.add(intent)
        if cleaned:
            scene.available_intents = cleaned

    # app_state: filter k/v strings, drop invalid values
    app_state = parsed.get("app_state")
    if isinstance(app_state, dict):
        for k, v in app_state.items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            k_clean = k.strip()[:24]
            v_clean = v.strip()[:32]
            if k_clean and v_clean:
                scene.app_state[k_clean] = v_clean

    # populate intent_label by id. A successful VLM response is authoritative
    # for the submitted Set-of-Mark ids, so omitted ids must not keep stale
    # labels from a previous frame/cache hit.
    for el in scene.elements:
        el.intent_label = None
        el.intent_confidence = None
        el.intent_source = None
    returned_ids: set[int] = set()
    for item in parsed.get("elements", []) or []:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        returned_ids.add(item_id)
        el = by_request_id.get(item_id)
        if el is None:
            continue
        label = item.get("intent_label")
        if item_id not in outcome.element_intents and not isinstance(label, str):
            continue
        el.intent_confidence = _confidence_or_none(item.get("confidence"))
        el.intent_source = "vlm"
        el.intent_label = outcome.element_intents.get(item_id)
    scene.vlm_returned_element_ids = sorted(returned_ids)
    scene.vlm_missing_element_ids = [eid for eid in requested_ids if eid not in returned_ids]
    scene.vlm_intent_coverage = (
        len(returned_ids & set(requested_ids)) / len(requested_ids)
        if requested_ids else None
    )

    return scene


def _mark_vlm(
    scene: Scene,
    status: str,
    *,
    scene_hint: str | None,
    client: _DescribeSceneMixin,
    response: VLMResponse | None = None,
    error: str | None = None,
) -> None:
    scene.vlm_status = status
    scene.vlm_described = status == "ok"
    scene.vlm_scene_hint = scene_hint
    scene.vlm_model = response.model if response is not None else getattr(client, "model", None)
    scene.vlm_elapsed_ms = response.elapsed_ms if response is not None else None
    scene.vlm_usage = dict(response.usage) if response is not None else {}
    scene.vlm_error = error[:256] if error else None


def _confidence_or_none(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    conf = float(value)
    if conf < 0.0 or conf > 1.0:
        return None
    return conf


# ─── CLI:`python -m glassbox.cognition.vlm_kimi --image foo.png --prompt "..."` ──
def _main():
    import argparse
    import pathlib

    ap = argparse.ArgumentParser(description="Kimi K2.6 vision probe")
    ap.add_argument("--image", required=True, help="local image path")
    ap.add_argument(
        "--prompt",
        default="请用简短的中文描述这张图里你看到的所有 UI 元素(文字、按钮、图标),按从上到下、从左到右列出。",
        help="user text",
    )
    ap.add_argument(
        "--system",
        default="你是一个善于阅读手机 UI 截图的助手。只返回严格 JSON,字段 elements 是数组,每项含 text、approx_location(top-left/top-right/...)、looks_like(button/text/icon/...)。",
    )
    ap.add_argument("--no-json", action="store_true", help="don't force json_object")
    args = ap.parse_args()

    img_path = pathlib.Path(args.image)
    if not img_path.exists():
        raise SystemExit(f"image does not exist: {img_path}")

    client = SiliconFlowVLM()
    print(f"→ model={client.model} url={client.url}")
    print(f"→ image={img_path}({img_path.stat().st_size} bytes)")

    resp = client.chat(
        system=args.system,
        user_text=args.prompt,
        image=img_path.read_bytes(),
        json_object=not args.no_json,
    )

    print(f"\n← elapsed={resp.elapsed_ms} ms  usage={resp.usage}")
    print("← raw_content:")
    print(resp.raw_content)
    if resp.parsed is not None:
        print("\n← parsed JSON:")
        print(json.dumps(resp.parsed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
