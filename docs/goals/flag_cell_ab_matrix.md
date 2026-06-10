# Flag × Cell A/B 矩阵与测试报告台账

> **这是什么**：回答"哪些默认关的选项打开后，能在真机上高于地板值"的执行计划 +
> 每次真机 A/B 的标准化报告台账。与
> `docs/goals/computer_use_quality_rig_validation.md`（CUQ 战役的 flip-and-A/B
> runbook）互补：那边是逐 flag 的验证条件，这边是 **flag × cell 的配对矩阵**、
> 统一的报告格式、和滚动的结果记录。
>
> **快照纪律**：台账里的数字只来自 committed fixture / runbook 原文 / 当次
> benchmark JSON，每条带代码 sha。行号会漂移，引用前回查源。

---

## 0. 核心原则：饱和的地板上测不出任何东西

当前干净设置地板（`reliability_baseline.json`, `dd74fbb`）的头条三项是
**completion 1.0 / action 1.0 / root 1.0 —— 已饱和，不可能被打败**。在饱和格子
上 A/B 任何 flag 只能证明"没变差"，不能证明"更好"。

因此测试必须**配对**：flag 的机制 × 该机制所在失败路径的**不饱和格子**。
每次测一个数字；赢了翻默认/换地板（人工审核后提交），没赢把证据写进 flag 的
docstring 和本台账。

当前的不饱和格子（按洞的大小）：

| 格子 | 不饱和指标 | 现值 | fixture |
|---|---|---|---|
| a11y cell（overlay ON） | ~~task_completion 0.0~~ → **loop-2 后 1.0 已饱和**；剩 action_success 0.87 / unknown 0.11 | 见台账 loop-2 | `a11y_voice_control_cell_snapshot.json` |
| 设置地板 scroll | scroll_success_rate | 0.077 | `reliability_baseline.json` |
| Clock cell | task_completion / 每轮耗时 | 0.8 / ~14min（launch 占大头） | `clock_tabs_baseline.json` |
| L2 快照 | task_completion | 0.8 | `l2_settings_expected_state_snapshot.json` |
| canonical primitives | （无 committed floor） | 夜间只存档 | — |
| zh cell | （不存在） | 需物理切语言 | — |

---

## 1. Flag × Cell 矩阵（按预期收益排）

| # | Flag / 改动 | 测试格子 | 看的数字 | 机制对位 | 估算机时 |
|---|---|---|---|---|---|
| 1 | （进行中）badge 减除（`VOICE_CONTROL_OVERLAY_HINTS` 行为扩展） | a11y cell | completion vs 0.0 | 徽章伪影毒化行匹配/验证器 → 感知层减除 | ~90min |
| 2 | `GLASSBOX_DETECT_ICONS_IN_PERCEIVE` × 后端（**双维 A/B**） | Clock cell | completion vs 0.8；每轮耗时 vs ~14min | launch_app 靠主屏找图标，纯 OCR 读不到图标本体。**后端是独立维度**：`GLASSBOX_ICON_DETECTOR=omniparser` vs `classical` 各跑一臂——"omniparser 肯定有帮助"是待验证假设（正面：主屏全是图标；反面实测：设置场景 185 帧 0 图标产出 + 每帧 5-10× 延迟）。注意 omniparser 臂的两个环境坑：worktree 需手拷插件、`uv sync` 会剪掉 AGPL runtime 需重装。另：`ui_layout`（默认开）会隐式按当前后端每帧跑图标检测，omniparser 臂 = 全程每帧 YOLO，耗时数字要连这笔账一起读 | ~75min ×2 臂 |
| 3 | `GLASSBOX_AI_SCROLL_PREFER_WHEEL` | 设置地板 | scroll_success_rate vs 0.077 | iPad 滚轮精确已验证（picokvm_ipad_wheel） | ~45min |
| 4 | `GLASSBOX_ENABLE_VLM`（P1 升级） | Clock cell 失败轮 / a11y cell | completion、unknown_rate | VLM 只在低置信/找不到目标时触发——必须在会失败的格子测 | ~90min+计费 |
| 5 | `GLASSBOX_WHITEBOX_HINT_SELECTION` | a11y cell（badge 减除之后） | completion、误点 | producer 已写 vc id，让选择器消费它 | ~90min |
| 6 | `GLASSBOX_RECOVER_THEN_RETRY` | 任一会失败的格子 | completion | 机器探针已证恢复触发；问"恢复后重试能否救完成率" | ~60min |
| 7 | `GLASSBOX_STRICT_TARGET_MATCHING` / `REVERIFY_FRESH_FRAME` | unknown_rate>0 的格子 | unknown_rate、误点 | 鲁棒性类，干净格子无感 | ~60min |
| 8 | `GLASSBOX_MEMORY_LOCATE_PRIORS` / `page_id_route_enabled` | 重复跑同任务 | 步数/耗时 | ⚠️ 前置：效率指标（duration/steps）尚未进 metrics，先补 | 前置离线 |
| 9 | canonical primitives 冻结 floor | canonical | （建立基线本身） | 夜间已跑只差 committed floor + 比对接线 | ~30min |
| 10 | zh cell 建立 | 设置任务 zh-Hans/CN | （建立基线本身） | 需物理切设备语言（操作者在场） | ~60min+人 |
| 11 | **反向 A/B**：`UI_LAYOUT_SEGMENTATION_ENABLED=0` | Clock cell（或任一不饱和格子） | completion、每轮耗时 | **默认开但无任务级证据**：翻默认依据是 App Store n≈1 的 under-bar 小赢；且它隐式跑图标检测器（绕过 `DETECT_ICONS_IN_PERCEIVE` 的门，omniparser 机器上=每帧 YOLO）。默认开的 flag 同样要有数字，否则是反方向的信仰 | ~75min |

