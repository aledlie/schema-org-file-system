"""Unit tests for src/cli_inputs.py — typed CLI input contracts.

Locks each ``add_*_arguments`` parser definition in ``src/cli.py`` to its
input dataclass in both directions: a field added to the parser but not the
dataclass (or vice versa) fails ``from_namespace`` with a named-field
``CLIInputError`` instead of surfacing as an ``AttributeError`` deep inside
the target's ``run()``.
"""

import argparse
import dataclasses

import pytest

from src.cli import (
    add_content_arguments,
    add_evaluate_arguments,
    add_name_arguments,
    add_preprocess_arguments,
    add_timeline_arguments,
    add_type_arguments,
    add_update_site_arguments,
)
from src.cli_inputs import (
    CLIInputError,
    ContentInputs,
    EvaluateInputs,
    NameInputs,
    PreprocessInputs,
    TimelineInputs,
    TypeInputs,
    UpdateSiteInputs,
)

# (parser definition, dataclass, minimal argv satisfying required options)
COMMAND_CONTRACTS = [
    pytest.param(add_content_arguments, ContentInputs, [], id="content"),
    pytest.param(add_name_arguments, NameInputs, [], id="name"),
    pytest.param(add_type_arguments, TypeInputs, [], id="type"),
    pytest.param(
        add_preprocess_arguments, PreprocessInputs, ["--input", "/data/in"],
        id="preprocess",
    ),
    pytest.param(add_evaluate_arguments, EvaluateInputs, [], id="evaluate"),
    pytest.param(add_update_site_arguments, UpdateSiteInputs, [], id="update-site"),
    pytest.param(add_timeline_arguments, TimelineInputs, [], id="timeline"),
]


def parse(add_arguments, argv):
    parser = argparse.ArgumentParser()
    add_arguments(parser)
    return parser.parse_args(argv)


class TestParserDataclassParity:
    """The drift guard: parser output and dataclass fields must match exactly."""

    @pytest.mark.parametrize("add_arguments,inputs_cls,argv", COMMAND_CONTRACTS)
    def test_parsed_defaults_build_inputs(self, add_arguments, inputs_cls, argv):
        namespace = parse(add_arguments, argv)
        inputs = inputs_cls.from_namespace(namespace)
        assert dataclasses.asdict(inputs) == vars(namespace)

    @pytest.mark.parametrize("add_arguments,inputs_cls,argv", COMMAND_CONTRACTS)
    def test_subparser_bookkeeping_attrs_are_excluded(
        self, add_arguments, inputs_cls, argv
    ):
        """organize-files namespaces carry command/func; both must be dropped."""
        namespace = parse(add_arguments, argv)
        namespace.command = "some-command"
        namespace.func = lambda args: None
        inputs = inputs_cls.from_namespace(namespace)
        assert "command" not in dataclasses.asdict(inputs)
        assert "func" not in dataclasses.asdict(inputs)

    @pytest.mark.parametrize("add_arguments,inputs_cls,argv", COMMAND_CONTRACTS)
    def test_inputs_are_frozen(self, add_arguments, inputs_cls, argv):
        inputs = inputs_cls.from_namespace(parse(add_arguments, argv))
        field_name = dataclasses.fields(inputs_cls)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(inputs, field_name, "mutated")


class TestStrictConversion:
    def test_missing_field_raises_named_error(self):
        namespace = parse(add_type_arguments, [])
        delattr(namespace, "dry_run")
        with pytest.raises(CLIInputError, match=r"missing: \['dry_run'\]"):
            TypeInputs.from_namespace(namespace)

    def test_unexpected_field_raises_named_error(self):
        namespace = parse(add_type_arguments, [])
        namespace.stray_option = True
        with pytest.raises(CLIInputError, match=r"unexpected: \['stray_option'\]"):
            TypeInputs.from_namespace(namespace)

    def test_error_names_the_dataclass(self):
        namespace = argparse.Namespace()
        with pytest.raises(CLIInputError, match="TimelineInputs"):
            TimelineInputs.from_namespace(namespace)
