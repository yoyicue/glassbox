# glassbox 评测分层设计（Evaluation Layers）

> **这是什么**：glassbox 自身评测体系的分层设计——每层回答什么问题、用什么指标、跑在哪、验收
> 标准、以及与现有产物（`reliability_baseline.json` / Tier A / `run_full` / `compare_benchmarks`）
> 的接线。外部领域依据见 `docs/reference/computer_use_evaluation_landscape.md`；本仓为什么"门禁
> 当评测"是病见 `docs/goals/computer_use_honest_gate_first.md`。
>
> **代码事实快照**：repo HEAD `5881a28`（2026-06-04）。**行号会漂移**——引用前请回查源；本文把
> 可断言的代码事实标了 file:line，把"已设计未建"明确区分于"已落地"。
>
> **核验**：本文的代码事实在 `5881a28` 上逐条核对过（`_metrics`、`_task_outcome`、
> `compare_benchmarks`、Makefile 目标、Tier A/B/C 设计、`navigation.py` 调用点）。

---

## 0. TL;DR — 4 层主干 + 1 条旁路

```
                  ▲ 保真度高 / 成本高 / 跑得稀
   ┌──────────────────────────────────────────────────────────┐
   │ L2  能力层 (on-rig)      execution-based outcome、n≥5、多cell │  ❌ 缺失（最大的洞）= "评测"
   ├──────────────────────────────────────────────────────────┤
   │ L3  门禁层 (floor+gate)  从 L2 冻结地板、守回归                │  ⚠️ 存在但错位 = "冻结地板+门禁"
   ├──────────────────────────────────────────────────────────┤
   │ L1  感知/组件层 (offline) 录制帧回放、grounding/场景/OCR       │  🟡 已设计未建 (Tier B)
   ├──────────────────────────────────────────────────────────┤
   │ L0  契约层 (offline)     verifier-golden 回放、schema、单元    │  ✅ 大体已有 (Tier A + smoke)
   └──────────────────────────────────────────────────────────┘
                  ▼ 成本低 / 确定性 / 每次 commit 都跑

   旁路：漂移模拟 (advisory，永不挡合并) — Tier C drift-sim + mode-3 UTG sim
```

**两个正交维度**：纵轴是**保真度×成本**（L0→L2 越来越真、越来越贵）；横切是**目的角色**——
L2=能力评测（eval）、L3=冻结地板+门禁（floor+gate）、L0/L1=门禁也会跑的廉价离线守卫。

**脊柱在 L2 和 L3 的分离**：现在本仓把 L3（门禁）当成了全部评测。把"它有多强"（L2）与
"有没有变差"（L3）分开，是整个设计的核心。

---

## 1. 设计原则（决定为什么是这个层数）

1. **L2 才是评测，L3 只是守回归。** 综述实证：动作 ACK / 硬规则会**漏报近一半**真实成功
   （AgentRewardBench rule-based recall 55.9%，见 reference 文档 §3）。所以 **L3 的地板必须从
   L2 的语义 outcome 派生，不能自己用 ACK 定义**。
2. **离线/真机这条线不模糊。** glassbox 绝大多数工作离线（`make check`），真机稀缺（一台 rig、
   n=1）。所以**确定性的东西全压到 L0/L1**（每 PR 跑），**只有 execution-based outcome 上真机**
   （L2，周期性）。
3. **漂移模拟永远是旁路。** mode-3 UTG sim 的 off-trajectory 墙（~17% 路由偏离即无后继帧，
   `utg_operable_sim.md §6`）决定它只能做图内回归评分。让它挡合并 = 又造一个假门禁。
4. **指标是多维的，不是单一成功率。** headline 用 `task_completion_rate`，但同时报告过程指标
   分布（coverage、recoveries、strategy_switches、scroll_success_rate），且**人类对照**单列。

---

## 2. 各层规格

每层给出：**问题 / 指标 / 环境·频率 / 验收 / 接线 / 现状**。接线行号为 `5881a28` 快照。

### L0 — 契约层（offline，每次 commit）

