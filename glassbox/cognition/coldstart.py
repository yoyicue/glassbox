"""glassbox/cognition/coldstart.py — cold-start VLM annotation.

When the agent lands on a screen whose UTG node is brand new, the OCR pipeline
has no priors to lean on: confusion-class matching needs a known label set, and
a new app has none. The VLM does not — it reads structure and semantics straight
from pixels. So on a cold-start view we make ONE VLM pass for a precise
structured annotation, fuse its semantics onto the OCR boxes (the VLM says WHAT
and ROUGHLY WHERE; OCR gives the pixel-precise box), cache it on the node, and
let the cheap OCR loop take over for everything after.

Probe `scripts/probe_vlm_annotation.py` measured Kimi-K2.6 on ~448x972 HDMI
frames: element enumeration / role / navigable / label are reliable; the x
coordinate is good (~1-2%) but y drifts up to ~5% near the screen bottom — which
is exactly why navigable elements are anchored to an OCR box by label rather
than tapped on raw VLM coordinates.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import cv2

_SYSTEM = """你是 iOS 界面理解专家。给你一张 iPhone app 截图——agent 冷启动后第一次看到这个界面。
请只依据画面像素,精确标注屏幕上所有可交互或可感知的元素,输出 JSON。看不见的不要臆测。

坐标用 0-1 归一化:x_frac / y_frac = 元素中心相对截图宽 / 高的比例。

JSON schema:
{
  "scene": "<一句话描述这是什么界面>",
  "scroll_axis": "vertical" | "horizontal" | "none",
  "elements": [
    {
      "label": "<元素上的可见文字;纯图标无文字则简述,如 '加号按钮'>",
      "role": "cell" | "button" | "toggle" | "tab" | "header" | "search" | "text" | "icon",
      "navigable": true,
      "x_frac": 0.5,
      "y_frac": 0.5
    }
  ]
}
navigable = 点击后是否会进入一个新界面。"""

_USER = "标注这张 iPhone 截图,严格按 schema 输出 JSON。"

_WS_RE = re.compile(r"\s+")


def _norm(text: str | None) -> str:
    """Whitespace-stripped, casefolded form for matching a VLM label to OCR text."""
    return _WS_RE.sub("", text or "").casefold()


def _clamp01(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


@dataclass
class AnnotatedElement:
    """One element of a cold-start annotation, after VLM↔OCR fusion."""

    label: str
    role: str           # cell | button | toggle | tab | header | search | text | icon
    navigable: bool
    center: tuple[int, int]                  # tap point, cropped-frame px
    box: tuple[int, int, int, int] | None    # (x,y,w,h) precise OCR box, None when VLM-only
    anchored: bool                           # True = matched to an OCR box (precise)


@dataclass
class ScreenAnnotation:
    """A whole-screen cold-start annotation cached against a UTG node."""

    screen_id: str
    scene_desc: str
    scroll_axis: str
    elements: list[AnnotatedElement] = field(default_factory=list)
    vlm_model: str = ""
    vlm_elapsed_ms: int = 0

    @property
    def anchored_count(self) -> int:
        return sum(1 for e in self.elements if e.anchored)

    @property
    def navigable(self) -> list[AnnotatedElement]:
        return [e for e in self.elements if e.navigable]


def _encode_png(frame_img: Any) -> bytes:
    ok, buf = cv2.imencode(".png", frame_img)
    if not ok:
        raise RuntimeError("cold-start annotator: PNG encode failed")
    return buf.tobytes()


# Containment match: the shorter string must be at least this fraction of the
# longer one. Loose substring matching would anchor a no-text icon's
# descriptive VLM label (e.g. "新建信息按钮") onto an unrelated OCR row that
# merely shares a fragment ("信息"); requiring substantial overlap rejects that.
_CONTAINMENT_RATIO = 0.6


def _best_ocr_match(label: str, predicted: tuple[int, int], ocr_norm: list[tuple[str, Any]]):
    """Pick the OCR element whose text matches the VLM label and whose box is
    closest to the VLM's predicted center.

    Matching is whitespace/case-insensitive. Beyond exact equality it allows
    containment only when the strings substantially overlap (`_CONTAINMENT_
    RATIO`), so OCR line-splitting or a trailing "..." still anchors but a
    shared fragment does not. The predicted center only disambiguates a label
    that occurs more than once; the VLM's y-drift cannot pick the wrong row
    because rows sit far apart.
    """
    vl = _norm(label)
    if len(vl) < 2:
        return None
    cands = []
    for nt, el in ocr_norm:
        if len(nt) < 2:
            continue
        if nt == vl:
            cands.append(el)
            continue
        short, long = (nt, vl) if len(nt) <= len(vl) else (vl, nt)
        if short in long and len(short) / len(long) >= _CONTAINMENT_RATIO:
            cands.append(el)
    if not cands:
        return None
    return min(cands, key=lambda el: math.dist(el.box.center, predicted))


# A CV-detected icon region must sit within this many px of the VLM's predicted
# center to anchor a no-text icon element onto it.
_ICON_ANCHOR_DIST = 70.0


def _best_icon_match(predicted: tuple[int, int], icon_regions: list[Any]):
    """Nearest detected icon region to the VLM's predicted center, or None.

    The icon-side counterpart of `_best_ocr_match`: a no-text icon the VLM
    identified semantically anchors to a CV-detected region's precise box."""
    near = [r for r in icon_regions if math.dist(r.center, predicted) <= _ICON_ANCHOR_DIST]
    if not near:
        return None
    return min(near, key=lambda r: math.dist(r.center, predicted))


