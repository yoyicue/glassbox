# glassbox 的 a11y-like 带外通道评估

> **这是什么**：评估 glassbox（iOS/iPadOS **out-of-band**：观测=HDMI 帧、动作=USB HID、**设备零
> 代码**）能否拿到一个"accessibility-tree-like"的结构化 UI 信号（元素 label / role / value / 可
> 聚焦枚举），而不破坏 out-of-band。把 5 条候选通道按可行性 × 对 glassbox 的增量排序。
>
> **快照**：research/code-fact 基线为 repo HEAD `5881a28`（2026-06-04）；Voice Control 实机补充为
> branch `docs/eval-and-a11y-design` working tree based on HEAD `a858e2e`。**行号会漂移**——引用前回查源。
>
> **生成方式**：`glassbox-a11y-channel-research` workflow（5 通道并行 web 检索 + 3 条最承重 iOS
> 事实对抗性核验）+ 本文作者对 rank-1（Voice Control overlay）与全部仓库 claim 的二次独立核验。
> 核验状态逐条标注；被否决通道单列。

---

## 0. TL;DR

**有机会，但不是"白嫖一棵 a11y 树"。** 对抗核验击穿了两条"听/读设备外发流"的浪漫路子（盲文、
VoiceOver 语音，均 `holds=false`）。真正能给 **label/role/value 语义 + 不破 out-of-band + 被现有
OCR 直接吃到**的现实路线只有两条且互补：

1. **🏆 Voice Control 持久 overlay**（Show Names / Show Numbers）——让 iOS 自己把 a11y label / 数字
   标签**画到屏幕上**，glassbox 现成 OCR 截**一帧**就读到。零设备代码、零新通道。
2. **合成 a11y 树**（synthetic）——纯像素重建，glassbox 已落地大半，是默认且唯一无条件合规的底座。

FKA 只补"枚举+几何"不补语义；盲文伪装、HDMI-VoiceOver-TTS 两条排后/排除。

---

## 1. 五条通道排序

| # | 通道 | 判定 | 能拿到什么 | 成本 | 核验 |
|---|---|---|---|---|---|
| **1** | **Voice Control overlay**（Show Names/Numbers）→ OCR | ✅ marker_viable_now | 屏上 marker OCR 可读；稳定 label/value identity 仍取决于 badge-to-target mapping。无嵌套层级树、无屏外元素 | 低 | ✅ overlay 已独立确认；坐标 HID 小样本共存通过 |
| **2** | **合成 a11y 树**（OmniParser/Set-of-Mark/分组层 + OCR + UTG） | 🟡 synthetic_only | 几何+可交互枚举（高保真）、role+label（中）、**state/value 最弱** | 中 | — |
| **3** | **FKA 焦点环 Tab-walk + 帧差** | ✅ viable_now | **仅几何+枚举+遍历顺序+focus-group 边界**。身份仍靠 OCR | 低 | ✅ 焦点环只画框不渲染 label（holds=true） |
| 4 | **PicoKVM 伪装 HID 盲文显示器**（usage 0x41） | ❌ 近排除 | 线上是**已渲染盲文点阵 bitmap**，非文本/a11y | 高 | ❌ holds=false |
| 5 | **HDMI 音频采 VoiceOver TTS** | ❌ 不建议 | 焦点元素口播 label | 高 | ❌ holds=false |

> 另：Appium WebDriverAgent / idb / XCUITest 等外部 introspection **都需在设备上跑 test-runner/
> companion** → 直接破 out-of-band，**已排除、未入排名**。

---

## 2. Rank 1 — Voice Control overlay（详）

### 机制（零设备代码）

经 `设置 > 辅助功能 > 语音控制` 开启，并把 **Continuous Overlay** 钉成 **Show Numbers** 或
**Show Names**。overlay 是 iOS 渲染在屏上的**可见文字层**，glassbox 用现成 HDMI 帧 + VisionOCR 读取：

- **Show Names**：把**每个元素的 accessibility name 作为文字**显示在屏上（"displays the accessible
  name of every element on the screen"）。→ 直接拿到真 **label**。
- **Show Numbers**：给每个可交互元素一个**高对比数字标签**，"helpful when an element is missing a
  name" → **连无可见文字的纯图标控件都兜得住**，但实机滚动样本显示数字是**当前可见帧内的 action
  anchor**，不是跨滚动稳定 identity。
- **Show Grid**：编号网格，覆盖无名/无号区域（兜底）。

一次读一帧即可（不是 O(N) 遍历）。**拿不到**：嵌套层级树、traits 位图、屏外/折叠元素。

### 为什么排第一