- **问题**：verifier / 插件 / schema 逻辑还对不对？（不碰真机、不碰感知）
- **指标**：golden case 通过率（确定性二元）；schema 校验。
- **环境·频率**：纯离线，确定性，每次 commit（`make check`）。
- **验收**：`make test` + `make regression-gate` + `make golden-audit` 全绿；新增/改动 verifier
  必须先 harvest 一组 golden case 再改逻辑（防止偷偷改判定）。
- **接线（现有）**：
  - **Tier A verifier-golden 回放**（`8fbd24f`，2026-06-01）：`skills/regression/golden_ingest.py`
    从 run ledger 把 verifier 输入/期望 harvest 进 `skills/golden/computer_use/*.json`；replay+floor
    守卫由 `skills/smoke/test_golden_ingest.py` 搭 `make test`。
  - `make golden-harvest`（手动重采）/ `make golden-audit`（在 `make check`，CI 无 `artifacts/` 时
    rc0 空转，`Makefile:53`）。
  - schema：`compare_benchmarks` 入口先跑 `validate_benchmark`（`computer_use_success_rate.py:1213`）；
    `regression-gate` 跑 `validate` + 门禁 smoke（`Makefile:38`）。
- **现状**：✅ **大体已有**。Tier A 已落地；smoke 套件覆盖大部分契约。

### L1 — 感知/组件层（offline，每次 commit 或 nightly）

- **问题**：感知在录制语料上回归了吗？grounding / 场景分类 / OCR 准不准？
- **指标**（组件级，非任务级）：
  - **grounding 准确率**：用 **point-in-box / 意图对齐**（点落入目标元素框算对），**不要** exact
    point-matching（综述 §3：几何接近≠意图正确）。
  - 场景分类一致性（`platform_scene_kind` / `semantic_scene_type` 对录制帧的容差比对）。
  - OCR 召回（小字、Cyrillic 同形——见现有 OCR 记录）。
- **环境·频率**：离线，录制帧回放，每 commit 或 nightly。
- **验收**：在冻结的录制语料上，各组件指标不低于地板；新语料经人工标注后并入。
- **接线（已设计·未建 = Tier B，`log_sim_replay_regression.md §5`）**：
  - `glassbox/perception/recording_source.py`（**NEW**）`RecordingFrameSource` —— 满足 `FrameSource`
    Protocol（`boundaries.py:58`），是唯一干净注入点（DI 到 `phone.source`，镜像 `static`）。
  - `glassbox/perception/replay_assert.py`（**NEW**）`SceneTolerance` + `compare_scenes`。
  - `skills/smoke/test_perception_replay.py`（**NEW**）。
  - 绑定 `GLASSBOX_REPLAY_DIR`（`config.py` 加在 `frame_dir` 旁，env_prefix 自动）。
- **现状**：🟡 **已设计未建**。注：grounding 的 point-in-box 真值标注是前置依赖（无 bbox truth
  时参照 SPA-Bench 人工对齐流程）。

### L2 — 能力层（on-rig，周期性，n≥5）★ 缺失的"评测"

- **问题**：**它到底有多强、哪里会坏？** 这是金标准评测。
- **评测方式**：**execution-based outcome**——核对是否真到达**目标语义状态**（目标 `page_id` /
  目标场景），而非动作 ACK。
- **指标**：
  - **headline = `task_completion_rate`**（outcome=='succeeded' 占比）。
  - **多采样**：每个任务 **n≥5**，报告 `task_completion_variance`（已实现，`_metrics:674`）；
    长期目标引入 **pass^k** 口径（综述 §4，τ-bench）。
  - **多 cell**：设备 × App × 语言（至少 iPad mini 7 × {Settings, 第二个 App} × {en, zh}）。
  - **人类对照基线**：同任务人工完成率，单列（综述 §4：WAA 19.5% vs 74.5%）。
  - **过程指标分布**：`expected_state_coverage` / `vlm_action_coverage` / `recoveries` /
    `strategy_switches` / `scroll_success_rate`（已实现，见 §4）。
- **环境·频率**：真机（PicoKVM rig），周期性（贵、稀），非每 PR。
- **验收**：
  - **关键架构前置**：被测任务的每步要带 `terminal_expected_state`（目标 page_id），让
    `_task_outcome`（`:622-624`）走 execution-based 分支，而**不是**回退到动作 ACK（`:625-633`）。
  - 任务经真机 n≥5 跑出 `task_completion_rate` + 方差 + 过程指标分布 + 人类对照。
  - 覆盖率指标**非零**（证明走的是 orchestrated 路径，不是 `tap_xy` 爬虫）。
