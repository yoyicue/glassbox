# Computer-Use / GUI Agent 评价体系：外部领域综述

> **这是什么**：对 computer-use / GUI agent **评测方法学（evaluation systems / benchmarks /
> metrics / methodology）** 的外部文献综述，用来给 glassbox 自身评测体系的设计做依据。**不是**
> 对本仓代码的描述。
>
> **快照时间**：2026-06-04（repo HEAD `5881a28`）。本领域演进极快，下方所有基准/综述均为
> 2024–2026 的论文或预印本；全景类结论的底层快照（OS Agents 综述 Table 3）截至 **2024 年中**。
>
> **生成方式**：`deep-research` workflow（5 检索角度 → 24 来源抓取 → 112 条论断抽取 →
> 25 条做 3 票对抗性核验，23 条确认 / 2 条否决 → 合并去重 13 条）。**只收录通过核验的论断**；
> 被否决与低置信项分别在 §8、§9 单列。引用一律带可核验来源（arXiv ID / 官方页）。

---

## 0. TL;DR

学界/业界公认的金标准是 **execution-based / outcome-based 评测**——在真实或容器化环境里把任务
真跑完，再用程序化 verifier 核对**最终状态**（而非比对动作轨迹，更非看动作 ACK）。围绕它有一套
方法学共识：**多次采样**量化随机性、**报告任务完成率而非步级准确率**、**verifier 本身要经人工
对齐校验**、**给出人类对照基线**。评测是**多维**的，不是单一成功率数字。

对一个 glassbox 式系统（真机、out-of-band、OCR-only）而言，最关键的两点：
1. **领域空白**：现有全景里移动端清一色 Android，**零 iOS/iPadOS、零 out-of-band 真机评测基准**
   ——这条赛道没有现成基准可抄，须自建 verifier。
2. **分层缺失**：一个 n=1、绕过真实编排路径、只看 action ACK、且把回归门禁当评测的体系，相对
   best-practice 缺四层（详见 §7）。

---

## 1. 三种评测范式

| 范式 | 怎么评 | 打分对象 | 主要风险 |
|---|---|---|---|
| **Execution-based / outcome-based**（金标准） | 真跑任务，程序化脚本核对最终状态（文件 / 系统状态 / DB / a11y 树） | 任务是否**真达成**（Task Success Rate） | 写 verifier 成本高；规则太硬会漏报 |
| **Trajectory / step-matching** | 把实际动作逐步对齐参考轨迹 | Step Success Rate / Progress Rate | **系统性高估**；惩罚"另一条正确路径" |
| **LLM-as-judge / 人工评审** | 让大模型或人看轨迹判成败 | 完成度的主观判断 | 无单一最优 judge、跨基准不可靠 |

综述 *Evaluation and Benchmarking of LLM Agents: A Survey*（arXiv:2507.21504）逐字区分了
"execution-based evaluation, in which the system runs the tool calls and assesses their
outcomes" 与轨迹类指标：AgentBoard 的 **Progress Rate**（比对实际 vs 期望轨迹，arXiv:2401.13178）、
**Step Success Rate**（成功执行步数占比）。**这就是 task completion rate 与 step accuracy 的分野。**

同一综述给出 **online/dynamic vs offline/static** 二分：offline "rely on datasets and static
test cases"（静态轨迹回放，便宜可复现但不真）；online "leverage simulations or fundamental user
interactions"（活环境真跑，贵但有效，可用 proxy 模拟用户/环境）。

---

## 2. Benchmark 全景（按平台分类）

*OS Agents* 综述（ACL 2025 Oral，arXiv:2508.04482）Table 3 按 **桌面 / Web / 移动** 三类编排
（约 29–31 个基准，截至 2024 年中）。下表中**粗体 = 本轮深度核验过的锚点**，其余为领域常识性分类
（未逐条核验具体数字，引用时请回溯原文）。

### 桌面 OS 级（execution-based 标杆区）

