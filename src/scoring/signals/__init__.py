"""Signal implementations for the unified scorer.

One module per signal (UNIFIED_SCORING_PLAN §4 / §10). Each module exposes:

- pure helper functions holding the extracted legacy logic (the legacy
  ``ContentOrganizer`` method delegates to these during the transition), and
- a Signal class (``name``/``weight``/``cost_tier`` + ``applies_to``/``run``)
  emitting ``CategoryScore`` entries over a ``FileContext``.

Signal modules must not import ``src.organizers.content_organizer`` (the
organizer imports them; the reverse would be circular). ``shared.*`` and
``src.classifiers.*`` imports are fine.
"""
