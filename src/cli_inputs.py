"""Typed input contracts for forwarded organize-files subcommands.

Each dataclass mirrors one ``add_*_arguments`` definition in ``src/cli.py``
(the single source for that command's options). Converting the parsed
Namespace through ``from_namespace()`` at the CLI boundary makes parser <->
consumer drift fail loudly with a named-field error instead of an
``AttributeError`` deep inside the target's ``run()``, and gives the
``run()`` signatures a concrete type mypy can check.

``tests/unit/test_cli_inputs.py`` locks each parser definition to its
dataclass in both directions.
"""

import argparse
from dataclasses import dataclass, fields
from typing import List, Optional, Type, TypeVar

# Bookkeeping attributes the organize-files subparser machinery adds
# (dest='command', set_defaults(func=...)); never part of a command's
# option contract and absent when a standalone script parses directly.
_NAMESPACE_BOOKKEEPING = frozenset({'command', 'func'})

_T = TypeVar('_T', bound='CommandInputs')


class CLIInputError(TypeError):
    """Parsed arguments do not match the command's typed input contract."""


@dataclass(frozen=True)
class CommandInputs:
    """Base class providing strict Namespace -> dataclass conversion."""

    @classmethod
    def from_namespace(cls: Type[_T], namespace: argparse.Namespace) -> _T:
        """Build the typed inputs, rejecting any missing/unexpected field."""
        values = {
            key: value
            for key, value in vars(namespace).items()
            if key not in _NAMESPACE_BOOKKEEPING
        }
        expected = {field.name for field in fields(cls)}
        missing = sorted(expected - values.keys())
        unexpected = sorted(values.keys() - expected)
        if missing or unexpected:
            raise CLIInputError(
                f"{cls.__name__} does not match the parsed arguments "
                f"(missing: {missing}, unexpected: {unexpected}); keep it in "
                f"sync with its add_*_arguments definition in src/cli.py"
            )
        return cls(**values)


@dataclass(frozen=True)
class ContentInputs(CommandInputs):
    """organize-files content (src.cli.add_content_arguments)."""

    sources: List[str]
    base_path: str
    dry_run: bool
    limit: Optional[int]
    report: Optional[str]
    force: bool
    no_cost_tracking: bool
    cost_report: str
    check_deps: bool
    skip_health_check: bool
    sentry_dsn: Optional[str]
    no_sentry: bool
    db_path: str
    no_db: bool
    run_migration: bool
    scorer: str
    ocr_clip_topk: Optional[int]


@dataclass(frozen=True)
class NameInputs(CommandInputs):
    """organize-files name (src.cli.add_name_arguments)."""

    sources: List[str]
    base_path: str
    recursive: bool
    dry_run: bool
    limit: Optional[int]


@dataclass(frozen=True)
class TypeInputs(CommandInputs):
    """organize-files type (src.cli.add_type_arguments)."""

    sources: List[str]
    base_path: str
    dry_run: bool


@dataclass(frozen=True)
class PreprocessInputs(CommandInputs):
    """organize-files preprocess (src.cli.add_preprocess_arguments)."""

    input: str
    output: str
    test_ratio: float
    min_freq: int
    report_only: bool


@dataclass(frozen=True)
class EvaluateInputs(CommandInputs):
    """organize-files evaluate (src.cli.add_evaluate_arguments)."""

    test_data: str
    output: str
    classifier: str
    min_support: Optional[int]


@dataclass(frozen=True)
class UpdateSiteInputs(CommandInputs):
    """organize-files update-site (src.cli.add_update_site_arguments)."""

    results_dir: str
    site_dir: str
    report: Optional[str]


@dataclass(frozen=True)
class TimelineInputs(CommandInputs):
    """organize-files timeline (src.cli.add_timeline_arguments)."""

    db_path: Optional[str]
