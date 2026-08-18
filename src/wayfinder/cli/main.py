"""The M1 demo surface. A situation goes in, an ordered plan comes out.

Exit codes follow the project convention: 0 pass, 1 a verdict of fail, 2 could
not evaluate. Collapsing 1 and 2 would let a broken check read as a passing one,
which is the failure mode any gate worth having exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from wayfinder.cli.render import render_plan
from wayfinder.corpus.loader import CorpusError, load_corpus
from wayfinder.corpus.models import Corpus, StalenessBand
from wayfinder.plan.builder import build_plan
from wayfinder.plan.diff import diff_plans
from wayfinder.plan.errors import PlanError
from wayfinder.plan.plan import Plan
from wayfinder.plan.situation import Situation

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_CANNOT_EVALUATE = 2

DEFAULT_CORPUS = Path(__file__).resolve().parent.parent / "corpus" / "data"


def _load_situation(path: Path) -> Situation:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Situation.model_validate(raw)


def _plan_as_dict(plan: Plan) -> dict[str, Any]:
    return {
        "built_on": plan.built_on.isoformat(),
        "frontier": list(plan.frontier_order),
        "blocked": [i.task.id for i in plan.blocked],
        "needs_info": [i.task.id for i in plan.needs_info],
        "done": [i.task.id for i in plan.done],
        "open_questions": sorted(plan.open_questions),
        "unblocking_route": {k: list(v) for k, v in plan.unblocking_route.items()},
        "next_actions": {k: list(v) for k, v in plan.next_actions.items()},
        "gated_wait_days": {k: v.days for k, v in plan.gated_wait.items()},
    }


def _cmd_plan(args: argparse.Namespace) -> int:
    corpus = load_corpus(args.corpus, today=args.today)
    situation = _load_situation(args.situation)
    plan = build_plan(corpus.tasks, situation, today=args.today)

    if args.format == "json":
        print(json.dumps(_plan_as_dict(plan), indent=2))
    else:
        print(render_plan(plan, corpus, situation), end="")
    return EXIT_OK


def _cmd_diff(args: argparse.Namespace) -> int:
    corpus = load_corpus(args.corpus, today=args.today)
    before = build_plan(corpus.tasks, _load_situation(args.before), today=args.today)
    after = build_plan(corpus.tasks, _load_situation(args.after), today=args.today)
    changes = diff_plans(before, after)

    if args.format == "json":
        print(changes.model_dump_json(indent=2))
        return EXIT_OK

    if changes.empty:
        print("Nothing has changed.")
        return EXIT_OK

    titles = {i.task.id: i.task.title for i in (*before.items, *after.items)}
    sections = (
        ("You can now start", changes.newly_unblocked),
        ("New for you", changes.newly_applicable),
        ("Now done", changes.newly_done),
        ("No longer on your list", changes.no_longer_applicable),
        ("Now waiting on something", changes.newly_blocked),
    )
    for heading, ids in sections:
        if not ids:
            continue
        print(heading)
        for task_id in ids:
            print(f"  {titles.get(task_id, task_id)}")
        print()
    return EXIT_OK


def _cmd_corpus_check(args: argparse.Namespace) -> int:
    corpus = load_corpus(args.corpus, today=args.today)
    print(
        f"{len(corpus.tasks)} tasks, {len(corpus.sources)} sources, "
        f"{len(corpus.artefacts)} artefacts. No integrity problems."
    )
    return EXIT_OK


def _cmd_corpus_health(args: argparse.Namespace) -> int:
    corpus: Corpus = load_corpus(args.corpus, today=args.today)
    health = corpus.health(today=args.today)
    for band in StalenessBand:
        ids = health[band]
        print(f"{band.value}: {len(ids)}")
        for source_id in ids:
            source = corpus.sources[source_id]
            print(f"  {source_id}  last verified {source.last_verified}")
    breached = health[StalenessBand.EXCLUDED]
    if breached:
        print()
        print(
            f"{len(breached)} source(s) are past a year old and are excluded from "
            "retrieval. This is an operational alarm, not a warning."
        )
        return EXIT_FAIL
    return EXIT_OK


def _date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wayfinder", description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS,
        help="corpus directory containing tasks/, sources/ and artefacts/",
    )
    parser.add_argument(
        "--today",
        type=_date,
        default=date.today(),  # noqa: DTZ011 - a local calendar date is the right unit here
        help="the date to plan against, ISO format. Injected so runs are reproducible",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_cmd = subparsers.add_parser("plan", help="build a plan for a situation")
    plan_cmd.add_argument("situation", type=Path)
    plan_cmd.add_argument("--format", choices=("text", "json"), default="text")
    plan_cmd.set_defaults(func=_cmd_plan)

    diff_cmd = subparsers.add_parser("diff", help="what changed between two situations")
    diff_cmd.add_argument("before", type=Path)
    diff_cmd.add_argument("after", type=Path)
    diff_cmd.add_argument("--format", choices=("text", "json"), default="text")
    diff_cmd.set_defaults(func=_cmd_diff)

    corpus_cmd = subparsers.add_parser("corpus", help="corpus integrity and staleness")
    corpus_sub = corpus_cmd.add_subparsers(dest="corpus_command", required=True)
    check_cmd = corpus_sub.add_parser("check", help="validate corpus integrity")
    check_cmd.set_defaults(func=_cmd_corpus_check)
    health_cmd = corpus_sub.add_parser("health", help="staleness report")
    health_cmd.set_defaults(func=_cmd_corpus_health)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAIL
    except PlanError as exc:
        print(f"plan engine refused to build: {exc}", file=sys.stderr)
        return EXIT_FAIL
    except (OSError, yaml.YAMLError) as exc:
        print(f"could not evaluate: {exc}", file=sys.stderr)
        return EXIT_CANNOT_EVALUATE
    return result


if __name__ == "__main__":
    raise SystemExit(main())
