"""FilepathSignal tests (UNIFIED_SCORING_PLAN §4 row 14)."""

from pathlib import Path

from src.scoring.signals.filepath import (
    FILEPATH_MATCH_CONFIDENCE,
    FILEPATH_PATTERNS,
    FilepathSignal,
    classify_filepath,
    classify_filepath_match,
    extract_project_name,
)
from src.scoring.context import FileContext
from src.scoring.weights import W_PATH


def make_ctx(path, schema_type="DigitalDocument"):
    return FileContext(path=Path(path), schema_type=schema_type)


class TestClassifyFilepath:
    def test_exact_filename_match(self):
        assert classify_filepath(Path("/project/Makefile"), FILEPATH_PATTERNS) == "Technical/Build"

    def test_extension_with_project_name(self):
        result = classify_filepath(Path("repos/MyProject/src/script.py"), FILEPATH_PATTERNS)
        assert result == "Technical/Python/MyProject"

    def test_double_extension(self):
        assert classify_filepath(Path("/logs/output.log.gz"), FILEPATH_PATTERNS) == "Technical/Logs"

    def test_unknown_extension_returns_none(self):
        assert classify_filepath(Path("/files/data.xyz123"), FILEPATH_PATTERNS) is None

    def test_match_reports_project_name(self):
        match = classify_filepath_match(Path("repos/MyProject/src/script.py"), FILEPATH_PATTERNS)
        assert match.path == "Technical/Python/MyProject"
        assert match.project_name == "MyProject"

    def test_exact_filename_has_no_project_name(self):
        match = classify_filepath_match(Path("/project/Makefile"), FILEPATH_PATTERNS)
        assert match.project_name is None


class TestExtractProjectName:
    def test_finds_project_dir(self):
        assert extract_project_name(Path("code/myproject/src/main.py")) == "myproject"

    def test_all_generic_dirs_returns_none(self):
        assert extract_project_name(Path("src/tests/main.py")) is None

    def test_skips_hidden_dirs(self):
        assert extract_project_name(Path(".config/myapp/settings.py")) == "myapp"

    def test_skips_home_directory_name(self):
        home_name = Path.home().name
        path = Path("/Users") / home_name / "Downloads" / "index.html"
        assert extract_project_name(path) is None

    def test_skips_other_user_directories(self):
        assert extract_project_name(Path("/Users/otheruser/Downloads/report.pdf")) is None


class TestSignalRun:
    def test_emits_filepath_category_with_path_subcategory(self):
        scores = FilepathSignal().run(make_ctx("repos/MyProject/src/script.py"))
        assert len(scores) == 1
        score = scores[0]
        assert score.category == "filepath"
        assert score.subcategory == "Technical/Python/MyProject"
        assert score.confidence == FILEPATH_MATCH_CONFIDENCE
        assert score.signal_name == "filepath"
        assert score.evidence == {"project_name": "MyProject"}

    def test_no_project_name_key_when_absent(self):
        scores = FilepathSignal().run(make_ctx("/project/Makefile"))
        assert scores[0].subcategory == "Technical/Build"
        assert "project_name" not in scores[0].evidence

    def test_no_match_emits_nothing(self):
        assert FilepathSignal().run(make_ctx("/files/data.xyz123")) == []

    def test_custom_patterns_override(self):
        signal = FilepathSignal({".foo": "Technical/Foo"})
        scores = signal.run(make_ctx("/x/thing.foo"))
        assert scores[0].subcategory.startswith("Technical/Foo")
        assert signal.run(make_ctx("/project/Makefile")) == []

    def test_applies_to_everything(self):
        assert FilepathSignal().applies_to(make_ctx("/any/file.bin")) is True

    def test_signal_metadata(self):
        signal = FilepathSignal()
        assert signal.name == "filepath"
        assert signal.weight == W_PATH
        assert signal.cost_tier == "cheap"
