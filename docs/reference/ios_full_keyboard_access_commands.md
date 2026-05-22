# iOS Full Keyboard Access Commands

Captured on 2026-05-19 from:

- Device: iPhone 17 Pro Max, iOS 26.5
- Path: Settings > Accessibility > Keyboards & Typing > Full Keyboard Access > Commands
- Locale: zh-Hans

## Confirmed shortcuts

| Command | Shortcut |
|---|---|
| 帮助 / 显示帮助 | Tab-H |
| 前移 | Tab |
| 后移 | Shift-Tab |
| 向上移动 | Up Arrow |
| 向下移动 | Down Arrow |
| 向左移动 | Left Arrow |
| 向右移动 | Right Arrow |
| 激活 | Space |
| 主屏幕 | Cmd-H |
| App 切换器 | Cmd-Up Arrow |
| 控制中心 | Cmd-C |
| 通知中心 | Cmd-N |
| Siri | Cmd-S |
| 移到开头 | Tab-Left Arrow |
| 移到结尾 | Tab-Right Arrow |
| 移到下一个项目 | Control-Tab |
| 移到上一个项目 | Control-Shift-Tab |
| 查找 | Tab-F |

## Commands shown without assigned shortcuts

- 向上轻扫
- 向下轻扫
- 向左轻扫
- 向右轻扫
- 缩小
- 放大
- 向左旋转
- 向右旋转
- 双指触摸
- 双指向下轻扫
- 双指向左轻扫
- 双指向右轻扫
- 双指向上轻扫

## Notes

- Device command shortcuts were changed on-device from `Fn` to `Cmd` on 2026-05-19 and verified from the Commands page.
- Glassbox `phone.home()` currently uses the regular hardware-keyboard `Cmd-H` path, not the Full Keyboard Access `Fn-H` binding.
- Glassbox `phone.recents()` currently returns Home first, then uses the Full Keyboard Access `Cmd-Up Arrow` App Switcher binding.
- Current runtime probe evidence is mixed: `cu09 recents` on 2026-05-19 still landed on the Settings Commands page and was correctly recorded as `semantic_status=failed`. Do not treat `recents()` as reliable until the binding/path is repaired and re-probed.
- Glassbox `phone.control_center()` currently returns Home first, then uses the Full Keyboard Access `Cmd-C` Control Center binding. This is a system-panel semantic, not a generic copy action.
- Glassbox `phone.notification_center()` currently returns Home first, then uses the Full Keyboard Access `Cmd-N` Notification Center binding.
- Screenshots used during capture: `/tmp/probe/315_commands_dump1_dump_after.png`, `/tmp/probe/318_commands_dump_mid_dump_after.png`, `/tmp/probe/317_commands_dump2_dump_after.png`.
- Panel validation screenshots: `/tmp/probe/380_control_center_homefirst_control_center_after.png`, `/tmp/probe/382_notification_center_homefirst_notification_center_after.png`.
