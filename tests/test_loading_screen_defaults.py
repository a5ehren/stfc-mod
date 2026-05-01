from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "mods" / "src" / "defaultconfig.h"
CONFIG_SOURCE = PROJECT_ROOT / "mods" / "src" / "config.cc"


class LoadingScreenDefaultTests(unittest.TestCase):
    def test_loading_screen_background_hook_default_matches_dev(self) -> None:
        source = DEFAULT_CONFIG.read_text(encoding="utf-8")

        self.assertIn("constexpr bool loadingscreenbghooks       = true;", source)
        self.assertNotRegex(source, r"#if\s+_WIN32\s+constexpr bool loadingscreenbghooks")

    def test_release_config_keeps_dev_default_for_loading_screen_hooks(self) -> None:
        source = CONFIG_SOURCE.read_text(encoding="utf-8")
        release_defaults = re.search(r"#if _MODDBG\s+.*?#else\s+(?P<body>.*?)#endif", source, re.S)

        self.assertIsNotNone(release_defaults)
        self.assertIn(
            "this->installLoadingScreenBgHooks       = true;",
            release_defaults.group("body"),
        )
        self.assertNotIn("this->installLoadingScreenBgHooks       = DCP::loadingscreenbghooks;", release_defaults.group("body"))


if __name__ == "__main__":
    unittest.main()
