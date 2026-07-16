"""ContentClassifier: classifies document content into categories using keyword patterns."""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from src.classifiers.entity_detector import EntityDetector

if TYPE_CHECKING:
    from shared.kie_utils import KIEResult

# Single-source the KIE confidence threshold and field-class groups from the
# canonical kie_schema_mapping module (scripts/shared/).  The previous private
# class attribute _KIE_CLASSIFICATION_MIN_CONFIDENCE = 0.5 duplicated the same
# 0.5 gate used by kie_schema_mapping.kie_result_to_schema_org but was
# maintained separately, so the two could silently drift.  The same applies to
# the hardcoded ("vendor_name", "store_name") etc. tuples.
try:
    from shared.kie_schema_mapping import (
        KIE_MIN_CONFIDENCE as _KIE_CLASSIFICATION_MIN_CONFIDENCE,
        KIE_VENDOR_CLASSES as _KIE_VENDOR_CLASSES,
        KIE_AMOUNT_CLASSES as _KIE_AMOUNT_CLASSES,
        KIE_DATE_CLASSES as _KIE_DATE_CLASSES,
    )
except ImportError:  # scripts/shared/ not on sys.path (unusual; fallback keeps tests green)
    _KIE_CLASSIFICATION_MIN_CONFIDENCE = 0.5
    _KIE_VENDOR_CLASSES: tuple[str, ...] = ("vendor_name", "store_name")
    _KIE_AMOUNT_CLASSES: tuple[str, ...] = ("total_amount", "receipt_total")
    _KIE_DATE_CLASSES: tuple[str, ...] = ("invoice_date", "receipt_date")


