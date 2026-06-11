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
| canonical primitives | task_completion / scroll_success_rate | **0.9 / 0.957**（2026-06-11 入库,见台账） | `canonical_primitives_baseline.json` |
| zh cell | （不存在） | 需物理切语言 | — |

---

## 1. Flag × Cell 矩阵（按预期收益排）

| # | Flag / 改动 | 测试格子 | 看的数字 | 机制对位 | 估算机时 |
|---|---|---|---|---|---|
| 1 | （进行中）badge 减除（`VOICE_CONTROL_OVERLAY_HINTS` 行为扩展） | a11y cell | completion vs 0.0 | 徽章伪影毒化行匹配/验证器 → 感知层减除 | ~90min |
| 2 | `GLASSBOX_DETECT_ICONS_IN_PERCEIVE` × 后端（**双维 A/B**） | Clock cell | completion vs 0.8；每轮耗时 vs ~14min | launch_app 靠主屏找图标，纯 OCR 读不到图标本体。**后端是独立维度**：`GLASSBOX_ICON_DETECTOR=omniparser` vs `classical` 各跑一臂。**✅已测 06-10：假设获正向支持但不充分**——omniparser（主屏 31 区域 vs classical 17）把 Clock completion **0.8→1.0**（修第 4 轮错启动），代价 **+~17% 每轮耗时**；但 n=5 仅一轮之差 + omniparser 是 AGPL 不能进核心默认 → **committed 默认仍 classical**，omniparser 作本地 opt-in 正向信号待更大 n 复验（详见台账）。omniparser 臂两个环境坑：worktree 需手拷插件、`uv sync` 会剪掉 AGPL runtime 需重装。`ui_layout`（默认开）隐式按当前后端每帧跑检测 → omniparser 臂 = 全程每帧 YOLO，+17% 是这笔账 | ~75min ×2 臂 |
| 3 | `GLASSBOX_AI_SCROLL_PREFER_WHEEL` | 设置地板 | scroll_success_rate vs 0.077 | iPad 滚轮精确已验证（picokvm_ipad_wheel）。**✅已测 06-10：保持关**——flag 唯一读取点 `ai.py:655`，设置地板走侧栏 drag 够不到；受控同页 facade 滚动 wheel==swipe（详见台账） | ~45min |
| 4 | `GLASSBOX_ENABLE_VLM`（P1 升级） | Clock cell 失败轮 / a11y cell | completion、unknown_rate | VLM 只在低置信/找不到目标时触发——必须在会失败的格子测 | ~90min+计费 |
| 5 | `GLASSBOX_WHITEBOX_HINT_SELECTION` | a11y cell（badge 减除之后） | completion、误点 | producer 已写 vc id，让选择器消费它。**✅已测 06-10：保持关**——离线 replay 1198 场景：爬虫不调 `expect_text`（flag 唯一读取点）+ 带 badge 行 100% 已有干净 OCR 文本 → 净恢复 0/25193，反带 4.2% slug 噪声（详见台账） | ~90min→离线 |
| 6 | `GLASSBOX_RECOVER_THEN_RETRY` | 任一会失败的格子 | completion | 机器探针已证恢复触发；问"恢复后重试能否救完成率" | ~60min |
| 7 | `GLASSBOX_STRICT_TARGET_MATCHING` / `REVERIFY_FRESH_FRAME` | unknown_rate>0 的格子 | unknown_rate、误点 | 鲁棒性类，干净格子无感 | ~60min |
| 8 | `GLASSBOX_MEMORY_LOCATE_PRIORS` / `page_id_route_enabled` | 重复跑同任务 | 步数/耗时 | ⚠️ 前置：效率指标（duration/steps）尚未进 metrics，先补 | 前置离线 |
| 9 | canonical primitives 冻结 floor | canonical | （建立基线本身） | **✅已完成 2026-06-11**：floor 入库 `canonical_primitives_baseline.json`（completion 0.9, n=5, iPad）+ 夜间 iPad lane 阻断比对接线（详见台账） | ~30min |
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

