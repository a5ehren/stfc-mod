#!/usr/bin/env python3
"""PvE combat model viability tooling."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.combat_model.compare import compare_traces
from lib.combat_model.buff_audit import BUFF_AUDIT_DETAILS, generate_buff_audit
from lib.combat_model.defender_diagnostics import build_defender_diagnostics, write_defender_diagnostics
from lib.combat_model.fixtures import load_fixture
from lib.combat_model.hull_buff_map import build_hull_buff_map
from lib.combat_model.mitigation_analysis import analyze_mitigation, write_mitigation_analysis
from lib.combat_model.mitigation_model import load_synced_linear_mitigation_model
from lib.combat_model.models import ReplayThreshold
from lib.combat_model.observations import export_observations, write_observations_jsonl
from lib.combat_model.projection_reporting import render_projection_json, render_projection_markdown
from lib.combat_model.replay import expected_trace_from_fixture, replay_fixture
from lib.combat_model.reporting import render_json_report, render_markdown_report
from lib.combat_model.round_projection import filter_observations, load_observations_jsonl, project_observations
from lib.combat_model.static_catalog import compare_static_catalog
from lib.combat_model.static_normalizer import build_fixture


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    report = subparsers.add_parser("report", help="replay a combat fixture and write comparison reports")
    report.add_argument("fixture", type=Path)
    report.add_argument("--out-dir", type=Path, required=True)
    report.add_argument("--threshold", choices=("mvp", "release"), default="mvp")

    build_fixture_cmd = subparsers.add_parser("build-fixture", help="build normalized fixture JSON")
    build_fixture_cmd.add_argument("--decoded-static-dir", type=Path, required=True)
    build_fixture_cmd.add_argument("--battle-journal", type=Path, required=True)
    build_fixture_cmd.add_argument("--out", type=Path, required=True)

    static_catalog = subparsers.add_parser("static-catalog", help="compare static hull/component specs to captures")
    static_catalog.add_argument("--decoded-static-dir", type=Path, required=True)
    static_catalog.add_argument("--capture-root", type=Path, required=True)
    static_catalog.add_argument("--out", type=Path, required=True)
    static_catalog.add_argument("--side", choices=("initiator", "target", "both"), default="target")

    observations = subparsers.add_parser("observations", help="export per-attack model observations as JSONL")
    observations.add_argument("--decoded-static-dir", type=Path, required=True)
    observations.add_argument("--capture-root", type=Path, required=True)
    observations.add_argument("--buff-audit", type=Path)
    observations.add_argument("--out", type=Path, required=True)

    mitigation = subparsers.add_parser("analyze-mitigation", help="fit and report mitigation formula baselines")
    mitigation.add_argument("--observations", type=Path, required=True)
    mitigation.add_argument("--decoded-static-dir", type=Path)
    mitigation.add_argument("--out", type=Path, required=True)

    project_rounds = subparsers.add_parser("project-rounds", help="project round-by-round combat from observations")
    project_rounds.add_argument("--observations", type=Path, required=True)
    project_rounds.add_argument("--mitigation-analysis", type=Path, required=True)
    project_rounds.add_argument("--out", type=Path, required=True)
    project_rounds.add_argument("--mode", choices=("observed-order", "deterministic"), default="observed-order")
    project_rounds.add_argument("--battle-id", action="append")
    project_rounds.add_argument("--battle-class", action="append")
    project_rounds.add_argument("--limit", type=int)
    project_rounds.add_argument("--max-rounds", type=int, default=30)
    project_rounds.add_argument("--max-attacks", type=int, default=500)

    defender_diagnostics = subparsers.add_parser(
        "defender-diagnostics",
        help="diagnose player-defender mitigation errors on hostile shots",
    )
    defender_diagnostics.add_argument("--observations", type=Path, required=True)
    defender_diagnostics.add_argument("--out", type=Path, required=True)
    defender_diagnostics.add_argument("--min-group-count", type=int, default=20)

    buff_audit = subparsers.add_parser("buff-audit", help="resolve captured player active buffs against static specs")
    buff_audit.add_argument("--decoded-static-dir", type=Path, required=True)
    buff_audit.add_argument("--capture-root", type=Path, required=True)
    buff_audit.add_argument("--out", type=Path, required=True)
    buff_audit.add_argument(
        "--detail",
        choices=BUFF_AUDIT_DETAILS,
        default="full",
        help="write the full diagnostic report or a slim simulator-facing report",
    )

    hull_buff_map = subparsers.add_parser("hull-buff-map", help="map hull core-stat and ship-bonus buff surfaces")
    hull_buff_map.add_argument("--decoded-static-dir", type=Path, required=True)
    hull_buff_map.add_argument("--buff-audit", type=Path)
    hull_buff_map.add_argument("--out-dir", type=Path, required=True)
    hull_buff_map.add_argument("--label", default="battle-data")

    return parser


def _threshold(name: str) -> ReplayThreshold:
    if name == "release":
        return ReplayThreshold.release()
    return ReplayThreshold.mvp()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "report":
        fixture = load_fixture(args.fixture)
        expected = expected_trace_from_fixture(fixture)
        actual = replay_fixture(fixture)
        comparison = compare_traces(expected=expected, actual=actual, threshold=_threshold(args.threshold))

        args.out_dir.mkdir(parents=True, exist_ok=True)
        fixture_name = args.fixture.stem
        (args.out_dir / f"{fixture_name}.md").write_text(
            render_markdown_report(fixture_name, comparison),
            encoding="utf-8",
        )
        (args.out_dir / f"{fixture_name}.json").write_text(render_json_report(comparison), encoding="utf-8")

        return 0 if comparison.passed else 2

    if args.command == "build-fixture":
        fixture = build_fixture(
            decoded_static_dir=args.decoded_static_dir,
            battle_journal_path=args.battle_journal,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0

    if args.command == "static-catalog":
        report = compare_static_catalog(
            decoded_static_dir=args.decoded_static_dir,
            capture_root=args.capture_root,
            side=args.side,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0

    if args.command == "observations":
        observations = export_observations(
            decoded_static_dir=args.decoded_static_dir,
            capture_root=args.capture_root,
            buff_audit_path=args.buff_audit,
        )
        write_observations_jsonl(observations=observations, out_path=args.out)
        return 0

    if args.command == "analyze-mitigation":
        analysis = analyze_mitigation(observations_path=args.observations, decoded_static_dir=args.decoded_static_dir)
        write_mitigation_analysis(analysis=analysis, out_path=args.out)
        return 0

    if args.command == "project-rounds":
        rows = filter_observations(
            load_observations_jsonl(args.observations),
            battle_ids=args.battle_id,
            battle_classes=args.battle_class,
            limit=args.limit,
        )
        model = load_synced_linear_mitigation_model(args.mitigation_analysis)
        projection = project_observations(
            rows,
            mitigation_model=model,
            mode=args.mode,
            max_rounds=args.max_rounds,
            max_attacks=args.max_attacks,
            filters={
                "battle_id": args.battle_id or [],
                "battle_class": args.battle_class or [],
                "limit": args.limit,
            },
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(render_projection_json(projection), encoding="utf-8")
        args.out.with_suffix(".md").write_text(render_projection_markdown(projection), encoding="utf-8")
        return 0

    if args.command == "defender-diagnostics":
        report = build_defender_diagnostics(
            observations_path=args.observations,
            min_group_count=args.min_group_count,
        )
        write_defender_diagnostics(report=report, out_path=args.out)
        return 0

    if args.command == "buff-audit":
        report = generate_buff_audit(
            decoded_static_dir=args.decoded_static_dir,
            capture_root=args.capture_root,
            detail=args.detail,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0

    if args.command == "hull-buff-map":
        build_hull_buff_map(
            decoded_static_dir=args.decoded_static_dir,
            buff_audit_path=args.buff_audit,
            out_dir=args.out_dir,
            label=args.label,
        )
        return 0

    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
