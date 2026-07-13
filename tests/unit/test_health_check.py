"""Unit tests for src/health_check.py (SystemHealthChecker and helpers)."""

import sys
from collections import namedtuple

import pytest

from src import health_check
from src.health_check import (
    FeatureStatus,
    SystemHealthChecker,
    check_system,
    get_health_checker,
    require_feature,
)

EXPECTED_FEATURES = {
    'python', 'pillow', 'heic', 'ocr', 'clip_vision',
    'database', 'geocoding', 'sentry', 'documents',
}

_VersionInfo = namedtuple('_VersionInfo', 'major minor micro releaselevel serial')


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    """Isolate the module-level singleton between tests."""
    monkeypatch.setattr(health_check, '_checker', None)


def _block_import(monkeypatch, module_name):
    """Force `import module_name` to raise ImportError."""
    monkeypatch.setitem(sys.modules, module_name, None)


class TestFeatureStatus:
    def test_defaults(self):
        status = FeatureStatus(name="X", available=True)
        assert status.version is None
        assert status.error is None
        assert status.impact == ""


class TestRunAllChecks:
    def test_populates_all_features_and_chains(self):
        checker = SystemHealthChecker()
        result = checker.run_all_checks()

        assert result is checker
        assert checker._checked is True
        assert set(checker.features) == EXPECTED_FEATURES

    def test_python_version_current_interpreter_passes(self):
        checker = SystemHealthChecker()
        checker._check_python_version()

        status = checker.features['python']
        assert status.available is True
        assert status.version == (
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )
        assert status.error is None

    def test_python_version_too_old_fails(self, monkeypatch):
        monkeypatch.setattr(sys, 'version_info', _VersionInfo(3, 7, 4, 'final', 0))
        checker = SystemHealthChecker()
        checker._check_python_version()

        status = checker.features['python']
        assert status.available is False
        assert status.version == "3.7.4"
        assert "Requires Python 3.8+" in status.error


class TestImportFailureHandling:
    @pytest.mark.parametrize("module_name,feature_key,install_hint", [
        ('pillow_heif', 'heic', 'pillow-heif'),
        ('doctr', 'ocr', 'python-doctr'),
        ('sqlalchemy', 'database', 'sqlalchemy'),
        ('geopy', 'geocoding', 'geopy'),
        ('sentry_sdk', 'sentry', 'sentry-sdk'),
    ])
    def test_missing_module_reports_unavailable(
        self, monkeypatch, module_name, feature_key, install_hint
    ):
        _block_import(monkeypatch, module_name)
        checker = SystemHealthChecker()
        checker.run_all_checks()

        status = checker.features[feature_key]
        assert status.available is False
        assert status.error
        assert install_hint in status.impact

    def test_geopy_without_version_attribute_reports_unknown(self, monkeypatch):
        # Suite-wide stubs (tests/unit/test_image_metadata.py) install a geopy
        # module without __version__; the check must degrade, not crash.
        import types
        monkeypatch.setitem(sys.modules, 'geopy', types.ModuleType('geopy'))
        checker = SystemHealthChecker()
        checker._check_geocoding()

        status = checker.features['geocoding']
        assert status.available is True
        assert status.version == 'unknown'

    def test_clip_vision_lists_each_missing_lib(self, monkeypatch):
        _block_import(monkeypatch, 'torch')
        _block_import(monkeypatch, 'open_clip')
        checker = SystemHealthChecker()
        checker._check_clip_vision()

        status = checker.features['clip_vision']
        assert status.available is False
        assert "torch" in status.error
        assert "open-clip-torch" in status.error

    def test_documents_partial_availability_still_available(self, monkeypatch):
        _block_import(monkeypatch, 'docx')
        checker = SystemHealthChecker()
        checker._check_document_processing()

        status = checker.features['documents']
        assert status.available is True
        assert "docx" not in status.version.split(", ")
        assert "2/3 libs" in status.impact

    def test_documents_all_missing_unavailable(self, monkeypatch):
        for lib in ('docx', 'pypdf', 'openpyxl'):
            _block_import(monkeypatch, lib)
        checker = SystemHealthChecker()
        checker._check_document_processing()

        status = checker.features['documents']
        assert status.available is False
        for hint in ('python-docx', 'pypdf', 'openpyxl'):
            assert hint in status.error


class TestAccessors:
    def test_is_available_runs_checks_lazily(self):
        checker = SystemHealthChecker()
        assert checker._checked is False

        assert checker.is_available('python') is True
        assert checker._checked is True

    def test_is_available_unknown_feature_is_false(self):
        checker = SystemHealthChecker().run_all_checks()
        assert checker.is_available('no_such_feature') is False

    def test_get_status_returns_feature_or_none(self):
        checker = SystemHealthChecker()
        status = checker.get_status('python')
        assert isinstance(status, FeatureStatus)
        assert checker.get_status('no_such_feature') is None

    def test_to_dict_shape(self):
        checker = SystemHealthChecker()
        exported = checker.to_dict()

        assert set(exported) == EXPECTED_FEATURES
        for entry in exported.values():
            assert set(entry) == {"available", "version", "error", "impact"}


def _synthetic_checker(statuses):
    checker = SystemHealthChecker()
    checker.features = {f"f{i}": s for i, s in enumerate(statuses)}
    checker._checked = True
    return checker


class TestPrintStatus:
    def test_all_available_summary(self, capsys):
        checker = _synthetic_checker([
            FeatureStatus(name="Alpha", available=True, version="1.0"),
            FeatureStatus(name="Beta", available=True, version="2.0"),
        ])
        checker.print_status()

        out = capsys.readouterr().out
        assert "SYSTEM HEALTH CHECK" in out
        assert "Alpha v1.0" in out
        assert "Features available: 2/2" in out
        assert "All features operational!" in out

    def test_unavailable_feature_prints_error_and_impact(self, capsys):
        checker = _synthetic_checker([
            FeatureStatus(name="Alpha", available=True, version="1.0"),
            FeatureStatus(
                name="Beta", available=False,
                error="beta not installed", impact="No beta - pip install beta",
            ),
        ])
        checker.print_status()

        out = capsys.readouterr().out
        assert "Error: beta not installed" in out
        assert "Impact: No beta - pip install beta" in out
        assert "Features available: 1/2" in out
        assert "1 feature(s) unavailable" in out

    def test_verbose_prints_error_for_available_features(self, capsys):
        checker = _synthetic_checker([
            FeatureStatus(name="Alpha", available=True, error="warned", impact="ok"),
        ])
        checker.print_status(verbose=True)

        assert "Error: warned" in capsys.readouterr().out


class TestModuleHelpers:
    def test_get_health_checker_is_singleton(self):
        first = get_health_checker()
        assert get_health_checker() is first

    def test_check_system_runs_and_prints(self, capsys):
        checker = check_system()

        assert checker is get_health_checker()
        assert checker._checked is True
        assert "SYSTEM HEALTH CHECK" in capsys.readouterr().out

    def test_require_feature_available(self, capsys):
        assert require_feature('python') is True
        assert "Warning" not in capsys.readouterr().out

    def test_require_feature_unavailable_warns(self, monkeypatch, capsys):
        _block_import(monkeypatch, 'pillow_heif')
        assert require_feature('heic') is False

        out = capsys.readouterr().out
        assert "Warning: HEIC Support unavailable" in out

    def test_require_feature_unknown_is_false(self):
        assert require_feature('no_such_feature') is False