- **接线**：
  - 测量入口 `skills/regression/ios_settings/run_full.py`；指标聚合 `aggregate_run_dir`
    （`computer_use_success_rate.py:801`）。
  - **承重改动**：Settings root 行入口必须给每个 action 标注目标 `page_id` expected-state；2026-06-06
    承重接线已落地：`tap_element` 在 semantic `tap` 开启时进入 strategy ladder，element-aware
    `target_tap` 仍复用 row hitbox / landing retry / actuation profile；正常 row tap 和 search root result
    都带 `page_id` expected-state，并支持中英/HK alias 的 `page_id.any_of`。`tap_xy` 仅保留为无
    `tap_element` 的 legacy test/fallback。Settings crawler 的这些 tap 禁用 semantic-plan 全局 recovery：
    单步失败应回到 crawler 决策，而不是跳到 Home 后污染 L2 轨迹。
  - 多采样：`run_full --rounds N`；测量起点用 `glassbox/action/recovery.py:98` 的
    `prepare_navigation_measurement_origin`（导出于 `glassbox.action`）保证每条轨迹是验证过的
    Home→X；已被 `skills/regression/canonical_primitives.py:106` 复用。
- **现状**：🟡 **承重代码已落地，单 App n≥5 已跑出 outcome；L2 验收仍未完成**。
  Settings row/search-result tap 已带 action-level expected-state 并走 semantic tap ladder。2026-06-06
  iPad mini 7 真机 snapshot（code `d9695ae`，命令：
  `GLASSBOX_PHONE_MODEL=ipad_mini_7 ... run-ios-settings --rounds 5 --drill-down --language en --region HK`，
  artifact `/tmp/glassbox-l2-rank2-full-20260606-164702/benchmark.json`）结果：
  `task_completion_rate=0.8`、`task_completion_variance=0.16`、
  `expected_state_coverage=0.976`、`root_pages_coverage=0.983`、`recoveries=0`；
  5 个样本中 4 成功、1 失败，失败样本缺 `隐私与安全性`。这条去敏 snapshot 已提交为
  `skills/regression/fixtures/l2_settings_expected_state_snapshot.json`，并由 smoke 断言其 schema、
  n≥5、`expected_state_coverage>0` 和 coverage-regression gate 行为。人类对照协议/空模板/校验器
  也已落地在 `skills.regression.human_baseline` 和
  `skills/regression/fixtures/human_baseline_settings_template.json`，但还没有采集完成的人类 trial。
  现有 `reliability_baseline.json` 仍保留 2026-06-01 的 5/5 completion floor，尚未把这条 4/5
  coverage-bearing snapshot 升格为 completion floor。

#### L2 附：为什么不直接用 SPA-Bench

SPA-Bench（arXiv:2410.15164，见 `docs/reference/computer_use_evaluation_landscape.md` §2）是现成
参照里**离 glassbox 最近的**——真机移动、execution-based、EN/ZH 双语、verifier 经人工对齐校验
（F1 0.845–0.926）。但**不能直接用**，原因是两道硬墙加 a11y 拿不到。

**两道硬墙**

| 墙 | SPA-Bench | glassbox |
|---|---|---|
| **平台** | Android-only（39 EN + 29 ZH 个 Android app） | iOS / iPadOS——任务、app 生态、harness 全搬不过来 |
| **带内 vs 带外** | ADB 在设备上装/重置/读状态（带内 instrumentation） | **out-of-band**：帧走 HDMI、动作走 USB HID、**设备零代码**（AGENTS.md）——没有 ADB 这条路 |

> 要"用 SPA-Bench"，得重建 Android out-of-band rig + 写一套不依赖 ADB 的 setup/reset + 把 a11y
> oracle 换成屏幕-only oracle。那已不是用 SPA-Bench，而是造一个受它启发的 iOS 版本。

**a11y 的两个角色（"截图 + a11y 能用吗"的关键）**——必须分开：