**红线**（沿用既有纪律）：VLM 计费且 opt-in；a11y cell 永不混入干净地板；
"覆盖率不许跌"对救场类指标是反的（守护用机器探针，不用棘轮）；任何翻默认都
要 `validate-floor-candidate` / `compare` + 人工审核后提交。

---

## 2. 每次测试的报告格式（追加到 §3 台账）

```markdown
### YYYY-MM-DD <标题>（代码 <sha>）
- 类型：flag A/B | 地板棘轮 | 基线建立 | 阻断门验证
- 格子：<cell>；n=<rounds>；命令：<一行可复现命令>
- A 臂（基线）：<来源 fixture/sha + 关键数字>
- B 臂（候选）：<关键数字>
- 判定：翻默认 / 保持关 / 换地板 / 入库快照 / 不采纳
- 产物：<benchmark JSON 位置；committed fixture 路径（如入库）>
- 注意事项：<诚实的 caveat：n、设备状态、中断、混杂因素>
```

---

## 3. 测试报告台账

### 2026-05-29 语义策略阶梯 A/B（代码见 runbook）
- 类型：flag A/B（`GLASSBOX_SEMANTIC_PLAN_OPS=back,scroll,tap`）
- 格子：canonical primitives；n=1；`make ab-semantic-plan ROUNDS=1`
- A 臂：flags-off — completion 0.0，action 0.50，scroll 0.70，unknown 0.50
- B 臂：ladder on — completion **0.5**，action 0.75，scroll 1.0，unknown 0.25，switches 0→4
- 判定：**翻默认**（`config.py` semantic_plan_ops → `back,scroll,tap`）
- 产物：记录于 `computer_use_quality_rig_validation.md` "DONE (2026-05-29)" 段
- 注意事项：n=1 × 4 个单动作原语；iPhone 平行 A/B 仅 0.25，不跨设备外推

### 2026-06-10 iPad 侧栏修复 + 诚实地板棘轮（`dd74fbb` → fixture `571e568` 提交）
- 类型：地板棘轮（核心修复后重跑）
- 格子：设置干净地板；n=5；`run-ios-settings --rounds 5 --drill-down --language en --region HK`
- A 臂：旧地板（`15d592c`，tap_xy 产）— completion 1.0 但 expected_state_coverage=0
- B 臂：修复后 — completion 1.0，**expected_state_coverage 0.978**，recoveries 2，scroll 样本 26
- 判定：**换地板**（`validate-floor-candidate` OK；语义验证路径首次可见）
- 产物：`skills/regression/fixtures/reliability_baseline.json`
- 注意事项：vlm/strategy=0 是诚实零（干净跑无事可救），由机器探针守护

