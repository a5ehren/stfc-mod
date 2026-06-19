import Foundation

enum TestFailure: Error, CustomStringConvertible {
  case failed(String)

  var description: String {
    switch self {
    case .failed(let message):
      return message
    }
  }
}

@main
struct UpdaterFileOperationsTests {
  static func main() throws {
    try testCopyNestedContentsAndOverwrite()
    try testCopyThrowsWhenSourceIsMissing()
    try testCopyThrowsWhenDestinationCannotAcceptDirectory()
    try testDeleteGamePathsRemovesObsoleteFile()
    try testDeleteGamePathsKeepsStagedReplacement()
    try testWriteInstalledGameVersion()
    print("UpdaterFileOperationsTests passed")
  }

  private static func testCopyNestedContentsAndOverwrite() throws {
    try withTemporaryRoot { root in
      let source = root.appendingPathComponent("source")
      let target = root.appendingPathComponent("target")
      let sourceFile = source.appendingPathComponent("Data/Managed/game.bin")
      let targetFile = target.appendingPathComponent("Data/Managed/game.bin")

      try FileManager.default.createDirectory(
        at: sourceFile.deletingLastPathComponent(), withIntermediateDirectories: true)
      try FileManager.default.createDirectory(
        at: targetFile.deletingLastPathComponent(), withIntermediateDirectories: true)
      try "new".write(to: sourceFile, atomically: true, encoding: .utf8)
      try "old".write(to: targetFile, atomically: true, encoding: .utf8)

      try copyContentsOfDirectory(from: source, to: target)

      let copied = try String(contentsOf: targetFile, encoding: .utf8)
      try require(copied == "new", "expected final copy to overwrite the destination file")
    }
  }

  private static func testCopyThrowsWhenSourceIsMissing() throws {
    try withTemporaryRoot { root in
      try expectThrows("expected missing source directory to throw") {
        try copyContentsOfDirectory(
          from: root.appendingPathComponent("missing-source"),
          to: root.appendingPathComponent("target"))
      }
    }
  }

  private static func testCopyThrowsWhenDestinationCannotAcceptDirectory() throws {
    try withTemporaryRoot { root in
      let source = root.appendingPathComponent("source")
      let sourceFile = source.appendingPathComponent("Data/Managed/game.bin")
      let targetFile = root.appendingPathComponent("target-file")

      try FileManager.default.createDirectory(
        at: sourceFile.deletingLastPathComponent(), withIntermediateDirectories: true)
      try "new".write(to: sourceFile, atomically: true, encoding: .utf8)
      try "not a directory".write(to: targetFile, atomically: true, encoding: .utf8)

      try expectThrows("expected blocked destination directory to throw") {
        try copyContentsOfDirectory(from: source, to: targetFile)
      }
    }
  }

  private static func testWriteInstalledGameVersion() throws {
    try withTemporaryRoot { root in
      let game = root.appendingPathComponent("game")
      try FileManager.default.createDirectory(at: game, withIntermediateDirectories: true)

      try writeInstalledGameVersion(168, gamePath: game.path)

      let version = try String(contentsOf: game.appendingPathComponent(".version"), encoding: .utf8)
      try require(version == "&game=168", "expected updater to write the installed game version")
    }
  }

  private static func testDeleteGamePathsRemovesObsoleteFile() throws {
    try withTemporaryRoot { root in
      let game = root.appendingPathComponent("game")
      let stage = root.appendingPathComponent("stage")
      let obsoleteFile = game.appendingPathComponent("obsolete.bin")

      try FileManager.default.createDirectory(at: game, withIntermediateDirectories: true)
      try FileManager.default.createDirectory(at: stage, withIntermediateDirectories: true)
      try "obsolete".write(to: obsoleteFile, atomically: true, encoding: .utf8)

      try deleteGamePaths(["obsolete.bin"], gamePath: game.path, preservingStagedRoot: stage)

      try require(!FileManager.default.fileExists(atPath: obsoleteFile.path), "expected delete rule to remove obsolete file")
    }
  }

  private static func testDeleteGamePathsKeepsStagedReplacement() throws {
    try withTemporaryRoot { root in
      let game = root.appendingPathComponent("game")
      let stage = root.appendingPathComponent("stage")
      let gameFile = game.appendingPathComponent("replace.bin")
      let stagedFile = stage.appendingPathComponent("replace.bin")

      try FileManager.default.createDirectory(at: game, withIntermediateDirectories: true)
      try FileManager.default.createDirectory(at: stage, withIntermediateDirectories: true)
      try "old".write(to: gameFile, atomically: true, encoding: .utf8)
      try "new".write(to: stagedFile, atomically: true, encoding: .utf8)

      try deleteGamePaths(["replace.bin"], gamePath: game.path, preservingStagedRoot: stage)

      try require(
        FileManager.default.fileExists(atPath: gameFile.path),
        "expected delete rule to keep a path with a staged replacement")
    }
  }

  private static func withTemporaryRoot(_ body: (URL) throws -> Void) throws {
    let root = URL(fileURLWithPath: NSTemporaryDirectory())
      .appendingPathComponent("UpdaterFileOperationsTests-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    try body(root)
  }

  private static func expectThrows(_ message: String, _ body: () throws -> Void) throws {
    do {
      try body()
    } catch {
      return
    }
    throw TestFailure.failed(message)
  }

  private static func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() {
      throw TestFailure.failed(message)
    }
  }
}