| a11y 角色 | SPA-Bench（Android，ADB 可取 a11y XML） | glassbox（iOS out-of-band） |
|---|---|---|
| **(a) 喂给 agent 的观察** | 可选（有 a11y agent，也有纯截图 agent） | ❌ 拿不到——OCR-only on screenshot，**故意**的架构选择 |
| **(b) verifier 的真值 oracle** | 用（结构化状态 + key-component 粗筛） | ❌ 拿不到——iOS 不向外部 HID 暴露 a11y |

- **截图**：✅ 是 glassbox 的原生模态。
- **a11y**：❌ 在 iOS out-of-band 下**两个角色都拿不到**（iOS 不向外部 HID 暴露 a11y；out-of-band
  设计见 `AGENTS.md` / `README.md`）。
- **关键区分**：benchmark 给 verifier 特权访问、agent 拿不到，是正常的（OSWorld/WAA 的 verifier
  都直接读系统状态）。glassbox 的特殊困境是**连 verifier 都只能 screenshot-only**——这正是更难、
  SPA-Bench 不用解的问题，即 §7 开放问题 #1。

**可借（方法论） vs 借不了（代码/数据/oracle）**

| 可借 ✅ | 借不了 ❌ |
|---|---|
| 难度分层 L1<5 / L2<10 / L3<15 动作 → L2 任务模板 | Android 任务集 / app / ADB harness |
| coarse-to-fine 的**细判半**：MLLM 看截图判最终态（VLM 已 opt-in） | 粗筛半：key-component 标注依赖 a11y |
| **verifier 报 F1**（对齐人工标注）的纪律 → 进 L2/L3 验收 | a11y/ADB 真值 oracle |
| EN/ZH 双语（已在乎，locale seam） | 与原榜单的数字可比性 |

**结论**：SPA-Bench 用不了（Android + ADB 带内 + a11y oracle），但它是最值得抄方法论的参照。
glassbox 真正缺的、也是 SPA-Bench 替不了的，是那个 **screenshot-only 的 outcome verifier**
（UTG `page_id` + expected-state，`_terminal_expected_state_met:368`）——这恰是 L2 的核心工作。
落地优先选**选项 A**：纯借方法论、自建 iOS 任务集、verifier 用 page_id+expected-state 做屏幕-only
判定并**报其 F1**；不走"搭 Android rig 跑原始 SPA-Bench"（基本等于重建且偏离 iOS 主线）。

### L3 — 门禁层（floor + gate）

- **问题**：这次改动有没有跌破地板？（只防退化，不替代 L2）
- **机制**：
  - **冻结地板**：从 **L2 的 outcome 指标**冻结 `reliability_baseline.json`（task_completion +
    覆盖率 + scroll，**不是** action ACK）。
  - **离线门**（每 PR，`make check`）：跑 L0/L1 + `validate` schema + 门禁 smoke。**不**跑真机。
  - **真机门**（nightly，阻塞性）：`make regression-compare CANDIDATE=...`（`Makefile:61`）拿新鲜
    真机跑比地板，`compare_benchmarks` 回归即 rc1 → 开 issue / 阻塞 release tag。
- **验收 / 待修**：
  1. **扩 gate 覆盖（已落地，2026-06-05）**：`compare_benchmarks` 现在把
     `expected_state_coverage` / `vlm_action_coverage` / `strategy_switches` / `recoveries`
     纳入单边棘轮 floor（可升不可降），并在 baseline 与 candidate 都有 scroll 样本时 gate
     `scroll_success_rate`。配套 smoke 用合成 benchmark 断言 coverage/process/scroll 回归会 rc1，且无
     scroll 样本不误报。
  2. **抬门槛**：把 floor 的 `task_completion_rate>0` 棘轮到 L2 实测值（n≥5 的 1.0，带容差），
     堵住"一个非失败任务的 n=1 floor"被当降级提交。
  3. **nightly 阻塞化**：`rig-nightly.yml` 的 `regression-compare` 从 advisory 变成 issue/阻塞。
- **接线（现有）**：`make check: lint test regression-gate golden-audit`（`Makefile:14`）；
  `regression-gate`（`:38`）；`regression-compare`（`:61`，nightly）；
  `reliability_baseline.json`（19 个 metrics）。
