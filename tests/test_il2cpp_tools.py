from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from lib import dump_parser, fixer, mod_extractor, validator
from lib.models import DumpClass, DumpIndex, Issue, ModReference, RefType, Severity


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _sample_dump(class_decl: str, body: str = "") -> str:
    return f"""// Image 0: Assembly-CSharp.dll - 0

// Namespace: Digit.Client.UI
{class_decl} // TypeDefIndex: 1
{{
{body}}}
"""


class DumpParserTests(unittest.TestCase):
    def test_parses_generic_class_names_with_spaced_commas(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dump_path = _write(
                Path(td) / "dump.cs",
                _sample_dump(
                    "public abstract class LocalViewController<CanvasContextType, LocalContextType> "
                    ": ViewController<CanvasContextType>",
                    "\tpublic CanvasContextType CanvasContext { get; }\n",
                ),
            )

            index = dump_parser.parse_dump(dump_path)

        self.assertIn(
            ("Assembly-CSharp", "Digit.Client.UI", "LocalViewController`2"),
            index.by_qualified_name,
        )

    def test_parse_dump_cached_uses_cache_for_unchanged_dump(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dump_path = _write(
                Path(td) / "dump.cs",
                _sample_dump("public class CachedClass"),
            )

            index = dump_parser.parse_dump_cached(dump_path)
            self.assertIn(("Assembly-CSharp", "Digit.Client.UI", "CachedClass"), index.by_qualified_name)
            self.assertTrue(list(Path(td).glob("*.dump-index-cache*")))

            original = dump_parser.parse_dump

            def fail_if_reparsed(path: Path) -> DumpIndex:
                raise AssertionError(f"cache miss for {path}")

            dump_parser.parse_dump = fail_if_reparsed
            try:
                cached = dump_parser.parse_dump_cached(dump_path)
            finally:
                dump_parser.parse_dump = original

        self.assertIn(("Assembly-CSharp", "Digit.Client.UI", "CachedClass"), cached.by_qualified_name)


class ModExtractorTests(unittest.TestCase):
    def test_target_platform_selects_preprocessor_branch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source_root = Path(td) / "mods" / "src"
            _write(
                source_root / "prime" / "PlatformSample.h",
                """
struct PlatformSample {
#if _WIN32
  static auto get_class_helper()
  {
    static auto helper = il2cpp_get_class_helper("A", "N", "WinClass");
    return helper;
  }
  void method() { get_class_helper().GetMethod("WindowsOnly"); }
#else
  static auto get_class_helper()
  {
    static auto helper = il2cpp_get_class_helper("A", "N", "MacClass");
    return helper;
  }
  void method() { get_class_helper().GetMethod("MacOnly"); }
#endif
};
""",
            )

            mac_refs = mod_extractor.extract_references(source_root, target_platform="macos")
            win_refs = mod_extractor.extract_references(source_root, target_platform="windows")
            all_report = mod_extractor.extract_references_with_report(source_root, target_platform="macos")

        mac_members = {(r.class_name, r.member_name) for r in mac_refs if r.type == RefType.METHOD}
        win_members = {(r.class_name, r.member_name) for r in win_refs if r.type == RefType.METHOD}
        skipped_members = {(r.class_name, r.member_name) for r in all_report.platform_skipped_refs}

        self.assertIn(("MacClass", "MacOnly"), mac_members)
        self.assertNotIn(("WinClass", "WindowsOnly"), mac_members)
        self.assertIn(("WinClass", "WindowsOnly"), win_members)
        self.assertNotIn(("MacClass", "MacOnly"), win_members)
        self.assertIn(("WinClass", "WindowsOnly"), skipped_members)

    def test_static_get_class_helper_scope_maps_to_wrapper_class(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source_root = Path(td) / "mods" / "src"
            _write(
                source_root / "prime" / "FleetsManager.h",
                """
struct FleetsManager {
  static auto get_class_helper()
  {
    static auto helper = il2cpp_get_class_helper("Assembly-CSharp", "", "FleetsManager");
    return helper;
  }

  void request() { get_class_helper().GetMethod("RequestViewFleet"); }
};

struct FleetsManagerTow {
  static auto get_class_helper()
  {
    static auto helper = il2cpp_get_class_helper("Assembly-CSharp", "", "FleetsManager.<Tow>d__192");
    return helper;
  }

  void move_next() { get_class_helper().GetMethod("MoveNext"); }
};
""",
            )

            refs = mod_extractor.extract_references(source_root, target_platform="macos")

        methods = {
            r.member_name: r.class_name
            for r in refs
            if r.type == RefType.METHOD and r.member_name in {"RequestViewFleet", "MoveNext"}
        }
        self.assertEqual("FleetsManager", methods["RequestViewFleet"])
        self.assertEqual("FleetsManager.<Tow>d__192", methods["MoveNext"])


class FixerTests(unittest.TestCase):
    def test_semantic_hint_calls_out_similar_property_return_type(self) -> None:
        dc = DumpClass(
            assembly="A",
            namespace="N",
            name="HttpResponse",
            properties=["Body"],
            methods={"get_Body": ["public string get_Body()"]},
        )
        index = DumpIndex(
            by_qualified_name={("A", "N", "HttpResponse"): dc},
            by_class_name={"HttpResponse": [dc]},
            by_ns_class={("N", "HttpResponse"): [dc]},
        )
        issue = Issue(
            severity=Severity.MISSING,
            ref=ModReference(
                type=RefType.PROPERTY,
                source_file="mods/src/prime/HttpResponse.h",
                source_line=17,
                assembly="A",
                namespace="N",
                class_name="HttpResponse",
                member_name="Bytes",
            ),
            message="Missing property",
        )

        _, suggestions = fixer.analyze_issues([issue], index, PROJECT_ROOT)

        descriptions = "\n".join(s.description for s in suggestions)
        self.assertIn("Body", descriptions)
        self.assertIn("getter return type 'string'", descriptions)
        self.assertIn("manual review", descriptions)


class ValidatorReportTests(unittest.TestCase):
    def test_categorizes_drift_report_buckets(self) -> None:
        missing = Issue(
            severity=Severity.MISSING,
            ref=ModReference(
                type=RefType.METHOD,
                source_file="mods/src/example.h",
                source_line=10,
                assembly="A",
                namespace="N",
                class_name="C",
                member_name="MissingMethod",
            ),
            message="missing",
        )
        changed = Issue(
            severity=Severity.SIGNATURE_CHANGED,
            ref=ModReference(
                type=RefType.METHOD,
                source_file="mods/src/example.h",
                source_line=11,
                assembly="A",
                namespace="N",
                class_name="C",
                member_name="ChangedMethod",
            ),
            message="changed",
        )

        categories = validator.categorize_issues([missing, changed])

        self.assertEqual([missing], categories["missing_current_refs"])
        self.assertEqual([changed], categories["signature_changed"])
        self.assertIn("platform_skipped_refs", categories)
        self.assertIn("inherited_base_refs", categories)
        self.assertIn("optional_probes", categories)
        self.assertIn("tool_limitations", categories)


class WorkflowCliTests(unittest.TestCase):
    def test_resolve_context_and_ensure_dump_reuse_existing_dump(self) -> None:
        from lib import il2cpp_workflow

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game_dir = root / "Star Trek Fleet Command.app"
            data_dir = game_dir / "Contents" / "Resources" / "Data"
            _write(game_dir / "Contents" / "Frameworks" / "GameAssembly.dylib", "")
            _write(data_dir / "il2cpp_data" / "Metadata" / "global-metadata.dat", "")
            _write(data_dir / "globalgamemanagers", "Unity 6000.0.59f2 STFC 1.000.48902")

            dump_root = root / "dump"
            existing_dump = _write(dump_root / "1.000.48902" / "dump.cs", "// existing dump\n")

            context = il2cpp_workflow.resolve_context(game_dir, dump_root=dump_root)
            calls: list[Path] = []

            def fail_if_called(_: il2cpp_workflow.DumpContext, *, reinstall: bool = False) -> None:
                calls.append(existing_dump)
                raise AssertionError("dump runner should not be called when dump.cs exists")

            dump_cs = il2cpp_workflow.ensure_dump(
                context,
                run_dump=fail_if_called,
                log=lambda _: None,
            )

        self.assertEqual(existing_dump, dump_cs)
        self.assertEqual([], calls)
        self.assertEqual("1.000.48902", context.game_version)
        self.assertEqual("6000.0.59f2", context.unity_version)

    def test_unified_cli_accepts_dump_validate_fix_and_scaffold_commands(self) -> None:
        from lib import il2cpp_cli

        parser = il2cpp_cli.build_parser()
        cases = [
            (["dump", "--game-dir", "/game"], "dump"),
            (["validate", "--game-dir", "/game", "--target-platform", "macos"], "validate"),
            (["fix", "--game-dir", "/game", "--dry-run"], "fix"),
            (["scaffold", "UnityEngine.Camera", "--game-dir", "/game"], "scaffold"),
            (["scaffold-all", "--game-dir", "/game", "--target-platform", "all"], "scaffold-all"),
        ]

        for argv, expected in cases:
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                self.assertEqual(expected, args.command)

    def test_legacy_codegen_parser_keeps_old_subcommands(self) -> None:
        from lib import il2cpp_cli

        parser = il2cpp_cli.build_codegen_parser()
        args = parser.parse_args([
            "fix",
            "--game-dir",
            "/game",
            "--dry-run",
            "--target-platform",
            "macos",
        ])

        self.assertEqual("fix", args.command)
        self.assertTrue(args.dry_run)
        self.assertEqual("macos", args.target_platform)


if __name__ == "__main__":
    unittest.main()
