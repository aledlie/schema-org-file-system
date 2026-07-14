#!/usr/bin/env python3
"""Launcher for the correction-feedback CLI — logic lives in src/feedback/.

Subcommands: add / check / suggest / stats / export-rules / list
(see ``src.feedback.correction_tracker``).
"""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))

    from src.feedback.correction_tracker import main

    main()