def fuse(
    screen_id: str,
    parsed: dict[str, Any] | None,
    ocr_elements: list[Any],
    *,
    frame_size: tuple[int, int],
    model: str = "",
    elapsed_ms: int = 0,
    icon_regions: list[Any] | None = None,
) -> ScreenAnnotation:
    """Fuse a VLM annotation with OCR text + CV-detected icon regions.

    A VLM element anchors to a precise box in priority order: a matching OCR
    text row, else a detected icon region near the predicted center, else it
    stays VLM-only (rough coordinate). Pure function — unit-testable.
    """
    w, h = frame_size
    parsed = parsed or {}
    icon_regions = icon_regions or []
    ocr_norm = [(_norm(el.text), el) for el in ocr_elements if getattr(el, "text", None)]
    out: list[AnnotatedElement] = []
    for raw in parsed.get("elements") or []:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        role = str(raw.get("role") or "text")
        navigable = bool(raw.get("navigable", False))
        predicted = (
            int(_clamp01(raw.get("x_frac")) * w),
            int(_clamp01(raw.get("y_frac")) * h),
        )
        match = _best_ocr_match(label, predicted, ocr_norm)
        if match is not None:
            b = match.box
            out.append(AnnotatedElement(
                label=label or (match.text or ""),
                role=role,
                navigable=navigable,
                center=b.center,
                box=(b.x, b.y, b.w, b.h),
                anchored=True,
            ))
            continue
        icon = _best_icon_match(predicted, icon_regions)
        if icon is not None:                  # no-text icon → CV region's precise box
            x, y, iw, ih = icon.box
            out.append(AnnotatedElement(
                label=label,
                role=role,
                navigable=navigable,
                center=icon.center,
                box=(x, y, iw, ih),
                anchored=True,
            ))
            continue
        out.append(AnnotatedElement(
            label=label,
            role=role,
            navigable=navigable,
            center=predicted,
            box=None,
            anchored=False,
        ))
    return ScreenAnnotation(
        screen_id=screen_id,
        scene_desc=str(parsed.get("scene") or ""),
        scroll_axis=str(parsed.get("scroll_axis") or "none"),
        elements=out,
        vlm_model=model,
        vlm_elapsed_ms=elapsed_ms,
    )


