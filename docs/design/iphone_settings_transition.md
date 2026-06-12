# iPhone Settings transition recognition — forensics & fix design

Status: **landing lever-by-lever — S6 (`ea13305`), S1+S2 (PR #92), S3
(nav-band mint fix; reviewed flip allow-list in
`skills/regression/fixtures/ios_settings_mint_flip_allowlist.json`), S4
(comparator fold-normalize fallback; the review's `ios_settings_*` ↔
`com.apple.settings.*` equivalence was confirmed in the run's audit ledger —
got `ios_settings_wallpaper`/`_notifications`/`_developer`/`_apps`/`_focus`
vs wanted `com.apple.settings.*` — and implemented; token-level pins in
`skills/smoke/test_ios_settings_transition_replay.py`; no re-mint pin flips:
every remaining rejected group re-mints `None` or a genuinely different page)
and S5a (skill-side entered_unverified 归因税则:
`navigation.classify_unverified_transition` 产出
same_page / mint_none / name_mismatch / unknown_scene 四类——locale-neutral by
construction;left-the-root 类目改为刻意 back-out → 重接地 → 单次重试,绝不在
已进入页上重按根坐标,iPhone-only(iPad 分屏侧栏行真实可见,floor 行为不变);
corpus 类目钉在 replay 测试的 `S5A_REPLAY_CATEGORY_PINS`,报告新增 additive
仅取证 `unverified_transitions` 列表;Wallpaper grp_000050 离线 strict-xfail
保持——S5a 改运行时恢复,不改离线 re-mint)and S5b(核心梯子边沿,**landed
flag-gated**:`GLASSBOX_TAP_RETRY_IDENTITY_GUARD`,默认关——verification
failed/unknown 但 before/after 铸造页身份已变(S4 同款 fold 比较,
`semantic_plan.page_identity_changed`)时,tap 梯子的同目标重按支路被禁止
(orchestrator `_identity_guard_stop`,在既有 advance 上的 edge、非新 rung),
计划以 semantic unknown 停止而非在已进入页上重按;act-63-65 形状由语料记录
信号重放钉住(`test_ios_settings_transition_replay.py` S5b 节:flag-on 单
rung 停止 + flag-off 复现记录的双 rung 形状),平台中立(ios/ipados 参数化
钉)、默认关字节不变(钉);**默认开翻转 = rig A/B 交付物**,与 P2 梯子本身
同一门槛;Wallpaper strict-xfail 仍保持——S5b 改运行时重试行为,不改离线
re-mint)are landed; forensics snapshot as of `8eb69f7` (2026-06-12).**
Produced by a 5-agent forensic pass over the live repro
(`run_2026_06_12_06_04_38_737160`: 144 actions, ~49 min, iPhone 17 Pro Max,
en/CN) — 3 anatomists (ledger data / code path / iPad working precedent) → fix
design → adversarial review that independently re-verified the ledger rows and
file:line claims. Methodology template:
[`ipad_settings_state_machine.md`](ipad_settings_state_machine.md) (C1–C5 →
levers → outcome-gated validation).

## 0. What the forensics overturned

Every prior theory about this failure died on the data:

| 此前以为 | 实证 |
|---|---|
| 报告说 visits=[root]、0/17 覆盖 | **那不是这次 run 的报告**:`run_full` 每次启动 unlink 共享报告路径(run_full.py:254-255),真报告被 06:57 一次 9 动作的重试覆盖。144 动作的 run 干净跑完(`run.finished: finished`),**16/22 候选 tap 语义验证成功** |
| zh 规范名期望 vs en 页面(主嫌疑) | **证伪**:expected_state 本就是 zh+en+bundle 多值 `any_of`;WLAN 行 `any_of=[settings/无线局域网, settings/Wi-Fi, com.apple.settings.wi-fi, settings/WLAN, …]` → 实测 `page_id matched: settings/WLAN` |
| 36 次 back = 拒绝性撤退 | 21/36 跟在成功 tap 之后 = 正常"进入→记录→返回"循环 |
| 滚动是墙(昨夜结论,已在台账修正) | 34 次 drag 抵达折叠线下;非墙 |

真实损害 = **4 个假拒绝**(Wallpaper / 声音与触感 / Face ID与密码 / Developer
— 全部物理进入,铸出的 page_id 不在 `any_of` 里)+ 报告证据被毁 + 流死亡
(rounds 1-4 preflight 全灭;run 中 5 次 transport_failed)。

## 1. 结构性根因(C1–C5,全部经对抗复核)

- **C1 — 期望词表是"机架形状"而非"locale 形状"。** `any_of` 由
  `navigation.py:495-504` → `policy.py:1266-1284` 构建,EN 别名来自
  `ROOT_SEARCH_QUERIES_EN/GREATER_CHINA_EN`(policy.py:197-221)——那是**搜索
  查询表**,编码的是 iPad mini 7 的物理行标签:`Face ID与密码 → 'Touch ID &
  Passcode'`(policy.py:210,iPad 是 Touch ID!)、`声音与触感 → 'Sounds'`
  (:202,iPad 页题)。`sections.py` 的 SectionVocab(`_EN_DISPLAY:120,124` 有
  正确的 'Sounds & Haptics' / 'Face ID & Passcode')**从未被咨询**。iPad
  en/HK 12/12 通过是"标签运气":iPad 物理标签恰与表一致。
- **C2 — settings_detail 身份从正文带标题猜测铸造,结构性排除真导航标题。**
  `_semantic_detail_title_candidate`(glassbox/ios/scene.py:749-772)只接受
  `cy ≥ h*0.11`(≈107px)的元素,而 iPhone 捕获帧上居中导航标题在 cy≈92px —
  于是 'Silent Mode'(首行)被当成页题铸出 `settings/Silent Mode`(真题
  'Sounds & Haptics' 可见但被排除);同因产出 `settings/CURRENT`、
  `settings/Paired Devices`(Developer 页)。姊妹分支 scene.py:333 已用
  nav-band 标题——本分支(:266-273)没有。
- **C3 — 三个互不协调的命名空间做精确字符串比对。**
  `verify_expected_state`(glassbox/action/semantic_plan.py:400-416)对
  OCR 铸造的 `settings/<title>`、builder slug 的 `com.apple.settings.<slug>`、
  VLM 自由生成的 token(实测 `faceid_passcode` vs 表内 `face-id`)做
  `actual in wanted` 精确成员判断。
- **C4 — "物理成功但验证失败"被归因为 no-transition 并破坏性重试。**
  重试梯子在**已进入的子页上重按同一坐标**(ledger acts 63-65/74-76/96-98;
  22 次 'wrong_target' 审计归因);depth-0 期望失败后循环静默 `continue`
  (navigation.py:949-951),人留在已进入页上、访问不记账,下轮再重新接地。
- **C5 — harness 销毁证据并在基建故障上不体面地死亡。** 报告 unlink
  (run_full.py:254-255);`return_to_settings_root`(navigation.py:896)无
  try/except(滚动循环在 :835-840 有同款保护),帧源死亡被制造成
  `limits_hit=['exception']`。

## 2. 杠杆(S1–S6,评审修正已折入;按落地顺序重排)

执行顺序(评审建议):**S6 → S1+S2(首发 PR)→ S3 → S4 → S5a → S5b**。
每步独立 PR、`make check` 绿;离线回放先行,rig 最后(n=1 验证 → n=5 floor)。

- **S6(先行,iPad 零风险)— 证据保全 + 体面死亡。**
  (a) navigation.py:896 的 `return_to_settings_root` 加与 :835-840 同款
  try/except → `limits_hit.add('return_to_root_failed')` + 体面终止;
  (b) run_full 不再 unlink 既有报告(改为时间戳改名保留);
  (c) 冒烟测试:模拟 SettingsRootUnreachable → 报告完成且分类正确;连续两次
  run_full 两份报告并存。
- **S1 — 提交离线转场回放语料 + 回放 harness(strict-xfail 钉住现状)。**
  从 144 动作 run 提取 22 个候选 tap 组(zh 规范 target、录得的
  expected_state、after-scene JSON、录得 verdict)+ 根场景 →
  `skills/golden/ios_settings_transitions/`。**提交式 scrubber**(账户显示名、
  SSID、蓝牙设备名、电话数字片段)+ 覆盖全部场景的 scrub 断言测试 + 语料
  floor 测试(非空、覆盖 22 组)+ 生成命令内嵌。16 组钉 green、2 组正确拒绝
  钉 rejected、4 组假拒绝钉 `xfail(strict=True)`。
- **S2 — expected_state 标签扩展接入 SectionVocab seam(与 S1 同 PR)。**
  `page_id_route_label_candidates`(policy.py:1266-1284)在既有搜索查询别名
  之后,union `section_vocab_for(language, region).all_terms(root_section_for_
  canonical_label(canonical))`(sections.py:81/190/268)。不新增字面字符串、
  无设备维度、zh 输出字节不变(单测钉死)、iPad 超集断言(对 iPad fixture 里
  每个已验证 payload,新 any_of ⊇ 旧 any_of)。验证:S1 语料上
  Face ID与密码 组 xfail→pass;16 组不变;2 拒绝不变。附 route 路径
  (`page_id_route_enabled=true`)单测。
- **S3 — 核心铸造修复:settings_detail 页题取 nav-band 优先**(scene.py
  :266-273 分支对齐 :333 姊妹分支)。验证:对 144 run 的 95+ 捕获场景 +
  committed `skills/golden/ios_scene` 全量重放 classify,**翻转允许清单由生成
  器产出、人工复核后提交**(已知成员:scn_000305/306 settings/CURRENT→
  settings/Wallpaper、scn_000357 settings/Silent Mode→settings/Sounds &
  Haptics…);显式 iPadOS 回放断言(改动经 `_classify_ios_compat_fallback`
  可达 iPad 路径,ipados/scene.py:98,139-140)。
- **S4 — 比较器:page_id 成员判断加 fold-normalize 回退**(精确匹配快路径
  保留;casefold + 去非字母数字:`faceid_passcode ≡ face-id-passcode`)。
  正例用 ledger 实测 VLM token;负例钉不碰撞('settings/Sounds' ≁
  'settings/Silent Mode')。评审补充:加 tested 的 `ios_settings_*` ↔
  `com.apple.settings.*` 等价,或显式记录 VLM 描述场景仍可假拒绝。
- **S5a(skill 侧,先行)—** 归因税则:页面已变化的验证失败 =
  `entered_unverified`(非 no-transition),刻意 back-out 而非静默
  continue(navigation.py:949-958、:1002-1009、重按块 :971-989)。
- **S5b(核心,自带 flag)—** 梯子边沿:expected 失败但 before/after 页身份
  已变 → 停止重按同坐标。Loop 级离线回放验证(mock-Phone 范式照
  test_readonly_walkthrough.py)。

## 3. 验证分层(评审要求显式划分)

- **CI 合并门内**(`make check`):22 组语料回放、golden ios_scene 语料、
  S3 翻转允许清单、iPad 超集断言、zh 字节不变断言。
- **仅本地工件回放**(rig 主机,artifacts 在场):95 场景全量 classify diff、
  144 动作 loop 级回放。
- **rig 终验**:n=1 单轮(预期:visits ≥ 16+4,无 wrong_target 重按)→
  n=5 floor 候选 → 谱系表新行(守卫强制)。

## 4. 已否决

- 为 iPhone 复制一份 `ROOT_SEARCH_QUERIES_IPHONE_EN` 表(继续机架形状反模式;
  词表归 SectionVocab seam 所有)。
- 砍掉精确匹配、全面模糊比较(C3 修复以回退方式叠加,快路径保留,负例钉防
  碰撞)。
- 跳过 S1 直接修(无回放语料则 S2-S5 的每一步都退化为"再烧一轮 rig 看看")。

## 5. 并行第二债(不在本设计内,已具名)

多轮间 PicoKVM 流翘死(rounds 1-4 preflight 全灭;run 中 5 次
transport_failed)。S6 让它不再伪装成 walkthrough exception;其本体修复
(流会话级恢复/重建)另立工单。

### 5.1 环境危害族:iOS 自呈现安全弹层(Apple Account safety sheet)

证据:`iphone_transition_n1`(2026-06-12,两次复现)。run 抵达 settings/root
后 iOS 自动弹出 Apple Account 安全卡片 "Is this still your phone number?"
(全屏单卡;右上角 close-X ≈ (0.90w, 0.11h);底部按钮 "Keep using <number>" /
"Change trusted number")。三个失败模式与修复(全部含冒烟测试钉):

1. **逃逸梯子对弹层全盲(core)。** OCR 级联里没有弹层类:弹层的短值行
   ("+1 …"、"Date added:")摊成 icon-grid 形状 → `springboard(0.82,
   icon_grid)`,后续 perceive 落 `unknown(0.2)`;梯子打出 back_gesture、
   tap_xy(24,83)(左上角镜像 miss)、tap_xy(394,938)(贴着底部
   "Change trusted number" 的盲点)、back_gesture——全部无效。(同屏 UTG 节点
   的 `scene_type='modal'` 来自 VLM(`vlm_platform_scene_kind`),与 OCR 级联
   无关——能"认出"的层与决策用的层不是同一层。)修复:
   `glassbox/ios/scene.py` 新增 `modal_sheet` 分类(veto+anchor+abstain:
   右上带 close-X 锚 + 卡片形/安全弹层词表锚,排在 springboard icon-grid 尾
   判之前,顺带否决了 icon_grid 误判)+ `glassbox/ios/recovery.py`
   `dismiss_modal_sheet_overlay`(只点右上 close-X 区,READ-ONLY,按钮行在场
   也绝不触碰)。技能侧梯子(`skills/regression/ios_settings/recovery.py`)
   加 bounded rung:每次恢复 episode ≤2 次 dismiss,然后 abstain 回既有
   unknown 梯子;`_return_one_level` 见弹层证据立即 abstain(不再左上角
   镜像 miss)。
2. **S6 收尾(skill)。** `navigation.py` post-child-crawl 的
   `return_to_settings_root`(原 :1258 及 depth>0 兄弟位)是最后一个未包裹
   位点,恢复耗尽时 `SettingsRootUnreachable` 以裸异常逃逸 → rc=1 两次。
   已按 S6 同款包裹:`limits_hit.add('return_to_root_failed')` + 体面返回,
   报告总能写完。
3. **Apple-Account-review row en blocked-safety vocab(skill,具名工单
   落地)。** en 根行 "Review Apple Account phone number" 即该弹层族的锚行,
   加入 `policy.py UNSAFE_OR_NON_NAV_TEXT`("Review Apple Account" 子串,
   与既有 zh Apple账户/iCloud 同族),drill-down 永不主动点它。

夹具纪律:测试场景全部按记录形状**构造**(synthetic 数字/无账户名/无
SSID),未提交本次 run 的任何原始 OCR;隐私守卫测试通过。
