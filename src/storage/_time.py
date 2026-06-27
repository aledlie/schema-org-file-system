"""Shared timestamp helper for the storage layer.

datetime.utcnow() is deprecated in Python 3.12+. This returns the same value
it produced -- a *naive* datetime in UTC -- so it is a drop-in replacement that
preserves the existing column semantics (all DateTime columns are timezone
-naive) and avoids naive/aware comparison errors in kv_store.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC timestamp (drop-in for the deprecated datetime.utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
