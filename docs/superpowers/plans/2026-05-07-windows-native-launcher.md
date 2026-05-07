# Windows Native Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this task-by-task.

**Goal:** Add an optional Windows launcher that visually matches the macOS LCARS launcher, manages config/game/mod updates, launches STFC with the mod injected, removes legacy game-folder `version.dll`, and ships through an xmake NSIS installer.

**Architecture:** Build a C++23 Win32 launcher target with custom-painted LCARS UI. The launcher installs beside `stfc-community-mod.dll`, owns `community_patch_settings.toml` in its install folder, launches `prime.exe` suspended, injects the mod DLL with `LoadLibraryW`, sets `STFC_MOD_LAUNCHER_MANAGED=1`, passes `-ccm <installer-config-path>`, and deletes any legacy `version.dll` from the game folder. Shared Windows GitHub release code should serve both the proxy DLL self-updater and launcher mod-update checks.

**Tech Stack:** C++23, Win32 API, xmake targets, xmake `xpack` NSIS packaging, existing `cpr`, `nlohmann_json`, and `toml++`.

---

## Key Changes

- Add `windows-launcher/` with a native Win32 executable target named `stfc-community-mod-launcher`.
- Add shared Windows update helpers so the launcher and `win-proxy-dll` use one GitHub release-selection implementation.
- Add `STFC_MOD_LAUNCHER_MANAGED=1` as the process-level flag that makes `version.dll` skip its automatic pre-launch self-update.
- Launcher-owned config path is `<launcher install dir>\community_patch_settings.toml`; on first run, copy `community_patch_settings.toml` from the detected game folder if present.
- Launcher startup and launch flow must delete `<game dir>\version.dll`; if deletion fails, show an error and do not launch.
- Use xmake's builtin xpack plugin: `includes("@builtin/xpack")`, `set_formats("nsis")`, and package with `xmake pack stfc-community-mod-windows-launcher -y`. Context7 xmake docs confirm `set_formats("nsis")` plus `xmake pack` generates the NSIS installer and can auto-install `nsis`.

## Implementation Tasks

1. **Static Tests First**
   - Add `tests/test_windows_launcher_static.py`.
   - Assert root `xmake.lua` includes `windows-launcher` only on Windows.
   - Assert `windows-launcher/xmake.lua` defines `stfc-community-mod-launcher`, links `User32`, `Shell32`, `Comdlg32`, uses `add_deps("stfc-community-mod")`, and defines an `xpack` with `set_formats("nsis")`.
   - Assert `win-proxy-dll/src/self_update.cc` checks `STFC_MOD_LAUNCHER_MANAGED`.
   - Assert CI and release workflows upload a Windows launcher installer artifact.

2. **Shared Windows Update Library**
   - Create `win-common/github_release.h/.cc`.
   - Move or duplicate only the non-UI release logic from `win-proxy-dll/src/self_update.cc`: channel normalization, GitHub release fetch, asset selection, stable/prerelease comparison, metadata read/write.
   - Keep `win-proxy-dll` silent: if `STFC_MOD_LAUNCHER_MANAGED=1`, `StartPreLaunchSelfUpdate()` immediately returns `false`.

3. **Launcher Core**
   - Create focused files under `windows-launcher/src/`:
     - `main.cc`: WinMain, message loop, top-level window.
     - `lcars_view.cc/.h`: custom-painted LCARS layout matching macOS colors, large rounded bands, random LCARS labels, and fixed-size buttons.
     - `game_locator.cc/.h`: locate game folder from Xsolla launcher settings in `%LOCALAPPDATA%` or `%APPDATA%`, fallback to `C:\Games\Star Trek Fleet Command\Star Trek Fleet Command\default\game`, validate `prime.exe`.
     - `launcher_config.cc/.h`: get install dir, migrate game-folder config if launcher config is missing, create empty config if needed, open config with `ShellExecuteW`.
     - `launcher_update.cc/.h`: check/install mod update by downloading `stfc-community-mod.zip`, extracting `version.dll`, and replacing install-dir `stfc-community-mod.dll`.
     - `game_update.cc/.h`: check Xsolla game updates with `platform=win32`; if available, expose update action using the same action parser model as macOS.
     - `injector.cc/.h`: delete game-folder `version.dll`, create `prime.exe` suspended with env var and `-ccm`, inject install-dir `stfc-community-mod.dll`, resume process, report failures.
   - UI buttons: `Open Config`, `Check Game Updates`, `Check Mod Updates`, and `Engage`.
   - If a game update or mod update is available, change the corresponding button/status text to make the update action explicit before applying it.

4. **Build and Installer**
   - Add `windows-launcher/xmake.lua` target and include it from root `xmake.lua` inside `if is_plat("windows")`.
   - Package installer contents: launcher EXE, `stfc-community-mod.dll`, `example_community_patch_settings.toml`, icon assets, and any required runtime-free resources.
   - Default NSIS install dir: per-user local app data, e.g. `$LOCALAPPDATA\STFC Community Mod`, so config in the installer folder is writable without admin.
   - Add `assets/launcher.ico` generated from existing launcher artwork if NSIS requires `.ico`.

5. **CI, Release, and Docs**
   - Update Windows CI to build launcher and run `xmake pack stfc-community-mod-windows-launcher -y`.
   - Upload installer artifact as `stfc-community-mod-windows-launcher-installer`.
   - Update stable and pre-release workflows to attach the Windows launcher installer alongside ZIP and DMG assets.
   - Update `INSTALL.md`: Windows users may use either manual `version.dll` installation or the optional launcher; launcher mode removes game-folder `version.dll`, owns config in its install folder, and launches the mod by injection.
   - Update README development/release notes if new packaging commands are added.

## Test Plan

- Red/green static tests:
  - `python3 -m unittest tests/test_windows_launcher_static.py`
  - `python3 -m unittest tests/test_auto_update_static.py`
- YAML/workflow checks:
  - Ruby YAML parse for `.github/workflows/ci.yaml`, `release.yaml`, and `pr-prerelease.yaml`.
- Local non-Windows verification:
  - `git diff --check`
  - Static tests only, since Windows build may be unavailable locally.
- Windows verification:
  - `xmake f -p windows -m release -y`
  - `xmake -y stfc-community-mod stfc-community-mod-launcher`
  - `xmake pack stfc-community-mod-windows-launcher -y`
  - Install NSIS output on Windows, confirm launcher starts, opens config, deletes legacy game-folder `version.dll`, checks mod update, checks game update, and launches `prime.exe` with injected mod.
- Runtime acceptance:
  - Manual `version.dll` install still self-updates.
  - Launcher mode never triggers DLL self-update because `STFC_MOD_LAUNCHER_MANAGED=1` is visible inside the game process.
  - Launcher config migration copies an existing game-folder config once and preserves it in installer folder.

## Assumptions

- Windows launcher uses C++ Win32 custom drawing, not WinUI or Qt.
- Mod loading uses DLL injection, not a temporary proxy DLL.
- Launcher config lives in the installer folder; first run copies an old game-folder config if present.
- Game update API uses the same Xsolla project id as macOS with Windows platform `win32`; implementation should fail visibly if the endpoint does not return usable update XML.
- Installer is per-user by default so the launcher can write config and update metadata without elevation.
