"""The safety layer. It runs before the graph, and its first two layers run
before any model.

`crisis`, `markers`, `classify`, `reference`, `normalise`, `models`, `taxonomy`
and `refusals` are pure: no I/O, no framework, no model library. `loader` is the
only module here that touches a file. The split is enforced by an import-linter
contract, because "the crisis path contains no model" is the kind of claim that
decays the first time somebody needs just one import.
"""

from wayfinder.safety.classify import RemainderClassifier, classify
from wayfinder.safety.crisis import respond, screen
from wayfinder.safety.loader import SafetyDataError, load_directory, load_lexicon
from wayfinder.safety.markers import determination_marker
from wayfinder.safety.models import (
    Classification,
    CrisisCategory,
    CrisisDirectory,
    CrisisHit,
    CrisisLexicon,
)
from wayfinder.safety.normalise import normalise
from wayfinder.safety.refusals import refusal_for
from wayfinder.safety.taxonomy import Layer, QuestionClass

__all__ = [
    "Classification",
    "CrisisCategory",
    "CrisisDirectory",
    "CrisisHit",
    "CrisisLexicon",
    "Layer",
    "QuestionClass",
    "RemainderClassifier",
    "SafetyDataError",
    "classify",
    "determination_marker",
    "load_directory",
    "load_lexicon",
    "normalise",
    "refusal_for",
    "respond",
    "screen",
]