| Benchmark | 模态 | 评测方式 | 规模 / 关键数字 |
|---|---|---|---|
| **OSWorld** (arXiv:2404.07972) | 截图 + a11y 树 | **execution**（核对最终状态，支持多条正确路径） | **369 真实任务**，跨 Ubuntu/Win/macOS，**134 个执行式评测函数** |
| **Windows Agent Arena (WAA)** (arXiv:2409.08264) | 截图 + a11y 树 | **execution**（核对 OS 状态变更，非轨迹匹配） | **154 任务**；头条 **Navi 基线 19.5% vs 无辅助人类 74.5%** |
| OmniACT / ASSISTGUI / OfficeBench / AgentStudio | 截图(+树) | execution / 混合 | 桌面办公 / 工具流 |

### Web 级

| Benchmark | 模态 | 评测方式 | 规模 |
|---|---|---|---|
| WebArena / VisualWebArena | DOM/HTML(+截图) | execution（功能性核对） | 自托管站点，多步任务 |
| Mind2Web / WebLINX | HTML/DOM | 多为 **step-matching** | 真实网站轨迹，离线 |
| WebVoyager / WebShop / MiniWoB | 截图 / DOM | online 模拟 | 端到端 web 导航 |

### 移动级（**全部 Android**——对 glassbox 关键）

| Benchmark | 模态 | 评测方式 | 规模 |
|---|---|---|---|
| AndroidWorld / AndroidArena | 截图 + a11y | execution | 真机 / 模拟器，动态 |
| **SPA-Bench** (arXiv:2410.15164) | 截图 + a11y | **execution**（coarse-to-fine，MLLM verifier） | **300 单 app + 40 跨 app**，中英各半，L1<5 / L2<10 / L3<15 步 |
| AndroidControl / AITW / B-MoCA / LlamaTouch | 截图(+树) | static / execution | 大规模离线轨迹为主 |

> **空白区（= glassbox 的处境）**：上述全景里移动端清一色 Android，**零 iOS/iPadOS、零 out-of-band
> （设备零代码、纯屏幕观测 + 外部 HID 注入）真机评测条目**。本轮检索未找到任何公认的 iOS/iPadOS
> 屏幕观测真机评测基准。**这是"未找到"而非"确证不存在"**，且快照截至 2024 年中——不排除 2025 年后
> 出现新工作。

另有一篇 GUI Agent 基准综述（TechRxiv 预印本，TMLR under review；PDF 直取 403，经 OpenReview 镜像
核验）给出与平台**正交**的对象 taxonomy，强调评测是**多维**的：沿**组件级能力**（intent
understanding / GUI grounding / navigation / context tracking）与**系统级能力**（adaptation /
personalization / privacy / safety / computational efficiency）两轴展开，而非单一成功率。

---

## 3. 关键指标的陷阱（"动作 ACK ≠ 任务成功"有实证）

- **规则匹配会系统性漏报真实成功率**——step/规则匹配相对 outcome 评测的核心坑。
  **AgentRewardBench**（arXiv:2504.08942，McGill/Mila/DeepMind/ServiceNow）实测：常用 web 基准的
  rule-based 评测 **recall 仅 55.9%**（把近一半有效轨迹误判为失败；经典例：agent 答对但因要求精确
  字符串而判败）。**这是"action-level ACK / 硬规则 ≠ task success"的硬证据。**
- **LLM-as-judge 不可靠**：同篇是首个评估 LLM judge 有效性的基准，测 12 个 judge 发现
  "no single LLM excels across all benchmarks"——judge 可靠性依赖基准。（作用域限 web agent，勿外推。）
- **grounding 用 exact point-matching 有根本缺陷**：度量"几何接近度"而非"交互意图是否正确"——
  任何落在可交互元素框内的点击都应算对。AndroidControl-Curated（arXiv:2510.18488）改用
  **point-in-box / bbox 意图对齐**。（补注：point-in-box 非新发明，ScreenSpot 系列 arXiv:2504.07981
  已是多年标准；该批评最咬合 τ≈0 的精确点匹配，不应读作否定所有容差点指标。）
