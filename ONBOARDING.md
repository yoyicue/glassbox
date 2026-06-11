# Onboarding: from parts to your first run

This is a linear runbook for a brand-new operator: assemble the rig, configure
the iPhone, install glassbox, and confirm everything works with a read-only
walkthrough of the iOS Settings app. Plan on about half an hour once you have
the parts.

The [README](README.md) is the reference (architecture, backends, design
boundaries); this guide is the step-by-step path and links back to it instead of
repeating it.

> **Goal:** end on a green `diagnose` and a passing
> `run_full --quick` against Settings — proof the whole
> perception → action → verification pipeline works on your hardware.

---

## 1. Bill of materials

| Item | Notes |
| --- | --- |
| **iPhone** | iPhone 17 Pro Max is the calibrated reference. Other models work for the geometry layer but the PicoKVM pointer mapping needs re-calibration — see [Device support and calibration](README.md#device-support-and-calibration). |
| **Luckfox PicoKVM** | The capture + USB-HID gadget that sits between phone and Mac. |
| **USB-C Digital AV Multiport Adapter** | One adapter carries HDMI out, a USB-A host port for HID, and USB-C power-in. |
| **HDMI cable** | Adapter HDMI → PicoKVM capture input. |
| **USB-A ↔ USB-C cable** | PicoKVM HID gadget → adapter USB-A port. |
| **USB-C power adapter (charger)** | Into the adapter's USB-C power-in. Required — it powers the iPhone *and* the PicoKVM. |
| **A Mac** | The controller host (macOS is the primary platform). |

## 2. Wire it up

Follow the diagram and bullets in
[README → Hardware setup](README.md#hardware-setup). In short:

1. iPhone USB-C → USB-C Digital AV Multiport Adapter.
2. Adapter **HDMI** → HDMI cable → PicoKVM capture input.
3. PicoKVM HID gadget → USB-A ↔ USB-C cable → adapter **USB-A** port.
4. Charger → adapter **USB-C power-in**.

**Confirm video:** open the PicoKVM web UI in a browser (see step 4) and check
the iPhone screen is visible there before going further. No video here means
nothing downstream will work.

## 3. Configure the iPhone

Set the five built-in iOS toggles in
[README → iOS prerequisites](README.md#ios-prerequisites-controlled-iphone).
Quick checklist:

- [ ] AssistiveTouch — **On**
- [ ] AssistiveTouch tracking speed — **Slowest** (slider fully left)
- [ ] AssistiveTouch tracking sensitivity — **Highest** (slider fully right)
- [ ] Auto-Lock — **Never**
- [ ] Full Keyboard Access — **On**

Nothing is installed on the phone; these are all stock Settings entries.

## 4. Find the PicoKVM

- Default address is `http://picokvm.local`. If mDNS is flaky on your network,
  use the device's IP instead.
- Open it in a browser and confirm the web UI loads and shows the iPhone screen.
- Note the auth mode. The default is `nopassword`. If your unit requires a login,
  you will set `GLASSBOX_PICOKVM_AUTH_MODE=password` plus
  `GLASSBOX_PICOKVM_USERNAME` / `GLASSBOX_PICOKVM_PASSWORD` in the next step.

## 5. Install glassbox

```bash
uv sync --extra dev
uv run python -c "import glassbox"
```

Create a local `.env` from the template and fill in your endpoint:

```bash
cp .env.example .env
```

Set at least:

```bash
GLASSBOX_PICOKVM=1
GLASSBOX_PICOKVM_BASE_URL=http://picokvm.local   # or http://<picokvm-ip>
# Only if your PicoKVM requires a login:
# GLASSBOX_PICOKVM_AUTH_MODE=password
# GLASSBOX_PICOKVM_USERNAME=...
# GLASSBOX_PICOKVM_PASSWORD=...
# If your phone is not an iPhone 17 Pro Max:
# GLASSBOX_PHONE_MODEL=iphone_16_pro_max
```

You can also export these inline instead of using `.env`.

## 6. First run

Work up from "can I see a frame" to "can I drive Settings".

```bash
# a) Eyeball the live video.
uv run glassbox-show-screen

# b) Readiness preflight: RPC reachable + one decoded frame.
uv run python -m skills.regression.ios_settings.diagnose --json

# c) Fast read-only Settings walkthrough, then verify the report.
uv run python -m skills.regression.ios_settings.run_full --quick
```

> **VLM note:** unlike plain `open_phone()` runs (OCR-only and free by
> default), the `run_full` harness defaults **VLM on** for live cold-start
> runs (`skills/regression/ios_settings/config.py` sets
> `GLASSBOX_ENABLE_VLM=1`) — its SpringBoard icon-grounding fallback needs it.
> Without a VLM API key in `.env` (e.g. `MOONSHOT_API_KEY`, see
> `.env.example`) a first cold-start run can die with `Missing API key`.
> Either put the key in `.env`, or run OCR-only with
> `GLASSBOX_ENABLE_VLM=0` (deterministic-path misses then go unrecovered).

`diagnose` prints a readiness report. Key fields when something is wrong:

| `code` / error | Meaning | First thing to check |
| --- | --- | --- |
| `PicoKVM effector not selected` | `GLASSBOX_PICOKVM` is unset | `export GLASSBOX_PICOKVM=1` |
| `picokvm_unreachable` | RPC could not reach the PicoKVM | `GLASSBOX_PICOKVM_BASE_URL`, network, PicoKVM powered |
| `picokvm_no_video` | PicoKVM reachable but no HDMI signal | HDMI cable, adapter power, phone awake |
| `frame source unavailable` / `frame decode failed` | Video stream did not open/decode | Open `<base_url>/video/stream` in a player; check the URL |

Drop `--quick` for the full exhaustive Settings audit once the quick run passes.

## 7. Read the results

- The walkthrough report defaults to `/tmp/ios-settings-full.json`; the
  `diagnose` preflight is written next to it as
  `/tmp/ios-settings-full.diagnose.json`. Override with `--report`.
- A per-run memory store and artifacts land under
  `/tmp/ios-settings-full.artifacts/<run_id>/`.
- A passing verification prints `OK`. Verification failures are printed as
  `ERROR: ...` lines describing what the report was missing.

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `diagnose` NOT READY, effector "not selected" | `GLASSBOX_PICOKVM` unset | `export GLASSBOX_PICOKVM=1` |
| `diagnose` `picokvm_unreachable` | Wrong address / PicoKVM off / network | Fix `GLASSBOX_PICOKVM_BASE_URL`; open the web UI |
| `diagnose` `picokvm_no_video`; `show-screen` black | HDMI not captured | Reseat HDMI; confirm video in the PicoKVM web UI; wake the phone |
| Frame "did not open" / decode failed | Stream URL / codec / network | Open `<base_url>/video/stream` in VLC; verify the base URL |
| Pointer never moves; taps do nothing | AssistiveTouch off | Enable AssistiveTouch / external pointer |
| Taps land in the wrong place | Tracking sliders not set, or wrong phone model | Set tracking speed slowest + sensitivity highest; set `GLASSBOX_PHONE_MODEL`; re-calibrate (step 9) |
| Home / Back / App Switcher do nothing | Full Keyboard Access off | Enable Full Keyboard Access |
| Screen sleeps mid-run | Auto-Lock not Never | Set Auto-Lock to Never |
| `run_full` stops early or verify fails | Full exhaustive run on a flaky rig | Use `--quick`; read the `ERROR:` lines in the report |

## 9. Using a different iPhone

The geometry table covers the iPhone 15/16/17 families via `GLASSBOX_PHONE_MODEL`,
but the PicoKVM pointer mapping was calibrated only on iPhone 17 Pro Max. On a
different phone the pointer will land off-target until you re-measure the linear
fit and gesture anchors and export new `GLASSBOX_PICOKVM_*` values. See
[Device support and calibration](README.md#device-support-and-calibration).

## 10. Next steps

- **Author mode:** drive the device from Python with the stable `glassbox.ai`
  facade (`open_phone`). Start from
  [`skills/regression/ios_settings/ai_native_example.py`](skills/regression/ios_settings/ai_native_example.py)
  and [`docs/design/public_api.md`](docs/design/public_api.md).
- **Full audit:** run `run_full` without `--quick`.
- **Remote agents:** the stdio MCP server `glassbox-mcp-server`, and the
  long-lived `glassbox-ai-session`.
- **Understand the internals:** [README → Architecture](README.md#architecture).
