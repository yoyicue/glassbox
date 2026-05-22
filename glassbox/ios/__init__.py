"""glassbox.ios — iOS-specific glassbox primitives.

通用 iOS 状态识别与动作几何,供 glassbox 主循环与各 eval 适配器消费:

    scene       SceneClassifier — settings_root/search/detail/system_search/...
    recovery    前台恢复原语(dismiss_system_search 等)
    safe_area   IOSSafeArea — back/tab/search/edge 的安全区几何
    progress    无进展检测(same_visible_page / trace_payload_no_progress)
    springboard SpringBoard / App Library 识别与开 app

这些是 glassbox primitive,不是 Settings 专属规则;Settings 行名 alias、
root coverage 策略等只能留在 skills/regression/ios_settings/。
"""
