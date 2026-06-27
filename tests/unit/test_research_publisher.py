"""Tests for the research-publisher prefix detector and Research category routing."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from file_organizer_content_based import _detect_research_publisher  # noqa: E402


class TestDetectResearchPublisher:
    @pytest.mark.parametrize(
        "stem,expected_key,expected_name,expected_id",
        [
            ("ssrn-5458215", "ssrn", "SSRN", "5458215"),
            ("SSRN-id12345", "ssrn", "SSRN", "12345"),
            ("ssrn_98765", "ssrn", "SSRN", "98765"),
            ("arxiv-2401.12345", "arxiv", "arXiv", "2401.12345"),
            ("arxiv_2503.04567v2", "arxiv", "arXiv", "2503.04567v2"),
            ("ARXIV:2401.12345", "arxiv", "arXiv", "2401.12345"),
            ("2401.12345", "arxiv", "arXiv", "2401.12345"),
            ("2401.12345v3", "arxiv", "arXiv", "2401.12345v3"),
            ("doi-10.1234_abc.def", "doi", "DOI", "10.1234_abc.def"),
            ("10.1234_smith_2024", "doi", "DOI", "10.1234_smith_2024"),
        ],
    )
    def test_recognized_prefixes(self, stem, expected_key, expected_name, expected_id):
        result = _detect_research_publisher(stem)
        assert result is not None, f"expected a match for {stem!r}"
        key, identifier, name, url = result
        assert key == expected_key
        assert name == expected_name
        assert identifier == expected_id
        assert url.endswith(identifier) or identifier in url

    @pytest.mark.parametrize(
        "stem",
        [
            "random_filename_2024",
            "contract-final",
            "NOTICE OF CT SETTING FOR 040126",
            "Photos",
            "3'x5'_PlacementMap_Draft (1)",
            "",
        ],
    )
    def test_non_research_stems_return_none(self, stem):
        assert _detect_research_publisher(stem) is None

    def test_urls_are_canonical(self):
        assert _detect_research_publisher("ssrn-5458215")[3] == "https://ssrn.com/abstract=5458215"
        assert _detect_research_publisher("2401.12345")[3] == "https://arxiv.org/abs/2401.12345"
        assert _detect_research_publisher("doi-10.1234_abc")[3] == "https://doi.org/10.1234_abc"