- **基准标注噪声会反向低估能力**：AndroidControl-Curated 称原基准约 **30% 任务**有歧义/多解未记/
  错标，系统性惩罚正确行为。⚠️ caveat：单篇、作者同时卖解法、30% 的统计派生未充分披露、无独立
  复现；与之绑定的"净化后 SOTA 升到 76.5%"**已被 3 票否决**（见 §8），不予采纳。

---

## 4. 公认难点与可复现性

- **随机性 → 必须多次采样**：综述明确 "LLM agents are inherently probabilistic"，
  "measuring consistency requires executing the same task multiple times"。**τ-bench**
  （arXiv:2406.12045）为此提出 **pass^k**（同一任务多 trial 的可靠性指标）。代价是计算贵——
  这就是"**n 的问题**"。
- **可复现 best-practice**：容器化环境 + 确定性 reset + 程序化 verifier + **verifier 经人工对齐
  校验**（SPA-Bench 报告自动 verifier 对人工标注的 **F1 0.845–0.926**，即 verifier 被验证而非
  假定正确）+ **报告 task success rate** + **给人类对照**（WAA 19.5% vs 74.5%）。

---

## 5. 工业界做法（低置信度——本轮未通过核验）

OpenAI（Computer-Using Agent / Operator）、Anthropic（Claude computer use）、Google 对外主要在
**OSWorld、WebArena、WebVoyager** 这类公开基准上报告 **task success rate**。但⚠️ **本轮研究没有
一条厂商自报的具体数字通过对抗性核验**（抓到了官方页但相关 claim 未进最终确认集）。**具体百分比
请以官方页为准，本文不断言数字。** 公认争议：厂商自报口径不一、基准可能被训练数据污染、headline
数字常被质疑"挑了对自己有利的 benchmark 子集"。

---

## 6. 业界推荐的分层评测体系

```
第①层  能力评测 (eval)      ← execution-based、多次采样(n≥5)、多 App/语言、带人类对照
                              产出：task success rate + 过程指标分布
        ↓ 从评测里冻结一个诚实的地板
第②层  冻结地板 (floor)     ← 以 outcome 指标 (task completion) 定义，不是 action ACK
        ↓
第③层  回归门禁 (gate)      ← 每个 PR 跑，只回答"有没有跌破地板"，离线/确定/便宜
```

关键纪律：**门禁只防退化，不替代独立的 outcome 评测和人类对照。** 地板必须从第①层派生，且以
outcome 指标定义——否则门禁会被 `task_completion=0.0` 的失败样本静默通过。

---

## 7. 映射回 glassbox：缺的四层

将"一个 n=1、绕过真实编排路径、只看 action ACK、把回归门禁当评测"的体系对照上面的共识，
**至少缺四层**：

1. **多次采样量化随机性**——现在 n=1（同任务同天重跑测的是台子稳定性，不是能力）。共识要求
   pass^k 式多 trial。
2. **execution-based 的语义最终状态核对**——现在看的是动作 ACK。共识金标准是核对"真的进到目标
   状态"。AgentRewardBench 证明硬 ACK / 规则会漏报近一半。
3. **经人工对齐校验的 verifier**——现在的 verifier 没有"对齐人工标注的 F1"这种自证环节
   （SPA-Bench 有）。verifier 要被验证，不能假定正确。
4. **"评测 → 冻结地板 → 门禁守回归"的分层**——现在把第③层（门禁）当成了全部。

> **本仓现状的对照点**（代码事实，截至 2026-06-06 本分支变更，行号会漂移，引用时请回查源）：第①层
> 仍缺失（无真正的 multi-sample outcome 评测）；第②层正在修正但地板仍不诚实（2026-06-06 正常
> Settings row tap 已带 action-level `page_id` expected-state，且 verifier 支持 `page_id.any_of` 以覆盖
> 中英/HK alias；但 committed baseline 仍来自 coverage 全 0 的旧路径，search/fallback 坐标 taps 和 n≥5
> 采样还没收口）；第③层部分修正（2026-06-05：`compare_benchmarks` 已 gate coverage/process 回归和有样本时的
> scroll 回归）。详见 `docs/goals/computer_use_honest_gate_first.md`。

