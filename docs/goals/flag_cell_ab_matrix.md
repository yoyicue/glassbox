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
| iPhone 设置地板（en/HK） | task_completion | **0.0**（2026-06-12 入库；操作按钮 5/5 确定性缺失,见台账） | `iphone_settings_baseline.json` |
| Clock cell | task_completion / 每轮耗时 | 0.8 / ~14min（launch 占大头） | `clock_tabs_baseline.json` |
| L2 快照 | task_completion | 0.8 | `l2_settings_expected_state_snapshot.json` |
| canonical primitives | task_completion / scroll_success_rate | **0.9 / 0.957**（2026-06-11 入库,见台账） | `canonical_primitives_baseline.json` |
| zh cell | （不存在） | 需物理切语言 | — |

---

## 0.5 地板谱系——数值时间线

**规则**:任何改变下列 fixture 头条指标的提交,必须在对应格子末尾**追加一行**
(守卫:`skills/smoke/test_floor_lineage.py` 会在 fixture 与本表最后一行不一致
时把合并门打红,失败信息里直接给出待粘贴的行)。生成当前行:

```bash
uv run python -m skills.regression.floor_lineage
```

列语义(顺序与 `floor_lineage.py:VALUE_KEYS` 锁定;数值格式 `%.3g`;
历史行由 git 逐版本重放生成 2026-06-11,🔼 = 抬高):

| 列 | 指标 | 含义 | 怎么读 |
|---|---|---|---|
| completion | task_completion_rate | 任务级完成率:整轮任务按**终态证据**判定成功的占比 | **头条,↑好** |
| action | action_success_rate | 动作级成功率:任务型主要动作(排除滚动填充)语义验证 succeeded 的占比 | ↑好;**≠任务成功**(勿把 0.955 时代读成任务成功) |
| esc | expected_state_coverage | 带显式期望状态(`expect=`)验证的动作占比 | **覆盖率,非成功率**;↑ = P2 语义验证在路径上 |
| recov | recoveries | 恢复机制实际触发并成功的次数(原始计数) | **救场计数,方向中性**:干净跑诚实为 0,降可能 = 路径更可靠 |
| switch | strategy_switches | 策略阶梯切换次数(P2 升级频次) | 同上(a8b6281 行 5→0 是诚实零,不是退化) |
| vlm | vlm_action_coverage | VLM 参与的动作占比(P1 触发频次,计费路径) | 同上;守护者是机器探针,不是棘轮 |
| scroll | scroll_success_rate | 滚动动作成功率(已知弱原语,单列以防稀释 action) | ↑好;样本少时波动大(看 scroll_action_count) |

