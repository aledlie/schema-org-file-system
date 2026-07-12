#!/usr/bin/env python3
"""
textstat-appendix.py — Run readability analysis on a Jekyll report and append results.

Usage:
    python3 textstat-appendix.py <path-to-report.md>

Requires:
    pip install textstat
"""

import sys
import re
from pathlib import Path


def install_textstat():
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "textstat", "-q"])


try:
    import textstat
except ImportError:
    print("textstat not found — installing...")
    install_textstat()
    import textstat


APPENDIX_MARKER = "## Appendix: Readability Analysis"

GRADE_LABELS = {
    range(0, 6): "Elementary",
    range(6, 9): "Middle School",
    range(9, 13): "High School",
    range(13, 17): "College",
    range(17, 100): "Graduate+",
}


def grade_label(score: float) -> str:
    for r, label in GRADE_LABELS.items():
        if int(score) in r:
            return label
    return "Graduate+"


def strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter and markdown syntax before analysis."""
    # Strip frontmatter block
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL)
    # Strip markdown headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Strip markdown links
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Strip inline code and code blocks
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]+`", "", text)
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Strip table separators
    text = re.sub(r"^\|[-| :]+\|$", "", text, flags=re.MULTILINE)
    # Strip bold/italic markers
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    return text.strip()


def build_appendix(stats: dict) -> str:
    lines = [
        "",
        "---",
        "",
        APPENDIX_MARKER,
        "",
        "Readability metrics computed with [textstat](https://github.com/textstat/textstat) on the report body (frontmatter, code blocks, and markdown syntax excluded).",
        "",
        "### Scores",
        "",
        "| Metric | Score | Notes |",
        "|--------|-------|-------|",
        f"| Flesch Reading Ease | {stats['flesch_reading_ease']:.1f} | 0–30 very difficult, 60–70 standard, 90–100 very easy |",
        f"| Flesch-Kincaid Grade | {stats['flesch_kincaid_grade']:.1f} | US school grade level ({grade_label(stats['flesch_kincaid_grade'])}) |",
        f"| Gunning Fog Index | {stats['gunning_fog']:.1f} | Years of formal education needed |",
        f"| SMOG Index | {stats['smog_index']:.1f} | Grade level (requires 30+ sentences) |",
        f"| Coleman-Liau Index | {stats['coleman_liau_index']:.1f} | Grade level via character counts |",
        f"| Automated Readability Index | {stats['automated_readability_index']:.1f} | Grade level via characters/words |",
        f"| Dale-Chall Score | {stats['dale_chall_readability_score']:.2f} | <5 = 5th grade, >9 = college |",
        f"| Linsear Write | {stats['linsear_write_formula']:.1f} | Grade level |",
        f"| Text Standard (consensus) | {stats['text_standard']} | Estimated US grade level |",
        "",
        "### Corpus Stats",
        "",
        "| Measure | Value |",
        "|---------|-------|",
        f"| Word count | {stats['word_count']:,} |",
        f"| Sentence count | {stats['sentence_count']:,} |",
        f"| Syllable count | {stats['syllable_count']:,} |",
        f"| Avg words per sentence | {stats['avg_words_per_sentence']:.1f} |",
        f"| Avg syllables per word | {stats['avg_syllables_per_word']:.2f} |",
        f"| Difficult words | {stats['difficult_words']:,} |",
        "",
    ]
    return "\n".join(lines)


def analyse(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")

    # Remove existing appendix if present so re-runs are idempotent
    if APPENDIX_MARKER in raw:
        raw = raw[: raw.index(APPENDIX_MARKER)].rstrip()
        # Also strip the preceding `---` separator if present
        raw = re.sub(r"\n---\s*$", "", raw)

    body = strip_frontmatter(raw)

    if not body.strip():
        print("No body text found after stripping frontmatter.", file=sys.stderr)
        sys.exit(1)

    word_count = textstat.lexicon_count(body, removepunct=True)
    sentence_count = textstat.sentence_count(body)

    stats = {
        "flesch_reading_ease": textstat.flesch_reading_ease(body),
        "flesch_kincaid_grade": textstat.flesch_kincaid_grade(body),
        "gunning_fog": textstat.gunning_fog(body),
        "smog_index": textstat.smog_index(body),
        "coleman_liau_index": textstat.coleman_liau_index(body),
        "automated_readability_index": textstat.automated_readability_index(body),
        "dale_chall_readability_score": textstat.dale_chall_readability_score(body),
        "linsear_write_formula": textstat.linsear_write_formula(body),
        "text_standard": textstat.text_standard(body),
        "word_count": word_count,
        "sentence_count": sentence_count,
        "syllable_count": textstat.syllable_count(body),
        "avg_words_per_sentence": word_count / max(sentence_count, 1),
        "avg_syllables_per_word": textstat.syllable_count(body) / max(word_count, 1),
        "difficult_words": textstat.difficult_words(body),
    }

    updated = raw + build_appendix(stats)
    path.write_text(updated, encoding="utf-8")

    print(f"Appendix written to {path}")
    print(f"  Flesch Reading Ease : {stats['flesch_reading_ease']:.1f}")
    print(f"  Flesch-Kincaid Grade: {stats['flesch_kincaid_grade']:.1f} ({grade_label(stats['flesch_kincaid_grade'])})")
    print(f"  Consensus grade     : {stats['text_standard']}")
    print(f"  Words               : {stats['word_count']:,}  |  Sentences: {stats['sentence_count']:,}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python3 {Path(__file__).name} <report.md>", file=sys.stderr)
        sys.exit(1)

    report_path = Path(sys.argv[1]).expanduser().resolve()

    if not report_path.exists():
        print(f"File not found: {report_path}", file=sys.stderr)
        sys.exit(1)

    analyse(report_path)
