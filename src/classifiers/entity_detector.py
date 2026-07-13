"""EntityDetector: extracts companies, people, and their relationships from text.

Split out of ``ContentClassifier`` (God Script #1 refactor, plan Part 2): the
company/people/relationship regex extraction and company-name
validation/normalization/sanitization are a self-contained concern, independent
of the keyword-based category scoring that remains in ``ContentClassifier``.
``ContentClassifier`` now composes an ``EntityDetector`` and delegates to it, so
the public method surface (``extract_company_names`` etc.) is unchanged.
"""
from __future__ import annotations

import re

# Personal titles that strongly indicate a human (vs. an org/brand name).
_HUMAN_TITLE_RE = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Dr|Prof|Sir|Madam|Hon|Rev|Esq|Atty)\.?\s+[A-Z]",
)
# First-person / signatory phrases that only humans write about themselves.
_HUMAN_CONTACT_PHRASES = (
    "date of birth",
    "d.o.b",
    "dob:",
    "signed by",
    "signature of",
    "undersigned",
    "to whom it may concern",
    "i hereby",
    "i am pleased to",
    "social security",
    "ssn:",
    "driver license",
    "driver's license",
    "maiden name",
    "next of kin",
    "emergency contact",
)


def _has_human_name_signal(text: str) -> bool:
    """
    Require evidence that a document is about a human, not an org/brand.

    Org-precedence rule: when none of these signals appear, defer person
    classification so org/document-type classifiers can win on names like
    "Morning Train" that look human but aren't.
    """
    if _HUMAN_TITLE_RE.search(text):
        return True
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in _HUMAN_CONTACT_PHRASES)


class EntityDetector:
    """Detects Schema.org-style entities (Organization, Person) in document text."""

    def __init__(self) -> None:
        """Compile the entity-extraction regex patterns once (hot path)."""
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

        # Pre-compile regex patterns once (hot path: extract_* methods)
        self._company_regexes = [re.compile(p) for p in self.company_patterns]
        self._people_regexes = [re.compile(p) for p in self.people_patterns]
        self._relationship_regexes = [
            re.compile(p) for p in (
                r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s+(?:at|from)\s+([A-Z][A-Za-z0-9\s&\-\.]{2,50}(?:\s+LLC|\s+Inc\.?|\s+Corp\.?|\s+Ltd\.?|\s+LLP))',
                r'([A-Z][a-z]+\s+[A-Z][a-z]+),?\s+(?:CEO|CFO|CTO|COO|President|Director|Manager|Founder)\s+(?:of|at)\s+([A-Z][A-Za-z0-9\s&\-\.]{2,50}(?:\s+LLC|\s+Inc\.?|\s+Corp\.?|\s+Ltd\.?|\s+LLP))',
                r'([A-Z][A-Za-z0-9\s&\-\.]{2,50}(?:\s+LLC|\s+Inc\.?|\s+Corp\.?|\s+Ltd\.?|\s+LLP))\s*[-:]\s*(?:Contact|Representative):\s*([A-Z][a-z]+\s+[A-Z][a-z]+)',
                r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s+\(([A-Z][A-Za-z0-9\s&\-\.]{2,50}(?:\s+LLC|\s+Inc\.?|\s+Corp\.?|\s+Ltd\.?|\s+LLP))\)',
                r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s+<[a-zA-Z0-9._%+-]+@([a-zA-Z0-9.-]+)\.[a-zA-Z]{2,}>',
            )
        ]
        self._spaced_letters_re = re.compile(r'\b([A-Z] ){2,}[A-Z]\b')
        self._sentence_regexes = [
            re.compile(p) for p in (
                r'\b(?:is|are|was|were|be|been|being)\b',
                r'\b(?:to|of|in|on|at|by)\s+(?:the|a|an)\b',
                r'\b(?:you|your|we|our|they|their|it|its)\b',
                r'\b(?:can|could|will|would|shall|should|may|might|must)\b',
                r'\b(?:and|or|but|nor|yet|so)\s+\w+\s+\w+',
            )
        ]
        self._copyright_regexes = [
            re.compile(p, re.IGNORECASE) for p in (
                r'(?:copyright|©|\(c\))\s*(?:\(c\))?\s*(?:\d{4}(?:\s*[-–—]\s*\d{4})?)\s+(.+)',
                r'^\d{4}(?:\s*[-–—]\s*\d{4})?\s+([A-Z][A-Za-z0-9\s&\-\.]+)$',
                r'(?:copyright|©|\(c\))\s+([A-Z][A-Za-z0-9\s&\-\.]+?)\s+\d{4}',
                r'^(?:copyright|©|\(c\))\s+([A-Za-z][A-Za-z0-9\s&\-\.]+)$',
            )
        ]
        self._year_prefix_re = re.compile(r'^(\d{4}(?:\s*[-–—]\s*\d{4})?)\s+(.+)$')
        # Legal suffixes stripped from the *end* of a company name.  Order
        # matters (longer suffixes first) and each pattern is applied once in
        # sequence, so stacked suffixes like "Foo Co. Inc." collapse to "Foo"
        # ("Inc." strips first, then "Co." — matches the production organizer).
        self._legal_suffix_regexes = [
            re.compile(p, re.IGNORECASE) for p in (
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
            )
        ]
        self._folder_sanitize_re = re.compile(r'[<>:"/\\|?*]')

    def extract_company_names(self, text: str) -> list[str]:
        """
        Extract company names from text using regex patterns.

        Returns:
            List of detected company names
        """
        companies: list[str] = []
        for regex in self._company_regexes:
            companies.extend(regex.findall(text))

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
        return self._spaced_letters_re.sub(collapse_match, text)

    def extract_people_names(self, text: str) -> list[str]:
        """
        Extract people names from text using regex patterns.

        Returns:
            List of detected people names
        """
        # Preprocess: collapse spaced-out text (common in stylized resumes)
        text = self._collapse_spaced_text(text)

        people: list[str] = []
        for regex in self._people_regexes:
            matches = regex.findall(text)
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

        for regex in self._relationship_regexes:
            matches = regex.findall(text)
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
        for regex in self._sentence_regexes:
            if regex.search(name_lower):
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

        name_lower = company_name.lower().strip()
        result = company_name

        # Check if this looks like a copyright notice
        if any(indicator in name_lower for indicator in ('copyright', '©', '(c)')):
            for regex in self._copyright_regexes:
                match = regex.search(company_name)
                if match:
                    extracted = match.group(1).strip()
                    # Clean up trailing punctuation
                    extracted = extracted.rstrip('.,;:').strip()
                    if extracted and len(extracted) >= 2:
                        result = extracted
                        break

        # Check for year prefix pattern (e.g., "2024 Google")
        if result == company_name:
            year_prefix_match = self._year_prefix_re.match(company_name)
            if year_prefix_match:
                extracted = year_prefix_match.group(2).strip()
                if extracted and len(extracted) >= 2:
                    result = extracted

        # Strip legal suffixes to consolidate company variants.  One ordered
        # pass over the suffix list, so stacked suffixes are all removed
        # (e.g. "Foo Co. Inc." -> "Foo") — matches the production organizer.
        for suffix_regex in self._legal_suffix_regexes:
            result = suffix_regex.sub('', result).strip()
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
        sanitized = self._folder_sanitize_re.sub('', normalized)
        # Replace multiple spaces with single space
        sanitized = ' '.join(sanitized.split())
        # Limit length
        if len(sanitized) > 50:
            sanitized = sanitized[:50].strip()
        return sanitized if sanitized else None
