#!/usr/bin/env python3
"""Launcher for the feedback-integration status demo — logic lives in src/feedback/.

Programmatic use: ``from src.feedback import FeedbackIntegration``.
"""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))

    from src.feedback.feedback_loop import main

    main()
