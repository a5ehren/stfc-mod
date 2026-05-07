#include "self_update.h"

#include "version.h"

#include <cpr/cpr.h>
#include <nlohmann/json.hpp>
#include <toml++/toml.h>

#include <Windows.h>
#include <shellapi.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace
{
constexpr std::string_view kOwner = "netniv";
constexpr std::string_view kRepo  = "stfc-mod";
constexpr std::string_view kZip   = "stfc-community-mod.zip";

struct ReleaseInfo {
  std::string tag;
  std::string published_at;
  std::string asset_url;
  bool        prerelease = false;
};

struct InstalledMetadata {
  std::string tag;
  std::string published_at;
};

std::string WideToUtf8(const std::wstring_view value)
{
  if (value.empty()) {
    return {};
  }

  const int size = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
  std::string result(size, '\0');
  WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), size, nullptr, nullptr);
  return result;
}

std::wstring Utf8ToWide(const std::string_view value)
{
  if (value.empty()) {
    return {};
  }

  const int size = MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0);
  std::wstring result(size, L'\0');
  MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), size);
  return result;
}

std::filesystem::path ModulePath(HINSTANCE module)
{
  std::array<wchar_t, MAX_PATH> buffer{};
  GetModuleFileNameW(module, buffer.data(), static_cast<DWORD>(buffer.size()));
  return std::filesystem::path(buffer.data());
}

std::filesystem::path ProcessPath()
{
  std::array<wchar_t, MAX_PATH> buffer{};
  GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
  return std::filesystem::path(buffer.data());
}

