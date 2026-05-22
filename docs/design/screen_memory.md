# UI Transition Graph / 屏幕记忆 — 设计草案

> 状态:**草案 v0**(2026-05-16)。等拍板后再拆 milestone / 落代码。
> 关联:`gui_understanding.md` §6.4(已知 App 锚点缓存)、`../roadmap.md`、
> `glassbox/profile.py`(`match_vc` / whitebox)、`glassbox/obs/recorder.py`。

---

## 0. 问题 & 目标

当前 glassbox 有三类「记得住」的东西,但都不是经验记忆:

- **缓存** — `perceive` 帧间静止复用、`CachedKimi` 跨 run 的精确帧缓存(`sha256` 原始字节)。
- **静态先验** — `profile` / `whitebox`,出厂知识,不随走查更新。
- **录像** — `obs` 的 `events.jsonl`,写下来了但 agent 不回查。

两个能力缺口:

1. **认不出「看过的界面」** — `CachedKimi` 是逐字节哈希,状态栏变一下就 miss;
   `match_vc` 能做语义识别,但只覆盖 profiled app 的已知 VC。
2. **不记得操作元素在哪** — 每次 `perceive()` 重跑 OCR,没有元素位置地图。

**目标**:做一个 **UI Transition Graph(UTG)** 组件,把每次走查观察到的屏幕
归纳成一张图 —— 节点是屏幕状态(存元素布局),边是转移(点了什么 → 到了哪)。
它提供:屏幕识别、元素位置先验、转移规划的地基。

业界最佳实践对齐:UTG + pathfinding 规划(Agent+P)、一次探索复用
(GUI-Xplore)、屏幕知识 RAG(KG-RAG)。

---

## 1. 概念

```
            tap(设备cell)              tap(返回)
  ListVC ─────────────────▶ MainVC ─────────────▶ ListVC
    │                         │
    │ tap(设置)                │ tap(模式)
    ▼                         ▼
  SettingsVC               ModePanel
```

- **节点 ScreenNode** = 一个屏幕状态 + 它的元素布局(= 位置记忆)。
- **边 ScreenEdge** = `(from, action, to)`,action = 在某元素上的某操作。
- 图按 **app(bundle_id)+ app 版本** 分库持久化,跨 run / 跨 session。

定位:`profile/whitebox` 是**出厂先验**,UTG 是**跑出来的经验记忆**,两者互补 ——
节点身份优先用 whitebox(`current_vc`),UTG 补 whitebox 没有的像素位置。

---

## 2. 数据模型(pydantic,对齐 `cognition/base.py` 风格)

```python
class RememberedElement(BaseModel):
    key: str                      # 节点内稳定 id(见 §4)
    box: Box                      # 最近一次/平滑后的位置  ← 位置记忆
    type: ElementType
    text: str | None = None
    intent_label: str | None = None
    whitebox_hint: WhiteboxHint | None = None
    volatile: bool = False         # 内容易变(列表项等),位置不可信
    visit_count: int = 0

class ScreenNode(BaseModel):
    screen_id: str                 # 稳定主键(见 §3)
    vc_name: str | None = None     # match_vc 命中时的 VC
    signature: ScreenSignature     # 结构签名(识别用)
    elements: list[RememberedElement] = []
    scene_type: str | None = None
    app_state: dict[str, str] = {}
    visit_count: int = 0
    first_seen: float; last_seen: float

class ScreenEdge(BaseModel):
    from_id: str
    to_id: str
    action_op: str                 # tap / swipe_up / ...
    element_key: str | None        # 在哪个元素上操作
    count: int = 0                 # 观察到几次(置信度)

class UTG(BaseModel):
    bundle_id: str
    app_version: str | None = None
    nodes: dict[str, ScreenNode] = {}
    edges: list[ScreenEdge] = []
```

---

## 3. 屏幕签名 & 识别(认出「看过的界面」)

**原则:结构化签名,不用逐字节哈希。** 主键 `screen_id` 的来源,优先级:

1. **whitebox 命中** → `screen_id = vc_name`(语义级,最强)。
2. **未命中** → 用 `ScreenSignature` 做最近邻匹配。

```python
class ScreenSignature(BaseModel):
    stable_texts: list[str]        # 稳定区文本(标题/按钮/nav),已归一化、排序
    type_histogram: dict[str, int] # 元素类型计数
    phash: str                     # 帧感知哈希(辅助)
```

- **稳定区** = 排除易变内容(列表项、时间、计数)。签名只取标题、按钮、导航、
  开关等结构性元素 —— 否则设备列表每次刷新都变成「新屏幕」。
- 识别:`recognize(scene)` 算签名 → 和现有节点比 `similarity()`(Jaccard(文本)
  + 类型直方图距离 + phash 汉明距),> 阈值 → 同节点;否则新建。
