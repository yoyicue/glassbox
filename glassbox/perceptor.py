"""Snapshot, OCR, scene classification, and perception cache handling."""

from __future__ import annotations

import hashlib
import inspect
import threading
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from loguru import logger

from glassbox.cognition import (
    DEFAULT_SCENE_CLASSIFICATION_PROJECTOR,
    Box,
    Scene,
    SceneClassification,
    SceneClassificationPrior,
    UIElement,
)
from glassbox.cognition.coldstart import apply_annotation_to_scene
from glassbox.cognition.ocr_contract import ocr_results_to_elements
from glassbox.perception.app_viewport import (
    detect_iphone_compat_viewport,
    detected_viewport_needs_update,
)

if TYPE_CHECKING:
    import numpy as np

    from glassbox.memory.schema import ActionRecord
    from glassbox.perception.source import Frame

_LETTERBOX_BBOX_TOLERANCE_PX = 4


def _frame_image_hash(frame: Frame) -> str:
    img = frame.img
    digest = hashlib.blake2b(digest_size=8)
    digest.update(str(getattr(img, "shape", "")).encode("ascii", errors="ignore"))
    digest.update(img.tobytes())
    return digest.hexdigest()


def _bbox_within_tolerance(
    a: tuple[int, int, int, int] | None,
    b: tuple[int, int, int, int] | None,
    tol: int,
) -> bool:
    if a is None or b is None:
        return False
    return all(abs(int(a[i]) - int(b[i])) <= tol for i in range(4))


def _platform_key_from_model(model: object) -> str | None:
    value = str(model or "").lower().replace("-", "_")
    if value.startswith("ipad"):
        return "ipados"
    if value:
        return "ios"
    return None