std::string NormalizeChannel(std::string channel)
{
  channel.erase(channel.begin(), std::find_if(channel.begin(), channel.end(), [](unsigned char c) {
                  return !std::isspace(c);
                }));
  channel.erase(std::find_if(channel.rbegin(), channel.rend(), [](unsigned char c) { return !std::isspace(c); }).base(),
                channel.end());
  std::ranges::transform(channel, channel.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return channel == "prerelease" ? "prerelease" : "stable";
}

std::string ReadUpdateChannel(const std::filesystem::path& module_dir)
{
  const auto config_path = module_dir / "community_patch_settings.toml";
  try {
    const auto config = toml::parse_file(config_path.string());
    return NormalizeChannel(config["updates"]["channel"].value_or("stable"));
  } catch (...) {
    return "stable";
  }
}

std::optional<nlohmann::json> GetJson(const std::string& url)
{
  const auto response = cpr::Get(cpr::Url{url}, cpr::Header{{"Accept", "application/vnd.github+json"},
                                                           {"User-Agent", "stfc-community-mod-windows-updater"}},
                                 cpr::Timeout{10'000},
                                 cpr::Redirect{3, true, false, cpr::PostRedirectFlags::POST_ALL});
  if (response.status_code < 200 || response.status_code >= 300) {
    return std::nullopt;
  }

  try {
    return nlohmann::json::parse(response.text);
  } catch (...) {
    return std::nullopt;
  }
}

std::optional<ReleaseInfo> ReleaseFromJson(const nlohmann::json& release, const bool require_prerelease)
{
  if (release.value("draft", false)) {
    return std::nullopt;
  }
  if (require_prerelease && !release.value("prerelease", false)) {
    return std::nullopt;
  }

  for (const auto& asset : release.value("assets", nlohmann::json::array())) {
    if (asset.value("name", "") == kZip) {
      return ReleaseInfo{.tag          = release.value("tag_name", ""),
                         .published_at = release.value("published_at", ""),
                         .asset_url    = asset.value("browser_download_url", ""),
                         .prerelease   = release.value("prerelease", false)};
    }
  }

  return std::nullopt;
}

std::optional<ReleaseInfo> LatestStableRelease()
{
  const auto url = "https://api.github.com/repos/" + std::string(kOwner) + "/" + std::string(kRepo) + "/releases/latest";
  const auto json = GetJson(url);
  if (!json) {
    return std::nullopt;
  }
  return ReleaseFromJson(*json, false);
}

std::optional<ReleaseInfo> LatestPrerelease()
{
  const auto url =
      "https://api.github.com/repos/" + std::string(kOwner) + "/" + std::string(kRepo) + "/releases?per_page=30";
  const auto json = GetJson(url);
  if (!json || !json->is_array()) {
    return std::nullopt;
  }

  std::optional<ReleaseInfo> latest;
  for (const auto& release : *json) {
    auto candidate = ReleaseFromJson(release, true);
    if (!candidate) {
      continue;
    }
    if (!latest || candidate->published_at > latest->published_at) {
      latest = candidate;
    }
  }
  return latest;
}

std::vector<int> VersionParts(std::string tag)
{
  if (!tag.empty() && tag.front() == 'v') {
    tag.erase(tag.begin());
  }
  if (const auto suffix = tag.find('-'); suffix != std::string::npos) {
    tag.erase(suffix);
  }

  std::vector<int> parts;
  std::stringstream stream(tag);
  std::string       part;
  while (std::getline(stream, part, '.') && parts.size() < 3) {
    try {
      parts.push_back(std::stoi(part));
    } catch (...) {
      parts.push_back(0);
    }
  }
  while (parts.size() < 3) {
    parts.push_back(0);
  }
  return parts;
}

bool IsStableNewer(const ReleaseInfo& release)
{
  return VersionParts(release.tag) > std::vector<int>{VERSION_MAJOR, VERSION_MINOR, VERSION_REVISION};
}

InstalledMetadata ReadInstalledMetadata(const std::filesystem::path& metadata_path)
{
  try {
    std::ifstream file(metadata_path);
    const auto    json = nlohmann::json::parse(file);
    return InstalledMetadata{.tag = json.value("tag_name", ""), .published_at = json.value("published_at", "")};
  } catch (...) {
    return {};
  }
}

bool IsPrereleaseNewer(const ReleaseInfo& release, const InstalledMetadata& installed)
{
  return release.tag != installed.tag && release.published_at > installed.published_at;
}

std::wstring PowerShellSingleQuoted(const std::wstring& value)
{
  std::wstring result = L"'";
  for (const auto ch : value) {
    if (ch == L'\'') {
      result += L"''";
    } else {
      result += ch;
    }
  }
  result += L"'";
  return result;
}

std::wstring PowerShellSingleQuotedUtf8(const std::string& value)
{
  return PowerShellSingleQuoted(Utf8ToWide(value));
}

std::wstring PowerShellArgumentArray()
{
  int      argc = 0;
  LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
  if (argv == nullptr || argc <= 1) {
    if (argv != nullptr) {
      LocalFree(argv);
    }
    return L"@()";
  }

  std::wstring result = L"@(";
  for (int i = 1; i < argc; ++i) {
    if (i > 1) {
      result += L", ";
    }
    result += PowerShellSingleQuoted(argv[i]);
  }
  result += L")";
  LocalFree(argv);
  return result;
}

std::wstring HelperScript(const ReleaseInfo& release, const std::filesystem::path& module_path,
                          const std::filesystem::path& process_path, const std::filesystem::path& metadata_path)
{
  const auto working_directory = std::filesystem::current_path();

  std::wstringstream script;
  script << L"$ErrorActionPreference = 'Stop'\n";
  script << L"$ProgressPreference = 'SilentlyContinue'\n";
  script << L"$PidToWait = " << GetCurrentProcessId() << L"\n";
  script << L"$ZipUrl = " << PowerShellSingleQuotedUtf8(release.asset_url) << L"\n";
  script << L"$TargetDll = " << PowerShellSingleQuoted(module_path.wstring()) << L"\n";
  script << L"$ExePath = " << PowerShellSingleQuoted(process_path.wstring()) << L"\n";
  script << L"$WorkingDirectory = " << PowerShellSingleQuoted(working_directory.wstring()) << L"\n";
  script << L"$MetadataPath = " << PowerShellSingleQuoted(metadata_path.wstring()) << L"\n";
  script << L"$TagName = " << PowerShellSingleQuotedUtf8(release.tag) << L"\n";
  script << L"$PublishedAt = " << PowerShellSingleQuotedUtf8(release.published_at) << L"\n";
  script << L"$ArgumentList = " << PowerShellArgumentArray() << L"\n";
  script << LR"ps1(
$Stage = Join-Path $env:TEMP 'stfc-community-mod-update'
$ExtractPath = Join-Path $Stage 'extract'
$ZipPath = Join-Path $Stage 'stfc-community-mod.zip'
Remove-Item -Path $Stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $ExtractPath -Force | Out-Null
Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipPath -UseBasicParsing
Expand-Archive -Path $ZipPath -DestinationPath $ExtractPath -Force
$NewDll = Get-ChildItem -Path $ExtractPath -Filter 'version.dll' -Recurse | Select-Object -First 1
if ($null -eq $NewDll) {
  exit 1
}
Wait-Process -Id $PidToWait -ErrorAction SilentlyContinue
if (Test-Path $TargetDll) {
  Copy-Item -Path $TargetDll -Destination "$TargetDll.bak" -Force
}
Copy-Item -Path $NewDll.FullName -Destination $TargetDll -Force
@{ tag_name = $TagName; published_at = $PublishedAt } | ConvertTo-Json | Set-Content -Path $MetadataPath -Encoding UTF8
Start-Process -FilePath $ExePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory
Remove-Item -Path $Stage -Recurse -Force -ErrorAction SilentlyContinue
)ps1";
  return script.str();
}

bool WriteHelperScript(const std::filesystem::path& script_path, const std::wstring& script)
{
  std::ofstream file(script_path, std::ios::binary);
  if (!file) {
    return false;
  }

  const auto utf8 = WideToUtf8(script);
  file.write(utf8.data(), static_cast<std::streamsize>(utf8.size()));
  return file.good();
}

bool LaunchHiddenPowerShell(const std::filesystem::path& script_path)
{
  std::wstring command_line = L"powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ";
  command_line += PowerShellSingleQuoted(script_path.wstring());

  STARTUPINFOW        startup_info{};
  PROCESS_INFORMATION process_info{};
  startup_info.cb          = sizeof(startup_info);
  startup_info.dwFlags     = STARTF_USESHOWWINDOW;
  startup_info.wShowWindow = SW_HIDE;

  const auto success = CreateProcessW(nullptr, command_line.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr,
                                      nullptr, &startup_info, &process_info);
  if (!success) {
    return false;
  }

  CloseHandle(process_info.hThread);
  CloseHandle(process_info.hProcess);
  return true;
}

DWORD WINAPI ExitSoon(LPVOID)
{
  Sleep(250);
  ExitProcess(0);
  return 0;
}

void ScheduleCurrentProcessExit()
{
  const auto thread = CreateThread(nullptr, 0, ExitSoon, nullptr, 0, nullptr);
  if (thread != nullptr) {
    CloseHandle(thread);
  }
}
} // namespace

bool StartPreLaunchSelfUpdate(HINSTANCE module)
{
  const auto module_path  = ModulePath(module);
  const auto module_dir   = module_path.parent_path();
  const auto process_path = ProcessPath();
  const auto channel      = ReadUpdateChannel(module_dir);
  const auto metadata     = module_dir / "stfc-community-mod-update.json";

  const auto release = channel == "prerelease" ? LatestPrerelease() : LatestStableRelease();
  if (!release) {
    return false;
  }

  const auto installed = ReadInstalledMetadata(metadata);
  const auto should_update =
      channel == "prerelease" ? IsPrereleaseNewer(*release, installed) : IsStableNewer(*release);
  if (!should_update) {
    return false;
  }

  const auto helper_path = std::filesystem::temp_directory_path() / "stfc-community-mod-prelaunch-update.ps1";
  if (!WriteHelperScript(helper_path, HelperScript(*release, module_path, process_path, metadata))) {
    return false;
  }

  if (!LaunchHiddenPowerShell(helper_path)) {
    return false;
  }

  ScheduleCurrentProcessExit();
  return true;
}
