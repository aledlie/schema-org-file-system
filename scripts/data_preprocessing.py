#!/usr/bin/env python3
"""Data preprocessing CLI wrapper.

Thin wrapper around ``src.ml`` (see ``feature_extractor.py`` and
``data_preprocessor.py`` there). Prefer ``organize-files preprocess``; this
script remains for direct invocation and for the historical import path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ml.data_preprocessor import DataPreprocessor, main, run  # noqa: E402,F401
from src.ml.feature_extractor import (  # noqa: E402,F401
    GAME_ASSET_PATTERNS,
    FileFeatureExtractor,
)

if __name__ == "__main__":
    main()
