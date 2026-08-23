"""The command line. A situation goes in, an ordered plan comes out.

`ask` runs one whole turn through the graph and `serve` starts the API. Both
refuse to run with the deterministic crisis screen alone unless told to in so
many words, because ADR-0008 measured that configuration catching two crisis
turns out of twelve.

Exit codes follow the project convention: 0 pass, 1 a verdict of fail, 2 could
not evaluate. Collapsing 1 and 2 would let a broken check read as a passing one,
which is the failure mode any gate worth having exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import os
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


class CannotEvaluateError(Exception):
    """Not a failed check. A check that could not be run at all.

    Kept distinct so exit code 2 never gets collapsed into exit code 1, which
    would let a configuration problem read as a verdict.
    """


def _needs_extra(exc: Exception, extra: str, what: str) -> CannotEvaluateError:
    """A missing optional dependency, said in one line instead of a traceback.

    `uv sync` deliberately installs neither the web framework nor the model
    client, because the plan engine and the safety layers are usable as a
    library without them. The cost of that choice is that the first thing a new
    reader runs can be the thing that needs one, and a `ModuleNotFoundError`
    stack does not tell them which flag fixes it.
    """
    return CannotEvaluateError(
        f"{what} needs the '{extra}' extra, which is not installed. "
        f"Install it with: uv sync --extra {extra}"
    )


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

    # Newly unblocked leads, because it is the good news and somebody six months
    # in is reading this to find out what they can finally do.
    #
    # The wording of the fourth heading is deliberate. A task disappearing can
    # read as something being taken away, and for somebody in this position that
    # is a frightening sentence to read by accident. Naming the cause, that the
    # situation changed rather than that an entitlement was withdrawn, is the
    # difference. It also happens to be the only thing this system knows: it has
    # no idea whether the task was completed or simply stopped applying.
    sections = (
        ("You can now start", changes.newly_unblocked),
        ("New on your list", changes.newly_applicable),
        ("Now done", changes.newly_done),
        (
            "Not on your list any more, because your situation changed",
            changes.no_longer_applicable,
        ),
        ("Now waiting on something", changes.newly_blocked),
    )
    for heading, ids in sections:
        if not ids:
            continue
        print(heading)
        for task_id in ids:
            print(f"  {titles.get(task_id, task_id)}")
        print()

    if changes.blocker_changed:
        print("Still waiting, but on something different now")
        for change in changes.blocker_changed:
            print(f"  {titles.get(change.task_id, change.task_id)}")
            print(f"    was: {', '.join(change.was) or 'nothing recorded'}")
            print(f"    now: {', '.join(change.now) or 'nothing recorded'}")
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


# --- turns and serving -------------------------------------------------------


def _crisis_screen(args: argparse.Namespace) -> object | None:
    """The model screen, or a refusal to start without one.

    ADR-0008 is the reason this is a hard stop rather than a warning. The
    deterministic lexicon caught 2 of 12 held-out crisis turns. Starting
    silently with it alone would ship a safety claim the measurements do not
    support, so the way to do it is to say so on the command line.
    """
    if args.no_model_screen:
        print(
            "Starting with the deterministic crisis screen only. ADR-0008 "
            "measured that at 0.167 recall on held-out data.",
            file=sys.stderr,
        )
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        msg = (
            "ANTHROPIC_API_KEY is not set, so the model-backed crisis screen "
            "cannot start. Set it, or pass --no-model-screen to run with the "
            "deterministic screen alone and accept what ADR-0008 measured."
        )
        raise CannotEvaluateError(msg)
    try:
        from wayfinder.safety.llm import AnthropicCrisisScreen

        return AnthropicCrisisScreen()
    except (ModuleNotFoundError, RuntimeError) as exc:
        raise _needs_extra(exc, "llm", "the model crisis screen") from exc


def _cmd_ask(args: argparse.Namespace) -> int:
    """One whole turn, printed the way a person would read it."""
    from wayfinder.graph.build import compile_graph
    from wayfinder.graph.nodes import Deps
    from wayfinder.graph.state import WayfinderState
    from wayfinder.retrieval.index import Index
    from wayfinder.safety.loader import load_directory, load_lexicon

    screen = _crisis_screen(args)
    corpus = load_corpus(args.corpus, today=args.today)
    situation = _load_situation(args.situation) if args.situation else Situation()
    graph = compile_graph(
        Deps(
            lexicon=load_lexicon(today=args.today),
            directory=load_directory(today=args.today),
            index=Index(corpus, today=args.today),
            tasks=corpus.tasks,
            model_screen=screen,  # type: ignore[arg-type]
        )
    )
    result = dict(
        graph.invoke(
            WayfinderState(
                current_question=args.question, situation=situation, today=args.today
            )
        )
    )

    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        print("This one needs a person, so it has gone to a caseworker.")
        print()
        print(json.dumps(payload, indent=2, default=str))
        return EXIT_OK

    answer = result.get("answer")
    print(answer.text if answer else "")
    for span in answer.citations if answer else ():
        print(f"  {span.source_title}, checked {span.last_verified}")
        print(f"  {span.url}")
    return EXIT_OK


def _cmd_serve(args: argparse.Namespace) -> int:
    """Start the API with a durable checkpointer.

    The checkpointer is a file rather than memory because the pause this system
    is built around lasts days. An in-memory one would lose every caseworker
    queue item on restart, which is the one failure this design cannot have.
    """
    try:
        import uvicorn

        from wayfinder.api import create_app
    except ModuleNotFoundError as exc:
        raise _needs_extra(exc, "api", "the API") from exc

    from wayfinder.api.auth import AuthError, load_caseworkers
    from wayfinder.graph.checkpoint import sqlite_checkpointer

    screen = _crisis_screen(args)

    try:
        staff = load_caseworkers(path=args.caseworkers)
    except AuthError as exc:
        # Exit 2. A registry that cannot be read is a configuration problem,
        # not a verdict about anything, and starting anyway would open the API
        # with the queue silently shut.
        print(f"could not read the caseworker registry: {exc}", file=sys.stderr)
        return EXIT_CANNOT_EVALUATE

    with sqlite_checkpointer(args.db) as saver:
        app = create_app(
            checkpointer=saver,
            today=args.today,
            model_screen=screen,  # type: ignore[arg-type]
            caseworkers=staff,
        )
        print(f"Threads and queue state persist in {args.db}.")
        # Said at startup rather than discovered at the first 503. Nobody
        # registered is a working configuration for the applicant endpoints and
        # a closed door for the queue, and that is worth knowing before a
        # caseworker is waiting on it.
        if staff.configured:
            print(f"{len(staff)} caseworker(s) may open the queue.")
        else:
            print(
                "No caseworkers are registered, so the queue is closed. "
                'Mint one with `wayfinder caseworker-token "Name"` and set '
                "WAYFINDER_CASEWORKERS, or pass --caseworkers."
            )
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return EXIT_OK


def _cmd_caseworker_token(args: argparse.Namespace) -> int:
    """Mint a caseworker token and print the line to configure.

    Printed once and never stored. Only the digest goes into configuration, so
    losing the token means minting another rather than recovering this one,
    which is the property that makes a leaked config harmless.
    """
    from wayfinder.api.auth import ENV_VAR, mint_token

    token, digest = mint_token()

    print(f"Token for {args.name}. Copy it now, it is not stored anywhere:")
    print()
    print(f"    {token}")
    print()
    print("Add this caseworker to the registry and restart the API:")
    print()
    print(
        f"    {ENV_VAR}='"
        + json.dumps([{"name": args.name, "token_sha256": digest}])
        + "'"
    )
    print()
    print("To add somebody to an existing registry, put both entries in the")
    print("same JSON list. Two people must never share a token: the name on a")
    print("determination comes from the credential that posted it.")
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

    token_cmd = subparsers.add_parser(
        "caseworker-token",
        help="mint a token for somebody who may answer determinations",
    )
    token_cmd.add_argument(
        "name",
        help="the name this person's determinations will be signed with, "
        "for example 'Clare Nolan, Irish Refugee Council'",
    )
    token_cmd.set_defaults(func=_cmd_caseworker_token)

    ask_cmd = subparsers.add_parser("ask", help="run one turn through the graph")
    ask_cmd.add_argument("question")
    ask_cmd.add_argument("--situation", type=Path, default=None)
    _add_screen_flag(ask_cmd)
    ask_cmd.set_defaults(func=_cmd_ask)

    serve_cmd = subparsers.add_parser("serve", help="start the API")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8000)
    serve_cmd.add_argument(
        "--db",
        type=Path,
        default=Path("wayfinder.sqlite"),
        help="where paused threads live. A file, so the queue survives restarts",
    )
    serve_cmd.add_argument(
        "--caseworkers",
        type=Path,
        default=None,
        help="a JSON file of caseworkers, instead of $WAYFINDER_CASEWORKERS. "
        "Easier to manage than a long environment variable once there is more "
        "than one person",
    )
    _add_screen_flag(serve_cmd)
    serve_cmd.set_defaults(func=_cmd_serve)

    return parser


def _add_screen_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-model-screen",
        action="store_true",
        help=(
            "run with the deterministic crisis lexicon alone. ADR-0008 measured "
            "that at 0.167 recall against a design gate of 0.99"
        ),
    )


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
    except CannotEvaluateError as exc:
        print(f"could not evaluate: {exc}", file=sys.stderr)
        return EXIT_CANNOT_EVALUATE
    except (OSError, yaml.YAMLError) as exc:
        print(f"could not evaluate: {exc}", file=sys.stderr)
        return EXIT_CANNOT_EVALUATE
    return result


if __name__ == "__main__":
    raise SystemExit(main())