唯一"真补 label/role/value 语义缺口 + 立即可落地 + 现有 OCR 直接吃 + 零新 HID/固件/设备代码"的
路线。复用现成 VisionOCR + `minimumTextHeight` 调参 + ROI tiling。Apple 自家 app / Settings（主
战场）a11y label 质量高，正中 envelope。

### ★ 接上仓库里已存在却始终为 None 的钩子

`WhiteboxHint.accessibility_id`（`glassbox/cognition/base.py:80`）**存在且被签名/匹配机器读取**——
`memory/element_key.py:54`（`return f"aid:{wb.accessibility_id}"`）、`memory/signature.py:85`、
`cognition/heuristic.py:502`、`action/actuation.py:178`——但**生产里始终为 None，只有 smoke 夹具
赋值**（`skills/smoke/test_tap_intent.py:358`、`test_heuristic.py:369` 的 `WhiteboxHint(
accessibility_id="nextBtn")`）。这是个 CUQ-2.10 whitebox-identity 钩子，**接线齐全却无生产 producer**。
Voice Control overlay 的 **Item Names** 是这个 producer 的候选输入，直接对症已记录的 **App Store 误判 /
iPad Settings root 签名碎裂**（见 `MEMORY` / `docs/design/settings_detail_false_positive_arbitration.md`）。
2026-06-04 第一版实机样本显示，Item Names 的 badge-to-target mapping 会把位于目标下方的 badge 错配到
下一行；后续 matcher 已补上"上方/下方/轻微重叠"几何关系、文本匹配约束和 OCR typo 容错，并新增
`skills.regression.voice_control_overlay_labeled_replay`。在同一保存样本的 12 条 label manifest 上已通过
12/12，但这仍只是小样本 replay gate；因此当前实现只解析 marker，`WhiteboxHint.accessibility_id` 写入
必须显式 opt in。**Item Numbers/Grid 不应默认进入这个稳定出口**：它们可作为同帧 action anchor，但不能
作为 UTG 长期 key。

### 上机验证清单（落地前必做）

1. **HID 共存**：2026-06-04 的 iPad mini 7 小样本已证实 Voice Control overlay 开启时
   `tap_xy(..., coordinate_space="cropped_px")` 可切换 `Item Numbers -> None -> Item Numbers`，
   transport OK；`Numbered Grid -> None -> Numbered Grid` 也通过同款 A/B。`Item Numbers` 与
   `Numbered Grid` 的三次长 swipe scroll transport OK。负例：同日 `phone.tap("Item Names")` 在 overlay
   活跃时虽然切到了 Item Names，但 semantic-plan 后续漂到 Home/widget surface 并以
   `expect_text("Item Names")` 超时结束；text-targeted tap 不能算验收通过。wheel 的小 delta 样本曾是
   负/弱结果：显式 `cropped_px` focus 后，`scroll_wheel(90)` transport OK，但 frame diff 只有
   `0.008027`；`90 -> -90` 双方向 probe 仍只有 `0.007753` / `0.007524` 小 diff 和 OCR/状态噪声；
   加 `focus_click=True` 后产生大 frame diff，但只是选中了 sidebar 的 `Notifications` row。后续清掉
   FKA help trap 并恢复 HDMI 后，`360 -> -360` hover-only wheel 在同一 focus point 上得到正向
   `frame_changed` 证据（`0.087163` / `0.086383`），页面保持 `settings/Overlay`。keyboard visible
   insertion 早期样本也曾为负：`gbvckbd` / `gbvccmdf` / overlay-off `gbvcoffdt` 都未显示，`Cmd-F`
   还会离开 Overlay；但 after-reboot 的 coordinate Search-field retry 成功显示 `gbvcretry`。该样本暴露了
   `type_text` 即时 semantic reason 早于后续 capture 的时序问题；当前 facade 已默认把 typed text 当作
   post-action visible expectation，但 patched path 还需上机复验。`Ctrl-Space` 输入源切换仍禁用，因为它会离开
   Settings 并打开 Full Keyboard Access help overlay。详见
   `docs/measurements/voice_control_overlay_ipad_mini_2026_06_04.md`。
2. overlay 会**遮挡内容、扰动 letterbox/stability** → 需要一个分层解析 pass（overlay 文字层 vs
   内容层），把 number/label 映回元素 bbox。
3. Continuous Overlay 能否经 Settings **脚本化钉死**（而非每次语音触发）。
4. Show Numbers 的数字索引在滚动后是否稳定：2026-06-04 iPad mini 7 样本给出反例，同名 label
   `Siri` / `Wallpaper` 在滚动后编号变化（`22→13`、`23→15`）。因此数字/grid 只能当
   frame-local action anchor；`WhiteboxHint.accessibility_id` 默认不接受任何 overlay mapping，直到
   Item Names 的 badge-to-target replay 在更多页面/滚动位置通过更强验收。

### 落地形态

