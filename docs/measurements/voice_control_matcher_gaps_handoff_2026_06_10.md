# Handoff: Voice Control item-names matcher — 4 个待修 gap（含逐例复现）

> **给谁**：badge-to-target matcher（`glassbox/cognition/voice_control_overlay.py`）
> 的维护者。
> **为什么**：`WhiteboxHint.accessibility_id` 的稳定生产写入（a11y 文档
> `docs/design/glassbox_a11y_channels.md` rank-1 的终点）按既定纪律必须等
> badge→target 映射在更广样本上过关才能开。2026-06-10 的 v2 扩样
> （PR #58，44 标签/3 采样全过并入了 committed gate）同时钉出 **4 个当前
> matcher 修不过的失败**——本文是它们的工单：精确数据、一条命令复现、根因
> 诊断（其中 2 个已实验确认）、修复方向与验收标准。
> **快照**：main `4d10f9a`（2026-06-10）。行号会漂移，引用前回查源。

---

## 0. 一条命令复现

复现素材（场景 JSON + 帧 PNG + gap 清单）固化在本机
`artifacts/vc_matcher_gaps_20260610/`（帧含设备账户行，**不入 git**）：

```bash
# GAP 1-2（General 详情页采样）— 期望输出 0/2 全失败
uv run python -m skills.regression.voice_control_overlay_labeled_replay \
  --labels artifacts/vc_matcher_gaps_20260610/labels_GAPS_general.json \
  --scene  artifacts/vc_matcher_gaps_20260610/01_general_itemnames.scene.json \
  --frame  artifacts/vc_matcher_gaps_20260610/01_general_itemnames.png

# GAP 3-4（侧栏滚动到中段的采样）— 期望输出 0/2 全失败
uv run python -m skills.regression.voice_control_overlay_labeled_replay \
  --labels artifacts/vc_matcher_gaps_20260610/labels_GAPS_scrolled.json \
  --scene  artifacts/vc_matcher_gaps_20260610/02_general_sidebar_scrolled.scene.json \
  --frame  artifacts/vc_matcher_gaps_20260610/02_general_sidebar_scrolled.png
```

同目录还有当日完整草稿清单（`labels_general.json` / `labels_scrolled.json`，
含全部 36 对原始标注）和原始 replay 报告，方便回归全量。

---

## 1. 四个 gap（坐标 = cropped px，640×989 视口）

### GAP 1 — 1 字符 OCR 错字卡在 0.82 相似度线下（已定位到行）

| | |
|---|---|
| badge OCR 文本 | `ADOUt`（真名 About），center **(446,299)** |
| 目标行 | `About`，center **(337,327)** |
| 失败原因 | `target_missing` |
| 根因（确定） | `_name_text_matches`（`voice_control_overlay.py:346`）三连判定全 miss：compact 后 `adout` vs `about` 互不为子串、token 无交集、`SequenceMatcher.ratio()=0.80` **恰好低于 :360 的 0.82 下限**。5 字符标签上 1 个替换错字就会死。 |

### GAP 2 — 烂 badge × 长行名，三种桥全断（已定位到行）

| | |
|---|---|
| badge OCR 文本 | `AutOFiI`（真名 AutoFill & Passwords），center **(444,708)** |
| 目标行 | `AutoFill & Passwords`，center **(384,735)** |
| 失败原因 | `target_missing` |
| 根因（确定） | compact `autofii` vs `autofillpasswords`：子串 ✗、token 交集 ✗、ratio≈0.58 ✗。 |
| 修复线索 | 对目标**首 token** 匹配可桥：`autofii` vs `autofill` 的 ratio = **0.93**。`_label_tokens` 交集要求 token 全等，烂字 token 永远不等。 |

### GAP 3 — 文本全等却失败，仅在滚动位（根因已实验确认）

