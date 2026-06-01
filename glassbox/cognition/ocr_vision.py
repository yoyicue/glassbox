"""glassbox/cognition/ocr_vision.py — Apple Vision Framework OCR (direct PyObjC calls)

A replacement for the thin ocrmac wrapper. The latter exposes only
recognition_level + languages; this implementation surfaces all of the key
Vision OCR parameters:

    - usesLanguageCorrection   turn off to let single characters / non-corpus
                               words like +/- through
    - minimumTextHeight        default 0.03125 filters out small characters,
                               can be tuned down to 0
    - customWords              strongly hint the language model to treat given
                               strings as valid tokens
    - regionOfInterest         small-window re-OCR (plan C / fallback after Kimi
                               hints a location)
    - automaticallyDetectsLanguage  iOS 17+, lets Vision pick the language itself

The interface is compatible with AppleVisionOCR (.recognize(image) → list[UIElement]),
so Phone / Scene need no changes.

Coordinate transform: Vision uses normalized coordinates (0..1) with a
        **bottom-left origin**. Box (cv2 style) has a top-left origin → Y must
        be flipped.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from glassbox.cognition.base import Box, UIElement

if TYPE_CHECKING:
    import numpy as np
    from PIL import Image as PILImage


# ─── soft-import Vision / Quartz / Foundation (only available on macOS) ──
def _import_vision():
    try:
        import Foundation
        import Quartz
        import Vision
        return Vision, Quartz, Foundation
    except ImportError as e:
        raise ImportError(
            "pyobjc-framework-Vision is not installed. On macOS run "
            "`uv add pyobjc-framework-Vision pyobjc-framework-Quartz pyobjc-framework-Cocoa`."
        ) from e


_LEVEL_MAP = {"accurate": 0, "fast": 1}


class VisionOCR:
    """Apple Vision OCR (direct PyObjC calls)."""

    def __init__(
        self,
        languages: Sequence[str] = ("zh-Hans", "en-US"),
        recognition_level: str = "accurate",
        uses_language_correction: bool = False,
        minimum_text_height: float = 0.0,
        custom_words: Sequence[str] = ("+", "-"),
        confidence_threshold: float = 0.3,
        auto_detect_language: bool = False,
        unsharp_mask: bool = True,
        unsharp_sigma: float = 1.5,
        unsharp_amount: float = 1.6,
    ):
        """
        languages:
            list of ISO language codes, default ["zh-Hans", "en-US"]. Ignored
            when auto_detect_language=True.
        recognition_level:
            "accurate" (default, slow but good) / "fast".
        uses_language_correction:
            language-model correction. **Default False** — in iOS walkthroughs
            a lot of button text is single symbols / non-corpus words
            (+ - ✓ ✕ abbreviations), and NL correction would drop them. Use
            cases that need plain prose (long-form OCR, email, notes) can turn
            this on.
        minimum_text_height:
            minimum text height (relative to image height), default 0.0 (no
            filtering). Apple's default 0.03125 drops characters below ~3%
            height, which is unfriendly to small button text.
        custom_words:
            "known words" fed into the NL model; only useful when
            uses_language_correction=True. Default ["+", "-"] is
            walkthrough-friendly.
        confidence_threshold:
            filter out low-confidence OCR results, default 0.3.
        auto_detect_language:
            let Vision pick the language itself (iOS 17+). When on, languages
            is ignored.
        unsharp_mask:
            apply an unsharp mask sharpening to the image before OCR. Default
            True — autoresearch experiments proved this preprocessing
            successfully surfaces the minus button whose "3px stroke is not
            recognized" (as an em-dash), with almost no increase in dt.
            See experiments/visionocr_minus/.
        unsharp_sigma:
            Gaussian blur radius. Default 1.5.
        unsharp_amount:
            sharpening strength. Default 1.6 (blurred part -0.6, original +1.6).
        """
        if recognition_level not in _LEVEL_MAP:
            raise ValueError(
                f"recognition_level must be 'accurate' or 'fast', got {recognition_level!r}"
            )
        self.languages = list(languages)
        self.recognition_level = recognition_level
        self.uses_language_correction = uses_language_correction
        self.minimum_text_height = minimum_text_height
        self.custom_words = list(custom_words)
        self.confidence_threshold = confidence_threshold
        self.auto_detect_language = auto_detect_language
        self.unsharp_mask = unsharp_mask
        self.unsharp_sigma = unsharp_sigma
        self.unsharp_amount = unsharp_amount
        self._Vision, self._Quartz, self._Foundation = _import_vision()

    # —— public API ─────────────────────────────────────────────────
    def recognize(
        self,
        image: PILImage.Image | np.ndarray | str,
        *,
        region_of_interest: tuple[float, float, float, float] | None = None,
    ) -> list[UIElement]:
        """Run OCR, return a list of type='text' UIElements.

        region_of_interest:
            (x, y, w, h), **normalized coordinates (0..1), bottom-left origin**
            (Vision's own convention). OCR only within this region. Used for
            plan C (VLM gives a location → re-OCR a small window for precision).
            None means the full image.
        """
        if self.unsharp_mask:
            image = self._apply_unsharp(image)
        cg_image, _keep_alive, img_w, img_h = self._image_to_cgimage(image)
        handler = self._Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            cg_image, None
        )

        request = self._Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(_LEVEL_MAP[self.recognition_level])
        if self.auto_detect_language:
            request.setAutomaticallyDetectsLanguage_(True)
        else:
            request.setRecognitionLanguages_(self.languages)
        request.setUsesLanguageCorrection_(bool(self.uses_language_correction))
        if self.minimum_text_height > 0:
            request.setMinimumTextHeight_(float(self.minimum_text_height))
        if self.custom_words:
            request.setCustomWords_(list(self.custom_words))
        if region_of_interest is not None:
            x, y, w, h = region_of_interest
            request.setRegionOfInterest_(self._Quartz.CGRectMake(x, y, w, h))

        success, err = handler.performRequests_error_([request], None)
        if not success:
            raise RuntimeError(f"VNRecognizeTextRequest failed: {err}")

        observations = request.results() or []
        elements: list[UIElement] = []
        for i, obs in enumerate(observations):
            top = obs.topCandidates_(1)
            if not top:
                continue
            cand = top[0]
            text = str(cand.string())
            conf = float(cand.confidence())
            if conf < self.confidence_threshold:
                continue
            elements.append(UIElement(
                type="text",
                box=self._bbox_to_pixel(obs.boundingBox(), img_w, img_h),
                text=text,
                confidence=conf,
                suggested_actions=[],
                element_id=i,
            ))
        return elements

    # —— helpers ────────────────────────────────────────────────────
    def _apply_unsharp(self, image):
        """Return a sharpened ndarray for ndarray / PIL.Image / path inputs.

        autoresearch verified: sigma=1.5 + amount=1.6 makes the 29×3-stroke `-`
        recognizable by Vision (returned as an em-dash).
        """
        import cv2
        import numpy as np
        from PIL import Image

        if isinstance(image, Image.Image):
            arr = np.array(image)
            if arr.ndim == 3 and arr.shape[2] == 3:
                arr = arr[..., ::-1]   # RGB → BGR
        elif isinstance(image, np.ndarray):
            arr = image
        elif hasattr(image, "__fspath__") or isinstance(image, str):
            arr = cv2.imread(str(image))
            if arr is None:
                return image
        else:
            return image
        blurred = cv2.GaussianBlur(arr, (0, 0), sigmaX=self.unsharp_sigma)
        return cv2.addWeighted(arr, self.unsharp_amount,
                               blurred, 1.0 - self.unsharp_amount, 0)

    def _image_to_cgimage(self, image):
        """Uniformly convert to a CGImage, return (cg_image, bytes_keepalive, width, height).

        bytes_keepalive must be held by the caller: Quartz's CGDataProvider
        references this byte buffer via a pointer, and the moment Python GC
        frees it you get a segfault.
        """
        import cv2
        import numpy as np
        from PIL import Image

        if isinstance(image, np.ndarray):
            arr = image
            if arr.ndim == 2:
                arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        elif isinstance(image, Image.Image):
            arr = np.array(image)
            if arr.ndim == 3 and arr.shape[2] == 3:
                arr = arr[..., ::-1]   # PIL RGB → cv2 BGR (handled uniformly below)
        elif hasattr(image, "__fspath__") or isinstance(image, str):
            arr = cv2.imread(str(image))
            if arr is None:
                raise ValueError(f"can't read image: {image!r}")
        else:
            raise TypeError(f"unsupported image type: {type(image)}")

        h, w = arr.shape[:2]
        rgba = cv2.cvtColor(arr, cv2.COLOR_BGR2RGBA)
        rgba = np.ascontiguousarray(rgba)
        data = rgba.tobytes()
        Q = self._Quartz
        provider = Q.CGDataProviderCreateWithData(None, data, len(data), None)
        cs = Q.CGColorSpaceCreateDeviceRGB()
        bitmap_info = Q.kCGImageAlphaNoneSkipLast | Q.kCGBitmapByteOrderDefault
        cg_image = Q.CGImageCreate(
            w, h, 8, 32, w * 4, cs, bitmap_info, provider,
            None, False, Q.kCGRenderingIntentDefault,
        )
        return cg_image, data, w, h

    @staticmethod
    def _bbox_to_pixel(bbox, img_w: int, img_h: int) -> Box:
        """Vision normalized bbox (bottom-left origin) → pixel Box (top-left origin)."""
        nx = float(bbox.origin.x)
        ny = float(bbox.origin.y)
        nw = float(bbox.size.width)
        nh = float(bbox.size.height)
        px = round(nx * img_w)
        pw = round(nw * img_w)
        ph = round(nh * img_h)
        # Vision: ny is the distance from the bbox bottom edge to the image bottom → bbox top edge to image top = 1 - ny - nh
        py = round((1.0 - ny - nh) * img_h)
        return Box(x=px, y=py, w=pw, h=ph)
