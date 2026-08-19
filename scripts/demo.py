"""The whole system in one run, told as Amara's story.

Runs in process against the shipped corpus. No server, no network, no model:
the composer is the deterministic one and the crisis screen is the lexicon
alone. That last part matters and the script says so where it happens, because
ADR-0008 measured the lexicon on its own catching 2 of 12 held-out crisis turns
and a demo that hides that is selling something.

    uv run python scripts/demo.py

Everything printed here is produced by the same code paths the API and the
tests use. Nothing is scripted output.
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from langgraph.types import Command

from wayfinder.corpus.loader import load_corpus
from wayfinder.corpus.models import StalenessBand
from wayfinder.graph.build import compile_graph
from wayfinder.graph.checkpoint import sqlite_checkpointer, thread
from wayfinder.graph.nodes import Deps
from wayfinder.graph.state import HumanDetermination, WayfinderState
from wayfinder.plan.builder import build_plan
from wayfinder.plan.diff import diff_plans
from wayfinder.plan.situation import Situation
from wayfinder.retrieval.index import Index
from wayfinder.safety.loader import load_directory, load_lexicon

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "wayfinder" / "corpus" / "data"
EXAMPLES = ROOT / "examples"

TODAY = date(2026, 8, 18)
CLARE = "Clare Nolan, Irish Refugee Council"


def heading(number: int, text: str) -> None:
    print()
    print(f"--- {number}. {text} " + "-" * max(0, 68 - len(text)))
    print()


def situation_from(name: str) -> Situation:
    raw = yaml.safe_load((EXAMPLES / name).read_text(encoding="utf-8"))
    return Situation.model_validate(raw)


def main() -> int:
    corpus = load_corpus(DATA, today=TODAY)
    deps = Deps(
        lexicon=load_lexicon(today=TODAY),
        directory=load_directory(today=TODAY),
        index=Index(corpus, today=TODAY),
        tasks=corpus.tasks,
    )
    week_one = situation_from("amara-week-one.yaml")

    print("Wayfinder demo. Amara, two weeks in Ireland, one child aged seven.")
    print(f"Planning against {TODAY}. Crisis screen: deterministic lexicon only.")

    # 1 ----------------------------------------------------------------------
    heading(1, "What she can start now, and what is waiting")
    plan = build_plan(corpus.tasks, week_one, today=TODAY)
    titles = {item.task.id: item.task.title for item in plan.items}

    print("Start now, in this order:")
    for task_id in plan.frontier_order:
        print(f"  {titles[task_id]}")

    print()
    print("Waiting on something:")
    for item in plan.blocked[:5]:
        route = plan.next_actions.get(item.task.id, ())
        print(f"  {item.task.title}")
        if route:
            print(f"    do first: {', '.join(titles.get(t, t) for t in route)}")
        for ref in item.determination_refs:
            print(f"    decided by somebody else: {ref}")

    print()
    if plan.open_questions:
        print("Genuinely unknown, so it asks rather than assuming:")
        for question in sorted(plan.open_questions)[:4]:
            print(f"  {question}")
    else:
        print("Nothing is unknown here. This situation file states everything")
        print("the applicable tasks depend on, either as held or as absent.")

    # 2 ----------------------------------------------------------------------
    heading(2, "A procedural question. Answered, with a dated source")
    graph = compile_graph(deps)
    result = dict(
        graph.invoke(
            WayfinderState(
                current_question="how do I apply for a PPS number",
                situation=week_one,
                today=TODAY,
            )
        )
    )
    answer = result["answer"]
    print(answer.text.rstrip())
    print()
    print("Every source behind that, with the date it was last checked:")
    for span in answer.citations:
        print(f"  {span.url}")
        print(f"    {span.source_title}, checked {span.last_verified}")

    # 3 ----------------------------------------------------------------------
    heading(3, "An entitlement question. Not answered by this system")
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "demo.sqlite"
        with sqlite_checkpointer(db) as saver:
            durable = compile_graph(deps, checkpointer=saver)
            config = thread("amara")
            paused: dict[str, Any] = dict(
                durable.invoke(
                    WayfinderState(
                        current_question="Am I entitled to child benefit?",
                        situation=week_one,
                        today=TODAY,
                    ),
                    config,
                )
            )
            payload = paused["__interrupt__"][0].value
            print("The graph stopped. This is what reached the caseworker queue:")
            print()
            print(f"  asked: {payload['question']}")
            print(f"  on:    {payload['asked_on']}")
            print()
            for line in payload["situation_summary"].splitlines():
                print(f"  {line}")

            # The pause is on disk now. The process could exit here and the
            # question would still be waiting when it came back. That is the
            # whole reason this runs on a checkpointer rather than in memory.
            heading(4, "Clare answers, three days later")
            final = dict(
                durable.invoke(
                    Command(
                        resume=HumanDetermination(
                            answer=(
                                "Habitual residence has not been assessed for you "
                                "yet. I have asked the Department to start that. "
                                "Do not delay the PPS number in the meantime."
                            ),
                            answered_by=CLARE,
                            answered_on=date(2026, 8, 21),
                        ).model_dump(mode="json")
                    ),
                    config,
                )
            )
            print(final["answer"].text.rstrip())

    # 5 ----------------------------------------------------------------------
    heading(5, "Six weeks later. What changed")
    later = build_plan(
        corpus.tasks, situation_from("amara-six-weeks-later.yaml"), today=TODAY
    )
    changes = diff_plans(plan, later)
    titles.update({i.task.id: i.task.title for i in later.items})
    for label, ids in (
        ("You can now start", changes.newly_unblocked),
        ("New on your list", changes.newly_applicable),
        ("Now done", changes.newly_done),
    ):
        if not ids:
            continue
        print(f"{label}:")
        for task_id in ids:
            print(f"  {titles.get(task_id, task_id)}")
        print()

    # 6 ----------------------------------------------------------------------
    heading(6, "Is the corpus still trustworthy")
    health = corpus.health(today=TODAY)
    for band in StalenessBand:
        print(f"  {band.value}: {len(health[band])}")
    excluded = health[StalenessBand.EXCLUDED]
    print()
    print(
        "Nothing is excluded, so /v1/corpus/health returns 200."
        if not excluded
        else f"{len(excluded)} source(s) aged out. /v1/corpus/health returns 503."
    )

    print()
    print("What this run did not show, because it needs a key:")
    print("  The model-backed crisis screen. Without it the lexicon caught 2 of")
    print("  12 held-out crisis turns. See docs/adr/ADR-0008.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
