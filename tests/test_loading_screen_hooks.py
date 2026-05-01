from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "mods" / "src" / "patches" / "parts" / "loading_screen_bg.cc"


class LoadingScreenHookTests(unittest.TestCase):
    def test_unity_value_type_calls_use_runtime_invoke(self) -> None:
        source = SOURCE.read_text(encoding="utf-8-sig")
        load_texture = self._function_source(source, "LoadTextureFromBytes", "static void*")
        apply_sprite = self._function_source(source, "ApplySpriteToImage", "static void")
        apply_bg = self._function_source(source, "ApplyCustomSpriteToBGImage", "static void")

        self.assertIn('GetMethodInfoSpecial("LoadImage"', load_texture)
        self.assertIn("param_count == 3", load_texture)
        self.assertIn("IL2CPP_TYPE_SZARRAY", load_texture)
        self.assertIn('GetMethodInfoSpecial(".ctor"', load_texture)
        self.assertIn("InvokeBool(fn_load", load_texture)
        self.assertIn("void* loadArgs[3]", load_texture)
        self.assertIn("InvokeBool(fn_load, nullptr", load_texture)
        self.assertNotIn("reinterpret_cast<void*(*)(void*, void*, bool)>(fn_load)", load_texture)

        self.assertIn('GetMethodInfo("Create", 3)', apply_sprite)
        self.assertIn("InvokeObject(fn_cre", apply_sprite)
        self.assertNotIn("reinterpret_cast<void*(*)(void*, void*, void*)>(fn_cre)", apply_sprite)
        self.assertNotIn("reinterpret_cast<void(*)(void*, void*)>(fn_col)", apply_sprite)

        for setter in ("set_anchorMin", "set_anchorMax", "set_sizeDelta", "set_anchoredPosition"):
            with self.subTest(setter=setter):
                self.assertIn(f'GetMethodInfo("{setter}")', apply_bg)
        self.assertNotIn("reinterpret_cast<void(*)(void*, FakeVector2", apply_bg)
        self.assertNotIn("reinterpret_cast<void(*)(void*, void*, void*)>(fn_eu)", apply_bg)
        self.assertNotIn("reinterpret_cast<void(*)(void*, void*, void*)>(fn_sc)", apply_bg)

    def test_loading_screen_hooks_remain_in_installer(self) -> None:
        source = SOURCE.read_text(encoding="utf-8-sig")

        for needle in (
            'GetMethod("SetLoadingScreen")',
            "TransitionManager_SetLoadingScreen_Hook",
            "TransitionViewController_Awake_Hook",
            "TransitionViewController_AboutToShow_Hook",
            "SlideShowViewController_ShowCurrentSlide_Hook",
            "LoginSequence_Awake_Hook",
            "SPUD_STATIC_DETOUR",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, source)

    def _function_source(self, source: str, name: str, prefix: str = "void") -> str:
        pattern = re.compile(
            rf"{re.escape(prefix)}\s+{name}\s*\(.*?\n(?=(?:static\s+)?void\*?\s+\w+\s*\(|void\s+InstallLoadingScreenBgHooks\s*\(|\Z)",
            re.S,
        )
        match = pattern.search(source)
        self.assertIsNotNone(match, f"{name} not found")
        return match.group(0)


if __name__ == "__main__":
    unittest.main()
