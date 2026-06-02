#!/bin/bash
# iOS Settings L1 rig A/B matrix.
#
# Runs B/A interleaved on one PicoKVM-backed iOS device session. A-arm non-zero exits
# are expected baseline data, so every run is harvested into RESULTS.

set -u

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  cat <<'EOF'
Usage: skills/regression/ios_settings/ab_matrix.sh

Environment overrides:
  IPAD_SETTINGS_AB_DIR      Output directory (default: artifacts/ios_settings/ab)
  IPAD_SETTINGS_AB_ROUNDS   Rounds per arm per locale (default: 3)
  IPAD_SETTINGS_AB_LOCALES  Space-separated lang:REGION list (default: en:HK zh-Hans:CN)
  IPAD_SETTINGS_AB_DEVICES  Space-separated phone_model:platform[:acceptance] list
                            (default: current IPAD_SETTINGS_PHONE_MODEL/IPAD_SETTINGS_PLATFORM,
                             falling back to ipad_mini_7:ipados:state_machine).
                            acceptance: state_machine or none. Example:
                            "ipad_mini_7:ipados:state_machine iphone_17_pro_max:ios:none"
  IPAD_SETTINGS_AB_ARMS     Space-separated arms (default: baseline ocr_minheight0 ocr_tiling ui_layout ocr_tiling_ui_layout)
  IPAD_SETTINGS_AB_EXTRA_ARGS Extra run_full args appended after --language/--region (for example: --quick)
  IPAD_SETTINGS_AB_STAMP    Session stamp for filenames (default: current time)

Built-in arms:
  baseline              Current default Settings rig.
  ocr_minheight0        GLASSBOX_OCR_MINIMUM_TEXT_HEIGHT=0.
  ocr_tiling            minimumTextHeight=0 + GLASSBOX_OCR_TILING_ENABLED=1.
  ui_layout             GLASSBOX_UI_LAYOUT_SEGMENTATION_ENABLED=1.
  ocr_tiling_ui_layout  OCR tiling + UI layout segmentation.
  root_projection_off   Legacy A-arm: root projection off, state-machine acceptance disabled.
EOF
  exit 0
fi
if [ "$#" -ne 0 ]; then
  echo "ERROR: unexpected arguments: $*"
  echo "Run with --help for usage."
  exit 2
fi

cd /Users/biu/glassbox || exit 2

AB=${IPAD_SETTINGS_AB_DIR:-artifacts/ios_settings/ab}
LOCK="$AB/.matrix.lock"
ROUNDS=${IPAD_SETTINGS_AB_ROUNDS:-3}
LOCALES=${IPAD_SETTINGS_AB_LOCALES:-"en:HK zh-Hans:CN"}
DEFAULT_DEVICE_MODEL=${IPAD_SETTINGS_PHONE_MODEL:-ipad_mini_7}
DEFAULT_DEVICE_PLATFORM=${IPAD_SETTINGS_PLATFORM:-ipados}
DEFAULT_DEVICE_ACCEPTANCE=state_machine
case "$(printf '%s:%s' "$DEFAULT_DEVICE_MODEL" "$DEFAULT_DEVICE_PLATFORM" | tr '[:upper:]' '[:lower:]')" in
  ipad*:*)
    DEFAULT_DEVICE_ACCEPTANCE=state_machine
    ;;
  *:ipados)
    DEFAULT_DEVICE_ACCEPTANCE=state_machine
    ;;
  *)
    DEFAULT_DEVICE_ACCEPTANCE=none
    ;;
esac
DEVICES=${IPAD_SETTINGS_AB_DEVICES:-"${DEFAULT_DEVICE_MODEL}:${DEFAULT_DEVICE_PLATFORM}:${DEFAULT_DEVICE_ACCEPTANCE}"}
ARMS=${IPAD_SETTINGS_AB_ARMS:-"baseline ocr_minheight0 ocr_tiling ui_layout ocr_tiling_ui_layout"}
EXTRA_ARGS=${IPAD_SETTINGS_AB_EXTRA_ARGS:-}
STAMP=${IPAD_SETTINGS_AB_STAMP:-$(date +%Y%m%d_%H%M%S)}
RESULTS="$AB/results_${STAMP}.jsonl"

cleanup() {
  rm -rf "$LOCK" 2>/dev/null
}

on_signal() {
  cleanup
  exit 130
}

mkdir -p "$AB"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "ERROR: matrix lock held: $LOCK"
  echo "       holder: $(cat "$LOCK/owner" 2>/dev/null || echo unknown)"
  echo "       if that PID is dead, remove $LOCK and retry."
  exit 3
fi
printf 'pid=%s host=%s stamp=%s\n' "$$" "$(hostname)" "$STAMP" > "$LOCK/owner"
trap cleanup EXIT
trap on_signal INT TERM

: > "$RESULTS"

