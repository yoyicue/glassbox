# iOS AssistiveTouch Safe Primitives

这份目录是 `glassbox.ios.assistive_touch.assistive_touch_safe_primitives()` 的落盘版本。
运行时可通过 `phone.assistive_touch_run_primitive(name)` 执行这些菜单指令;不在目录里的
AssistiveTouch 系统危险项继续由 `assistive_touch_tap_menu_item()` 在发送物理输入前拦截。

JSON 目录: `docs/reference/ios_assistive_touch_primitives.json`(同目录,代码读取路径)

| Primitive | 菜单项 | 路径 | 层级 | 效果 |
|---|---|---|---|---|
| `assistive_touch.notification_center` | 通知中心 | - | level1 | open_notification_center |
| `assistive_touch.app_switcher` | App切换器 | - | level1 | open_app_switcher |
| `assistive_touch.device` | 设备 | - | level1 | open_device_menu |
| `assistive_touch.hold_and_drag` | 按住并拖移 | - | level1 | enter_hold_and_drag |
| `assistive_touch.home` | 主屏幕 | - | level1 | go_home |
| `assistive_touch.control_center` | 控制中心 | - | level1 | open_control_center |
| `assistive_touch.rotate_screen` | 旋转屏幕 | 设备 | device | open_rotate_screen_menu |
| `assistive_touch.volume_up` | 调高音量 | 设备 | device | volume_up |
| `assistive_touch.volume_down` | 调低音量 | 设备 | device | volume_down |
| `assistive_touch.more` | 更多 | 设备 | device | open_more_menu |
| `assistive_touch.screenshot` | 截屏 | 设备 > 更多 | more | take_screenshot |
| `assistive_touch.shake` | 摇动 | 设备 > 更多 | more | shake |
| `assistive_touch.accessibility_shortcut` | 辅助功能快捷键 | 设备 > 更多 | more | accessibility_shortcut |
| `assistive_touch.reachability` | 便捷访问 | 设备 > 更多 | more | reachability |
| `assistive_touch.more_app_switcher` | App切换器 | 设备 > 更多 | more | open_app_switcher |

排除项: `锁定屏幕` / `操作按钮` / `SOS` / `重新启动` / `关机` / `关闭电源` / `锁屏`。

使用示例:

```python
phone.assistive_touch_run_primitive("assistive_touch.control_center")
phone.assistive_touch_run_primitive("assistive_touch.screenshot")
```