class Perceptor:
    """Owns Phone's perception pipeline while Phone keeps the public facade."""

    def __init__(self, phone: Any) -> None:
        self._phone = phone
        self._context = phone.action_context

    def set_last_scene(self, scene: Scene, frame: Frame | None) -> None:
        context = self._context
        context.last_scene = scene
        context.last_scene_coordinate_space = frame.context.coordinate_space if frame is not None else None
        context.implicit_coordinate_space_error = None

    def observe_memory(self, scene: Scene, frame_img) -> None:
        host = self._phone
        context = self._context
        if host.memory is None:
            context.pending_actions_for_memory.clear()
            return
        actions = [
            action for action in context.pending_actions_for_memory
            if self.memory_action_candidate(action)
        ]
        last_action = actions[0] if len(actions) == 1 else None
        node = host.memory.observe(scene, last_action, frame_img=frame_img)
        context.pending_actions_for_memory = []
        if host.coldstart is not None and frame_img is not None:
            try:
                annotation = host.coldstart.observe(node=node, scene=scene, frame_img=frame_img)
            except Exception as exc:
                logger.warning(f"cold-start annotation failed: {exc}")
            else:
                if annotation is not None:
                    apply_annotation_to_scene(
                        scene, annotation, promote_controls=host.coldstart_promote_controls_enabled
                    )

    @staticmethod
    def memory_action_candidate(action: ActionRecord) -> bool:
        if action.params.get("action_ok") is not True:
            return False
        return action.params.get("action_synthetic") is not True

    def scene_classification_prior(
        self,
        scene: Scene,
        frame_img: np.ndarray | None,
    ) -> SceneClassificationPrior | None:
        host = self._phone
        context = self._context
        actions = [
            action for action in context.pending_actions_for_memory
            if self.memory_action_candidate(action)
        ]
        last_action = actions[0] if len(actions) == 1 else None
        node = None
        recognition_score = None
        memory = getattr(host, "memory", None)
        recognize = getattr(memory, "recognize", None) if memory is not None else None
        if callable(recognize):
            try:
                node = recognize(scene, frame_img)
                if node is not None:
                    recognition_score = getattr(memory, "last_recognize_score", None)
            except Exception as exc:
                logger.warning(f"screen-memory prior recognition failed: {exc}")
        if node is None and last_action is None:
            return None
        return SceneClassificationPrior(
            screen_id=getattr(node, "screen_id", None),
            page_id=getattr(node, "page_id", None),
            recognition_score=recognition_score,
            scene_type=getattr(node, "scene_type", None),
            semantic_scene_type=getattr(node, "semantic_scene_type", None),
            platform_scene_kind=getattr(node, "platform_scene_kind", None),
            last_action_op=getattr(last_action, "op", None),
            last_action_target=getattr(last_action, "target", None),
            last_action_via=getattr(last_action, "via", None),
        )

    def apply_scene_classifiers(self, scene: Scene, frame_img: np.ndarray | None) -> None:
        host = self._phone
        viewport_size = None
        if frame_img is not None and getattr(frame_img, "ndim", 0) >= 2:
            viewport_size = (int(frame_img.shape[1]), int(frame_img.shape[0]))
        prior = self.scene_classification_prior(scene, frame_img)
        if host.scene_classifiers:
            classifications: list[SceneClassification] = []
            for classify in host.scene_classifiers:
                result = self.call_scene_classifier(
                    classify,
                    scene,
                    viewport_size=viewport_size,
                    prior=prior,
                )
                if result is not None:
                    classifications.append(result)
            if classifications:
                vlm_classification = self.vlm_classification_from_scene(scene)
                if vlm_classification is not None:
                    classifications.append(vlm_classification)
            DEFAULT_SCENE_CLASSIFICATION_PROJECTOR.project(scene, classifications)
        self.maybe_arbitrate_uncertain_scene_with_vlm(scene, frame_img, viewport_size=viewport_size)
        self.apply_scene_annotations(scene, viewport_size=viewport_size)

    @staticmethod
    def vlm_classification_from_scene(scene: Scene) -> SceneClassification | None:
        if getattr(scene, "vlm_status", None) != "ok":
            return None
        semantic_scene_type = getattr(scene, "semantic_scene_type", None)
        evidence = tuple(getattr(scene, "classification_evidence", ()) or ())
        platform_scene_kind = None
        if "vlm_platform_scene_kind" in evidence:
            platform_scene_kind = getattr(scene, "platform_scene_kind", None)
        if not semantic_scene_type and not platform_scene_kind:
            return None
        return SceneClassification(
            page_id=getattr(scene, "page_id", None) if platform_scene_kind else None,
            semantic_scene_type=semantic_scene_type,
            platform_scene_kind=platform_scene_kind,
            confidence=1.0,
            source="vlm",
            evidence=evidence,
            clear_page_id=platform_scene_kind == "unknown",
            clear_safe_actions=platform_scene_kind == "unknown",
        )

    def maybe_arbitrate_uncertain_scene_with_vlm(
        self,
        scene: Scene,
        frame_img: np.ndarray | None,
        *,
        viewport_size: tuple[int, int] | None,
    ) -> None:
        host = self._phone
        if "vlm_on_uncertain" not in set(getattr(scene, "safe_actions", ()) or ()):
            return
        if getattr(host, "kimi", None) is None:
            return
        if getattr(scene, "vlm_status", None) is not None:
            return
        frame = getattr(host, "last_frame", None)
        if frame is None:
            return
        try:
            from glassbox.cognition.vlm_kimi import enrich_scene
        except Exception:
            return
        if hasattr(host.kimi, "last_hit"):
            host.kimi.last_hit = False
        t0 = time.monotonic()
        enrich_scene(
            scene,
            frame,
            host.kimi,
            scene_hint="scene_arbitration:vlm_on_uncertain",
            set_of_mark=bool(getattr(host, "vlm_set_of_mark_enabled", False)),
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if getattr(scene, "vlm_status", None) == "ok":
            self.apply_profile(scene, frame_img)
        if host.recorder is not None:
            host.recorder.kimi_call(
                model=scene.vlm_model or getattr(host.kimi, "model", "?"),
                hit=bool(getattr(host.kimi, "last_hit", False)),
                elapsed_ms=elapsed_ms,
                usage=dict(scene.vlm_usage),
                scene_hint=scene.vlm_scene_hint,
                status=scene.vlm_status or "unknown",
                error=scene.vlm_error,
                parse_ok=scene.vlm_status == "ok",
            )

    @staticmethod
    def call_scene_classifier(
        classify,
        scene: Scene,
        *,
        viewport_size: tuple[int, int] | None,
        prior: SceneClassificationPrior | None,
    ) -> SceneClassification | None:
        try:
            signature = inspect.signature(classify)
        except (TypeError, ValueError):
            return classify(scene, viewport_size)
        params = signature.parameters
        accepts_varkw = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())
        accepts_prior = accepts_varkw or "prior" in params
        viewport = params.get("viewport_size")
        accepts_viewport_kw = accepts_varkw or (
            viewport is not None
            and viewport.kind
            in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        )
        if accepts_prior:
            if accepts_viewport_kw:
                return classify(scene, viewport_size=viewport_size, prior=prior)
            return classify(scene, viewport_size, prior=prior)
        if accepts_viewport_kw:
            return classify(scene, viewport_size=viewport_size)
        return classify(scene, viewport_size)

    def apply_scene_annotations(
        self,
        scene: Scene,
        *,
        viewport_size: tuple[int, int] | None,
    ) -> None:
        platform = _platform_key_from_model(getattr(getattr(self._phone, "device_geometry", None), "model", ""))
        scene_kind = str(scene.platform_scene_kind or "")
        if not bool(getattr(self._phone, "ios_closed_set_canonicalization_enabled", True)):
            return
        if platform not in {"ios", "ipados"} and not (
            scene_kind.startswith("springboard")
            or scene_kind.startswith("settings")
            or "appstore_chrome" in set(scene.classification_evidence or ())
        ):
            return
        try:
            from glassbox.ios.app_store import annotate_app_store_search_intents
            from glassbox.ios.settings_rows import annotate_settings_root_row_intents
            from glassbox.ios.springboard import annotate_springboard_icon_intents
        except Exception:
            return
        annotate_springboard_icon_intents(scene, viewport_size=viewport_size, platform=platform)
        annotate_settings_root_row_intents(
            scene,
            viewport_size=viewport_size,
            aliases=getattr(self._phone, "settings_root_label_aliases", None),
            fuzzy_aliases=bool(getattr(self._phone, "settings_root_fuzzy_aliases", False)),
        )
        annotate_app_store_search_intents(scene, viewport_size=viewport_size)

    def classify_platform_scene_now(
        self,
        scene: Scene,
        viewport_size: tuple[int, int] | None,
        prior: SceneClassificationPrior | None = None,
    ) -> SceneClassification | None:
        host = self._phone
        classifier = host.platform_scene_classifier
        if classifier is None:
            return None
        kwargs: dict[str, Any] = {"viewport_size": viewport_size}
        if host.strict_settings_detail_enabled:
            kwargs["strict_settings_detail"] = True
        if prior is not None:
            kwargs["prior"] = prior
        return classifier.classify(scene, **kwargs)

    def apply_profile(self, scene: Scene, frame_img=None) -> None:
        host = self._phone
        if host.profile is None:
            return
        match = host.profile.match_vc_detail(scene)
        scene.current_vc = None if match.ambiguous else match.vc_name
        if frame_img is not None:
            from glassbox.cognition.whitebox import apply_whitebox
            scene.whitebox_evaluated = True
            apply_whitebox(scene, frame_img, host.profile)

    def should_wait_stable(self, stable: bool | None) -> bool:
        host = self._phone
        context = self._context
        if stable is not None:
            return stable
        policy = host.stability_policy
        if policy is None or not policy.enabled:
            return False
        return not policy.after_action_only or context.needs_stable_frame

    def should_fresh_snapshot(self, fresh: bool | None) -> bool:
        context = self._context
        if fresh is not None:
            return bool(fresh)
        if context.fresh_source_reopened_after_action:
            return False
        return context.needs_stable_frame and self.source_supports_fresh_snapshot()

    def source_supports_fresh_snapshot(self) -> bool:
        return callable(getattr(self._phone.source, "fresh_snapshot", None))

    def source_snapshot(self, *, fresh: bool) -> Frame | None:
        host = self._phone
        if fresh:
            fresh_snapshot = getattr(host.source, "fresh_snapshot", None)
            if callable(fresh_snapshot):
                frame = fresh_snapshot()
                self._context.fresh_source_reopened_after_action = True
                return frame
            host.reopen_source_for_fresh_capture()
        return host.source.snapshot()

    def capture_source_frame(self, *, stable: bool | None, fresh: bool | None) -> Frame | None:
        host = self._phone
        context = self._context
        fresh_source = self.should_fresh_snapshot(fresh)
        if self.should_wait_stable(stable):
            from glassbox.perception.stable import wait_stable_result
            policy = host.stability_policy
            assert policy is not None
            result = wait_stable_result(
                host.source,
                timeout=policy.timeout,
                diff_threshold=policy.diff_threshold,
                consecutive=policy.consecutive,
                poll_interval=policy.poll_interval,
                initial_frame=self.source_snapshot(fresh=True) if fresh_source else None,
            )
            context.last_observation_mode = "stable"
            context.last_stable_frame = True
            context.last_stability_score = result.stability_score
            context.last_stability_policy = {
                "timeout": policy.timeout,
                "diff_threshold": policy.diff_threshold,
                "consecutive": policy.consecutive,
                "poll_interval": policy.poll_interval,
            }
            return result.frame
        context.last_observation_mode = "raw"
        context.last_stable_frame = None
        context.last_stability_score = None
        context.last_stability_policy = None
        return self.source_snapshot(fresh=fresh_source)

    def clear_snapshot_state(self) -> None:
        context = self._context
        context.last_frame = None
        context.last_scene = None
        context.last_scene_coordinate_space = None
        context.implicit_coordinate_space_error = None

    def apply_letterbox_crop(self, raw: Frame) -> Frame:
        from glassbox.perception.source import Frame as _Frame

        host = self._phone
        if host.crop is None:
            return raw
        if raw.shape != host.crop.frame_size:
            from glassbox.perception.letterbox import LetterboxCrop
            host.crop = LetterboxCrop.auto_detect(raw.img, phone_size=host.crop.phone_size)
            logger.info(
                "letterbox crop refreshed after source resolution changed: "
                f"frame={host.crop.frame_size} bbox={host.crop.crop_bbox}"
            )
        elif host.auto_refresh_letterbox_crop:
            self.refresh_letterbox_crop_bbox(raw)
        return _Frame(
            img=host.crop.crop(raw.img),
            ts=raw.ts,
            context=raw.context.with_crop(
                source_shape=raw.shape,
                crop_bbox=host.crop.crop_bbox,
                projection="cropped_px",
                name="device",
            ),
        )

    def commit_snapshot_frame(self, raw: Frame, *, previous_scene_space: str | None) -> Frame:
        context = self._context
        context.last_frame = raw
        current_space = raw.context.coordinate_space
        if previous_scene_space is not None and previous_scene_space != current_space:
            context.implicit_coordinate_space_error = (previous_scene_space, current_space)
        else:
            context.implicit_coordinate_space_error = None
        context.last_scene = None
        context.last_scene_coordinate_space = None
        return raw

    def snapshot(
        self,
        *,
        stable: bool | None = None,
        scope: str | None = None,
        fresh: bool | None = None,
    ) -> Frame | None:
        host = self._phone
        context = self._context
        frame_scope = host.normalize_observation_scope(scope or host.default_observation_scope)
        previous_scene_space = context.last_scene_coordinate_space if context.last_scene is not None else None
        raw = self.capture_source_frame(stable=stable, fresh=fresh)
        if raw is None:
            self.clear_snapshot_state()
            if host.recorder is not None:
                host.recorder.snapshot(None)
            return None
        raw = self.apply_letterbox_crop(raw)
        if frame_scope == "app":
            raw = self.apply_app_viewport(raw)
        raw = self.commit_snapshot_frame(raw, previous_scene_space=previous_scene_space)
        if host.recorder is not None:
            host.recorder.snapshot(context.last_frame)
        return context.last_frame

    def refresh_letterbox_crop_bbox(self, raw: Frame) -> None:
        host = self._phone
        context = self._context
        if host.crop is None:
            return
        try:
            from glassbox.perception.letterbox import LetterboxCrop
            detected = LetterboxCrop.auto_detect(raw.img, phone_size=host.crop.phone_size)
        except Exception:
            return
        tol = _LETTERBOX_BBOX_TOLERANCE_PX
        if _bbox_within_tolerance(detected.crop_bbox, host.crop.crop_bbox, tol):
            context.pending_crop_bbox = None
            context.pending_crop_count = 0
            return
        if _bbox_within_tolerance(detected.crop_bbox, context.pending_crop_bbox, tol):
            context.pending_crop_count += 1
        else:
            context.pending_crop_count = 1
        context.pending_crop_bbox = detected.crop_bbox
        if context.pending_crop_count < host.letterbox_refresh_consecutive:
            return
        host.crop = detected
        context.pending_crop_bbox = None
        context.pending_crop_count = 0
        logger.info(
            "letterbox crop refreshed after source bbox changed: "
            f"frame={host.crop.frame_size} bbox={host.crop.crop_bbox}"
        )

    def apply_app_viewport(self, frame: Frame) -> Frame:
        from glassbox.perception.source import Frame as _Frame

        host = self._phone
        viewport = host.app_viewport
        if self.should_detect_app_viewport(frame):
            detected = detect_iphone_compat_viewport(frame.img)
            if detected is not None:
                detected = replace(detected, parent_coordinate_space=frame.context.coordinate_space)
                if viewport is None or (
                    viewport.source == "detected" and detected_viewport_needs_update(viewport, detected)
                ):
                    viewport = detected
                    host.app_viewport = detected
            elif viewport is not None and viewport.source == "detected":
                host.app_viewport = None
                viewport = None
        if viewport is None:
            return frame
        return _Frame(
            img=viewport.crop(frame.img),
            ts=frame.ts,
            context=frame.context.with_crop(
                source_shape=frame.shape,
                crop_bbox=viewport.bbox,
                projection=viewport.coordinate_space,
                name=viewport.name,
            ),
        )

    def should_detect_app_viewport(self, frame: Frame) -> bool:
        host = self._phone
        if host.app_viewport_mode == "device":
            return False
        if frame.context.coordinate_space not in {"cropped_px", "frame_px"}:
            return False
        model = str(getattr(getattr(host, "device_geometry", None), "model", "") or "").lower().replace("-", "_")
        if model and not model.startswith("ipad"):
            return False
        return host.app_viewport_mode in {"auto", "iphone_compat"}

    def invalidate_app_viewport(self) -> None:
        host = self._phone
        if host.app_viewport is not None and host.app_viewport.source == "detected":
            host.app_viewport = None

    def invalidate_perceive_cache(self) -> None:
        context = self._context
        context.cache_frame = None
        context.cache_scene = None
        context.last_scene = None
        context.last_scene_coordinate_space = None
        context.implicit_coordinate_space_error = None

    def perceive(
        self,
        *,
        stable: bool | None = None,
        scope: str | None = None,
        fresh: bool | None = None,
    ) -> Scene:
        from glassbox.perception.stable import frame_diff_ratio

        host = self._phone
        context = self._context
        frame_scope = host.normalize_observation_scope(scope or host.default_observation_scope)
        vote_cfg = host.ocr_temporal_voting_config
        if (
            vote_cfg.enabled
            and vote_cfg.frames > 1
            and context.ocr_temporal_voting_opt_in
            and stable is None
            and fresh is None
            and not context.suppress_ocr_temporal_voting
        ):
            return self.perceive_voted(
                n=vote_cfg.frames,
                text_normalizer=None,
                scope=frame_scope,
                pos_tol=vote_cfg.pos_tol,
                min_presence=vote_cfg.min_presence,
                sample_spacing_ms=vote_cfg.sample_spacing_ms,
            )
        frame = self.snapshot(stable=stable, scope=frame_scope, fresh=fresh)
        observation_mode = context.last_observation_mode
        stable_frame = context.last_stable_frame

        if (
            host.perceive_cache_diff > 0
            and context.cache_frame is not None
            and context.cache_scene is not None
            and context.cache_scope == frame_scope
            and context.cache_frame.img.shape == frame.img.shape
            and frame_diff_ratio(context.cache_frame.img, frame.img) < host.perceive_cache_diff
        ):
            scene = context.cache_scene.model_copy(
                update={
                    "frame_id": int(frame.ts * 1000),
                    "timestamp": frame.ts,
                    "source_frame_ids": [int(frame.ts * 1000)],
                    "source_timestamps": [frame.ts],
                    "observation_mode": observation_mode,
                    "stable_frame": stable_frame,
                    "viewport_size": (int(frame.img.shape[1]), int(frame.img.shape[0])),
                },
                deep=True,
            )
            self.apply_scene_classifiers(scene, frame.img)
            host.perceive_cache_stats["hits"] += 1
            self.observe_memory(scene, frame.img)
            self.set_last_scene(scene, frame)
            context.cache_scene = scene.model_copy(deep=True)
            if host.recorder is not None:
                host.recorder.scene(scene)
            context.needs_stable_frame = False
            return scene

        elements = self.recognize_elements(frame)
        scene = Scene(
            frame_id=int(frame.ts * 1000),
            timestamp=frame.ts,
            elements=elements,
            source_frame_ids=[int(frame.ts * 1000)],
            source_timestamps=[frame.ts],
            observation_mode=observation_mode,
            stable_frame=stable_frame,
            viewport_size=(int(frame.img.shape[1]), int(frame.img.shape[0])),
        )
        if host.typer is not None:
            host.typer.upgrade(scene, frame_img=frame.img)
        self.apply_profile(scene, frame.img)
        self.apply_scene_classifiers(scene, frame.img)
        self.maybe_detect_icons(scene, frame.img)
        self.maybe_segment_layout(scene, frame.img)
        self.maybe_apply_voice_control_overlay(scene, frame.img)
        host.perceive_cache_stats["misses"] += 1
        self.observe_memory(scene, frame.img)
        context.cache_frame = frame
        context.cache_scene = scene.model_copy(deep=True)
        context.cache_scope = frame_scope
        self.set_last_scene(scene, frame)
        if host.recorder is not None:
            host.recorder.scene(scene)
        context.needs_stable_frame = False
        return scene

    def recognize_elements(self, frame: Frame) -> list[UIElement]:
        elements = self.run_ocr(frame)
        return self.bound_ocr_elements(elements)

    def run_ocr(self, frame: Frame) -> list[UIElement]:
        host = self._phone
        self._context.last_ocr_timeout_hit = False

        def _recognize() -> list[UIElement]:
            if getattr(host.ocr, "contract", None) == "TextRegionOCR":
                if host.ocr_tiling_config.enabled:
                    return ocr_results_to_elements(self.recognize_tiled_regions(frame))
                return ocr_results_to_elements(host.ocr.recognize(frame))
            return ocr_results_to_elements(host.ocr.recognize(frame.img))

        if host.ocr_timeout <= 0:
            return _recognize()

        result: list[list[UIElement]] = []
        error: list[BaseException] = []

        def _worker() -> None:
            try:
                result.append(_recognize())
            except BaseException as exc:
                error.append(exc)

        worker = threading.Thread(target=_worker, name="glassbox-ocr", daemon=True)
        worker.start()
        worker.join(host.ocr_timeout)
        if worker.is_alive():
            logger.warning(
                "OCR recognize() exceeded {}s watchdog; treating frame as empty "
                "(scene will classify unknown → recovery)", host.ocr_timeout,
            )
            self._context.last_ocr_timeout_hit = True
            return []
        if error:
            raise error[0]
        return result[0] if result else []

    def recognize_tiled_regions(self, frame: Frame):
        host = self._phone
        cfg = host.ocr_tiling_config
        from glassbox.cognition.ocr_tiling import merge_text_regions, tile_boxes

        regions = []
        if cfg.include_full_frame:
            regions.extend(host.ocr.recognize(frame))
        for roi in tile_boxes(
            int(frame.img.shape[1]),
            int(frame.img.shape[0]),
            rows=cfg.rows,
            cols=cfg.cols,
            overlap=cfg.overlap,
        ):
            try:
                regions.extend(host.ocr.recognize(frame, roi=roi, native_roi=False))
            except TypeError:
                regions.extend(host.ocr.recognize(frame, roi=roi))
        return merge_text_regions(regions, iou_threshold=cfg.nms_iou)

    def bound_ocr_elements(self, elements: list[UIElement]) -> list[UIElement]:
        host = self._phone
        cap = host.max_ocr_elements
        if cap and len(elements) > cap:
            logger.warning(
                "OCR returned {} elements (> cap {}); clipping — likely a "
                "live-camera/noise frame", len(elements), cap,
            )
            elements = elements[:cap]
        max_chars = host.max_ocr_text_chars
        if max_chars:
            for element in elements:
                if element.text is not None and len(element.text) > max_chars:
                    element.text = element.text[:max_chars]
        return elements

    def maybe_detect_icons(self, scene: Scene, frame_img) -> None:
        host = self._phone
        if (
            not host.detect_icons_in_perceive_enabled
            and not host.ui_layout_segmentation_enabled
        ) or frame_img is None:
            return
        try:
            from glassbox.cognition.icon_detect import detect_icons

            text_boxes = tuple(
                (element.box.x, element.box.y, element.box.w, element.box.h)
                for element in scene.elements
                if getattr(element, "text", None)
            )
            regions = detect_icons(frame_img, text_boxes=text_boxes)
        except Exception:
            return
        if not regions:
            return
        next_id = max(
            (element.element_id for element in scene.elements if element.element_id is not None),
            default=-1,
        ) + 1
        for region in regions:
            x, y, w, h = region.box
            scene.elements.append(
                UIElement(
                    type="image",
                    box=Box(x=int(x), y=int(y), w=int(w), h=int(h)),
                    text=None,
                    confidence=0.3,
                    element_id=next_id,
                )
            )
            next_id += 1

    def maybe_segment_layout(self, scene: Scene, frame_img) -> None:
        host = self._phone
        if not host.ui_layout_segmentation_enabled:
            return
        try:
            from glassbox.cognition.layout_segment import segment_layout

            viewport_size = scene.viewport_size
            if viewport_size is None and frame_img is not None:
                viewport_size = (int(frame_img.shape[1]), int(frame_img.shape[0]))
            segment_layout(scene, viewport_size=viewport_size)
        except Exception as exc:
            logger.warning(f"layout segmentation failed: {exc}")

    def maybe_apply_voice_control_overlay(self, scene: Scene, frame_img) -> None:
        """A11Y-VC-1 (flag-gated, default off): parse Voice Control Item-Names
        badges from the finished element set and write matched
        ``vc:item-name:<slug>`` ids into ``WhiteboxHint.accessibility_id``.

        Names only — Item Numbers/Grid are frame-local action anchors and are
        deliberately never written into UTG identity. ``frame_img`` is required:
        without the dark-badge pixel gate, ordinary row text would be
        misparsed as badges. Runs after icon/layout stages (the element set is
        final) and before memory observation + the perceive-cache write, so
        hints reach memory, cached scenes, consumers, and recorded artifacts.
        """
        host = self._phone
        if not host.voice_control_overlay_hints_enabled or frame_img is None:
            return
        try:
            from glassbox.cognition.voice_control_overlay import (
                apply_voice_control_overlay_hints,
                parse_voice_control_overlay,
            )

            markers = parse_voice_control_overlay(
                scene.elements, mode="item_names", frame_img=frame_img
            )
            if markers:
                apply_voice_control_overlay_hints(scene, markers, include_names=True)
        except Exception as exc:
            logger.warning(f"voice-control overlay hints failed: {exc}")

    def perceive_voted(
        self,
        n: int = 3,
        *,
        text_normalizer=None,
        scope: str | None = None,
        pos_tol: int | None = None,
        min_presence: int | None = None,
        sample_spacing_ms: int | None = None,
    ) -> Scene:
        host = self._phone
        context = self._context
        if n <= 1:
            previous = context.suppress_ocr_temporal_voting
            context.suppress_ocr_temporal_voting = True
            try:
                return self.perceive(scope=scope)
            finally:
                context.suppress_ocr_temporal_voting = previous
        frame_scope = host.normalize_observation_scope(scope or host.default_observation_scope)
        from glassbox.cognition.ocr_vote import vote_scenes

        vote_cfg = host.ocr_temporal_voting_config
        pos_tol = vote_cfg.pos_tol if pos_tol is None else max(1, int(pos_tol))
        min_presence = vote_cfg.min_presence if min_presence is None else max(1, int(min_presence))
        sample_spacing_ms = (
            vote_cfg.sample_spacing_ms
            if sample_spacing_ms is None
            else max(0, int(sample_spacing_ms))
        )
        scenes: list[Scene] = []
        last_frame = None
        source_frame_ids: list[int] = []
        source_timestamps: list[float] = []
        source_frame_hashes: list[str] = []
        ocr_timeout_samples: list[int] = []
        started = time.monotonic()
        stopped_by_outer_timeout = False
        for sample_index in range(n):
            if sample_index > 0 and sample_spacing_ms > 0:
                time.sleep(sample_spacing_ms / 1000.0)
            if sample_index > 0 and vote_cfg.outer_timeout > 0 and time.monotonic() - started > vote_cfg.outer_timeout:
                stopped_by_outer_timeout = True
                break
            frame = self.snapshot(scope=frame_scope)
            last_frame = frame
            frame_id = int(frame.ts * 1000)
            source_frame_ids.append(frame_id)
            source_timestamps.append(frame.ts)
            try:
                source_frame_hashes.append(_frame_image_hash(frame))
            except Exception:
                source_frame_hashes.append("")
            elements = self.recognize_elements(frame)
            if context.last_ocr_timeout_hit:
                ocr_timeout_samples.append(sample_index)
            scene = Scene(
                frame_id=frame_id,
                timestamp=frame.ts,
                elements=elements,
                source_frame_ids=[frame_id],
                source_timestamps=[frame.ts],
                observation_mode=context.last_observation_mode,
                stable_frame=context.last_stable_frame,
                viewport_size=(int(frame.img.shape[1]), int(frame.img.shape[0])),
            )
            if host.typer is not None:
                host.typer.upgrade(scene, frame_img=frame.img)
            scenes.append(scene)
        source_frame_hashes_present = {item for item in source_frame_hashes if item}
        distinct_frames = len(source_frame_hashes_present)
        duplicate_frames = max(0, len(source_frame_hashes) - distinct_frames)
        usable_samples = len(scenes) - len(ocr_timeout_samples)
        degrade_reason: str | None = None
        if len(scenes) < 2:
            degrade_reason = "insufficient_samples"
        elif usable_samples < 2:
            degrade_reason = "ocr_timeouts"
        elif distinct_frames < 2:
            degrade_reason = "duplicate_frames" if source_frame_hashes else "frame_hash_unavailable"
        if degrade_reason is None:
            scene = vote_scenes(
                scenes,
                pos_tol=pos_tol,
                min_presence=min_presence,
                text_normalizer=text_normalizer,
            )
        elif scenes:
            scene = scenes[-1].model_copy(deep=True)
        else:
            scene = Scene(frame_id=0, timestamp=time.monotonic(), elements=[])
        metadata = {
            **scene.ocr_vote_metadata,
            "enabled": True,
            "samples_requested": int(n),
            "samples_used": len(scenes),
            "distinct_frames": distinct_frames,
            "duplicate_frames": duplicate_frames,
            "sample_spacing_ms": int(sample_spacing_ms),
            "outer_timeout": float(vote_cfg.outer_timeout),
            "outer_timeout_hit": stopped_by_outer_timeout,
            "timeouts": len(ocr_timeout_samples),
            "ocr_timeout_samples": ocr_timeout_samples,
            "degrade_reason": degrade_reason or scene.ocr_vote_metadata.get("degrade_reason"),
        }
        if vote_cfg.keep_raw_samples:
            metadata["source_frame_hashes"] = source_frame_hashes
            metadata["raw_samples"] = [
                [
                    {
                        "text": element.text,
                        "type": element.type,
                        "box": element.box.model_dump(mode="json"),
                        "confidence": element.confidence,
                    }
                    for element in sample.elements
                ]
                for sample in scenes
            ]
        scene = scene.model_copy(update={"ocr_vote_metadata": metadata})
        if last_frame is not None:
            scene = scene.model_copy(
                update={
                    "frame_id": int(last_frame.ts * 1000),
                    "timestamp": last_frame.ts,
                    "source_frame_ids": source_frame_ids,
                    "source_timestamps": source_timestamps,
                    "observation_mode": (
                        "voted"
                        if degrade_reason is None and scene.ocr_vote_metadata.get("degrade_reason") is None
                        else "voted_degraded"
                    ),
                    "stable_frame": any(item.stable_frame is True for item in scenes),
                    "viewport_size": (
                        int(last_frame.img.shape[1]),
                        int(last_frame.img.shape[0]),
                    ),
                },
                deep=True,
            )
        frame_img = last_frame.img if last_frame is not None else None
        self.apply_profile(scene, frame_img)
        self.apply_scene_classifiers(scene, frame_img)
        self.maybe_detect_icons(scene, frame_img)
        self.maybe_segment_layout(scene, frame_img)
        self.maybe_apply_voice_control_overlay(scene, frame_img)
        context.cache_frame = None
        context.cache_scene = None
        context.cache_scope = frame_scope
        if frame_img is not None:
            self.observe_memory(scene, frame_img)
        self.set_last_scene(scene, last_frame)
        if host.recorder is not None:
            host.recorder.scene(scene)
        context.needs_stable_frame = False
        return scene


__all__ = ["Perceptor"]
