"""glassbox/cognition/ocr.py — Apple Vision OCR (M2a temporary implementation, via ocrmac)

A minimal usable OCR engine for getting the whole cognition pipeline working.
**M2b will switch to a Swift CLI** long-running subprocess (`_vision_helper/`),
keeping the interface compatible.

ocrmac is a thin PyObjC wrapper over the Vision Framework, exposing only OCR.
Performance (M3 Max baseline):
    accurate  207ms ± 1.49ms
    fast      131ms ± 702µs
    livetext  174ms ± 4.12ms

Coordinate transform note:
    The Vision Framework outputs normalized coordinates [x, y, w, h] ∈ [0, 1],
    with a **bottom-left origin**. Box (cv2 style) needs a top-left origin, so
    the Y axis must be flipped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from glassbox.cognition.base import Box, UIElement

if TYPE_CHECKING:
    import numpy as np
    from PIL import Image as PILImage


# soft-import ocrmac, give a clear error if the package is missing
def _import_ocrmac():
    try:
        from ocrmac import ocrmac
        return ocrmac
    except ImportError as e:
        raise ImportError(
            "ocrmac is not installed. On macOS run `pip install ocrmac` (M2a temporary solution). "
            "M2b will switch to a Swift CLI and no longer depend on ocrmac."
        ) from e


class AppleVisionOCR:
    """Apple Vision OCR client (via ocrmac)."""

    def __init__(
        self,
        languages: list[str] | None = None,
        recognition_level: str = "accurate",
        confidence_threshold: float = 0.3,
    ):
        """
        languages: list of ISO language codes, default ["zh-Hans", "en-US"]
                   see the ocrmac README for the full list
        recognition_level: "accurate" (default) / "fast" / "livetext"
        confidence_threshold: filter out low-confidence text, default 0.3
        """
        self.languages = languages or ["zh-Hans", "en-US"]
        self.recognition_level = recognition_level
        self.confidence_threshold = confidence_threshold
        self._impl = _import_ocrmac()  # fail fast if it raises

    def recognize(self, image: PILImage.Image | np.ndarray | str) -> list[UIElement]:
        """Run OCR on one image, return a list of type='text' UIElements.

        image accepts:
            - PIL.Image.Image
            - np.ndarray (H × W × 3, BGR or RGB, cv2 standard)
            - file path (str / Path)

        The returned UIElement:
            type='text', box (pixel coordinates), text, confidence,
            suggested_actions=[]  ← only Layer 2 upgrades / adds actions
        """
        pil_img = self._to_pil(image)
        img_w, img_h = pil_img.size

        # ocrmac call
        annotations = self._impl.OCR(
            pil_img,
            language_preference=self.languages,
            recognition_level=self.recognition_level,
        ).recognize()
        # annotations: list[(text, confidence, (nx, ny, nw, nh))]
        # normalized coordinates, bottom-left origin

        elements: list[UIElement] = []
        for i, (text, confidence, bbox) in enumerate(annotations):
            if confidence < self.confidence_threshold:
                continue
            box = self._normalized_to_pixel(bbox, img_w, img_h)
            elements.append(UIElement(
                type="text",
                box=box,
                text=text,
                confidence=float(confidence),
                suggested_actions=[],
                element_id=i,
            ))
        return elements

    # ─── helpers ────────────────────────────────────────────────
    @staticmethod
    def _to_pil(image) -> PILImage.Image:
        from PIL import Image
        if isinstance(image, Image.Image):
            return image
        if isinstance(image, (str, bytes)) or hasattr(image, "__fspath__"):
            return Image.open(image)
        # numpy ndarray: cv2 uses BGR, Vision wants RGB → convert
        import numpy as np
        if isinstance(image, np.ndarray):
            arr = image
            if arr.ndim == 3 and arr.shape[2] == 3:
                arr = arr[..., ::-1]  # BGR → RGB
            return Image.fromarray(arr)
        raise TypeError(f"unsupported image type: {type(image)}")

    @staticmethod
    def _normalized_to_pixel(
        bbox: tuple[float, float, float, float],
        img_w: int,
        img_h: int,
    ) -> Box:
        """Vision normalized coordinates (bottom-left origin) → pixel coordinates (top-left origin)."""
        nx, ny, nw, nh = bbox
        px = int(nx * img_w)
        pw = int(nw * img_w)
        ph = int(nh * img_h)
        # Y flip: Vision's y counts from the bottom up to the box's bottom edge
        py = int((1.0 - ny - nh) * img_h)
        return Box(x=px, y=py, w=pw, h=ph)


# ─── convenience function: find text in a list[UIElement] ─────────
def find_text(
    elements: list[UIElement],
    target: str,
    *,
    fuzzy_ratio: float = 0.8,
    exact_first: bool = True,
    ambiguity_guard: bool = False,
    ambiguity_margin: float = 0.1,
) -> UIElement | None:
    """Find the element matching target in OCR results.

    fuzzy_ratio: levenshtein-like similarity threshold (0..1); 0.8 means 80% identical characters counts as a hit
    exact_first: when True, try exact matching first, fall back to fuzzy if nothing is found
    ambiguity_guard: CUQ-1.5 — when True, the substring tier prefers the
        closest-length containing row (not the first), and the fuzzy tier returns
        None when the best match does not beat the runner-up by ``ambiguity_margin``
        (so an ambiguous read escalates instead of guessing). Default off keeps
        the historical first-match behavior byte-for-byte.
    """
    from glassbox.cognition.text_match import (
        fuzzy_ratio as _fr,
    )
    from glassbox.cognition.text_match import (
        norm_text,
        text_contains,
        texts_match,
    )

    if exact_first:
        for el in elements:
            if el.text and texts_match(el.text, target):
                return el
    # substring
    containing = [el for el in elements if el.text and text_contains(el.text, target)]
    if containing:
        if ambiguity_guard:
            tgt_len = len(norm_text(target))
            return min(containing, key=lambda el: abs(len(norm_text(el.text)) - tgt_len))
        return containing[0]
    # fuzzy
    best: UIElement | None = None
    best_ratio = fuzzy_ratio
    second_best_ratio = 0.0
    for el in elements:
        if not el.text:
            continue
        r = _fr(target, el.text)
        if r >= best_ratio:
            if best is not None:
                second_best_ratio = max(second_best_ratio, best_ratio)
            best, best_ratio = el, r
        elif r > second_best_ratio:
            second_best_ratio = r
    if ambiguity_guard and best is not None and (best_ratio - second_best_ratio) < ambiguity_margin:
        return None
    return best