| 格子 | 日期 | commit | 事件 | completion | action | esc | recov | switch | vlm | scroll |
|---|---|---|---|---|---|---|---|---|---|---|
| 设置 | 2026-05-30 | `1a83c2e` | 诞生(动作级时代,outcome=failed) | 0 | 0.955 | 0 | 2 | 5 | 0 | 0.222 |
| 设置 | 2026-06-01 | `c9c4692` | 门诚实化(数值未动) | 0 | 0.955 | 0 | 2 | 5 | 0 | 0.222 |
| 设置 | 2026-06-01 | `a8b6281` | **🔼抬高①** completion 0→1(n=5 真实成功;tap_xy 产,救场计数归诚实零) | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| 设置 | 2026-06-03 | `1a00cab` | world-model 评审修订(数值未动) | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| 设置 | 2026-06-06 | `5acec51` | clean-HDMI cell 约束(数值未动) | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| 设置 | 2026-06-10 | `571e568` | **🔼抬高②(质量棘轮)** 语义验证路径产出 | 1 | 1 | 0.978 | 2 | 0 | 0 | 0.0769 |
| 设置 | 2026-06-11 | `03a2255` | schema 刷新 +duration(数值未动) | 1 | 1 | 0.978 | 2 | 0 | 0 | 0.0769 |
| iPhone设置 | 2026-06-12 | `baa6274` | 诞生(诚实 0 地板:操作按钮 5/5 确定性缺失,#99 实机不充分;数据 sha=fixture.git_sha,a11y loop-1 先例) | 0 | 0.883 | 0.525 | 14 | 39 | 0.181 | 0.11 |
| Clock | 2026-06-10 | `89a3bed` | 创建(第二 App cell;launch 弱原语如实保留) | 0.8 | 0.974 | 0.447 | 0 | 0 | 0 | 0 |
| Clock | 2026-06-11 | `03a2255` | schema 刷新(数值未动) | 0.8 | 0.974 | 0.447 | 0 | 0 | 0 | 0 |
| canonical | 2026-06-11 | `23c9fc4` | 创建(矩阵 #9;六次尝试换来 #75-#82 五个核心修复) | 0.9 | 1 | 0 | 0 | 7 | 0 | 0.957 |
| a11y | 2026-06-10 | `dbe48a3` | loop-1 创建(overlay 代价如实入账) | 0 | 0.422 | 0.34 | 7 | 21 | 0.136 | 0 |
| a11y | 2026-06-10 | `cbad3ae` | **🔼抬高③** badge 减除(loop-2) | 1 | 0.873 | 0.864 | 0 | 1 | 0.0409 | 0 |
| a11y | 2026-06-11 | `03a2255` | schema 刷新(数值未动) | 1 | 0.873 | 0.864 | 0 | 1 | 0.0409 | 0 |
| L2快照 | 2026-06-06 | `9faa706` | 创建(advisory 覆盖率格,messier 4/5 跑) | 0.8 | 0.895 | 0.976 | 0 | 9 | 0.0861 | 0 |
| L2快照 | 2026-06-11 | `03a2255` | schema 刷新(数值未动) | 0.8 | 0.895 | 0.976 | 0 | 9 | 0.0861 | 0 |

> 截至 2026-06-11:真正的抬高共 **3 次**(①设置 completion 0→1、②设置质量
> 棘轮 esc 0→0.978、③a11y 0→1),其余为诞生/诚实化/约束/刷新。L2 快照此前
> 被误记为 `ed6db61` 创建——git 逐版本重放更正为 `9faa706`(06-06);
> `ed6db61`(06-10)只加了保护未动数值。

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

### 2026-06-12 iPhone 转场识别战役收官(S1-S6 全杠杆 + rig n=1 通过)+ 修复前 n=5 聚合 —— PRs #91-#100
- 类型：战役验证(rig n=1)+ 基线测量(修复前 5 轮聚合,**未入库**;修复后 n=5 **已完成并入库**,见产物行)
- 格子：iPhone 17 Pro Max 设置钻取 en/CN;代码:离线杠杆 `#91-#97`,n=1 复验在 `2fa4911`,floor 候选在 `2434d09`(#98-#100)
- 离线杠杆(设计 `docs/design/iphone_settings_transition.md`,每步独立 PR):S6 证据保全 #91 → S1 语料 + S2 SectionVocab 接入 #92(隐私前向擦洗支线 #93)→ S3 nav-band 铸造 #94 → S4 比较器折叠归一 #95 → S5a 归因+主动退出 #96 → S5b 身份守卫(flag-gated)#97
- **rig n=1(尝试 3,§3 判据全过)**:30 visits、21 个子页进入+验证(判据 ≥16+4)、**4 个法医假拒绝全部翻正**(Wallpaper/声音与触感/Face ID与密码/Developer)、`unverified_transitions=0`、零破坏性重拍(S5b 守卫全程惰性=无假失败可挡);单轮 23-28 分钟(法医基线 49 分钟)。必需根页仅缺 `操作按钮`(确定性结构 miss,见下)
- 尝试 1/2 死因 = **新环境雷:Apple Account 受信号码确认弹层**(Settings 前台时 iOS 自动弹;逃逸梯子对 sheet 无效——OCR 分类器无 modal 类,误判 springboard/icon_grid;VLM 层其实认得 'modal')。处置:经用户授权代点确认(弹层永久解除,root 的 Review 行随之消失)+ **#98** core `modal_sheet` 分类 + 只点右上 X 的 dismiss 级(veto+anchor+abstain,READ-ONLY 钉死)+ S6 补漏 `:1258` 兄弟调用点 + en "Review Apple Account" 进 unsafe 词表(关闭既有 backlog 项)
- n=1 残留法医(对抗复核级,全部 file:line 钉死)→ 同日修复:**#99** 操作按钮双根因(policy `cy<260` 全局死区使每个落带前 3 行结构性不可 tap——Camera/控制中心一直被跳;Settings 应用内搜索面板被弱分支误判 system_search → 查询从未输入,`search_no_result` 是谎言 + 错归因诽谤 picokvm)、**#100** visit 标题委托 core classifier(skill 选择器绕过 S3 守卫产出 'Edit'=WLAN/'+'=蓝牙/'I!I,'=隐私与安全性/'Appearance'=显示与亮度 四案;core 标题四案全对;core 增 CJK 臂保 zh 二字标题)
- **修复前 n=5 聚合(@`2fa4911`,5×独立单轮进程绕多轮翘死,离线补聚合 `iphone_floor_n5/aggregate_2fa4911.json`)**:task_completion **0.0**(操作按钮死区每轮命中 → 根覆盖永不完整 → 终态判 0)、action 0.904、root 覆盖 0.84(16/17↔14/17 轮间方差:无线局域网/隐私与安全性在 3/5 轮未开)、scroll 0.095、switches 29、unknown 0.015。S6 报告保全链(.prev-mtime)是离线补聚合的使能者
- 判定：转场识别墙已拆(iPad 状态机战役的 iPhone 同类物收官);completion 0.0 的唯一结构性根因(#99)已修,修复后 n=5(单进程 5 轮,顺带实测多轮翘死债 + `GLASSBOX_PICOKVM_ROBUST_CAPTURE=1` 默认)= fixture 候选,完成后补谱系行
- 产物：**修复后 n=5 完成并入库**(round 0 @`2434d09`,rounds 1-4 @`baa6274`,#101 仅文档代码同一;单进程 5 轮 `--keep-going`):task_completion **0.0**(5/5 failed)、action 0.883、root 覆盖 0.88(每轮进入 12-14/17;蜂窝网络 device_unavailable + 钱包 blocked 豁免)、esc 0.525、scroll 0.110(136 滚)、switches 39、recoveries 14、unknown 0.0088、vlm 覆盖 0.181(101 调用,host env 开 VLM,config.vlm_enabled 只记 `--vlm` flag)。源数据 `iphone_floor_n5_post99/floor_candidate.json` → fixture `skills/regression/fixtures/iphone_settings_baseline.json`(本仓**首个 iPhone 设备匹配 floor**;离线门 `test_iphone_settings_floor.py` + nightly iPhone lane 阻断比对接线,lane env zh-Hans→en/CN)。修复后法医:**操作按钮仍 5/5 缺失**(0-2 轮零 tap 尝试、3-4 轮各 2 次 failed tap,报告 0-3 轮记 search_absent)→ **#99 实机不充分**;**Camera 首次进入**(5/5 tap succeeded;修复前 n=5 零尝试)→ 死区修复部分起效;**蜂窝网络 5/5 tap failed**(page_id mismatch)→ 新异常待查;round 4 限位 'exception'(PicoKVM 流打开 RuntimeError)保留 = 诚实方差
- 注意事项：S5b 默认开翻转的 rig A/B 证据 = n=1 守卫零触发(惰性)+ 离线语料钉,翻转决策留给下一轮守卫真实触发样本;设备挂着"今晚安装软件更新"(用户决策:不管);`--out` 在轮验证 rc≠0 且无 `--keep-going` 时不写(已三次踩 zsh 管道掩码,取内层 rc 用 `${pipestatus[1]}`)
- **区域声明修正(2026-06-13)**:真机直读 Settings > General > Language & Region = **Hong Kong (China)**(首选语言 English + 简体中文)→ 本条及此前各条的 "en/CN" 实为 **en/HK**;fixture/lane/文档身份键已统一改 HK。功能零影响(en-CN ≡ en-HK 同一张 `GREATER_CHINA_EN_ROOT_LABEL_ALIASES`,settings_rows.py:89-90),数值不变。教训:"WLAN" 在 HK 区域同样渲染,不是 CN 判别器;区域以设备页直读为准,不靠环境推断

### 2026-06-12 iPhone 设备匹配 floor 三连试 —— 中止,launch 路径修复入库,滚动确定性立为前置战役
- 类型：基线建立(**未入库**——三次尝试均无法产出有意义 floor)
- 格子：iPhone 17 Pro Max 设置钻取;计划 n=5;en/CN(设备实为英文系统,nightly 矩阵的 zh 假设过时,已决策 floor 用 en/CN 并待改 lane)
- 尝试 1(zh 词表错配):设备英文 → zh 根页词表不可达 → SettingsRootUnreachable;顺带暴露 Apple Account review 弹层行陷阱
- 尝试 2(launch 全灭,**产出核心修复 #87**):混合 widget+网格首页被 `weatherish>=3` 误判为纯 Today 面 → launcher 跳过扫描**可见的** Settings 图标(OCR 实测 (150,541) 有标签)→ 全轮死于启动。修复 = `_scannable_app_labels` 语义过滤(几何网格判别被既有天气预报表守卫测试当场击杀,换语义路);同因解释 iPad Clock cell 的 launch 彩票成分
- 尝试 3(#87 后,--keep-going 诚实计分):**成功进入 Settings 爬取**(launch 修复验证),但 5 轮仅 1 轮写出 artifact,该轮覆盖 0/17、5 滚全败、asr 0.33——单栏设置折叠线下 7 个根页(WLAN/声音/专注/辅助功能/操作按钮/FaceID/隐私)需要滚动,iPhone swipe-fling 物理天花板(已知:覆盖 9-15/17)是真实承重墙
- 判定：~~iPhone floor 前置依赖 = 滚动确定性~~ **已证伪(06-12 晨法医修正)**:driver 选错 run 目录聚合了 9 动作辅助会话(修复 = `_pick_round_run_dir`,ledger 最大者胜);真实的 round 0 = **144 动作、物理进入 20 个 settings 页(含折叠线下的 WLAN/Face ID/Privacy——滚动够用)**,但 report 仅记 1 次 visit、失败类全是 `tap-no-transition`——**真墙 = 爬虫转场识别在 iPhone en/CN 上失灵**(点击开了页、爬虫不认 → back 回退 36 次 → 异常),iPad 状态机战役(C1-C5)的 iPhone 同类物。复现数据:`iphone_floor_runs/run_2026_06_12_06_04_38_*` + `ios-settings-000.json`。en/CN 词表路径确认完好(WLAN 别名生效,zh 规范 ID 层按设计工作);多轮间 rig 流翘死(rounds 1-4 preflight 全灭)为并行的第二债
- 产物：#87 合并;无 fixture;`--keep-going` 语义确认(verify 失败轮诚实计分不中止)
- 注意事项：设备已复位 verified-Home;Apple Account review 行陷阱待 settings_blocked_safety 词表覆盖(en:"Review Apple Account…");三次尝试的 run ledger 在本地 artifacts

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
