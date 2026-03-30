"""ContentClassifier: classifies document content into categories using keyword patterns."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.kie_utils import KIEResult


class ContentClassifier:
    """Classifies document content into categories."""

    def __init__(self) -> None:
        """Initialize classifier with keyword patterns."""
        # Company name patterns
        self.company_patterns = [
            r'\b([A-Z][A-Za-z0-9\s&\-\.]{2,50})\s+LLC\b',
            r'\b([A-Z][A-Za-z0-9\s&\-\.]{2,50})\s+L\.L\.C\.\b',
            r'\b([A-Z][A-Za-z0-9\s&\-\.]{2,50})\s+Inc\.?\b',
            r'\b([A-Z][A-Za-z0-9\s&\-\.]{2,50})\s+Incorporated\b',
            r'\b([A-Z][A-Za-z0-9\s&\-\.]{2,50})\s+Corp\.?\b',
            r'\b([A-Z][A-Za-z0-9\s&\-\.]{2,50})\s+Corporation\b',
            r'\b([A-Z][A-Za-z0-9\s&\-\.]{2,50})\s+Company\b',
            r'\b([A-Z][A-Za-z0-9\s&\-\.]{2,50})\s+Co\.\b',
            r'\b([A-Z][A-Za-z0-9\s&\-\.]{2,50})\s+Ltd\.?\b',
            r'\b([A-Z][A-Za-z0-9\s&\-\.]{2,50})\s+Limited\b',
            r'\b([A-Z][A-Za-z0-9\s&\-\.]{2,50})\s+LLP\b',
            r'\b([A-Z][A-Za-z0-9\s&\-\.]{2,50})\s+L\.L\.P\.\b',
        ]

        # People name patterns - look for common name patterns
        self.people_patterns = [
            # ALL-CAPS names at start of resume (common in templates)
            # Matches: "ISABEL BUDENZ\nLLM" or "JOHN DOE\nSoftware Engineer"
            r'^([A-Z]{2,})\s+([A-Z]{2,})\s*\n',
            # ALL-CAPS name followed by title/degree
            r'\b([A-Z]{2,})\s+([A-Z]{2,})\s*\n\s*(?:LLM|MBA|PhD|MD|JD|CPA|Software|Engineer|Manager|Director|Analyst)',
            # Name with document type indicators
            r'\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\s+(?:Resume|CV|Cover Letter)\b',
            r'\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\s+(?:Portfolio|Biography|Bio)\b',
            # Field labels followed by names
            r'\b(?:Name|Contact|From|To|Attn|Author|Client|Patient|Student):\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)\b',
            # Email signatures (name before email)
            r'\b([A-Z][a-z]+\s+[A-Z][a-z]+)\s+<[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}>',
            # Name in "Prepared by/for" statements
            r'\b(?:Prepared|Written|Submitted|Signed)\s+(?:by|for):\s+([A-Z][a-z]+\s+[A-Z][a-z]+)\b',
            # Name followed by credentials (MD, PhD, Esq, etc.)
            r'\b([A-Z][a-z]+\s+[A-Z][a-z]+),?\s+(?:MD|PhD|Esq|DDS|CPA|MBA|JD|RN)\b',
            # Mr./Mrs./Ms./Dr. followed by name
            r'\b(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)\b',
            # Name in meeting notes format
            r'\b(?:Attendee|Participant|Speaker|Presenter):\s+([A-Z][a-z]+\s+[A-Z][a-z]+)\b',
        ]

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
                    'reference', 'recommendation'
                ],
                'subcategories': {
                    'employment': ['resume', 'cv', 'cover letter', 'employment', 'reference'],
                    'identification': ['passport', 'driver license', 'ssn', 'id'],
                    'certificates': ['birth certificate', 'marriage', 'divorce', 'diploma'],
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
            }
        }

    def extract_company_names(self, text: str) -> list[str]:
        """
        Extract company names from text using regex patterns.

        Returns:
            List of detected company names
        """
        companies: list[str] = []
        for pattern in self.company_patterns:
            matches = re.findall(pattern, text)
            companies.extend(matches)

        # Remove duplicates and clean up
        unique_companies: list[str] = []
        seen: set[str] = set()
        for company in companies:
            # Clean up whitespace
            clean = ' '.join(company.split())
            # Skip if too short or already seen
            if len(clean) > 2 and clean.lower() not in seen:
                seen.add(clean.lower())
                unique_companies.append(clean)

        return unique_companies

    def _collapse_spaced_text(self, text: str) -> str:
        """
        Collapse spaced-out text like "I S A B E L  B U D E N Z" to "ISABEL BUDENZ".
        Common in stylized resume/CV templates.
        """
        # Pattern: single letters separated by spaces (at least 3 in a row)
        # Match sequences like "I S A B E L" (single chars with single spaces)
        def collapse_match(match: re.Match) -> str:
            spaced = match.group(0)
            # Remove single spaces between single characters
            collapsed = re.sub(r'(?<=\b[A-Z]) (?=[A-Z]\b)', '', spaced)
            return collapsed

        # Find sequences of spaced single uppercase letters
        # Pattern matches: capital letter, space, capital letter (repeated)
        result = re.sub(r'\b([A-Z] ){2,}[A-Z]\b', collapse_match, text)
        return result

    def extract_people_names(self, text: str) -> list[str]:
        """
        Extract people names from text using regex patterns.

        Returns:
            List of detected people names
        """
        # Preprocess: collapse spaced-out text (common in stylized resumes)
        text = self._collapse_spaced_text(text)

        people: list[str] = []
        for pattern in self.people_patterns:
            matches = re.findall(pattern, text)
            # Pattern can return tuples (first, last) or single strings
            for match in matches:
                if isinstance(match, tuple):
                    # Join tuple elements (e.g., first name + last name)
                    full_name = ' '.join([m for m in match if m])
                else:
                    full_name = match
                people.append(full_name)

        # Remove duplicates and clean up
        unique_people: list[str] = []
        seen: set[str] = set()
        for person in people:
            # Clean up whitespace
            clean = ' '.join(person.split())
            # Convert ALL-CAPS to Title Case (common in resume headers)
            if clean.isupper():
                clean = clean.title()
            # Skip if too short or already seen
            if len(clean) > 2 and clean.lower() not in seen:
                seen.add(clean.lower())
                unique_people.append(clean)

        return unique_people

    def extract_person_company_relationships(self, text: str) -> dict[str, str]:
        """
        Extract relationships between people and companies from text.
        Uses Schema.org-style connections (Person worksFor/memberOf Organization).

        Returns:
            Dictionary mapping person names to company names
        """
        relationships: dict[str, str] = {}

        # Patterns for person-company relationships
        relationship_patterns = [
            # "John Doe at Company LLC"
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s+(?:at|from)\s+([A-Z][A-Za-z0-9\s&\-\.]{2,50}(?:\s+LLC|\s+Inc\.?|\s+Corp\.?|\s+Ltd\.?|\s+LLP))',
            # "John Doe, CEO of Company LLC"
            r'([A-Z][a-z]+\s+[A-Z][a-z]+),?\s+(?:CEO|CFO|CTO|COO|President|Director|Manager|Founder)\s+(?:of|at)\s+([A-Z][A-Za-z0-9\s&\-\.]{2,50}(?:\s+LLC|\s+Inc\.?|\s+Corp\.?|\s+Ltd\.?|\s+LLP))',
            # "Company LLC - Contact: John Doe"
            r'([A-Z][A-Za-z0-9\s&\-\.]{2,50}(?:\s+LLC|\s+Inc\.?|\s+Corp\.?|\s+Ltd\.?|\s+LLP))\s*[-:]\s*(?:Contact|Representative):\s*([A-Z][a-z]+\s+[A-Z][a-z]+)',
            # "John Doe (Company LLC)"
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s+\(([A-Z][A-Za-z0-9\s&\-\.]{2,50}(?:\s+LLC|\s+Inc\.?|\s+Corp\.?|\s+Ltd\.?|\s+LLP))\)',
            # Email pattern: john.doe@company.com -> John Doe at Company
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s+<[a-zA-Z0-9._%+-]+@([a-zA-Z0-9.-]+)\.[a-zA-Z]{2,}>',
        ]

        for pattern in relationship_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if len(match) == 2:
                    person, company = match
                    # Clean up
                    person_clean = ' '.join(person.split())
                    company_clean = ' '.join(company.split())

                    # For email domains, capitalize company name
                    if '@' in text and '.' in company_clean and len(company_clean.split('.')) >= 2:
                        # This is likely a domain name, extract company name
                        domain_parts = company_clean.split('.')
                        if domain_parts[0].lower() not in ['gmail', 'yahoo', 'hotmail', 'outlook', 'mail']:
                            company_clean = domain_parts[0].capitalize()

                    # Store relationship (person -> company)
                    if len(person_clean) > 2 and len(company_clean) > 2:
                        relationships[person_clean] = company_clean

        return relationships

    def is_valid_company_name(self, name: str) -> bool:
        """
        Check if a string is a valid company name (not a sentence fragment).

        Returns:
            True if valid company name, False if likely a sentence fragment
        """
        if not name:
            return False

        name_lower = name.lower().strip()
        words = name.split()

        # Reject if too long (real company names are usually < 60 chars)
        if len(name) > 60:
            return False

        # Reject if too many words (company names rarely have > 6 words)
        if len(words) > 6:
            return False

        # Sentence fragment indicators - words that start sentences, not companies
        sentence_starters = {
            'neither', 'either', 'total', 'the', 'a', 'an', 'if', 'when',
            'where', 'while', 'although', 'because', 'since', 'unless',
            'however', 'therefore', 'moreover', 'furthermore', 'additionally',
            'please', 'note', 'see', 'refer', 'click', 'visit', 'contact',
            'for', 'with', 'from', 'into', 'about', 'above', 'below',
            'between', 'under', 'over', 'after', 'before', 'during',
            'this', 'that', 'these', 'those', 'which', 'what', 'who',
            'all', 'any', 'each', 'every', 'both', 'few', 'many', 'most',
            'other', 'some', 'such', 'no', 'not', 'only', 'own', 'same',
            'output', 'input', 'return', 'returns', 'required', 'optional',
        }

        # Check first word
        if words and words[0].lower() in sentence_starters:
            return False

        # Sentence patterns - these indicate full sentences, not company names
        sentence_patterns = [
            r'\b(?:is|are|was|were|be|been|being)\b',  # Verbs
            r'\b(?:to|of|in|on|at|by)\s+(?:the|a|an)\b',  # Preposition + article
            r'\b(?:you|your|we|our|they|their|it|its)\b',  # Pronouns
            r'\b(?:can|could|will|would|shall|should|may|might|must)\b',  # Modal verbs
            r'\b(?:and|or|but|nor|yet|so)\s+\w+\s+\w+',  # Conjunction + multiple words
        ]

        for pattern in sentence_patterns:
            if re.search(pattern, name_lower):
                return False

        # Check for specific problematic patterns
        problematic_phrases = [
            'the name of', 'in usd', 'total in', 'output only',
            'required for', 'agreement between', 'agreement of',
            'certificate of', 'description of', 'operating agreement',
            'license this', 'http rule', 'member-managed',
            'need some', 'print out', 'user provided',
            'ceo of', 'cfo of', 'cto of', 'coo of',  # Title patterns
            'president of', 'director of', 'manager of',
            'taxpayer number', 'tax id', 'ein number',  # Tax/ID patterns
            'student award', 'professional access',  # Award patterns
            'proprietor general', 'general partnership',  # Legal entity types
            'personal workload', 'workload and',  # Incomplete phrases
            'data usage agreement', 'service agreement',
            'contributions on behalf', 'on behalf of',
        ]

        for phrase in problematic_phrases:
            if phrase in name_lower:
                return False

        # Reject names ending with conjunctions (incomplete phrases)
        if words and words[-1].lower() in {'and', 'or', 'but', 'nor', 'yet', 'so', 'the', 'a', 'an', 'of', 'to', 'in', 'on', 'at', 'by'}:
            return False

        # Reject names starting with titles followed by "of"
        if len(words) >= 3 and words[1].lower() == 'of':
            title_words = {'ceo', 'cfo', 'cto', 'coo', 'president', 'director', 'manager', 'chairman', 'founder'}
            if words[0].lower() in title_words:
                return False

        return True

    def normalize_company_name(self, company_name: str) -> str:
        """
        Normalize company name by extracting actual company from common patterns.

        Handles patterns like:
        - "Copyright 2024 Google" -> "Google"
        - "© 2020 Microsoft Corporation" -> "Microsoft"
        - "(c) 2019-2024 Apple Inc" -> "Apple"
        - "Copyright (C) 2023 Amazon" -> "Amazon"
        - "Google LLC" -> "Google"
        - "Apple Inc." -> "Apple"

        Returns:
            Normalized company name, or None if invalid
        """
        if not company_name:
            return company_name

        # Patterns to extract company name from copyright notices
        copyright_patterns = [
            # "Copyright 2024 Google" or "Copyright (C) 2024 Google"
            r'(?:copyright|©|\(c\))\s*(?:\(c\))?\s*(?:\d{4}(?:\s*[-–—]\s*\d{4})?)\s+(.+)',
            # "2024 Google" (just year followed by company)
            r'^\d{4}(?:\s*[-–—]\s*\d{4})?\s+([A-Z][A-Za-z0-9\s&\-\.]+)$',
            # "(c) Google 2024" (company before year)
            r'(?:copyright|©|\(c\))\s+([A-Z][A-Za-z0-9\s&\-\.]+?)\s+\d{4}',
            # "Copyright Google" or "© Google" (without year)
            r'^(?:copyright|©|\(c\))\s+([A-Za-z][A-Za-z0-9\s&\-\.]+)$',
        ]

        name_lower = company_name.lower().strip()
        result = company_name

        # Check if this looks like a copyright notice
        if any(indicator in name_lower for indicator in ['copyright', '©', '(c)']):
            for pattern in copyright_patterns:
                match = re.search(pattern, company_name, re.IGNORECASE)
                if match:
                    extracted = match.group(1).strip()
                    # Clean up trailing punctuation
                    extracted = re.sub(r'[.,;:]+$', '', extracted).strip()
                    if extracted and len(extracted) >= 2:
                        result = extracted
                        break

        # Check for year prefix pattern (e.g., "2024 Google")
        if result == company_name:
            year_prefix_match = re.match(r'^(\d{4}(?:\s*[-–—]\s*\d{4})?)\s+(.+)$', company_name)
            if year_prefix_match:
                extracted = year_prefix_match.group(2).strip()
                if extracted and len(extracted) >= 2:
                    result = extracted

        # Strip legal suffixes to consolidate company variants
        # Order matters: check longer suffixes first
        legal_suffixes = [
            # Full words with variations
            r'\s+Incorporated$',
            r'\s+Corporation$',
            r'\s+Limited$',
            r'\s+Company$',
            # Abbreviations with optional period
            r'\s+L\.L\.C\.$',
            r'\s+L\.L\.P\.$',
            r'\s+LLC\.?$',
            r'\s+LLP\.?$',
            r'\s+Inc\.?$',
            r'\s+Corp\.?$',
            r'\s+Ltd\.?$',
            r'\s+Co\.?$',
            # Other common suffixes
            r'\s+PLC\.?$',
            r'\s+LP\.?$',
            r'\s+SA$',
            r'\s+GmbH$',
            r'\s+AG$',
        ]

        for suffix_pattern in legal_suffixes:
            result = re.sub(suffix_pattern, '', result, flags=re.IGNORECASE).strip()

        return result

    def sanitize_company_name(self, company_name: str) -> str | None:
        """
        Sanitize company name for use in folder names.

        Returns:
            Sanitized folder name, or None if the name is invalid (sentence fragment)
        """
        # First normalize the company name (extract from copyright patterns, etc.)
        normalized = self.normalize_company_name(company_name)

        # Validate that this is a real company name, not a sentence fragment
        if not self.is_valid_company_name(normalized):
            return None

        # Remove special characters that aren't allowed in folder names
        sanitized = re.sub(r'[<>:"/\\|?*]', '', normalized)
        # Replace multiple spaces with single space
        sanitized = ' '.join(sanitized.split())
        # Limit length
        if len(sanitized) > 50:
            sanitized = sanitized[:50].strip()
        return sanitized if sanitized else None

    # ------------------------------------------------------------------
    # KIE-based classification (structured document extraction)
    # ------------------------------------------------------------------

    # Minimum per-field confidence for KIE to drive classification.
    _KIE_CLASSIFICATION_MIN_CONFIDENCE = 0.5

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
        """
        threshold = self._KIE_CLASSIFICATION_MIN_CONFIDENCE

        # Look for strong financial document signals: a vendor/store AND
        # an amount OR a date.
        vendor = self._best_kie_field(kie_result, ("vendor_name", "store_name"), threshold)
        amount = self._best_kie_field(kie_result, ("total_amount", "receipt_total"), threshold)
        date = self._best_kie_field(kie_result, ("invoice_date", "receipt_date"), threshold)

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

        for category, data in self.patterns.items():
            keywords = data['keywords']
            hits = sum(1 for kw in keywords if kw.lower() in combined)
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

        # Score each category
        scores: dict[str, int] = defaultdict(int)
        category_subcats: dict[str, dict[str, int]] = {}

        for category, data in self.patterns.items():
            for keyword in data['keywords']:
                count = combined.count(keyword.lower())
                if count > 0:
                    scores[category] += count

                    # Track which subcategory keywords matched
                    for subcat, subcat_keywords in data['subcategories'].items():
                        if any(sk.lower() in combined for sk in subcat_keywords):
                            if category not in category_subcats:
                                category_subcats[category] = defaultdict(int)
                            category_subcats[category][subcat] += count

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
