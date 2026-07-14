#!/usr/bin/env python3
"""Launcher for the ML preprocessing pipeline — logic lives in src/ml/.

Prefer ``organize-files preprocess``; this script remains for direct
invocation only.
"""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))

    from src.ml.data_preprocessor import main

    main()
