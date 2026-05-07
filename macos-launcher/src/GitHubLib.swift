import AppKit
import Foundation
import UserNotifications
import os

private let githubLogger = Logger(subsystem: "com.stfcmod.startrekpatch", category: "github-updater")

enum UpdateChannel: String {
  case stable
  case prerelease

  static func fromConfig() -> UpdateChannel {
    let library = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask).first
    let configURL = library?
      .appendingPathComponent("Preferences")
      .appendingPathComponent("com.stfcmod.startrekpatch")
      .appendingPathComponent("community_patch_settings.toml")

    guard let configURL, let contents = try? String(contentsOf: configURL, encoding: .utf8) else {
      return .stable
    }

    var inUpdatesSection = false
    for rawLine in contents.components(separatedBy: .newlines) {
      let line = rawLine.split(separator: "#", maxSplits: 1).first?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
      if line.isEmpty {
        continue
      }
      if line.hasPrefix("[") && line.hasSuffix("]") {
        inUpdatesSection = line == "[updates]"
        continue
      }
      if inUpdatesSection && line.hasPrefix("channel") {
        let value = line.split(separator: "=", maxSplits: 1).dropFirst().first?
          .trimmingCharacters(in: .whitespacesAndNewlines)
          .trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
          .lowercased()
        return value == "prerelease" ? .prerelease : .stable
      }
    }

    return .stable
  }
}

struct GitHubAsset: Decodable {
  let name: String
  let browserDownloadURL: URL

  enum CodingKeys: String, CodingKey {
    case name
    case browserDownloadURL = "browser_download_url"
  }
}

struct GitHubRelease: Decodable {
  let tagName: String
  let prerelease: Bool
  let draft: Bool
  let publishedAt: Date?
  let assets: [GitHubAsset]

  enum CodingKeys: String, CodingKey {
    case tagName = "tag_name"
    case prerelease
    case draft
    case publishedAt = "published_at"
    case assets
  }

  func asset(named assetName: String) -> GitHubAsset? {
    assets.first { $0.name == assetName }
  }
}

struct GitHubUpdater {
  private let owner = "netniv"
  private let repo = "stfc-mod"
  private let installerAssetName = "stfc-community-mod-installer.dmg"
  private let installedTagKey = "GitHubUpdaterInstalledTag"
  private let installedPublishedAtKey = "GitHubUpdaterInstalledPublishedAt"

  func updateLauncherIfNeeded() async {
    do {
      let channel = UpdateChannel.fromConfig()
      guard let release = try await latestInstallableRelease(channel: channel, assetName: installerAssetName),
            let asset = release.asset(named: installerAssetName),
            shouldInstall(release: release, channel: channel)
      else {
        return
      }

      try await notifyLauncherUpdateStarted(release: release)
      let dmgURL = try await download(asset: asset)
      try launchInstallerHelper(dmgURL: dmgURL, release: release)
      NSApplication.shared.terminate(nil)
    } catch {
      githubLogger.error("Launcher update failed: \(error.localizedDescription)")
    }
  }

  func latestInstallableRelease(channel: UpdateChannel, assetName: String) async throws -> GitHubRelease? {
    switch channel {
    case .stable:
      let release: GitHubRelease = try await fetch(path: "/releases/latest")
      return release.draft || release.asset(named: assetName) == nil ? nil : release
    case .prerelease:
      let releases: [GitHubRelease] = try await fetch(path: "/releases?per_page=30")
      return releases
        .filter { !$0.draft && $0.prerelease && $0.asset(named: assetName) != nil }
        .sorted { ($0.publishedAt ?? .distantPast) > ($1.publishedAt ?? .distantPast) }
        .first
    }
  }

  private func fetch<T: Decodable>(path: String) async throws -> T {
    let url = URL(string: "https://api.github.com/repos/\(owner)/\(repo)\(path)")!
    var request = URLRequest(url: url)
    request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
    request.setValue("stfc-community-mod-macos-launcher", forHTTPHeaderField: "User-Agent")

    let (data, response) = try await URLSession.shared.data(for: request)
    if let httpResponse = response as? HTTPURLResponse, !(200..<300).contains(httpResponse.statusCode) {
      throw NSError(domain: "GitHubUpdater", code: httpResponse.statusCode, userInfo: nil)
    }

    let decoder = JSONDecoder()
    decoder.dateDecodingStrategy = .iso8601
    return try decoder.decode(T.self, from: data)
  }