cognition 加一个 `structure read` 感知子模式：钉 Continuous Overlay，先解析 **Item Names** marker；
用 `voice_control_overlay_labeled_replay` 持续回放人工 label 清单；只有在 badge-to-target mapping
跨更多页面/滚动位置通过 labeled replay 后，才灌入稳定 `accessibility_id` 出口；再用
**Item Numbers/Grid** 做同帧无名控件 action anchor（显式 frame-local，不进默认 UTG identity）。
**作为可选语义增强读**，叠加在 rank-2 默认感知之上，共享同一 `WhiteboxHint`/签名出口，但只让稳定来源
进入签名。

---

## 3. Rank 2 — 合成 a11y 树（默认底座）

纯像素重建（OmniParser-v2 / Set-of-Mark 索引喂 VLM / Screen2AX 式分组层 + 现有 OCR + UTG 跨帧图）。
out-of-band 下**唯一无条件合规的默认底座**，glassbox **已落地大半**（Apple Vision OCR + 可选
OmniParser + UTG 都在跑）——增量是把检测框转成 Set-of-Mark 索引喂（已 opt-in 的）VLM + 可选加一个
grouping/hierarchy 后处理 stage（走 `boundaries.py` seam，**不改 core**）。

- **保真度**：几何+可交互枚举（高）、多数 role + OCR label + 图标 caption（中）、合成层级 ~77% F1
  （低-中）、**state/value 最弱**（tint-color 启发式猜；选中态召回低、连续值不可恢复）。
- **与 rank-1 互补**：synthetic 最弱的 value/state，恰是 glassbox `observe→verify` 语义校验环最需要
  的（"开关是否真打开"）——Voice Control overlay 是潜在的真 label/value 来源，但当前只证明 marker
  可读，未证明自动 mapping 足够可靠。二者互补、非替代：rank-2 永远在线，rank-1 作为可选语义增强叠加其上。
- **红线**（已成文）：**OmniParser YOLO(AGPL) 不可 default-on 进 MIT core**（PR#55 default-on 后门
  事故已记 MEMORY）；**VLM 计费 opt-in**；**默认 OCR-only-free**。

---

## 4. Rank 3 — FKA 焦点环 Tab-walk（几何交叉校验）

`设置 > 辅助功能 > 键盘 > Full Keyboard Access`。glassbox 已能模拟 USB 键盘且 HID 原语齐全
（`glassbox/effectors/picokvm/keymap.py:5` Shift `0x02`、`:25` Tab `0x2B`、`:26` Space `0x2C`），
**源码里零 FKA 编排 = 只差 orchestration**。Tab/Shift-Tab 走的就是 a11y 可聚焦集
（`isAccessibilityElement && respondsToUserInteraction`），逐次帧差焦点环位置 → 精确 bbox + 数量 +
遍历顺序 + focus-group 边界。

**核验确认（holds=true）**：焦点环只画 border+highlight、**不渲染 label**（AbilityNet/Appt.org/
Apple HIG-WWDC21 多源收敛）→ 从 HDMI 只得几何，元素身份仍靠对框内像素 OCR；纯图标控件只剩几何。

**最佳用法窄而实**：作为 action 层 **"verify what's truly focusable"** 交叉校验，用系统 a11y 引擎的
真值纠正 OCR/OmniParser 对"哪些是真可交互"的猜测。代价：O(N) 次 Tab + N 帧差（逐屏 HID 往返），慢于
overlay 一次成帧 → **补充工具，非主通道**。可作**最便宜的先行件先 ship**（纯 HID Tab-walk + ring-diff，
连 Settings 都不用改）。

---

## 5. 被对抗核验击穿的通道（放弃/搁置）

### Rank 4 — PicoKVM 伪装 HID 盲文显示器 — `holds=false`

iOS/iPadOS **确实**原生支持符合 USB-IF "HID Braille Display"（usage page 0x41 / HUTRR78）的盲文显示器
（无需 App，开 VoiceOver 即插即用）。**但**：

- 线上传的是**已渲染的盲文点阵 bitmap**（每 cell 1 字节 8 点位图，ISO/TR 11548-1），**不是文本/a11y
  语义**——屏幕阅读器在**内部**做完"文本→盲文"翻译只发点阵；通常仅 14–40 cell 的**当前窗口**，非焦点
  元素完整 a11y；反译有损（Grade-2 缩写歧义，须强制 uncontracted/8-dot）。
- **结构墙（已对源码坐实）**：PicoKVM 是**纯单向注入**——`glassbox/effectors/picokvm/` 下 `effector.py`/
  `rpc.py` **零 `read/recv/*_report` 路径**（仅 `_wait_for_iphone_hid_ready`）；要接收 host←device
  报文得给 Luckfox USB gadget 加 0x41 复合接口 + 扩固件/RPC，固件级未知、未上机。