run_one() {
  local arm="$1" round="$2" lang="$3" region="$4" phone_model="$5" platform="$6" acceptance="$7" device_tag="$8"
  local tag="${arm}_${device_tag}_${lang}${region}_r${round}_${STAMP}"
  local report="$AB/${tag}.json"
  local log="$AB/${tag}.run.log"
  local -a env_args
  local -a make_args
  env_args=()
  make_args=(
    IPAD_SETTINGS_REPORT="$report"
    IPAD_SETTINGS_PHONE_MODEL="$phone_model"
    IPAD_SETTINGS_PLATFORM="$platform"
    IPAD_SETTINGS_EXTRA_ARGS="--language $lang --region $region $EXTRA_ARGS"
  )
  case "$acceptance" in
    state_machine)
      ;;
    none)
      make_args+=(IPAD_SETTINGS_ACCEPTANCE=)
      ;;
    *)
      echo "ERROR: unknown IPAD_SETTINGS_AB device acceptance: $acceptance" > "$log"
      local rc=2
      uv run python skills/regression/ios_settings/ab_extract.py \
        "$arm" "$round" "$lang-$region" "$rc" "$report" "$phone_model" "$platform" >> "$RESULTS" \
        || printf '{"arm":"%s","round":%s,"locale":"%s-%s","rc":%s,"device":"%s","platform":"%s","crash":true,"report":"%s","extraction_error":"ab_extract_crashed"}\n' \
          "$arm" "$round" "$lang" "$region" "$rc" "$phone_model" "$platform" "$report" >> "$RESULTS"
      return
      ;;
  esac

  case "$arm" in
    baseline|B)
      ;;
    ocr_minheight0)
      env_args+=(GLASSBOX_OCR_MINIMUM_TEXT_HEIGHT=0)
      ;;
    ocr_tiling)
      env_args+=(GLASSBOX_OCR_MINIMUM_TEXT_HEIGHT=0 GLASSBOX_OCR_TILING_ENABLED=1)
      ;;
    ui_layout)
      env_args+=(GLASSBOX_UI_LAYOUT_SEGMENTATION_ENABLED=1)
      ;;
    ocr_tiling_ui_layout)
      env_args+=(
        GLASSBOX_OCR_MINIMUM_TEXT_HEIGHT=0
        GLASSBOX_OCR_TILING_ENABLED=1
        GLASSBOX_UI_LAYOUT_SEGMENTATION_ENABLED=1
      )
      ;;
    root_projection_off|A)
      make_args+=(IPAD_SETTINGS_ROOT_PROJECTION=0 IPAD_SETTINGS_ACCEPTANCE=)
      ;;
    *)
      echo "ERROR: unknown IPAD_SETTINGS_AB arm: $arm" > "$log"
      local rc=2
      uv run python skills/regression/ios_settings/ab_extract.py \
        "$arm" "$round" "$lang-$region" "$rc" "$report" "$phone_model" "$platform" >> "$RESULTS" \
        || printf '{"arm":"%s","round":%s,"locale":"%s-%s","rc":%s,"device":"%s","platform":"%s","crash":true,"report":"%s","extraction_error":"ab_extract_crashed"}\n' \
          "$arm" "$round" "$lang" "$region" "$rc" "$phone_model" "$platform" "$report" >> "$RESULTS"
      return
      ;;
  esac

  if [ "${#env_args[@]}" -eq 0 ]; then
    make "${make_args[@]}" ipad-settings-state-machine > "$log" 2>&1
  else
    env "${env_args[@]}" make "${make_args[@]}" ipad-settings-state-machine > "$log" 2>&1
  fi

  local rc=$?
  uv run python skills/regression/ios_settings/ab_extract.py \
    "$arm" "$round" "$lang-$region" "$rc" "$report" "$phone_model" "$platform" >> "$RESULTS" \
    || printf '{"arm":"%s","round":%s,"locale":"%s-%s","rc":%s,"device":"%s","platform":"%s","crash":true,"report":"%s","extraction_error":"ab_extract_crashed"}\n' \
      "$arm" "$round" "$lang" "$region" "$rc" "$phone_model" "$platform" "$report" >> "$RESULTS"
}

for loc in $LOCALES; do
  lang="${loc%%:*}"
  region="${loc##*:}"
  for device_spec in $DEVICES; do
    IFS=':' read -r phone_model platform acceptance <<EOF_DEVICE
$device_spec
EOF_DEVICE
    if [ -z "$phone_model" ] || [ -z "$platform" ]; then
      echo "ERROR: invalid IPAD_SETTINGS_AB_DEVICES entry: $device_spec"
      exit 2
    fi
    if [ -z "${acceptance:-}" ]; then
      case "$(printf '%s:%s' "$phone_model" "$platform" | tr '[:upper:]' '[:lower:]')" in
        ipad*:*) acceptance=state_machine ;;
        *:ipados) acceptance=state_machine ;;
        *) acceptance=none ;;
      esac
    fi
    device_tag=$(printf '%s_%s' "$phone_model" "$platform" | tr -c '[:alnum:]_' '_')
    for round in $(seq 1 "$ROUNDS"); do
      for arm in $ARMS; do
        run_one "$arm" "$round" "$lang" "$region" "$phone_model" "$platform" "$acceptance" "$device_tag"
      done
    done
  done
done

expected=$(( ROUNDS * $(echo "$ARMS" | wc -w) * $(echo "$LOCALES" | wc -w) * $(echo "$DEVICES" | wc -w) ))
got=$(grep -c '"arm"' "$RESULTS")
echo "MATRIX_DONE $STAMP - rows: $got / expected: $expected"
if [ "$got" -ne "$expected" ]; then
  echo "ERROR: row count mismatch - a run produced no JSONL row"
  exit 4
fi
