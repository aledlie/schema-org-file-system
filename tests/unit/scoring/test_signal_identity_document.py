"""IdentityDocumentSignal tests (UNIFIED_SCORING_PLAN §4 row 4).

Pure detect_identity_document coverage (keyword gate, three name-extraction
methods in order) plus Signal gating over a synthetic FileContext: OCR
length/confidence gates, MRZ-vs-keyword confidence grades, evidence
payloads, and []-emissions. Fake OCR via SimpleNamespace — no models.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.scoring.context import FileContext
from src.scoring.signals.identity_document import (
    ID_KEYWORD_CONFIDENCE,
    ID_MIN_TEXT_CHARS,
    ID_MRZ_CONFIDENCE,
    IdentityDocumentSignal,
    detect_identity_document,
)
from src.scoring.weights import OCR_CONFIDENCE_GATE

MRZ_TEXT = "passport united states of america\nP<USALEDLIE<<ALYSHIA<<<<<<<<<<"
# The trailing periods terminate the greedy [/\w\s]* spans in the field
# patterns; without them the (legacy-faithful) regexes latch onto the last
# caps word in the run ("Nationality").
NAME_FIELDS_TEXT = "PASSPORT\nSurname/Nom\nLEDLIE.\nGiven names/Prenoms\nALYSHIA.\nNationality: USA"
KEYWORD_ONLY_TEXT = "passport united states of america date of birth 1990"
NON_ID_TEXT = "meeting agenda for the quarterly review session notes"
# Driver-license *front* OCR text: the "driver license" keyword fires, but the
# layout has no MRZ and no "Surname/Nom" field labels, so name extraction falls
# through to the injected general extractor (Method 3). "driver license"
# precedes "date of birth" in ID_KEYWORDS, so it is the reported keyword.
DRIVER_LICENSE_TEXT = (
    "texas driver license\nDL 12345678 CLASS C\n"
    "LN SAMPLE\nFN JAMIE\ndate of birth 01/09/1990\nSEX F HGT 5-05"
)
# Driver-license *back*: none of the front-side keywords ("driver license",
# "date of birth") appear — only class/restriction fields. Detection now hinges
# on the license-back keyword "corrective lenses". No names on the back, so
# keyword evidence alone files it (empty people_names, like the passport
# keyword-only case).
LICENSE_BACK_TEXT = (
    "class c single or comb veh which transports placarded hazmat\n"
    "rest a with corrective lenses\nend none\n"
    "texas roadside assistance directive to physician"
)


def no_names(_text):
    return []


def make_classifier(names=()):
    return SimpleNamespace(extract_people_names=lambda _text: list(names))


def make_ocr(text, confidence=0.9, language="en"):
    return SimpleNamespace(text=text, confidence=confidence, language=language)


def make_ctx(ocr, schema_type="ImageObject"):
    return FileContext(
        path=Path("/tmp/scan.png"),
        schema_type=schema_type,
        ocr_provider=(lambda _path: ocr) if ocr is not None else None,
    )


class TestDetectIdentityDocument:
    def test_no_keyword_returns_none(self) -> None:
        assert detect_identity_document(NON_ID_TEXT, extract_people_names=no_names) is None

    def test_mrz_parsed_first(self) -> None:
        match = detect_identity_document(MRZ_TEXT, extract_people_names=no_names)
        assert match is not None
        assert match.method == "mrz"
        assert match.people_names == ["Alyshia Ledlie"]
        assert match.matched_keyword == "passport"

    def test_name_fields_parsed_second(self) -> None:
        match = detect_identity_document(NAME_FIELDS_TEXT, extract_people_names=no_names)
        assert match is not None
        assert match.method == "name_fields"
        assert match.people_names == ["Alyshia Ledlie"]

    def test_extractor_fallback_third(self) -> None:
        match = detect_identity_document(
            KEYWORD_ONLY_TEXT, extract_people_names=lambda _text: ["Jane Doe"]
        )
        assert match is not None
        assert match.method == "extractor"
        assert match.people_names == ["Jane Doe"]

    def test_extractor_empty_still_matches(self) -> None:
        # Keyword evidence alone files the document (legacy parity): empty
        # people_names, method labelled by the last attempted extractor.
        match = detect_identity_document(KEYWORD_ONLY_TEXT, extract_people_names=no_names)
        assert match is not None
        assert match.method == "extractor"
        assert match.people_names == []

    def test_driver_license_keyword_detected(self) -> None:
        # Gap-closing fixture: a driver-license front must be detected via the
        # "driver license" keyword (previously only passports were covered).
        match = detect_identity_document(
            DRIVER_LICENSE_TEXT, extract_people_names=lambda _text: ["Jamie Sample"]
        )
        assert match is not None
        assert match.matched_keyword == "driver license"
        assert match.method == "extractor"
        assert match.people_names == ["Jamie Sample"]

    def test_license_back_detected_via_corrective_lenses(self) -> None:
        # Gap #2: a license *back* has no front-side keyword; the "corrective
        # lenses" restriction term must still file it (empty names, keyword
        # evidence alone).
        match = detect_identity_document(LICENSE_BACK_TEXT, extract_people_names=no_names)
        assert match is not None
        assert match.matched_keyword == "corrective lenses"
        assert match.method == "extractor"
        assert match.people_names == []

    def test_first_matching_keyword_reported(self) -> None:
        match = detect_identity_document(
            "her date of birth appears on the form", extract_people_names=no_names
        )
        assert match is not None
        assert match.matched_keyword == "date of birth"

    def test_extractor_not_called_when_mrz_matches(self) -> None:
        calls = []

        def tracking(text):
            calls.append(text)
            return []

        detect_identity_document(MRZ_TEXT, extract_people_names=tracking)
        assert calls == []


class TestAppliesTo:
    def test_image_applies(self) -> None:
        signal = IdentityDocumentSignal(make_classifier())
        assert signal.applies_to(make_ctx(make_ocr(MRZ_TEXT)))

    def test_document_gated(self) -> None:
        signal = IdentityDocumentSignal(make_classifier())
        assert not signal.applies_to(make_ctx(make_ocr(MRZ_TEXT), schema_type="DigitalDocument"))


class TestRunGating:
    def test_no_ocr_emits_nothing(self) -> None:
        signal = IdentityDocumentSignal(make_classifier())
        assert signal.run(make_ctx(None)) == []

    def test_short_text_emits_nothing(self) -> None:
        signal = IdentityDocumentSignal(make_classifier())
        short = "passport"
        assert len(short) < ID_MIN_TEXT_CHARS
        assert signal.run(make_ctx(make_ocr(short))) == []

    def test_min_length_boundary_accepted(self) -> None:
        signal = IdentityDocumentSignal(make_classifier())
        text = "passport " + "x" * (ID_MIN_TEXT_CHARS - 9)
        assert len(text) == ID_MIN_TEXT_CHARS
        assert signal.run(make_ctx(make_ocr(text))) != []

    def test_low_confidence_ocr_emits_nothing(self) -> None:
        signal = IdentityDocumentSignal(make_classifier())
        ocr = make_ocr(MRZ_TEXT, confidence=OCR_CONFIDENCE_GATE - 0.01)
        assert signal.run(make_ctx(ocr)) == []

    def test_gate_boundary_confidence_accepted(self) -> None:
        signal = IdentityDocumentSignal(make_classifier())
        ocr = make_ocr(MRZ_TEXT, confidence=OCR_CONFIDENCE_GATE)
        assert signal.run(make_ctx(ocr)) != []

    def test_none_confidence_treated_as_reliable(self) -> None:
        signal = IdentityDocumentSignal(make_classifier())
        assert signal.run(make_ctx(make_ocr(MRZ_TEXT, confidence=None))) != []

    def test_non_id_text_emits_nothing(self) -> None:
        signal = IdentityDocumentSignal(make_classifier())
        assert signal.run(make_ctx(make_ocr(NON_ID_TEXT))) == []


class TestRunEmission:
    def test_mrz_confidence_grade(self) -> None:
        signal = IdentityDocumentSignal(make_classifier())
        emissions = signal.run(make_ctx(make_ocr(MRZ_TEXT)))
        assert len(emissions) == 1
        score = emissions[0]
        assert (score.category, score.subcategory) == ("personal", "identification")
        assert score.confidence == pytest.approx(ID_MRZ_CONFIDENCE)
        assert score.signal_name == "identity_document"

    def test_keyword_confidence_grade(self) -> None:
        signal = IdentityDocumentSignal(make_classifier(names=["Jane Doe"]))
        score = signal.run(make_ctx(make_ocr(KEYWORD_ONLY_TEXT)))[0]
        assert score.confidence == pytest.approx(ID_KEYWORD_CONFIDENCE)

    def test_driver_license_files_identification(self) -> None:
        signal = IdentityDocumentSignal(make_classifier(names=["Jamie Sample"]))
        score = signal.run(make_ctx(make_ocr(DRIVER_LICENSE_TEXT)))[0]
        assert (score.category, score.subcategory) == ("personal", "identification")
        assert score.confidence == pytest.approx(ID_KEYWORD_CONFIDENCE)
        assert score.evidence["matched_keyword"] == "driver license"

    def test_name_fields_use_keyword_confidence(self) -> None:
        signal = IdentityDocumentSignal(make_classifier())
        score = signal.run(make_ctx(make_ocr(NAME_FIELDS_TEXT)))[0]
        assert score.confidence == pytest.approx(ID_KEYWORD_CONFIDENCE)

    def test_evidence_payload(self) -> None:
        signal = IdentityDocumentSignal(make_classifier())
        score = signal.run(make_ctx(make_ocr(MRZ_TEXT)))[0]
        assert score.evidence == {
            "people_names": ["Alyshia Ledlie"],
            "matched_keyword": "passport",
            "method": "mrz",
        }