### 2026-06-10 机器探针真机验证（`f1f22a7`/`4b0c110`）
- 类型：阻断门验证（故障注入 → 机器必须触发）
- 格子：machinery probe；n=3；`make machinery-probe-gate ROUNDS=3`
- 结果：每轮**确定性** strategy_switches=3 / recoveries=1 / vlm=1；rc=0
- 判定：**阻断式接入 nightly**（iPad 臂）
- 产物：nightly 步骤 + `run-machinery-probe`/`validate-machinery-probe`
- 注意事项：须显式 `GLASSBOX_SEMANTIC_PLAN_OPS=back,scroll,tap`（定时 nightly 默认空）

### 2026-06-10 Clock cell 基线（fixture `89a3bed` 提交）
- 类型：基线建立（第二 App cell）
- 格子：ipados_clock_tabs；n=5；`run-clock-tabs --rounds 5`
- 结果：completion **0.8**（第 4 轮 launch 落错应用，如实保留），action 0.974，
  expected_state_coverage 0.447；每轮 ~14min（launch 扫描占大头）
- 判定：**入库快照**（该 cell 的首版 floor）
- 产物：`skills/regression/fixtures/clock_tabs_baseline.json`
- 注意事项：launch_app 是该格子的弱原语 → 矩阵 #2 的测试对象

### 2026-06-10 verifier 对齐 F1（fixture `d45d22c` 提交）
- 类型：verifier 自校验（SPA-Bench 纪律）
- 样本：78（12 failed + 31 unknown + 15 小众 verifier + 20 随机 succeeded），盲标
- 结果：success 断言 P 0.943 / R 0.733 / **F1 0.825**；failure 断言 P 1.0 / R 0.364；
  `expected_state` 29/29，`scene_progressed` 0/29，`tap_target_effect` 被时钟走字骗 ×2
- 判定：**入库快照** + 修缮工单（tap_target_effect 排除时变内容）
- 产物：`skills/regression/fixtures/verifier_alignment_settings_v1.json`
- 注意事项：AI 盲标非人类盲标（出处已声明）；帧在本地不入库

### 2026-06-10 a11y cell 基线 = loop-1（fixture `dbe48a3` 提交，代码 `ac58ab6`）
- 类型：基线建立（a11y cell：overlay ON + producer 写 id）
- 格子：ios_settings_a11y_voice_control；n=5；`--evaluation-cell ios_settings_a11y_voice_control` + `GLASSBOX_VOICE_CONTROL_OVERLAY_HINTS_ENABLED=1`
- 结果：completion **0.0**，action 0.42，unknown 0.41，root 0.13；
  switches 21 / recoveries 7；producer 实证（351 场景带 vc id）
- 判定：**入库快照**（badge 感知改进必须打败的基线）
- 产物：`skills/regression/fixtures/a11y_voice_control_cell_snapshot.json`
- 注意事项：第 5 轮采集流卡死被操作者终止（--keep-going 聚合）；永不作地板候选

### 2026-06-10 badge 减除 = loop-2（代码 `94fa2fd`）
- 类型：改动 A/B（唯一差异：感知层减除徽章元素）
- 格子：a11y cell；n=5；与 loop-1 同命令
- A 臂：loop-1 快照（completion **0.0**，action 0.42，unknown 0.41，root 0.13，switches 21，recoveries 7）
- B 臂：completion **1.0（5/5）**，action 0.87，unknown 0.11，root 1.0，switches 1，recoveries 0，
  带 vc id 场景 351 → **1167**
- 判定：**入库快照**（替换 loop-1 为 cell 现状；loop-1 数字保留在 note/台账作历史基线）
- 产物：`skills/regression/fixtures/a11y_voice_control_cell_snapshot.json`（loop-2 版）
- 注意事项：recoveries 0 是诚实零（不再需要救场）；scroll_success_rate 仍 0；
  矩阵 #5（`WHITEBOX_HINT_SELECTION`）现在解锁——id 又多又对，该让选择器消费了