---

## 8. 被否决的论断（0-3，**不予采纳**）

| 论断 | 来源 | 否决 |
|---|---|---|
| AndroidControl 净化后 SOTA 从 ~60% 升至 76.5%，证明低分源于基准缺陷而非模型局限 | arXiv:2510.18488 | 0-3 |
| OSWorld 上人类完成 72.36% vs 最佳模型仅 12.24% | os-world.github.io | 0-3 |

（WAA 的人类对照采用论文原文 **Navi 基线 19.5% vs 单个无辅助人类 74.5%**；新 agent 在 WAA 上分数
更高。OSWorld 的具体人类/模型百分比本轮未能确认，故不引用。）

---

## 9. Caveats

1. **时效性**：全景快照截至 2024 年中；"无 iOS/iPadOS、无 out-of-band 真机评测"是对该快照的描述，
   是"未找到"而非"确证不存在"。
2. **预印本**：两篇关键综述（TechRxiv GUI 基准综述、arXiv:2507.21504）为预印本/审稿中；TechRxiv
   PDF 直取 403，论断经 OpenReview 镜像 + 逐字搜索二次核验；它们提供的是"综述自身的 taxonomy"
   （描述性），不等于领域共识。
3. **自利性单篇**：AndroidControl-Curated 的"约 30% 标注有缺陷"由同时发布解法/模型的同一作者
   提出，统计派生未充分披露，无独立复现。
4. **verifier 自报偏差**：SPA-Bench 的 F1（0.845–0.926）是基准作者验证自家 verifier 的自报数字；
   更广文献记录 MLLM-judge 在失败检测上的一致性可降至约 50%。
5. **作用域**：AgentRewardBench 的 LLM-judge 结论限于 web agent，不可直接外推到桌面/移动。
6. **分层框架**：§6 的"评测 → 冻结地板 → 门禁守回归"是对多源 best-practice 的综合推断，非任一
   来源逐字给出的工程规范。

---

## 来源（仅列通过核验的）

- OS Agents 综述（平台 taxonomy / 空白区）— arXiv:2508.04482（ACL 2025 Oral）
- LLM Agents 评测综述（范式分层 / online-offline）— arXiv:2507.21504
- AgentBoard（Progress Rate）— arXiv:2401.13178（NeurIPS 2024）
- τ-bench（pass^k）— arXiv:2406.12045
- AgentRewardBench（rule-based 漏报 55.9% / LLM-judge）— arXiv:2504.08942
- AndroidControl-Curated（标注噪声 / point-in-box）— arXiv:2510.18488；ScreenSpot — arXiv:2504.07981
- OSWorld（369 任务 / 134 函数）— arXiv:2404.07972 · https://os-world.github.io/
- Windows Agent Arena（154 任务 / 19.5% vs 74.5%）— arXiv:2409.08264（Microsoft/CMU）
- SPA-Bench（300+40 / verifier F1）— arXiv:2410.15164（NeurIPS 2024）
- GUI Agent Benchmarks 综述（组件级 vs 系统级能力）— TechRxiv 预印本（OpenReview ri3yPWE21Q，PDF 403，经镜像核验）

---

## 开放问题（glassbox 该自答）

1. iOS/iPadOS out-of-band 真机评测是**领域空白**——若想严肃评测，须**自建 execution-based outcome
   verifier**：在没有 a11y 树/系统状态访问、**仅凭屏幕观测**时，如何程序化核对"最终状态"？
   （glassbox 的 UTG + expected-state 机制本可承担此角色。）
2. 真机的**确定性 reset / 状态隔离**比容器难——需要多大 n 才能可靠量化随机性？真机相比 VM/容器
   的复现性损失有多大？
3. OCR-only 管线下 grounding 评测该用什么 **point-in-box / 意图对齐**指标，在没有元素 bbox 真值时
   怎么标注、怎么对齐 verifier（参照 SPA-Bench 的人工对齐 F1 流程）？
