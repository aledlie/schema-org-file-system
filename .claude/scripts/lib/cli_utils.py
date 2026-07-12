"""Shared CLI utilities for Python scripts."""

import argparse
import os

TELEMETRY_DIR = os.environ.get(
    "TELEMETRY_DIR",
    os.path.expanduser("~/.claude-history/telemetry"),
)


def add_telemetry_args(parser: argparse.ArgumentParser) -> None:
    """Add common telemetry filter arguments to an argparse parser."""
    parser.add_argument("--month", help="Filter telemetry to YYYY-MM")
    parser.add_argument("--days", type=int, help="Filter telemetry to last N days")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--telemetry-dir", default=TELEMETRY_DIR,
                        help=f"Telemetry directory (default: {TELEMETRY_DIR})")