def apply_annotation_to_scene(scene: Any, annotation: ScreenAnnotation) -> int:
    """Write cold-start VLM semantics onto the OCR UIElements they anchored to.

    Cold-start annotations are live-only hints. They must not populate
    `intent_label`, which is reserved for concrete action labels from Layer 3
    describe_scene. Returns the number of elements updated.
    """
    by_box: dict[tuple[int, int, int, int], Any] = {}
    for el in scene.elements:
        b = el.box
        by_box.setdefault((b.x, b.y, b.w, b.h), el)
    updated = 0
    for ae in annotation.elements:
        if not ae.anchored or ae.box is None:
            continue
        el = by_box.get(ae.box)
        if el is not None:
            evidence = list(el.type_evidence)
            role_tag = f"coldstart_role:{ae.role}"
            nav_tag = f"coldstart_navigable:{str(ae.navigable).lower()}"
            for tag in (role_tag, nav_tag):
                if tag not in evidence:
                    evidence.append(tag)
            el.type_evidence = evidence
            if ae.navigable and "tap" not in el.suggested_actions:
                el.suggested_actions = [*el.suggested_actions, "tap"]
            updated += 1
    return updated


class ColdStartAnnotator:
    """VLM cold-start annotator wired to UTG node identity.

    `observe()` is the UTG-driven entry point: a brand-new node triggers one
    VLM annotation, a revisited node reuses the cache, and a per-run call budget
    caps the (slow, billed) VLM cost.
    """

    def __init__(self, vlm: Any, *, max_calls: int = 80):
        self._vlm = vlm
        self._cache: dict[str, ScreenAnnotation] = {}
        self._max_calls = max_calls
        self.calls = 0

    def observe(self, *, node: Any, scene: Any, frame_img: Any) -> ScreenAnnotation | None:
        """Annotate iff `node` is a freshly-created UTG node; else serve cache.

        Returns the ScreenAnnotation, or None when the node is a known one that
        was never annotated, or the VLM call budget is exhausted.
        """
        screen_id = node.screen_id
        cached = self._cache.get(screen_id)
        if cached is not None:
            return cached
        if node.visit_count != 1:
            return None
        if self.calls >= self._max_calls:
            return None
        annotation = self.annotate(screen_id, scene, frame_img)
        self._cache[screen_id] = annotation
        return annotation

    def annotate(
        self, screen_id: str, scene: Any, frame_img: Any, *, icon_frames: Any = None
    ) -> ScreenAnnotation:
        """Run the VLM + CV icon detection + fuse. Bypasses the new-node gate.

        `icon_frames` (several capture frames of the same screen) enables
        multi-frame voted icon detection — a faint icon wobbles in and out of
        single-frame detection, so recurrence across frames stabilizes it.
        """
        from glassbox.cognition.icon_detect import detect_icons, detect_icons_voted

        self.calls += 1
        h, w = frame_img.shape[:2]
        resp = self._vlm.chat(
            system=_SYSTEM,
            user_text=_USER,
            image=_encode_png(frame_img),
            json_object=True,
        )
        text_boxes = tuple(
            (el.box.x, el.box.y, el.box.w, el.box.h)
            for el in scene.elements if getattr(el, "text", None)
        )
        if icon_frames:
            icon_regions = detect_icons_voted(list(icon_frames), text_boxes=text_boxes)
        else:
            icon_regions = detect_icons(frame_img, text_boxes=text_boxes)
        return fuse(
            screen_id,
            resp.parsed,
            list(scene.elements),
            frame_size=(w, h),
            model=resp.model,
            elapsed_ms=resp.elapsed_ms,
            icon_regions=icon_regions,
        )

    def get(self, screen_id: str) -> ScreenAnnotation | None:
        return self._cache.get(screen_id)