- **现状**：⚠️ **存在但仍不诚实**。离线 gate 已能守住 coverage/process/scroll 回归；但 committed
  地板仍由 `tap_xy` 爬虫产生（coverage 全 0），还不是 L2 outcome floor。

### 旁路 — 漂移模拟（advisory，永不挡合并）

- **问题**：图内/轨迹有没有漂移？（低置信，仅提示，不是 regression oracle）
- **接线（已设计/部分）**：
  - **Tier C drift-sim**（`log_sim_replay_regression.md §6`）：`glassbox/obs/decision_log.py`
    （NEW）+ `skills/regression/closed_loop_replay.py`（NEW）；自标"drift detector, not a regression
    oracle"，ships advisory；prompt/response 不记录 → 评不了 planner 选择。
  - **mode-3 UTG operable sim**（`utg_operable_sim.md`）：~70% built，缺 ~500 LOC `SimPhone` shell
    （`glassbox/sim/sim_phone.py` NEW）；off-trajectory 是墙。
- **现状**：🟡 部分。**纪律：永远 advisory，一旦让它 rc1 就是假门禁。**

---

## 3. 目的视图（eval → floor → gate 横切 4 层）

| 目的角色 | 落在哪层 | 一句话 |
|---|---|---|
| **能力评测 (eval)** | L2 | execution-based、多采样、多 cell、带人类对照——回答"有多强" |
| **冻结地板 (floor)** | L3（数据来自 L2） | 以 outcome 指标定义的最低线 |
| **门禁守回归 (gate)** | L3 + L0/L1 | 每 PR 离线守 L0/L1 + nightly 真机守 L2 floor——只回答"有没有变差" |

**反模式（本仓现状）**：L2 缺失 → 用 L3 的爬虫 ACK 冒充评测 → 地板不诚实 → 门禁错位。

---

## 4. 指标定义（附录，`5881a28` 实测语义）

核心计算在 `_metrics`（`computer_use_success_rate.py:636`）与 `_task_outcome`（`:612`）：

| 指标 | 定义（实测） | 关键点 |
|---|---|---|
| **`task_completion_rate`** | outcome=='succeeded' 的 measured task 占比（`:672-673`） | **headline**；measured 排除 `precondition_failed`（`:637`） |
| **outcome（每任务）** | ①`terminal_expected_state` 满足→succeeded/failed（**execution-based**，`:622-624`）；②否则回退到 primary 动作 verdict（全 succeeded→succeeded，含 blocked/failed/transport_failed→failed，否则 unknown，`:625-633`） | ★ **L2 杠杆点**：设了 terminal 才是真 outcome，否则就是 ACK |
| `task_completion_variance` | measured task 上 0/1 成败的方差（`:674`） | n≥5 多采样的离散度 |
| `action_success_rate` | succeeded / task_actions（**已排除 scroll filler**，`:652-655,708`） | 不含 scroll；back 占比高时会虚高 |
| `unknown_rate` | unknown / task_actions（`:709`） | 升则 gate rc1 |
| `scroll_success_rate` | scroll_succeeded / scroll_actions（`:712-714`） | scroll 单独计；filler 全 unknown 时=0 |
| **`expected_state_coverage`** | 带真实 `expected_state.kind` 的 task_action 占比（`:662-667,715`） | **走 orchestrated 路径才非零**；coverage_warnings 在=0 时告警（`:750`） |
| **`vlm_action_coverage`** | `vlm_calls>0` 的 task_action 占比（`:668-670,716`） | VLM 是否真在路径上 |
| `root_pages_coverage` | mean(covered/reachable)，reachable=expected−blocked（`:686-691`） | 故意 block 的页不罚覆盖率 |
| `recoveries` / `strategy_switches` / `retries` | 跨动作求和（`:683,719-726`） | P2/P3 机制是否真触发 |
| `vlm_*` | 调用/缓存命中等（`:692-735`） | 成本与缓存 |