### 2026-06-11 矩阵 #11 attempt 4（诚实仪器,#75/#76/#77/#81/#82 全栈）—— 判定:该格子当前不可测 #11
- 类型：flag A/B（**Arm A 完成,Arm B 取消**——格子被上游主导）
- 格子：Clock cell;n=5;classical 钉死;命令同 attempt 1-3 + 全修复栈
- A 臂（ui_layout 默认开）：completion **0.2**(1/5)、action 0.53、unknown 0.24(诚实弃权)、~78s/任务动作
- 关键分解：4/4 失败轮全死于 `open_app`(verifier 诚实 veto:落点 `settings/All Devices`);**round 4 一旦启动成功,4 tab 9 动作全程无瑕疵**。该格子的瓶颈被精确定位为 launch 彩票(widget 优先主屏无 Clock 图标),ui_layout 管 in-app 感知,在 launch 吃掉 80% 的格子上数学上不可测
- 判定：**#11 在 Clock cell 不可测,Arm B 取消不烧机时**;前置依赖改为"launch 稳定化"。下一个已定位 bug:**spotlight 兜底点错结果行**(搜 Clock 时 Settings/Screen Time 深链排在 app 之上;sweep surface 门 #82 已堵 OCR 误点,幸存路径只剩 spotlight 行选择)——候选修法:`open_app_via_spotlight` 结果行验证(要求 app 行,拒绝 settings 深链行),harness 已有 `require_visible_spotlight_result` 机制可挂
- 产物：armA JSON 本地(不入库——非 floor 候选);本日衍生核心修复 #75/#76/#77/#81/#82 全部已合并
- 注意事项：与 06-10 floor(0.8)不可比——当时主屏布局不同(图标可见);Clock cell 的 completion 强依赖主屏布局,floor 语义需注明布局前提;矩阵 #2 的 omniparser(0.8→1.0 修 launch)仍是已知杠杆(AGPL opt-in)