- 这就是「认出看过的界面」:容忍像素噪声,识别结构相同的屏。

---

## 4. 元素位置记忆

节点内每个元素要有跨访问稳定的 `key`,才能说「登录按钮上次在 box X」:

```
key = norm_text(text)              若有文本
    | "asset:" + whitebox.asset_match   若有 whitebox
    | type + "@" + 网格粗定位           兜底(粗划 6×N 网格)
```

- 每次访问该节点 → 元素按 key 合并:位置做平滑(指数移动平均或直接最近一次),
  `visit_count++`,记 `intent_label` / `whitebox_hint`。
- 列表项等标 `volatile=True` —— 位置不作为可信先验。
- **用法**:`find_text` / `tap_intent` 先查记忆拿位置先验 —— 可用于
  缩小 OCR ROI、给候选打分、或在 OCR 短暂失败时兜底。**永远是先验,不是真相**;
  实际操作前仍以当帧感知为准(防 app 改版 / 布局变化)。

---

## 5. 转移边 & 构建

**两种构建途径,共用同一套归并逻辑:**

- **在线被动** — `ScreenMemory` 挂进 `Phone`:每次 `perceive()` 后
  `observe(scene, last_action)` —— 识别或新建节点、合并元素布局;若上一步有
  action,则补一条 `from→to` 边。零额外感知开销。
- **离线归纳** — `build_from_recording(run_dir)`:回放 `obs` 的 `events.jsonl`
  (snapshot/scene/action 序列)灌进图。**把已有录像变成记忆** —— 历史 run 直接复用。

---

## 6. 查询 API

```python
class ScreenMemory:
    def observe(self, scene: Scene, last_action: Action | None) -> ScreenNode
    def recognize(self, scene: Scene) -> ScreenNode | None      # 见过吗?
    def locate(self, screen_id, element_key) -> Box | None      # 元素在哪?
    def expected_elements(self, screen_id) -> list[RememberedElement]
    def path(self, from_id, to_id) -> list[ScreenEdge] | None   # 规划:BFS/Dijkstra
```

`path()` 让 planner 把「到达某屏」化为图上 pathfinding(Agent+P 模式),
避免重复探索。

---

## 7. 持久化

- 一 app 一库:`memory/utg/<bundle_id>.json`(或 SQLite,边多时)。
- 按 `app_version` 分版本 —— app 升级 → 旧图标 stale,不混用。
- `Phone` 启动时按 bundle_id 加载,像 profile 一样。

---

## 8. 与现有组件的关系

| 组件 | 角色 | 与 UTG 的关系 |
|---|---|---|
| `profile` / `whitebox` | 出厂静态先验 | 给节点 `vc_name`、元素 whitebox 身份;UTG 补位置 |
| `match_vc` | VC 识别 | 直接做 `screen_id`,最强节点主键 |
| `obs.Recorder` | run 录像 | UTG 离线构建的原料 |
| `CachedKimi` | 帧级缓存 | 正交;UTG 节点可顺带缓存 describe 结果,键从 `sha256` 换成 `screen_id` |
| `perceive` 帧间缓存 | 会话内静止复用 | 正交,保留 |

UTG 是 `gui_understanding.md` §6.4「锚点缓存」的成熟形态。

---

## 9. 落地分期(建议)

| 阶段 | 内容 | 验收 |
|---|---|---|
| a | `ScreenSignature` + `recognize` | 同一屏不同帧识别为同节点;不同屏不混 |
| b | 节点元素布局合并 + `locate` | 二次进同屏能查到元素位置先验 |
| c | 转移边 + `observe` 挂进 Phone + `build_from_recording` | 跑完一轮走查能导出 UTG |
| d | `path()` 规划查询 | planner 能在图上算转移路径 |

阶段 a/b 不依赖 HID 桥,可立即做;c 的在线模式依赖走查真正跑起来(M1 之后),
但离线 `build_from_recording` 用现有录像就能验证。

---

## 10. 开放问题 / 风险

| 问题 | 处理方向 |
|---|---|
| 动态屏(列表内容变)签名漂移 | 签名只取稳定区;列表项标 `volatile` |
| 元素位置在可滚动屏不可信 | `volatile` 标记;位置仅作先验不作真相 |
| 签名阈值难定(同屏判异 / 异屏判同) | 阶段 a 用真实走查帧调阈值,autoresearch 式打分 |
| app 改版导致整图 stale | 按 `app_version` 分库;版本不符则冷启动 |
| 冷启动空图 | 优雅降级到纯感知,图随走查自增长 |

## 11. 不在本草案范围

- 跨 app 的图迁移 / world model(GUI-Xplore 式泛化)—— 远期。
- planner 本身的决策策略 —— UTG 只提供 `path()`,怎么用是 planner 的事。
- 元素位置的学习型预测(只做记忆 + 先验,不做模型)。
