"""Concise iOS Settings example using the public glassbox.ai facade."""

from __future__ import annotations

from glassbox.ai import RunArtifacts, open_phone
from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY


def run_settings_about_example() -> RunArtifacts:
    """Open Settings > General and verify About using only ``glassbox.ai``."""
    with open_phone(
        policy=DEFAULT_SETTINGS_POLICY,
        run_name="settings-about-ai-native",
    ) as phone:
        phone.goto("通用")
        phone.expect_visible("关于本机")
        return phone.save_report()


if __name__ == "__main__":
    artifacts = run_settings_about_example()
    print(artifacts.report_path or artifacts.run_dir)
