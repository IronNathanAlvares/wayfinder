"""Generate the demo site's data by running the real system.

The site is static and makes no network requests, so everything it shows has to
be recorded ahead of time. The honest way to record it is to run the actual
plan engine, the actual graph and the actual safety layers, and write down what
they produce. Nothing in `site/data.js` is written by hand.

**No model is involved and no API key is needed.** Every turn below is one the
deterministic layers resolve on their own: the crisis lexicon fires on the
crisis turn, the determination markers fire on the entitlement turn, and the
composer is the extractive one. That is not a shortcut, it is what makes this
reproducible: `test_site_data.py` regenerates the file and fails if it differs,
so the site cannot drift away from the system it claims to demonstrate.

What that costs in honesty is stated on the page itself: the crisis turn shown
is one the pattern list catches, and ADR-0008 is clear that the pattern list
alone catches about one in seven.

    uv run python scripts/build_site_data.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from wayfinder.cli.render import _deadline_line
from wayfinder.corpus.loader import load_corpus
from wayfinder.corpus.models import StalenessBand, staleness
from wayfinder.graph.build import compile_graph, edges_of
from wayfinder.graph.nodes import Deps
from wayfinder.graph.state import HumanDetermination, WayfinderState
from wayfinder.plan.builder import build_plan
from wayfinder.plan.diff import diff_plans
from wayfinder.plan.plan import Plan
from wayfinder.plan.situation import Situation
from wayfinder.retrieval.index import Index
from wayfinder.safety.loader import load_directory, load_lexicon

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "wayfinder" / "corpus" / "data"
EXAMPLES = ROOT / "examples"
MEASUREMENTS = ROOT / "tests" / "corpus" / "measurements"
OUT = ROOT / "site" / "data.js"

# Frozen, like every other date in this project. A demo that reads the wall
# clock shows different content every day and cannot be tested.
TODAY = date(2026, 8, 24)

# One turn per route out of classification, chosen so the deterministic layers
# resolve every one of them without a model.
TURNS: tuple[tuple[str, str], ...] = (
    ("procedural", "how do I apply for a PPS number"),
    ("planning", "I have just arrived, what do I do?"),
    ("determination", "am I entitled to child benefit?"),
    ("crisis", "i have nowhere to sleep tonight and my son is with me"),
    ("out_of_scope", "should I appeal or make a new application?"),
)

CASEWORKER = "Clare Nolan, Irish Refugee Council"
CASEWORKER_ANSWER = (
    "Habitual residence has not been assessed for you yet. I have asked the "
    "Department to start that, and it usually takes a few weeks. Do not wait "
    "on it before applying for the PPS number."
)


def situation_from(name: str) -> Situation:
    raw = yaml.safe_load((EXAMPLES / name).read_text(encoding="utf-8"))
    return Situation.model_validate(raw)


def span_as_dict(span: Any) -> dict[str, Any]:
    return {
        "title": span.title,
        "why": span.why,
        "source": span.source_title,
        "url": span.url,
        "lastVerified": span.last_verified.isoformat(),
        "staleness": span.staleness.value,
        "domain": span.domain.value,
    }


def plan_as_dict(plan: Plan) -> dict[str, Any]:
    titles = {item.task.id: item.task.title for item in plan.items}
    why = {item.task.id: item.task.why for item in plan.items}

    def clock(task_id: str) -> dict[str, Any] | None:
        """A closing window, rendered as the CLI renders it.

        The sentence is reused rather than rewritten for the page, because the
        wording carries a safety decision: nothing here ever says a window has
        shut. Two copies of that rule would eventually disagree.
        """
        state = plan.deadlines.get(task_id)
        if state is None:
            return None
        return {"status": state.status.value, "line": _deadline_line(state)}

    return {
        "startNow": [
            {
                "id": task_id,
                "title": titles[task_id],
                "why": why[task_id],
                "gatesDays": plan.gated_wait[task_id].days,
                "deadline": clock(task_id),
                "unblocks": len(
                    [t for t, route in plan.next_actions.items() if task_id in route]
                ),
            }
            for task_id in plan.frontier_order
        ],
        "waiting": [
            {
                "id": item.task.id,
                "title": item.task.title,
                "why": item.task.why,
                "deadline": clock(item.task.id),
                "doFirst": [
                    titles.get(t, t) for t in plan.next_actions.get(item.task.id, ())
                ],
                "decidedElsewhere": list(item.determination_refs),
            }
            for item in plan.blocked
        ],
        "done": [{"id": item.task.id, "title": item.task.title} for item in plan.done],
        "openQuestions": sorted(plan.open_questions),
        "counts": {
            "startNow": len(plan.frontier_order),
            "waiting": len(plan.blocked),
            "done": len(plan.done),
        },
    }


def build_turns(deps: Deps) -> list[dict[str, Any]]:
    graph = compile_graph(deps)
    week_one = situation_from("amara-week-one.yaml")
    out: list[dict[str, Any]] = []

    for expected, question in TURNS:
        result = dict(
            graph.invoke(
                WayfinderState(
                    current_question=question, situation=week_one, today=TODAY
                )
            )
        )
        entry: dict[str, Any] = {
            "question": question,
            "expected": expected,
            "route": result["question_class"].value,
            "trace": [
                {"node": e.node, "detail": e.detail} for e in result.get("trace", [])
            ],
        }

        if "__interrupt__" in result:
            payload = result["__interrupt__"][0].value
            entry["paused"] = True
            entry["escalation"] = {
                "kind": payload["kind"],
                "question": payload["question"],
                "situationSummary": payload["situation_summary"],
                "askedOn": payload["asked_on"],
            }
        else:
            answer = result.get("answer")
            entry["paused"] = False
            entry["answer"] = answer.text if answer else ""
            entry["citations"] = [
                span_as_dict(s) for s in (answer.citations if answer else ())
            ]
        out.append(entry)
    return out


def build_handoff(deps: Deps) -> dict[str, Any]:
    """The escalation, and the answer that comes back attributed to a person."""
    import tempfile

    from langgraph.types import Command

    from wayfinder.graph.checkpoint import sqlite_checkpointer, thread

    week_one = situation_from("amara-week-one.yaml")
    question = "am I entitled to child benefit?"

    with (
        tempfile.TemporaryDirectory() as tmp,
        sqlite_checkpointer(Path(tmp) / "demo.sqlite") as saver,
    ):
        graph = compile_graph(deps, checkpointer=saver)
        config = thread("amara")
        paused = dict(
            graph.invoke(
                WayfinderState(
                    current_question=question, situation=week_one, today=TODAY
                ),
                config,
            )
        )
        payload = paused["__interrupt__"][0].value
        resumed = dict(
            graph.invoke(
                Command(
                    resume=HumanDetermination(
                        answer=CASEWORKER_ANSWER,
                        answered_by=CASEWORKER,
                        answered_on=date(2026, 8, 21),
                    ).model_dump(mode="json")
                ),
                config,
            )
        )

    return {
        "queueItem": {
            "threadId": "amara",
            "asked": payload["question"],
            "askedOn": payload["asked_on"],
            "situationSummary": payload["situation_summary"],
        },
        "caseworker": CASEWORKER,
        "answeredOn": "2026-08-21",
        "reply": resumed["answer"].text,
        "attributedTo": resumed["answer"].attributed_to,
    }


def build_corpus_health() -> dict[str, Any]:
    corpus = load_corpus(DATA, today=TODAY)
    bands: dict[str, list[dict[str, str]]] = {b.value: [] for b in StalenessBand}
    for source in corpus.sources.values():
        bands[staleness(source, today=TODAY).value].append(
            {
                "id": source.id,
                "publisher": source.publisher,
                "title": source.title,
                "url": source.url,
                "lastVerified": source.last_verified.isoformat(),
            }
        )
    return {
        "checkedOn": TODAY.isoformat(),
        "tasks": len(corpus.tasks),
        "sources": len(corpus.sources),
        "artefacts": len(corpus.artefacts),
        "bands": bands,
        "alarm": bool(bands[StalenessBand.EXCLUDED.value]),
    }


def build_topology(deps: Deps) -> dict[str, Any]:
    """The compiled graph, so the page draws the real thing rather than a sketch."""
    compiled = compile_graph(deps)
    return {
        "edges": [{"from": a, "to": b} for a, b in sorted(edges_of(compiled))],
        "nodes": sorted(compiled.get_graph().nodes),
    }


def build_measurements() -> dict[str, Any]:
    """The eval results, read from the committed measurement files.

    Read rather than restated, so the chart on the page and the numbers in
    ADR-0008 cannot disagree.
    """
    latest = json.loads(
        (MEASUREMENTS / "2026-08-22-crisis-holdout-v4-opus.json").read_text(
            encoding="utf-8"
        )
    )
    union = json.loads(
        (MEASUREMENTS / "2026-08-22-crisis-holdout-v4-union.json").read_text(
            encoding="utf-8"
        )
    )

    def arm(source: dict[str, Any], needle: str) -> dict[str, Any]:
        r = next(x for x in source["results"] if needle in x["configuration"])
        return {
            "recall": r["recall"],
            "bound": r["lower_bound_95"],
            "caught": r["caught"],
            "of": r["crisis_items"],
            "falsePositives": len(r["fired_on_non_crisis"]),
            "byCategory": {k: v["recall"] for k, v in r["by_category"].items()},
        }

    return {
        "split": "crisis-holdout-v4",
        "crisisItems": 320,
        "nearMisses": 200,
        "gate": 0.99,
        "arms": [
            {
                "label": "Pattern list only",
                "model": "no model",
                **arm(union, "deterministic"),
            },
            {
                "label": "Haiku 4.5",
                "model": "claude-haiku-4-5",
                **arm(union, "prompt v5"),
            },
            {"label": "Opus 5", "model": "claude-opus-5", **arm(latest, "opus")},
        ],
        "stability": union["sample_stability"],
        "opusMisses": [
            {"text": m["text"], "category": m["category"]}
            for m in next(r for r in latest["results"] if "opus" in r["configuration"])[
                "missed"
            ]
        ],
    }


def main() -> int:
    corpus = load_corpus(DATA, today=TODAY)
    deps = Deps(
        lexicon=load_lexicon(today=TODAY),
        directory=load_directory(today=TODAY),
        index=Index(corpus, today=TODAY),
        tasks=corpus.tasks,
    )

    week_one = situation_from("amara-week-one.yaml")
    later = situation_from("amara-six-weeks-later.yaml")
    plan_one = build_plan(corpus.tasks, week_one, today=TODAY)
    plan_two = build_plan(corpus.tasks, later, today=TODAY)
    titles = {i.task.id: i.task.title for i in (*plan_one.items, *plan_two.items)}
    changes = diff_plans(plan_one, plan_two)

    payload = {
        "generatedFrom": "scripts/build_site_data.py",
        "today": TODAY.isoformat(),
        "plans": {
            "weekOne": plan_as_dict(plan_one),
            "sixWeeksLater": plan_as_dict(plan_two),
        },
        "diff": {
            "nowStartable": [titles.get(t, t) for t in changes.newly_unblocked],
            "newlyApplicable": [titles.get(t, t) for t in changes.newly_applicable],
            "nowDone": [titles.get(t, t) for t in changes.newly_done],
        },
        "turns": build_turns(deps),
        "handoff": build_handoff(deps),
        "corpusHealth": build_corpus_health(),
        "topology": build_topology(deps),
        "measurements": build_measurements(),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    OUT.write_text(
        "// Generated by scripts/build_site_data.py. Do not edit by hand.\n"
        "// Every value here was produced by running the real system; see the\n"
        "// script's docstring for what that does and does not include.\n"
        f"window.WAYFINDER = {body};\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(ROOT)} ({len(body):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