**`compare_benchmarks` 门禁集（2026-06-05 branch state）**：`task_completion_rate` /
`action_success_rate` / `root_pages_coverage` / `expected_state_coverage` / `vlm_action_coverage` /
`recoveries` / `strategy_switches` 下降 → rc1；`navigation_origin_precondition_failures` /
`unknown_rate` 上升 → rc1；`scroll_success_rate` 仅在 baseline 与 candidate 都有 scroll 样本时下降
→ rc1。其余成本/计数指标仍只打印。

---

## 5. 落地顺序（映射到既有 Rank）

| 步 | 动作 | 层 | 成本 | 依据 |
|---|---|---|---|---|
| **Rank 1** | ✅ 把 coverage/process/scroll 指标接进 `compare_benchmarks` rc1（单边棘轮）+ smoke 合成回归断言 | L3 | 低·离线 | 2026-06-05 已落地 |
| **Rank 2** | 🟡 承重代码：`tap_element` semantic ladder + Settings row/search-result `page_id` expected-state；iPad Settings n=5 snapshot 已完成并提交去敏 fixture（4/5 succeeded，`expected_state_coverage=0.976`）；人类对照协议/模板/校验器已落地但 trial 数据待采集；剩余：是否升格为 completion floor/nightly floor | L2 | 高·真机 | honest-gate；`_task_outcome:622` |
| **Rank 3** | 从 L2 冻结诚实地板 + nightly `regression-compare` 阻塞化 + 抬门槛>0 | L3 | 中 | `Makefile:61` |
| Rank 4 | canonical-primitive floor + gate `scroll_success_rate` | L2/L3 | 中·真机 | `run-canonical-primitives` |
| Rank 5 | world-model spine memory ON/OFF A/B（操作性门，非 census） | L2 | 中·真机 | spine 文档 |
| 后置 | Tier B 感知回放（L1）；Tier C / UTG sim（旁路） | L1/旁路 | 中·离线 | 无默认路径数字前模拟无对照 |

**关键依赖**：Rank 1 已给 Rank 2 的 coverage 指标"长出牙齿"；Rank 2 承重代码已把 Settings row/search
result tap 接上 action-level expected-state 和 semantic ladder，并已在 iPad Settings n=5 snapshot 中证明
coverage 非零且产出 execution-based outcome；该 snapshot 也已成为离线校验的 coverage-bearing fixture。
人类对照的协议/模板/校验器现在也有离线 smoke 保护；下一步要采集真实人类 trial，并决定是否用这条
4/5 outcome 替换/并入现有 5/5 completion floor；Rank 3 才能把最终 floor 变成 nightly 门禁。
L1/旁路排在 L2 跑通之后。

---

## 6. 验收门（每层一句话）

- **L0**：`make check` 绿 + 改 verifier 必先 harvest golden。
- **L1**：录制语料上 grounding(point-in-box)/场景/OCR 不破地板。
- **L2**：被测任务每个关键 action 带 expected-state、任务带 terminal_expected_state、coverage 非零、n≥5
  出 `task_completion_rate`+方差+人类对照。
- **L3**：`compare_benchmarks` gate 集含 coverage/process 指标 + 有样本时的 scroll；floor 门槛棘轮到
  L2 实测值；nightly 阻塞。
- **旁路**：永远 advisory，不进任何 rc1。

---

## 7. 开放问题

1. **L2 的 outcome verifier**：iOS/iPadOS out-of-band 无 a11y 树/系统状态访问，仅凭屏幕观测如何
   程序化核对"到达目标状态"？现成方向 = 复用 UTG `page_id` + expected-state（`_terminal_expected_state_met`），
   但需要把"到达 page_id"做成可靠 verifier，并按 SPA-Bench 流程对齐人工标注校验其 F1。
   → 比纯像素更强的 label/role/**value** 来源（验证"开关是否真打开"）见
   `docs/design/glassbox_a11y_channels.md`（rank-1 Voice Control overlay）。
2. **真机可复现性**：确定性 reset / 状态隔离比容器难——需要多大 n 才能可靠量化随机性？
3. **L1 grounding 真值**：OCR-only 无 bbox truth 时，point-in-box 标注怎么建、怎么对齐 verifier。
4. **人类对照数据**：协议、空模板和校验器已落地；仍需确定执行人/轮次安排，采集同任务人工完成率并
   单列报告（L2 验收要求）。
