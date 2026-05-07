import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AutoUpdateStaticTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        path = ROOT / relative_path
        self.assertTrue(path.exists(), f"{relative_path} should exist")
        return path.read_text(encoding="utf-8")

    def test_pr_prerelease_workflow_uses_explicit_prerelease_tags(self):
        workflow = self.read(".github/workflows/pr-prerelease.yaml")

        self.assertIn("tags:", workflow)
        self.assertIn('"v*-pr.*"', workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("github.event.pull_request", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("stfc-community-mod-installer.dmg", workflow)
        self.assertIn("stfc-community-mod.zip", workflow)

        self.assertIn("TAG: ${{ github.ref_name }}", workflow)
        self.assertIn("git rev-list -n 1", workflow)
        self.assertIn("--target \"$TARGET_SHA\"", workflow)

    def test_readme_documents_explicit_prerelease_tag_process(self):
        readme = self.read("README.md")

        self.assertIn("Pre-release tags", readme)
        self.assertIn("vX.Y.Z-pr.N+SHORTSHA", readme)
        self.assertIn("git tag", readme)
        self.assertIn("git push origin", readme)
        self.assertIn("Pre-releases are not created automatically when PRs merge", readme)

    def test_stable_release_workflow_ignores_pr_prerelease_tags(self):
        workflow = self.read(".github/workflows/release.yaml")
        self.assertIn("!contains(github.ref_name, '-pr.')", workflow)
        self.assertIn("^v[0-9]+\\.[0-9]+\\.[0-9]+\\.(alpha|beta)\\.[0-9]+$", workflow)
        self.assertNotIn("(?:\\.(alpha|beta)\\.[\\d]+)?", workflow)

    def test_update_channel_is_documented_and_defaults_to_stable(self):
        defaults = self.read("mods/src/defaultconfig.h")
        config_h = self.read("mods/src/config.h")
        config_cc = self.read("mods/src/config.cc")
        example = self.read("example_community_patch_settings.toml")

        self.assertIn("namespace Updates", defaults)
        self.assertIn('channel = "stable"', defaults)
        self.assertIn("std::string update_channel", config_h)
        self.assertIn('"updates", "channel"', config_cc)
        self.assertRegex(example, r"\[updates\]\s+channel\s*=\s*\"stable\"")

    def test_macos_github_updater_selects_platform_asset_and_prerelease_by_metadata(self):
        source = self.read("macos-launcher/src/GitHubLib.swift")

        self.assertIn("stfc-community-mod-installer.dmg", source)
        self.assertIn("/releases/latest", source)
        self.assertIn("/releases?per_page=30", source)
        self.assertIn("publishedAt", source)
        self.assertIn("UserDefaults", source)
        self.assertIn("UserNotifications", source)
        self.assertIn("hdiutil", source)

    def test_windows_prelaunch_updater_relaunches_after_replacing_version_dll(self):
        header = self.read("win-proxy-dll/src/self_update.h")
        source = self.read("win-proxy-dll/src/self_update.cc")
        main = self.read("win-proxy-dll/src/main.cc")
        xmake = self.read("win-proxy-dll/xmake.lua")

        self.assertIn("StartPreLaunchSelfUpdate", header)
        self.assertIn("version.dll", source)
        self.assertIn("stfc-community-mod.zip", source)
        self.assertIn("CreateProcessW", source)
        self.assertIn("GetCommandLineW", source)
        self.assertIn("ApplyPatches()", main)
        self.assertIn("StartPreLaunchSelfUpdate", main)
        self.assertIn("self_update.cc", xmake)


if __name__ == "__main__":
    unittest.main()