### 2026-06-11 矩阵 #11 ui_layout 反向 A/B —— 两次中止,产出一个核心发现（未采数据）
- 类型：flag A/B（**中止**,数据无效但发现入账）
- 格子：Clock cell;计划 n=5 ×2 臂;命令同 Clock 基线 + `GLASSBOX_UI_LAYOUT_SEGMENTATION_ENABLED=0`（B 臂）
- 尝试 1（无效）：worktree AGPL 陷阱原样复现——`.env` 软链带入 `GLASSBOX_ICON_DETECTOR=omniparser` 但 worktree venv 无 ultralytics/torch → 5/5 轮 open_app 直接异常。教训:worktree 跑 rig 必须显式钉 `GLASSBOX_ICON_DETECTOR=classical`(对 #11 本来就该如此——问题问的是 committed 默认配置)
- 尝试 2（无效,但**核心发现**）：completion 0.2(4 failed/1 succeeded)——失败轮的 `open_app(Clock)` 是**假阳性**:设备停在 Settings→Screen Time(此前 canonical back 轮遗留),`foreground_app_matches` 凭裸 token 'Clock' 匹配到 **Screen Time 应用使用列表里的 "Clock" 字样**,以 0.9 置信度宣布启动成功(matched_evidence=['Clock']),实际从未离开 Settings;随后 `expect_text('Alarms')` 如实超时。与 App-Store-误分类同一缺陷类(裸 token 身份判定)
- 判定：**不采纳本次数据;#11 推迟**到 foreground_app verifier 修复后(候选修法与 settings-detail 假阳性同款:veto+anchor+abstain——settings chrome 可见时拒绝裸 token 前台断言)。修复本身是测量仪器变更,必须先于 A/B 合入
- 产物：无 fixture;失败 ledger 在本地 artifacts(worktree 已清理,arm A JSON 未入库)
- 注意事项：尝试 2 的 launch 成功轮(round 4,完整走完 4 tab)证明流程本身可行;设备已复位 verified-Home;同日 #76 的 facade home 修复在复位时再次真机验证(`ios_home_screen_visible` succeeded)

### 2026-06-11 canonical primitives 首个 committed floor（矩阵 #9,fixture 入库）
- 类型：基线建立
- 格子：canonical primitives;n=5(20 task-rounds);命令:`GLASSBOX_PHONE_MODEL=ipad_mini_7 GLASSBOX_LANGUAGE=en GLASSBOX_REGION=HK GLASSBOX_PICOKVM_ROBUST_CAPTURE=1 GLASSBOX_PICOKVM_OPEN_RETRY_ATTEMPTS=8 uv run python -m skills.regression.computer_use_success_rate run-canonical-primitives --rounds 5 --out … --artifact-root …`
- A 臂（基线）：无（首个 floor）
- B 臂（候选）：task_completion **0.9**(go_home 5/5、launch_app 5/5、back 5/5、scroll 3/5+1 unknown+1 failed)、action_success 1.0、unknown 0.0、precondition 失败 **0/20**(全部 verified-Home origin,`ios_home_screen_visible`)、scroll_success 0.957(45/47 wheel)、strategy_switches 7、~27.2s/任务轮
- 判定：入库 floor + 夜间 iPad lane 阻断比对接线(config-identity 匹配;iPhone lane 无 floor 不比对)
- 产物：`skills/regression/fixtures/canonical_primitives_baseline.json`(final_state 按公共 fixture 惯例清空 visible_texts/elements——go_home 终态是机主主屏 widget 内容);守卫 `skills/smoke/test_canonical_floor.py`
- 注意事项：**本次跑通耗费 6 次尝试,前 5 次暴露并修复了 3 个真实缺陷**(#75 流打开无重试、#76 facade home 走未验证捷径 → 20/20 precondition_failed、#77 终态词表 iPad 不存在 → 动作全部语义验证成功但任务 0/5);scroll 的 1 failed + 1 unknown 是诚实方差保留可见;expected_state_coverage=0(canonical 原语不带 expect=,P2 由机器探针守护,非此格子职责)


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

### 2026-06-10 矩阵 #3 滚轮 flag A/B（`GLASSBOX_AI_SCROLL_PREFER_WHEEL`，代码 `efcf262`）
- 类型：flag A/B（scroll 机制：swipe-fling vs 精确 wheel）
- 格子：iPad Settings 详情页（`Privacy & Security`，同页受控）；每臂 n=1，单步 `scroll("down", max_steps=1)` ×6；
  命令：`set -a; source .env; set +a; GLASSBOX_PHONE_MODEL=ipad_mini_7 GLASSBOX_STABLE_DIFF_THRESHOLD=0.09 [GLASSBOX_AI_SCROLL_PREFER_WHEEL=1] uv run python scroll_probe.py {swipe|wheel}`
- **先决发现（脱靶）**：地板里的 `scroll_success_rate=0.077` 来自 Settings 基准，其滚动走的是
  `skills/regression/ios_settings/scrolling.py:68` 的**侧栏 drag**（iPad 恒走 `_settings_sidebar_drag`），
  根本不经过 `AIPhone.scroll`。该 flag 全仓**唯一读取点**是 `glassbox/ai.py:655`
  （`ai_scroll_prefer_wheel_enabled and supports("scroll_wheel")`）——所以它**够不到那块地板**。
  早先 `/tmp/ab3-wheel` 的 Settings 跑（completion 1.0、scroll 0.0 vs 0.077）只是 drag 路径的run-to-run抖动，非 flag 效应。
- A 臂（swipe，默认）：同页 6/6 每步推进，distinct=49
- B 臂（wheel，flag on）：`wheel_flag=True supports_wheel=True`（**确实进了 wheel 分支，非 no-op**）；同页 6/6，distinct=49
- 判定：**保持关**。在 flag 真正经过的 facade 路径上，受控同页单步滚动 **wheel == swipe（49==49，皆 6/6）**，
  无可测增益；且它够不到 Settings 地板。无翻默认理由。
- 产物：`/tmp/probe-swipe.out`、`/tmp/probe-wheel.out`（探针输出，未入库）；探针脚本 `scroll_probe.py`（未提交）
- 注意事项：n=1/臂、单页、`max_steps=1`——wheel 的理论优势（无 fling 过冲、精确定位）只会在
  多步/滚到目标任务上显现，本探针没压到那一面。先决条件踩了两个坑：① **在 git worktree 里跑丢了 `.env`**
  → 默认落 `NoOpEffector`（`supports` 全 False）。注意 `open_phone()` 其实**会**加载 `.env`
  （`import glassbox`→`_load_dotenv_once`，`glassbox/__init__.py:46`），但找的是**相对包根**的 `.env`；
  `.env` 是 gitignored，worktree 没有它 → 静默跳过。修法：从主仓跑 / 拷 `.env` 进 worktree / 显式 `source .env`；
  ② 真机视频有 ~6% h264 噪声 → 默认 `stable_diff_threshold=0.005` 会 `wait_stable` 超时，探针调到 0.09。

### 2026-06-10 矩阵 #5 白盒选择 flag A/B（`GLASSBOX_WHITEBOX_HINT_SELECTION`，离线 replay，代码 `efcf262`）
- 类型：flag A/B（白盒 id 选择 vs OCR 文本选择）；**离线 scene replay**（不占机器）
- 格子：a11y cell loop-2 录制场景；样本 = 5 轮 × ~240 场景 = **1198 场景 / 25193 个带 vc id 的元素观测**；
  命令：`set -a; source .env; set +a; uv run python wb5_replay.py`（replay `find_text` vs `find_by_whitebox_hint`）
- **先决发现①（脱靶，离线可证）**：该 flag 全仓**唯一读取点**是 `glassbox/element_selector.py:179`
  （`expect_text` 内的 OCR-失败-兜底）。而 a11y cell 的 ios_settings 爬虫走 **tap_xy**（`navigation.py`），
  **从不调用 `expect_text`**（全仓只有 `ai_native_example.py:16` 用 `expect_visible`，非本 cell）。
  → 在 cell 当前路径上该 flag **根本不被询问**（与 #3 同型的"机器对格子不可见"陷阱）。
- A 臂（flag off，OCR 文本选择）：25193 次选择里 OCR 正确命中 23701
- B 臂（flag on，白盒兜底）：**whitebox 独有恢复 = 0**；whitebox 返回**错行 = 30**（风险）；
  → **flag 净恢复 = 0/25193 = 0.00%**
- **数据发现②（即便接上 expect_text 也无收益）**：带 badge 的行 **100% 已有干净 OCR 文本**（empty=0），
  所以"OCR 失败才兜底"的 whitebox 分支**永无触发机会**；反而 producer 的 vc slug 自带 **4.2% OCR 噪声**
  （`accessibiity`/`accesssibility`）——白盒 id 并不比 OCR 文本更干净。
- 判定：**保持关**。矩阵原备注"id 又多又对，该让选择器消费"被数据**证伪**：id 是多（25193），
  但与已干净的 OCR 文本**冗余**且更**脏**（4.2% garble），消费它零收益 + 微风险。该 flag 的真正用武之地是
  **Tier-1 profiled app（有真 accessibility id 且无 OCR 文本）**，不是这种 OCR-over-HDMI、文本恒在的 a11y cell。
- 产物：`/tmp/wb5_replay.py`（replay 脚本，未提交）；输入 = `/tmp/glassbox-a11y2/runs/*/scenes`（loop-2 录制，本地未入库）
- 注意事项：`neither=1462` 是 `find_text` 对截断标签（`Analytics &`/`Access Within Apps`）的自匹配严格度，
  与本 flag 正交（whitebox 同样救不了）；本测离线确定性可复跑，比 n=1 真机探针更稳——故不再占机器单跑 #5。

### 2026-06-10 矩阵 #2 图标后端 A/B（`GLASSBOX_ICON_DETECTOR=omniparser` vs `classical`，代码 `efcf262`）
- 类型：flag A/B（图标检测后端，验证假设"打开图标检测器肯定有帮助"）
- 格子：ipados_clock_tabs；每臂 n=5；
  命令：`set -a; source .env; set +a; GLASSBOX_PHONE_MODEL=ipad_mini_7 GLASSBOX_ICON_DETECTOR=omniparser uv run python -m skills.regression.computer_use_success_rate run-clock-tabs --rounds 5 --out ... --artifact-root ...`
- A 臂（基线 classical，committed `89a3bed`）：completion **0.8**（第 4 轮 `open_app(Clock)` 落到 `settings/All Devices`，
  期望 "Sunrise" → **启动 grounding 错位/启错 App**），action 0.974，coverage 0.447，~14 min/轮
- B 臂（omniparser）：completion **1.0（5/5，修了那一轮错启动）**，action **1.0**，coverage 0.444，
  每轮 18.0/16.4/13.5/16.9/17.3 → 均 **~16.4 min/轮（+~17% 耗时）**
- **机制已核验**（同一主屏帧 `frm_000000`，强制后端对比）：omniparser **31** 个图标区域 vs classical **17** 个；
  `_get_model()->YOLO` 真加载（`~/.cache/glassbox/omniparser-icon-detect.pt`）；运行日志每轮 springboard regions=30-31
  → **B 臂确系 omniparser**（classical 只会给 ~17）。更密的图标候选 → Clock 图标消歧更稳 → 5/5 启动正确，机制自洽。
- 判定：**假设获正向支持但不充分；committed 默认仍 classical**。理由：① n=5、0.8→1.0 仅一轮之差，不能算稳赢；
  ② omniparser 是 **AGPL、git-ignored、不在默认 deps**——按 AGENTS.md"AGPL 不进 MIT 核心"，**再赢也不能翻默认后端**。
  → 作为**本地 opt-in** 有真实正向信号（这是该假设的首份正面证据），值得在更大 n 上复验后写进 reference（非 flip default）。
- 产物：`/tmp/ab2-omni/benchmark.json`（B 臂 benchmark，未入库）；A 臂 = committed `clock_tabs_baseline.json`
- 注意事项：**本机 `.env` 已 pin `GLASSBOX_ICON_DETECTOR=omniparser`**，故默认跑本就是 omniparser；classical 基线是显式 override 出来的——
  读这条对比时别把"本机默认"当 classical。`ui_layout`（默认开）令该后端每帧都跑，故 +17% 是"全程 YOLO"的账，非仅 launch。
  detect_icons_in_perceive 维度未单跑：ui_layout 默认开已隐式按当前后端每帧检测，再 `DETECT_ICONS_IN_PERCEIVE=1` 近乎冗余（省一臂机时）。