| | |
|---|---|
| badge OCR 文本 | `Wallpaper`，center **(129,478)** |
| 目标行 | `Wallpaper`，center **(99,450)** |
| 失败原因 | `target_missing`；几何达标（marker_below_gap≈11px ≤ max_y_delta=36，`:114`） |
| 对照 | **同一对在侧栏顶部位置通过**（committed `..._general_v2.json` 的 `sidebar_wallpaper` (131,848)→(101,820) ✓） |
| 根因（**已确认**） | 在滚动帧上对 scene 跑 `parse_voice_control_overlay(..., frame_img=...)`：**目标行本体 `Wallpaper@(99,450)` 自己被解析成了 item-name marker**——`_looks_like_overlay_badge` 的暗像素门（`:395-435`）在该帧上对行文本区域误放行（疑似下方 badge 与行框重叠拉低亮度）。被当成 marker 的元素随即被排除出目标候选（`:72` 的排除逻辑同款），于是"目标失踪"。 |

### GAP 4 — 同 GAP 3 机制（根因已实验确认）

| | |
|---|---|
| badge OCR 文本 | `Notifications）`（全角括号尾巴），center **(130,531)** |
| 目标行 | `Notifications`，center **(109,502)** |
| 失败原因 | `target_missing`；compact 后文本相等、几何达标 |
| 根因（**已确认**） | 同 GAP 3：`Notifications@(109,502)` 在该帧被解析为 marker。确认实验输出（两行都在 marker 列表里）：`[('Wallpaper',(99,450)), ('Wallpaper',(129,478)), ('Notifications',(109,502)), ('Notifications)',(130,531))]` |

---

## 2. 修复方向（建议，不绑定）

1. **GAP 3/4（优先，机制性）**：问题不在文本匹配在 marker/target 二分。方向：
   暗像素门对"已有同帧近邻 badge 的行文本"做互斥消歧（同 compact 文本的两个
   元素里，只把更暗/更小的那个当 badge）；或 target 候选池不排除
   "marker 但同时是某 badge 的最佳目标"的元素。修这条时注意别把真 badge 放进
   目标池（badge 映射到 badge 是 v1 设计里明确要防的）。
2. **GAP 1**：0.82 下限对短标签过严。方向：按标签长度调阈（≤6 字符放宽到
   ~0.78），或对 1 编辑距离的短词单独放行。**不要全局降阈**——风险见 §3。
3. **GAP 2**：`_name_text_matches` 增加"badge compact vs 目标首 token"的
   ratio 判定（本例 0.93）。

## 3. 修复时的红线

- **配错比配不上更糟**：accessibility_id 是长期身份，假身份证会污染记忆图。
  任何放宽都要跑全量证明没引入新的错配。
- **全量回归命令**：committed gate（44 标签）+ 本工单（4 标签）都要看：
  ```bash
  uv run pytest skills/smoke/test_voice_control_overlay_labeled_replay.py -q   # 44 全过
  # + §0 的两条命令 → 修完应 2/2 + 2/2
  ```
- v1 清单里的 `expect_mapped=false` 负例（`Dictate`、`Came Camera` 融合等）
  必须仍然**不**被映射。

## 4. 验收标准

1. §0 两条命令 4/4 通过。
2. 把 4 个 gap 标签加回 committed v2 清单（`expect_mapped=true` + 本文坐标），
   `make check` 绿（届时 48 标签全过）。
3. 之后才进入 producer 开关决策（`apply_voice_control_overlay_hints` 的
   `include_names`，`voice_control_overlay.py:112`）——那是单独一步，按
   a11y 文档的纪律走，不在本工单内。

## 5. 文件索引

- matcher 本体：`glassbox/cognition/voice_control_overlay.py`
  （`_name_text_matches:346`、0.82 下限 `:360`、`_item_name_target_score:298`、
  dx>180 门 `:315`、垂直间隙 `:325`、暗像素门 `:395-435`、marker 排除 `:72`）
- committed 清单：`skills/regression/fixtures/voice_control_overlay_itemnames_labels_{v1,general_v2,scrolled_v2}.json`
- 契约 smoke：`skills/smoke/test_voice_control_overlay_labeled_replay.py`
- replay harness：`skills/regression/voice_control_overlay_labeled_replay.py`
- 当日完整测量记录：`docs/measurements/voice_control_overlay_ipad_mini_2026_06_04.md`
  （2026-06-10 follow-up 一节）
- 复现素材（本机，不入 git）：`artifacts/vc_matcher_gaps_20260610/`
