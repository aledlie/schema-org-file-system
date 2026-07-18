"""Signal priors and decision thresholds — single source of truth.

See docs/architecture/UNIFIED_SCORING_PLAN.md §4 (priors) and §3.3
(thresholds). Weights are priors: relative magnitude matters, not the sum.
Aggregated scores are raw weighted sums over contributing signals — they can
exceed 1.0 — and the decision thresholds below are calibrated to that raw
scale. ``ClassificationDecision.confidence`` is clamped to [0, 1] for
persistence; thresholding always happens on the raw aggregate.

Phase 3 calibration re-tunes these values against
``results/file_organization.db`` backtests; treat this module as versioned
data and commit each re-tune with its backtest report (Open Question #3).
"""

# --------------------------------------------------------------------------- #
# Signal priors (§4, one per registered signal, descending)                    #
# --------------------------------------------------------------------------- #

W_RENAMED = 1.2  # RenamedScreenshotSignal — renamer already classified content
W_FILENAME = 1.1  # FilenamePatternSignal — shared/filename_classifier rules
W_KIE = 1.1  # KieStructuredSignal — structured invoice/receipt fields
W_ID = 1.0  # IdentityDocumentSignal — MRZ/OCR identity documents
W_ORG = 1.0  # OrganizationKeywordSignal — org indicators + company name
W_PERSON = 0.9  # PersonalDocSignal — person-document indicators (Option C)
W_LEGAL = 0.85  # LegalContentSignal — replaces the hard person-tier veto
# InteriorSignal — trained CLIP-embedding probe (C1). A supervised probe
# outranks the zero-shot ClipVisionSignal (0.7); set high enough that a
# confident interior (P>=~0.74) clears the demoted source-provenance filename
# (0.44) and photo_composition's photos_social (0.52) with MIN_DECISION_MARGIN.
# Re-tune with a results/file_organization.db backtest (Phase-3, as with W_*).
W_INTERIOR = 0.85
# SceneSignal — multi-class successor to the interior probe
# (MEDIA_EXTERIORS_PLAN §Weights: one weight, all scene classes share it —
# the signal emits one vote per file). Inherits the interior prior; the alias
# collapses to a single W_SCENE when the swap completes and W_INTERIOR is
# retired with interior.py.
W_SCENE = W_INTERIOR
W_GAME = 0.8  # GameAssetSignal — sprite/texture/audio filename heuristics
W_TEXT = 0.8  # TextContentSignal — keyword taxonomy (= shipped _TEXT_SIGNAL_PRIOR)
W_UI = 0.75  # ScreenshotOcrSignal — screenshot OCR keyword routing
W_GRAPHIC = 0.75  # GraphicDetectionSignal — cheap non-CLIP gate for logos/icons
W_CLIP = 0.7  # ClipVisionSignal — 20-prompt CLIP pass
W_MEDIA = 0.65  # MediaHeuristicSignal — extension/stem/EXIF media routing
W_PEOPLE_PHOTO = 0.65  # PhotoCompositionSignal — people / home-interior flags
W_PATH = 0.6  # FilepathSignal — extension/filename → Technical/* paths
W_MIME = 0.4  # MimeFallbackSignal — see note below (commits alone, yields to content)

# --------------------------------------------------------------------------- #
# Signal-internal confidence scaling shared with the legacy image path          #
# --------------------------------------------------------------------------- #

# OCR/extracted text contributes confidence scaled by extraction length:
# min(1, chars / TEXT_LENGTH_FULL_CHARS), ignored entirely below
# TEXT_MIN_CHARS. Mirrors _TEXT_LENGTH_FULL_CHARS / _TEXT_MIN_CHARS in
# src/organizers/content_organizer.py (kept separate until Phase 5 removes
# the legacy chain — do not let the values drift).
TEXT_LENGTH_FULL_CHARS = 200
TEXT_MIN_CHARS = 30

# Minimum OCR word confidence for KIE extraction and identity-document
# detection (mirrors _OCR_CONFIDENCE_THRESHOLD in content_organizer.py; the
# tier-3.5 → tier-6 hidden dependency is encoded by FileContext.ensure_kie).
OCR_CONFIDENCE_GATE = 0.3

# CLIP-based OCR gate: skip OCR unless a text-bearing label ranks in the top-K
# CLIP labels. K=3 is the eval-backed default (eval over ~270 images from the
# ~/Documents photo-library layout: 100% text recall, 35% of photos skip OCR).
# Ranking signal only — CLIP softmax scores are near-uniform (~0.05/label) so
# absolute probability cannot separate text from photos; the discriminative
# signal is whether a text-bearing label outranks non-text labels.
# Disable by passing 0 or None; applies to the unified scorer only (gate
# fails open when CLIP is unavailable or produces no scores).
OCR_CLIP_GATE_TOPK = 3

# --------------------------------------------------------------------------- #
# Decision thresholds (§3.3) — raw aggregate scale                             #
# --------------------------------------------------------------------------- #

# Skip later cost-tier waves once the aggregate reaches this (aggregated, not
# per-signal — preserves multi-evidence wins).
EARLY_EXIT_CONFIDENCE = 0.95

# Below this aggregate the decision routes to LOW_CONFIDENCE_FALLBACK.
MIN_DECISION_CONFIDENCE = 0.35

# Required lead over the runner-up to commit the winner.
MIN_DECISION_MARGIN = 0.10

# W_MIME (0.4) is calibrated against these two thresholds (BACKLOG Phase-3
# item #1). It must clear MIN_DECISION_CONFIDENCE so an extension-only file
# (mime the sole signal: 0.4 × 1.0 = 0.4 ≥ 0.35) commits instead of falling
# to Uncategorized — the legacy tier-6 MIME rescue the unified path had lost.
# The MIN_DECISION_MARGIN gate keeps it from overriding genuine content: when
# mime disagrees with a content winner scoring in [0.35, 0.40) the lead is
# < 0.10, so BOTH route to fallback rather than mime committing its guess; mime
# only out-commits content that scored below the floor (i.e. wouldn't have
# committed anyway). Keep W_MIME < MIN_DECISION_CONFIDENCE + MIN_DECISION_MARGIN
# (0.45) so it can never commit *over* a content signal that itself clears the
# floor. tests/unit/scoring/test_mime_commit_gap.py locks these invariants.

# Open Question #1 (low-confidence bucket placement) is unresolved; both
# low-confidence and low-margin decisions conservatively route to today's
# uncategorized bucket while telemetry records decision_state for calibration.
# Swap to ("review", "other") once OQ #1 resolves.
LOW_CONFIDENCE_FALLBACK = ("uncategorized", "other")
