# iPad mini Migration (target device: iPhone → iPad mini)

Status: design note; not implemented. Captures the architectural changes needed
to drive an **iPad mini 7 (A17 Pro, USB-C, iPadOS)** as the controlled device
instead of an iPhone, over the same out-of-band PicoKVM USB-HID rig.

## Why consider it

On iPhone (iOS) we exhausted the precise-scroll / touch problem and hit hard
platform walls (all on-device verified):

- HID **digitizer / touchpad / Magic-Trackpad** input is ignored by iOS — only
  Generic-Desktop **mouse** works. No native touch, no two-finger scroll.
- Mouse **wheel** under AssistiveTouch (which iPhone *requires* for any pointer)
  is severely intermittent (~5–7%) and not revivable from the PicoKVM side
  (USB re-enumeration at 1 s / 12 s / full reboot all fail to reset it).
- So iPhone scrolling is stuck with the imprecise **swipe-drag fling**
  (Settings drill-down coverage varies 9–15 / 17 from overshoot).

iPadOS removes these walls: **native pointer (no AssistiveTouch), reliable mouse
wheel, two-finger trackpad scroll/gestures, and keyboard-driven system
navigation** (⌘H / ⌘Space / ⌘Tab). iPad mini 7 is USB-C, so the same USB-HID
gadget plugs in directly. See the memory notes
`ios-ignores-usb-hid-digitizer`, `picokvm-scroll-overshoot-hardware-limit`,
`iphone-vs-ipad-mouse-keyboard-support`.

## What does NOT change (architecture is ready)

glassbox is built on pluggable seams (Platform / Effector / FrameSource / OCR /
VLM / CrawlPolicy / Verifier), so most of this is "add an iPad profile", not a
core rewrite.

- Core observe→decide→act→verify loop and all seams.
- The **HID gadget descriptors** (keyboard + absolute mouse + relative mouse +
  report-ID-2 wheel). iPad's native pointer consumes the same Generic-Desktop
  mouse reports; the wheel mechanism is already correct (commit `32d21e4`).
- PicoKVM hardware/firmware; the kvm_app RPCs (`absMouseReport`, `wheelReport`,
  `keyboardReport`, …).

## What must change (highest → lowest impact)

### 1. iPad Settings is a split view — the largest app-level rework
iPad "Settings" is a **two-pane split view** (left sidebar list + right detail),
not the iPhone single-column drill-down. The current
`skills/regression/ios_settings` model (enter a root row → record → return to
root) does not apply. If Settings remains a target workload, it needs an
iPad-specific navigation/crawl policy and scene classification that understands
sidebar + detail panes. This is the biggest piece of work.

### 2. Device profile / coordinate calibration (foundational, must-do)
- iPad mini 7 panel is **3:2 (1488×2266)**. Mirrored over the USB-C Digital AV
  adapter into a 16:9 HDMI frame it **pillarboxes** (side bars), unlike the
  iPhone's centered portrait strip — the letterbox-crop bbox is different.
- The PicoKVM absolute-pointer calibration is iPhone-specific:
  `abs_to_phone_scale_*`, `abs_origin_offset_*`, `abs_logical_max`, and
  `device_geometry.phone_size` (currently 1320×2868). **Re-calibrate the
  frame→0…32767 linear fit for the iPad** and add an iPad geometry.
- Deliverable: an iPad device config/profile (geometry + crop + calibration).

### 3. Drop AssistiveTouch; route system actions through native pointer + keyboard
iPad has a **native pointer and does not need AssistiveTouch**. Remove the
AssistiveTouch-only paths and replace with iPad-native equivalents:
- Home / app switcher / Spotlight via **keyboard ⌘ combos** (⌘H, ⌘Tab, ⌘Space),
  back via Meta+[ (unchanged).
- Affected code: PicoKVM capabilities (`home_strategy=assistive_touch` →
  keyboard/native), `Phone.home`/`recents`/`control_center`, the back_gesture
  blind-chevron fallback, and the springboard recovery — much of which exists
  only because of iPhone+AssistiveTouch and simplifies on iPad.

### 4. Enable the wheel for precise scrolling (direct win)
Set PicoKVM `wheel_enabled=True` for the iPad profile. The hover + report-ID-2
mechanism is already implemented (`32d21e4`) and the wheel is reliable on iPad's
native pointer, so the iPhone scroll-overshoot variance disappears. (A digitizer
two-finger scroll could be added later, but the wheel suffices.)

### 5. Platform seam: an iPadOS variant
Add/parameterize an iPadOS platform (`IOSPlatform` → iPadOS): scene
classification for split views / sidebars / different status-bar & chrome,
`safe_actions`, and app policies tuned to iPad layouts.

### 6. Wiring verification (small)
Confirm the USB-C Digital AV Multiport Adapter delivers **both** HDMI (video to
PicoKVM) **and** USB-HID passthrough (to the iPad) the same way it does for the
iPhone. Likely yes (same adapter), but verify once on hardware.

## Summary

Core stays; add an **iPad profile**: (a) re-calibrate coordinates/crop, (b) drop
AssistiveTouch and use keyboard system-nav, (c) enable the wheel. These make the
basic interactions (tap / scroll / navigate) more reliable than on iPhone. The
one large effort is **iPad split-view Settings navigation** plus the iPadOS
scene classifier; everything in §1 of the iPhone walkthrough assumes a
single-column layout that iPad does not use.
