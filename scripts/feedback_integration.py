#!/usr/bin/env python3
"""Feedback integration wrapper.

Thin wrapper around ``src.feedback.feedback_loop``, which holds
FeedbackIntegration (pre-categorization correction checks, batch application,
and correction-suggestion reports).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.feedback.feedback_loop import FeedbackIntegration, main  # noqa: E402,F401

if __name__ == "__main__":
    main()
