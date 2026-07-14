#!/usr/bin/env python3
"""Correction feedback CLI wrapper.

Thin wrapper around ``src.feedback.correction_tracker``, which holds
CorrectionFeedbackSystem and this CLI's implementation (add/check/suggest/
stats/export-rules/list subcommands).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.feedback.correction_tracker import CorrectionFeedbackSystem, main  # noqa: E402,F401

if __name__ == "__main__":
    main()
