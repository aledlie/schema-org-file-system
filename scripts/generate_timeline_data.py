#!/usr/bin/env python3
"""Launcher for timeline data generation — logic lives in src/api/timeline_api.py.

Prefer ``organize-files timeline``; this script remains for direct
invocation only.
"""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))

    from src.api.timeline_api import main

    main()