class ContentClassifier:
    """Classifies document content into categories.

    Entity extraction (companies, people, relationships, and company-name
    normalization) is delegated to a composed :class:`EntityDetector`; the
    ``extract_*``/``*_company_name`` methods below are thin pass-throughs that
    preserve the historical public API.
    """

    def __init__(self) -> None:
        """Initialize classifier with keyword patterns."""
        # Entity detection (company/people/relationship extraction) lives in a
        # dedicated collaborator; classification keeps only category scoring.
        self.entities = EntityDetector()

        self.patterns: dict[str, dict] = {
            'legal': {
                'keywords': [
                    'contract', 'agreement', 'terms', 'conditions', 'legal', 'attorney',
                    'law', 'litigation', 'plaintiff', 'defendant', 'court', 'settlement',
                    'lease', 'deed', 'will', 'testament', 'power of attorney', 'notary',
                    'amendment', 'exhibit', 'whereas', 'party', 'parties', 'executed',
                    'operating agreement', 'llc', 'corporation', 'bylaws', 'articles'
                ],
                'subcategories': {
                    'contracts': ['contract', 'agreement', 'terms', 'subscription', 'saas'],
                    'real_estate': ['lease', 'deed', 'property', 'real estate', 'mortgage'],
                    'litigation': [
                        'court', 'hearing', 'docket', 'plaintiff', 'defendant',
                        'petitioner', 'respondent', 'cause no', 'judgment',
                        'motion to', 'motion for',
                    ],
                    'corporate': ['llc', 'corporation', 'operating agreement', 'bylaws', 'articles', 'formation'],
                    'other': []
                }
            },
            'financial': {
                'keywords': [
                    'invoice', 'receipt', 'tax', 'irs', 'payment', 'bill', 'billing',
                    'statement', 'account', 'balance', 'transaction', 'credit', 'debit',
                    'bank', 'finance', 'loan', 'interest', '1098', '1099', 'w-2', 'w2',
                    'federal', 'state return', 'refund', 'revenue', 'expense', 'budget',
                    'investment', 'portfolio', 'ein', 'employer identification'
                ],
                'subcategories': {
                    'tax': ['tax', 'irs', '1098', '1099', 'w-2', 'w2', 'federal', 'state return'],
                    'invoices': ['invoice', 'bill', 'billing', 'payment'],
                    'statements': ['statement', 'account', 'balance', 'transaction'],
                    'other': []
                }
            },
            'business': {
                'keywords': [
                    'proposal', 'pitch', 'business plan', 'strategy', 'marketing',
                    'presentation', 'deck', 'startup', 'company', 'venture', 'investor',
                    'growth', 'revenue model', 'unit economics', 'expansion', 'rfp',
                    'guidelines', 'program', 'service package', 'pricing', 'client',
                    'customer', 'vendor', 'supplier', 'partner', 'contacts', 'crm',
                    'hiring', 'job posting', 'meeting', 'standup', 'minutes'
                ],
                'subcategories': {
                    'planning': ['business plan', 'strategy', 'expansion', 'growth', 'project'],
                    'marketing': ['marketing', 'pricing', 'service package', 'pitch', 'deck'],
                    'proposals': ['proposal', 'rfp', 'guidelines'],
                    'crm': ['crm', 'contacts', 'microlender', 'customer'],
                    'hr': ['hiring', 'job posting', 'team roster', 'application', 'linkedin'],
                    'meeting_notes': ['meeting', 'standup', 'minutes', 'agenda', 'retrospective'],
                    'clients': ['client', 'llc', 'inc', 'corp', 'company'],  # Legacy
                    'other': []
                }
            },
            'personal': {
                'keywords': [
                    'resume', 'cv', 'cover letter', 'curriculum vitae', 'employment',
                    'personal', 'identification', 'passport', 'driver license', 'ssn',
                    'birth certificate', 'marriage', 'divorce', 'diploma', 'transcript',
                    'reference', 'recommendation', 'vcard', 'contact',
                    'journal', 'diary', 'event', 'wedding', 'citation'
                ],
                'subcategories': {
                    'employment': ['resume', 'cv', 'cover letter', 'employment', 'reference'],
                    'identification': ['passport', 'driver license', 'ssn', 'id'],
                    'certificates': ['birth certificate', 'marriage', 'divorce', 'diploma'],
                    'contacts': ['resume', 'cv', 'vcard', 'contact', 'curriculum vitae'],
                    'journal': ['journal', 'diary', 'dream', 'reflection', 'memoir'],
                    'events': ['event', 'party', 'wedding', 'invitation', 'rsvp'],
                    'legal': ['dui', 'court', 'citation', 'traffic ticket', 'hearing', 'dmv'],
                    'records': ['personal record', 'records'],
                    'other': []
                }
            },
            'medical': {
                'keywords': [
                    'medical', 'health', 'doctor', 'patient', 'prescription', 'diagnosis',
                    'treatment', 'hospital', 'clinic', 'insurance claim', 'hipaa',
                    'vaccination', 'immunization', 'lab results', 'pharmacy'
                ],
                'subcategories': {
                    'records': ['medical record', 'patient', 'diagnosis', 'treatment'],
                    'insurance': ['insurance', 'claim', 'coverage'],
                    'prescriptions': ['prescription', 'pharmacy', 'medication'],
                    'other': []
                }
            },
            'property': {
                'keywords': [
                    'property management', 'tenant', 'landlord', 'rent', 'rental',
                    'maintenance', 'repair', 'inspection', 'utilities', 'hoa'
                ],
                'subcategories': {
                    'leases': ['lease', 'tenant', 'landlord', 'rent', 'rental'],
                    'maintenance': ['maintenance', 'repair', 'inspection'],
                    'other': []
                }
            },
            'education': {
                'keywords': [
                    'course', 'syllabus', 'lecture', 'assignment', 'homework', 'exam',
                    'grade', 'transcript', 'diploma', 'degree', 'certificate', 'university',
                    'college', 'school', 'research paper', 'thesis', 'dissertation'
                ],
                'subcategories': {
                    'coursework': ['course', 'syllabus', 'lecture', 'assignment'],
                    'research': ['research', 'paper', 'thesis', 'dissertation'],
                    'records': ['transcript', 'diploma', 'degree', 'certificate'],
                    'other': []
                }
            },
            'technical': {
                'keywords': [
                    'code', 'software', 'development', 'programming', 'api', 'database',
                    'documentation', 'technical', 'specification', 'architecture', 'design',
                    'system', 'infrastructure', 'deployment', 'configuration'
                ],
                'subcategories': {
                    'documentation': ['documentation', 'spec', 'specification', 'readme'],
                    'architecture': ['architecture', 'design', 'system', 'infrastructure'],
                    'other': []
                }
            },
            'creative': {
                'keywords': [
                    'design', 'graphic', 'illustration', 'artwork', 'photo', 'image',
                    'screenshot', 'mockup', 'prototype', 'wireframe', 'brand', 'logo'
                ],
                'subcategories': {
                    'design': ['design', 'mockup', 'wireframe', 'prototype'],
                    'branding': ['brand', 'logo', 'identity'],
                    'photos': ['photo', 'photography', 'image'],
                    'other': []
                }
            },
            # Game mod/workshop descriptors (e.g. Steam Workshop `.mod` manifests).
            # Keyed on strings unique to those descriptors so it only fires on real
            # game-mod content, never on generic documents that mention "game".
            'game_assets': {
                'keywords': [
                    'steamapps/workshop', 'remote_file_id', 'steam workshop',
                    'workshop/content',
                ],
                'subcategories': {
                    'other': []
                }
            }
        }

        # Pre-lowercase keywords and subcategory keyword lists
        self._keywords_lower: dict[str, list[str]] = {
            cat: [kw.lower() for kw in data['keywords']]
            for cat, data in self.patterns.items()
        }
        self._subcats_lower: dict[str, dict[str, list[str]]] = {
            cat: {sc: [kw.lower() for kw in kws] for sc, kws in data['subcategories'].items()}
            for cat, data in self.patterns.items()
        }

    # ------------------------------------------------------------------
    # Entity detection (delegated to EntityDetector; kept on the public
    # ContentClassifier surface for backward compatibility)
    # ------------------------------------------------------------------

    def extract_company_names(self, text: str) -> list[str]:
        """Extract company names from text (delegates to EntityDetector)."""
        return self.entities.extract_company_names(text)

    def extract_people_names(self, text: str) -> list[str]:
        """Extract people names from text (delegates to EntityDetector)."""
        return self.entities.extract_people_names(text)

    def extract_person_company_relationships(self, text: str) -> dict[str, str]:
        """Extract person→company relationships (delegates to EntityDetector)."""
        return self.entities.extract_person_company_relationships(text)

    def is_valid_company_name(self, name: str) -> bool:
        """Validate a candidate company name (delegates to EntityDetector)."""
        return self.entities.is_valid_company_name(name)

    def normalize_company_name(self, company_name: str) -> str:
        """Normalize a company name (delegates to EntityDetector)."""
        return self.entities.normalize_company_name(company_name)

    def sanitize_company_name(self, company_name: str) -> str | None:
        """Sanitize a company name for folder use (delegates to EntityDetector)."""
        return self.entities.sanitize_company_name(company_name)

    # ------------------------------------------------------------------
    # KIE-based classification (structured document extraction)
    # ------------------------------------------------------------------

    def classify_with_kie(
        self,
        kie_result: KIEResult,
        text: str = "",
        filename: str = "",
    ) -> tuple[str, str, str | None, list[str]] | None:
        """Attempt classification using KIE-extracted structured fields.

        Returns a ``(category, subcategory, company_name, people_names)``
        tuple when high-confidence invoice/receipt fields are detected.
        Returns ``None`` when the KIE result is insufficient and the caller
        should fall through to keyword-based ``classify_content()``.

        Confidence threshold and field-class groups are imported from
        ``shared.kie_schema_mapping`` so all KIE consumers share one value.
        """
        threshold = _KIE_CLASSIFICATION_MIN_CONFIDENCE

        # Look for strong financial document signals: a vendor/store AND
        # an amount OR a date.
        vendor = self._best_kie_field(kie_result, _KIE_VENDOR_CLASSES, threshold)
        amount = self._best_kie_field(kie_result, _KIE_AMOUNT_CLASSES, threshold)
        date = self._best_kie_field(kie_result, _KIE_DATE_CLASSES, threshold)

        if vendor and (amount or date):
            people_names = self.extract_people_names(text) if text else []
            return ("financial", "invoices", vendor.value, people_names)

        return None

    @staticmethod
    def _best_kie_field(
        kie_result: KIEResult,
        class_names: tuple[str, ...],
        min_confidence: float,
    ):
        """Return the highest-confidence KIEField across *class_names*, or None."""
        best = None
        for name in class_names:
            for f in kie_result.fields.get(name, ()):
                if f.confidence >= min_confidence and (best is None or f.confidence > best.confidence):
                    best = f
        return best

    def score_all_categories(self, text: str, filename: str = "") -> dict[str, float]:
        """Score text against all Schema.org keyword categories.

        Returns a dict of ``{category: confidence}`` where confidence is
        the fraction of category keywords found in the text.  Categories
        with zero hits are omitted.
        """
        combined = f"{text.lower()} {filename.lower()}"
        scores: dict[str, float] = {}

        for category, keywords in self._keywords_lower.items():
            hits = sum(1 for kw in keywords if kw in combined)
            if hits:
                scores[category] = hits / len(keywords)

        return scores

    def classify_content(
        self,
        text: str,
        filename: str = "",
        detected_language: str | None = None,
    ) -> tuple[str, str, str | None, list[str]]:
        """
        Classify content based on extracted text.
        Uses Schema.org person-company relationships to improve categorization.

        Args:
            text: Extracted document text.
            filename: Original filename (used as secondary signal).
            detected_language: BCP-47 language code from OCR (e.g. ``"en"``, ``"fr"``).
                When a non-English language is detected the English keyword matching
                is skipped to avoid false positives; the document routes to
                ``("uncategorized", "other")``.

        Returns:
            Tuple of (category, subcategory, company_name, people_names)
        """
        if not text:
            return ('uncategorized', 'other', None, [])

        # Non-English OCR text — English keyword patterns are unreliable.
        # Skip keyword classification and let the caller handle routing.
        if detected_language is not None and detected_language != 'en':
            return ('uncategorized', 'other', None, [])

        text_lower = text.lower()
        filename_lower = filename.lower()
        combined = f"{text_lower} {filename_lower}"

        # Check for known companies in text (canonical name mapping)
        known_text_companies: dict[str, tuple[str, str, str | None]] = {
            'capital city village': ('organization', 'property_management', 'Capital City Village'),
            'leora home health': ('organization', 'healthcare', 'Leora Home Health'),
            'integrity studio': ('organization', 'vendors', 'Integrity Studio'),
            'inspired movement': ('organization', 'vendors', 'Inspired Movement'),
            'new beginnings child development': ('organization', 'vendors', 'New Beginnings Child Development Center'),
            'zouk': ('zouk', 'events', None),
        }
        for phrase, (cat, subcat, canonical_name) in known_text_companies.items():
            if phrase in text_lower:
                return (cat, subcat, canonical_name, self.extract_people_names(text))

        # Extract company names and people names
        company_names = self.extract_company_names(text)
        primary_company: str | None = company_names[0] if company_names else None

        people_names = self.extract_people_names(text)

        # Extract person-company relationships (Schema.org connections)
        person_company_relationships = self.extract_person_company_relationships(text)

        # Prioritize company from person-company relationships over direct extraction
        # Relationships tend to be more accurate as they include context
        if person_company_relationships:
            # Get the first relationship's company
            relationship_company = next(iter(person_company_relationships.values()))

            # Check if relationship company has proper legal suffix
            has_legal_suffix = any(relationship_company.endswith(suffix)
                                  for suffix in ['LLC', 'Inc.', 'Inc', 'Corp.', 'Corp',
                                                'Ltd.', 'Ltd', 'LLP', 'L.L.C.', 'L.L.P.'])

            # Prefer relationship company if it has legal suffix or we don't have a primary company
            if has_legal_suffix or not primary_company:
                primary_company = relationship_company
            # Or if the relationship company is much cleaner (shorter and no weird prefixes)
            elif primary_company and 'CEO' not in relationship_company and 'at' not in relationship_company:
                if len(relationship_company) < len(primary_company) * 0.8:
                    primary_company = relationship_company

        # Fallback: If we found people but no company, check relationships again
        if people_names and not primary_company and person_company_relationships:
            # Try to find a company for the first person mentioned
            for person in people_names:
                if person in person_company_relationships:
                    primary_company = person_company_relationships[person]
                    break

        # Score each category by its keyword counts. Subcategories score on
        # their OWN keyword counts, independent of the category score, so the
        # winning subcategory is the one whose vocabulary dominates the text —
        # not the first-listed subcategory with any hit (the old behavior gave
        # every matched subcategory an identical copy of the category total,
        # making max() a dict-insertion-order tie-break).
        scores: dict[str, int] = defaultdict(int)
        category_subcats: dict[str, dict[str, int]] = {}

        for category, keywords in self._keywords_lower.items():
            # Short-circuit: skip count() pass entirely if no keyword is present.
            # `in` stops at first hit; count() always scans the full string.
            if not any(kw in combined for kw in keywords):
                continue

            for keyword in keywords:
                scores[category] += combined.count(keyword)

            subcat_scores = {
                sc: sum(combined.count(sk) for sk in sc_kws)
                for sc, sc_kws in self._subcats_lower[category].items()
                if any(sk in combined for sk in sc_kws)
            }
            if subcat_scores:
                category_subcats[category] = subcat_scores

        if not scores:
            return ('uncategorized', 'other', primary_company, people_names)

        # Get category with highest score
        best_category = max(scores.items(), key=lambda x: x[1])[0]

        # Get subcategory with highest score for this category
        if best_category in category_subcats:
            subcat_scores = category_subcats[best_category]
            if subcat_scores:
                best_subcategory = max(subcat_scores.items(), key=lambda x: x[1])[0]
            else:
                best_subcategory = 'other'
        else:
            best_subcategory = 'other'

        # If we detected a company (either directly or via person relationship)
        # and it's business-related, use clients subcategory
        if primary_company and best_category == 'business':
            best_subcategory = 'clients'

        return (best_category, best_subcategory, primary_company, people_names)
