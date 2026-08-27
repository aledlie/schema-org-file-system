"""Unit tests for the Phase-0 model-free organization extractor.

Covers the two documented failure modes of the fragile ``EntityDetector`` regex:

1. Single-token brand with no legal suffix (``GeneDx``) — recovered via the
   ``genedx.com`` domain-ownership cue and ranked first.
2. Garbled citation fragment from a References section — excluded by
   reference-span stripping.

Plus a suffix-based invoice fixture to confirm ordinary detection still works,
and a gazetteer smoke test.
"""

from __future__ import annotations

from src.classifiers.entity_detector import EntityDetector
from src.classifiers.org_extraction import extract_organizations

# Representative of the real GeneDx document: brand appears 8x (body + footer +
# genedx.com), with a References section whose citation line is the source of the
# garbled "Medical Genetics and Genomics and the Association" fragment.
GENEDX_DOC = (
    "General Variant Classification Assertion Criteria\n"
    "Data analysis and variant classification at GeneDx is a multi-step "
    "process. Variant interpretation at GeneDx combines automated algorithms "
    "and internal databases. GeneDx classifies sequencing variants into five "
    "categories.\n"
    "207 Perry Parkway - Gaithersburg, MD 20877 - Phone 301-519-2100 - "
    "zebras@genedx.com - genedx.com\n"
    "References:\n"
    "Richards et al. (2015) Standards and guidelines for the interpretation of "
    "sequence variants: a joint consensus recommendation of the American "
    "College of Medical Genetics and Genomics and the Association for "
    "Molecular Pathology. Genet Med 17(5):405-24\n"
)

# Ordinary suffix-based org detection must keep working.
INVOICE_DOC = (
    "INVOICE\n\n"
    "Vendor: Acme Widgets LLC\n"
    "Bill To: Jane Roe\n"
    "Invoice #4471 - Total Due: $1,240.00\n"
)

GARBLE = "Medical Genetics and Genomics and the Association"


def _detector() -> EntityDetector:
    return EntityDetector()


def test_genedx_recovered_via_domain_cue_and_ranked_first():
    result = extract_organizations(GENEDX_DOC, base_extractor=_detector())
    assert "GeneDx" in result, result
    assert result[0] == "GeneDx", result


def test_reference_span_excludes_citation_garble():
    result = extract_organizations(GENEDX_DOC, base_extractor=_detector())
    assert GARBLE not in result, result
    # No citation-derived org should leak through at all.
    joined = " | ".join(result)
    assert "Molecular Pathology" not in joined, result
    assert "Association" not in joined, result


def test_base_extractor_alone_misses_genedx():
    # Sanity check on the premise: the fragile regex never finds GeneDx, so the
    # domain cue (not the base extractor) is what recovers it.
    assert "GeneDx" not in _detector().extract_company_names(GENEDX_DOC)


def test_invoice_suffix_detection_preserved():
    result = extract_organizations(INVOICE_DOC, base_extractor=_detector())
    assert "Acme Widgets" in result, result
    assert result[0] == "Acme Widgets", result


def test_callable_base_extractor_accepted():
    # base_extractor may be a plain callable, not just an EntityDetector.
    detector = _detector()
    result = extract_organizations(INVOICE_DOC, base_extractor=detector.extract_company_names)
    assert result[0] == "Acme Widgets", result


def test_known_brands_gazetteer_catches_bare_single_token():
    text = "Meeting notes: synced with the Contoso team about the Q3 rollout.\n"
    result = extract_organizations(text, base_extractor=_detector(), known_brands={"Contoso"})
    assert "Contoso" in result, result


def test_empty_text_returns_empty_list():
    assert extract_organizations("", base_extractor=_detector()) == []


# ---------------------------------------------------------------------------
# Regression: CamelCase code identifiers must not become company names
# (Bug: _DOMAIN_RE used re.IGNORECASE, so Routes.signup / AuthMode.signIn
# matched as "domains" and seeded _find_body_brand with tokens that recovered
# capitalized identifiers as org names.)
# ---------------------------------------------------------------------------

FLUTTER_AUTH_DOC = """\
Authentication Mode

This module handles authentication for the Flutter application.

The AuthMode enum defines the authentication mode:

enum AuthMode { signUp, signIn }

Navigator.pushNamed(context, Routes.signup);
Navigator.pushNamed(context, Routes.login);

When the client selects signUp mode, navigate to signup screen.
When the client selects signIn mode, navigate to login screen.
"""


def test_camelcase_identifiers_not_extracted_as_companies():
    """Routes.signup / AuthMode.signIn must NOT be treated as domain names."""
    result = extract_organizations(FLUTTER_AUTH_DOC, base_extractor=_detector())
    code_identifiers = {"Routes", "AuthMode", "Navigator", "Mode"}
    leaked = code_identifiers & set(result)
    assert not leaked, f"Code identifiers leaked as company names: {leaked!r} in {result!r}"


def test_lowercase_domain_cue_still_works_after_case_fix():
    """Lowercase domains (genedx.com) must still be recovered after removing IGNORECASE."""
    result = extract_organizations(GENEDX_DOC, base_extractor=_detector())
    assert "GeneDx" in result, result
    assert result[0] == "GeneDx", result


# ---------------------------------------------------------------------------
# Regression: bare dotted code references (file paths, method calls, property
# access) must not become company names either.
#
# Even after the CamelCase/IGNORECASE fix above, bare ``label.label`` prose
# still matched the domain regex: a file path (``lib/config/content/
# constants.dart``) recovered "Constants" as a false company, and a method
# call (``error.contains(...)``) or property access (``context.go``,
# ``state.uri``) would recover "Error"/"Context"/"State" the same way. There
# is no finite denylist of "not a domain" second labels that closes this gap
# (an extension denylist stopped ``constants.dart`` but not ``error.contains``).
# The actual fix restricts domain matching to genuine URL/email syntax
# (``@domain`` / ``http(s)://domain`` / ``www.domain``), which a dotted code
# reference never has.
# ---------------------------------------------------------------------------

FLUTTER_AUTH_DOC_WITH_CODE_REFERENCES = FLUTTER_AUTH_DOC + (
    "\n### Routes Constants\n\n"
    "**Location:** `lib/config/content/constants.dart:95-110`\n\n"
    "if (error.contains('token')) {\n"
    "  context.go(state.uri.toString());\n"
    "}\n"
)


def test_code_file_path_not_extracted_as_company():
    """A bare ``constants.dart`` file reference must NOT be treated as a domain."""
    result = extract_organizations(
        FLUTTER_AUTH_DOC_WITH_CODE_REFERENCES, base_extractor=_detector()
    )
    assert "Constants" not in result, result


def test_code_method_and_property_access_not_extracted_as_company():
    """Dotted method/property references (error.contains, context.go, state.uri)
    must NOT be treated as domains either."""
    result = extract_organizations(
        FLUTTER_AUTH_DOC_WITH_CODE_REFERENCES, base_extractor=_detector()
    )
    leaked = {"Error", "Context", "State"} & set(result)
    assert not leaked, f"Code references leaked as company names: {leaked!r} in {result!r}"