- 利好仅一条（盲文是标准 HID class，**明确不在 MFi Program**，绕开 iPad trackpad 的 MFi 墙），不足翻盘。
- **若真要探**：先用**现成 HID 盲文显示器**插 USB-C iPad 验"iOS 原生绑定 + 抓到 uncontracted cell 流"，
  **绝不先动固件**。

### Rank 5 — HDMI 音频采 VoiceOver TTS — `holds=false`

HDMI 确实带系统音频，**但 VoiceOver 语音被 iOS 当特殊流单独处理、默认不走 HDMI**，锁在
`设置 > 辅助功能 > 旁白 > 音频 > Send to HDMI` 这个**专门开关**后（开关存在本身即证明默认 OFF；大量
AppleVis 用户接 HDMI 听不到旁白佐证）。即便开了也有副作用（本地扬声器可能失声、静音/勿扰可能抑制镜像
音频）。且 **glassbox 当前零音频栈**，等于新建采集 + TTS-ASR 管线（又一层有损）+ 仍需设备端一次性开
VO+Send-to-HDMI。三重不契合，不建议投入。

---

## 6. 建议

1. **继续 rank 1（Voice Control overlay）**：坐标 HID tap/drag scroll 小样本已过；labeled replay
   harness 已建立，并在一帧 Item Names 样本的 12 条 manifest 上通过。下一步仍不是直接接
   `accessibility_id`，而是扩展到更多页面/滚动位置，验证 Item Names badge-to-target mapping 之后再打开
   稳定 `WhiteboxHint.accessibility_id` 写入。Item Numbers/Grid 只做 frame-local action anchor。
2. **并行保住 rank 2（synthetic）作为默认底座**，rank 1 叠加其上，共享 `WhiteboxHint`/签名出口；守
   AGPL/VLM/OCR-only 三红线。
3. **最便宜先行件 rank 3（FKA Tab-walk）**：做 action 层"什么真的可聚焦"交叉校验，明确只给几何。
4. **放弃 rank 4/5**（核验均 holds=false）：盲文撞 PicoKVM 单向注入结构墙；TTS 撞 Send-to-HDMI 默认
   OFF + 零音频栈。

**对评测的意义**：拿到真 label/role/value 会显著增强 L2 outcome verifier 的语义校验（"开关是否真被
打开"正是 synthetic 最弱、overlay 最强处）。见 `docs/design/glassbox_evaluation_layers.md §7` 开放
问题 #1（screenshot-only verifier）——本评估为其提供了一条比纯像素更强的 label/value 来源。

---

## 7. 核验来源

- Voice Control overlays（Show Names/Numbers/Grid 渲染 a11y 名/数字为屏上文字）— ✅ 确认：
  https://a11ysupport.io/learn/at/vc_ios · https://support.apple.com/en-us/111778 ·
  https://www.deque.com/blog/new-in-ios-13-accessibility-voice-control-and-more/
- FKA 焦点环仅几何、不渲染 label — ✅ holds=true：AbilityNet（iOS 18 外接键盘指南）· Appt.org
  accessibility-focus-indicator · Apple WWDC21-10120 / HIG keyboards
- HID 盲文显示器=点阵 bitmap 非文本 — ❌ holds=false：https://support.apple.com/guide/iphone/use-a-braille-display-iph73b8c43/ios ·
  USB HUTRR78（usage page 0x41）· NVDA PR #12523（文本→盲文在屏幕阅读器内部完成）
- VoiceOver TTS 默认不走 HDMI（须 Send to HDMI 开关）— ❌ holds=false：Apple VoiceOver 音频设置文档 ·
  AppleVis "deep dive VoiceOver settings" · AppleVis 论坛 "no VoiceOver speech over HDMI"
- 仓库 claim（`accessibility_id` 仅夹具赋值、keymap Tab/Space/Shift、PicoKVM 单向注入）— ✅ 本文作者
  对 `5881a28` 源码逐条核验。

**Caveats**：(1) rank-1 的 **Voice Control + 坐标 HID tap/drag scroll**已在 iPad mini 7 小样本证实；
text tap、keyboard visible insertion、wheel scroll 均已有负/弱样本，仍未闭合。(2) Voice Control overlay 的 OCR 解析
需处理 overlay 遮挡；当前 parser 是 mode-scoped，不负责自动识别 `Item Numbers` vs `Numbered Grid`；
数字/grid marker 是 frame-local；Item Names 自动映射已能用 labeled replay gate 复放，但仍需更广样本后
才能作为默认稳定 identity。(3) 5 通道研究的两个 search 角度（VoiceOver-audio 细节、external-introspection）
在 workflow 中未产出结构化 finding，相关结论由对抗核验判词 + 既有领域常识补足。
