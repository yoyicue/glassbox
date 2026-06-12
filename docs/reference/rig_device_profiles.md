# Rig device profiles — 默认配置与设备状态速查

> **这是什么**:本 rig 两台真机的权威配置档案——locale、输入能力、对应
> floor/lane、以及会漂移的设备状态(带 as-of 日期)。跨会话的"设备到底是什么
> 配置"问题以本文为准;**易变状态(SIM、系统弹窗、待装更新)每次上 rig 前仍
> 应实际核验**,本文只记录最后一次确认值。
>
> 身份键核验命令(fixture 是机器可信源,本表是人读摘要):
>
> ```bash
> uv run python -c "
> import json
> for f in ['iphone_settings_baseline','reliability_baseline','canonical_primitives_baseline','clock_tabs_baseline']:
>     c = json.load(open(f'skills/regression/fixtures/{f}.json')).get('config', {})
>     print(f, {k: c.get(k) for k in ('phone_model','language','region','task_set','evaluation_cell')})"
> ```

## iPhone 17 Pro Max

| 项 | 值 |
|---|---|
| `GLASSBOX_PHONE_MODEL` | `iphone_17_pro_max`(**代码内默认**,可不设) |
| 设备 UI locale | **English / 地区 HK**(2026-06-13 直读 Settings > General > Language & Region:"Hong Kong (China)",首选语言 English + 简体中文)→ 所有跑分用 `--language en --region HK` |
| Floor fixture | `skills/regression/fixtures/iphone_settings_baseline.json`(en/HK, `ios_settings_clean_hdmi`;2026-06-13 区域声明修正,见 fixture note) |
| Nightly lane | en/HK,floor 比对 **blocking**(`rig-nightly.yml` matrix) |
| 输入 | 仅 AssistiveTouch 指针;滚动 = swipe-fling(过冲 + 落带后 ~25-36px 蠕动);精确滚轮间歇性失效 → 默认关;键盘 = 文本 + 少数组合键 |
| 已知陷阱 | `make computer-use-success-rate-ios-settings` 不传 `--language` → 落到代码内 zh-Hans 默认,**与物理英文设备错配**;直接用 `run-ios-settings`/`run_full` 加 `--language en --region HK`。注意 **"WLAN" 标签在 HK 区域同样显示**——它是大中华标记,不能用来区分 CN/HK(2026-06-13 教训:CN 声明就是这么推错的;区域以 Language & Region 页直读为准) |

设备状态(as of 2026-06-12,上 rig 前核验):

- **无 SIM**(蜂窝网络行显示 "No SIM" → `device_unavailable` entry-exempt,
  completion 中性;恢复 SIM/eSIM 后覆盖率才会把它算回来)
- Apple Account 受信号码确认弹层已人工确认(2026-06-12),不会再弹
- 曾有"今晚安装软件更新"排程——iOS 版本若变,地板按新基线对待

## iPad mini 7

| 项 | 值 |
|---|---|
| `GLASSBOX_PHONE_MODEL` | `ipad_mini_7`(**必须显式设置**) |
| 设备 UI locale | **English / 地区 HK** → 所有跑分用 `--language en --region HK` |
| Floor fixtures | `reliability_baseline.json`(en/HK)、`canonical_primitives_baseline.json`、`clock_tabs_baseline.json` |
| Nightly lane | en/HK;canonical primitives 比对 **blocking** |
| 输入 | 原生指针 + 可靠滚轮(`kvm_app.wheelReport` RPC,见 [picokvm_ipad_wheel.md](picokvm_ipad_wheel.md));键盘系统导航可用。**滚动密集型工作优先 iPad** |

## 共享代码默认 / .env 纪律

- 代码内 locale 默认 **zh-Hans**;**永不在 `.env` 里钉 `GLASSBOX_LANGUAGE`**
  (会翻转包括 smoke 套件在内所有调用方的全局默认)——locale 只用每次运行的
  `--language/--region` 旗标。
- 本 rig `.env`(gitignored):`GLASSBOX_PICOKVM=1`、icon 检测器 omniparser
  (AGPL 本地 opt-in,不入仓)、VLM 经 env 开启(计费)。注意:benchmark 的
  `config.vlm_enabled` 只记录 `--vlm` 旗标——宿主 env 仍可能让 VLM 实际参与
  (iPhone 地板 fixture note 已记录此口径)。
- Worktree 必须用 `make worktree` 创建(symlink `.env`);裸 `git worktree add`
  → 无 `.env` → 静默 NoOp effector。
- 多轮基准:`GLASSBOX_PICOKVM_ROBUST_CAPTURE=1` 已是驱动默认;流打开有界重试
  `open_retry_attempts=4`(翘死债仍可能命中,单进程 5 轮实测 4/5 存活,
  2026-06-12)。