  private func shouldInstall(release: GitHubRelease, channel: UpdateChannel) -> Bool {
    switch channel {
    case .stable:
      return versionComponents(from: release.tagName).lexicographicallyPrecedes(versionComponents(from: currentAppVersion()))
        == false && versionComponents(from: release.tagName) != versionComponents(from: currentAppVersion())
    case .prerelease:
      let defaults = UserDefaults.standard
      let installedTag = defaults.string(forKey: installedTagKey)
      let installedPublishedAt = defaults.object(forKey: installedPublishedAtKey) as? Date ?? .distantPast
      return release.tagName != installedTag && (release.publishedAt ?? .distantPast) > installedPublishedAt
    }
  }

  private func currentAppVersion() -> String {
    Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.0.0"
  }

  private func versionComponents(from version: String) -> [Int] {
    let trimmed = version
      .replacingOccurrences(of: "v", with: "")
      .split(separator: "-")
      .first
      .map(String.init) ?? version
    return trimmed.split(separator: ".").prefix(3).map { Int($0) ?? 0 }
  }

  private func notifyLauncherUpdateStarted(release: GitHubRelease) async throws {
    let center = UNUserNotificationCenter.current()
    _ = try await center.requestAuthorization(options: [.alert, .sound])

    let content = UNMutableNotificationContent()
    content.title = "STFC Community Mod Update"
    content.body = "Installing \(release.tagName). The launcher will restart automatically."
    content.sound = .default

    let request = UNNotificationRequest(
      identifier: "stfc-community-mod-launcher-update-\(release.tagName)",
      content: content,
      trigger: nil)
    try await center.add(request)
  }

  private func download(asset: GitHubAsset) async throws -> URL {
    let (localURL, response) = try await URLSession.shared.download(from: asset.browserDownloadURL)
    if let httpResponse = response as? HTTPURLResponse, !(200..<300).contains(httpResponse.statusCode) {
      throw NSError(domain: "GitHubUpdater", code: httpResponse.statusCode, userInfo: nil)
    }

    let targetDirectory = FileManager.default.temporaryDirectory
      .appendingPathComponent("stfc-community-mod-launcher-update-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: targetDirectory, withIntermediateDirectories: true)
    let target = targetDirectory.appendingPathComponent(installerAssetName)
    try FileManager.default.moveItem(at: localURL, to: target)
    return target
  }

  private func launchInstallerHelper(dmgURL: URL, release: GitHubRelease) throws {
    let helperDirectory = dmgURL.deletingLastPathComponent()
    let helperURL = helperDirectory.appendingPathComponent("install-stfc-community-mod-update.sh")
    let appURL = Bundle.main.bundleURL
    let publishedAt = release.publishedAt ?? Date()
    let publishedAtValue = ISO8601DateFormatter().string(from: publishedAt)
    let script = """
      #!/bin/zsh
      set -euo pipefail

      pid_to_wait='\(ProcessInfo.processInfo.processIdentifier)'
      app_path='\(shellSingleQuoted(appURL.path))'
      dmg_path='\(shellSingleQuoted(dmgURL.path))'
      tag_name='\(shellSingleQuoted(release.tagName))'
      published_at='\(shellSingleQuoted(publishedAtValue))'
      defaults_domain='com.stfcmod.startrekpatch'
      mount_point="$(mktemp -d /tmp/stfc-mod-update.XXXXXX)"

      while kill -0 "$pid_to_wait" 2>/dev/null; do
        sleep 0.25
      done

      cleanup() {
        hdiutil detach "$mount_point" -quiet >/dev/null 2>&1 || true
        rm -rf "$mount_point"
      }
      trap cleanup EXIT

      hdiutil attach "$dmg_path" -mountpoint "$mount_point" -nobrowse -quiet
      rm -rf "$app_path"
      cp -R "$mount_point/STFC Community Mod.app" "$app_path"
      defaults write "$defaults_domain" GitHubUpdaterInstalledTag "$tag_name"
      defaults write "$defaults_domain" GitHubUpdaterInstalledPublishedAt -date "$published_at"
      open "$app_path"
      rm -rf "$(dirname "$dmg_path")"
      """

    try script.write(to: helperURL, atomically: true, encoding: .utf8)
    try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: helperURL.path)

    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/bin/zsh")
    process.arguments = [helperURL.path]
    try process.run()
  }

  private func shellSingleQuoted(_ value: String) -> String {
    value.replacingOccurrences(of: "'", with: "'\\''")
  }
}
