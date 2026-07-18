# Organization Name Extraction: replace fragile regex with a robust NER stack

**Status:** Planned — Phase-0 prototype + GLiNER latency benchmark in progress (2026-07-18).
**Priority:** P3 (implements the BACKLOG item "`entity_detector` misses brand-name orgs and over-extracts cited bodies from reference sections").
**Source:** GeneDx PDF content analysis + org-NER library research, 2026-07-18.
**Related:** [`docs/BACKLOG.md`](../BACKLOG.md) · [`docs/plans/PERSON_NAME_VALIDATION_PLAN.md`](PERSON_NAME_VALIDATION_PLAN.md) (symmetric people-name validation gate).

## Problem

`src/classifiers/entity_detector.py` extracts `Organization` names from document text with hand-rolled regex (legal-suffix patterns `X LLC/Inc/Corp/…` + one institutional-keyword pattern). It is fragile. Two failure modes, both verified on `GeneDx_Variant_Classification_Process_June_2021.pdf`:

1. **Single-token brand names are invisible.** Every pattern needs a legal suffix or ≥2 tokens + an institutional keyword. A bare CamelCase brand like `GeneDx` (8 occurrences, incl. footer + `genedx.com`) matches nothing and is never detected. Same class: Netflix, Google, Spotify, OpenAI.
2. **Cited orgs in reference sections become truncated false positives.** From the References line *"American College of Medical Genetics and Genomics and the Association for Molecular Pathology"* the institutional pattern (anchored on `Association`, `{1,5}` token cap, no-line-break rule) returned the garble `"Medical Genetics and Genomics and the Association"` — a cited standards body, not the document's own org. Because downstream code takes `companies[0]`, this garble would become the `Organization/{…}` folder name.

## Decision (from research, 2026-07-18)

**Primary: GLiNER v2.1** (zero-shot NER) — the only option class that fixes failure mode #1. Fixed-label taggers (spaCy/Flair/HF) learned entity *shape* from CoNLL-2003/OntoNotes and won't reliably catch a novel brand token either; GLiNER scores spans against the *semantic* label `"organization"`, so `GeneDx` classifies like `Google` would, no suffix/shape heuristic required.
- **License gate (hard):** use **v2.1+ checkpoints only** (`urchade/gliner_small-v2.1`, `gliner_medium-v2.1`) — Apache-2.0. **Never v1** (`*-v1` = CC-BY-NC, non-commercial — disqualified for a distributable tool). Note: v2.1's NuNER training corpus was LLM-synthesized (theoretical GPT-ToS gray area; low realized risk — one line of disclosure).
- torch is already a dependency (the `ai` extra) → no new heavyweight runtime.

**The latency catch and its mitigation.** GLiNER can be ~300× slower than spaCy unbounded on CPU, and this pipeline is already OCR-bound. Mitigation is mandatory and does double duty:
- Run GLiNER **only on a bounded window** — first ~1,800 chars (letterhead) + last ~500 (footer) — with a 1–3 label set, calling the `gliner` library **directly** (not `gliner-spacy`, which caused the worst slowdown).
- That window is *also* where the document's own org lives and it excludes the References section — independently killing failure mode #2.
- **Benchmark on real docs before finalizing `small` vs `medium`** (in progress).

**Fallback: spaCy `en_core_web_trf`/`_lg` + `EntityRuler` gazetteer** (MIT, mature, materially faster on CPU) if GLiNER latency is unacceptable even windowed. A gazetteer seeded from `src/feedback/correction_tracker` covers recurring known brands regardless of primary model.

**Canonicalization: `cleanco`** (MIT) — chain `cleanco.basename()` after extraction to strip legal suffixes (Ltd/GmbH/K.K./S.A./…), replacing the 16-pattern `_legal_suffix_regexes` list. The org name becomes a folder name, so this matters.

**Rejected / deferred:** fixed-label models *alone* (won't catch novel brands); hosted APIs (AWS Comprehend / GCP NL / Azure / LLM extraction) as the *default* path — they break the offline-capability requirement — kept only as an optional, opt-in enrichment for low-confidence cases (~$1–2 / 1k docs).

## Integration surface (favorable — drop-in)

Org extraction sits behind a clean injected `Callable[[str], list[str]]` seam, so a library-backed replacement needs **zero call-site changes**:
- `ContentClassifier` composes `EntityDetector` and exposes `extract_company_names`; the unified `OrganizationKeywordSignal` (`src/scoring/signals/organization.py`) and `content_organizer` receive it by injection (`extract_company_names=self._classifier.extract_company_names`).
- **`detect_organization` takes `companies[0]`** → the replacement must return a **ranked** list (document's own org first).
- **The org *subtype* (`healthcare`/`vendor`/`client`) comes from keyword hits, not the org name** — so this swap fixes *which name* lands in the folder, and leaves subtype logic untouched.
- Ownership cue already present: the email domain `genedx.com` — ignored by the current regex.
- Existing `validate/normalize/sanitize_company_name` + `person_name_validator.py` give a precedent home for canonicalization + the ranking layer.

## The "own org vs. merely-cited org" problem

No NER/zero-shot/LLM library distinguishes a document's own org from one it cites — it is uniformly a downstream heuristic:
1. **Reference/bibliography-span exclusion** — drop text after a `References`/`Bibliography`/`Works Cited` heading before extraction (kills failure mode #2 directly).
2. **Email/URL-domain match** — high-precision, nearly free: an org whose normalized name matches a domain in the text (`genedx.com` → `GeneDx`) is almost certainly the document's own org → rank first. Also usable to *add* a brand the regex missed.
3. **Position** — header (first ~2k chars) / footer (last ~500) proximity.
4. **Frequency/salience** — mention count across non-reference text (Dunietz & Gillick: count + first-mention index are the strongest salience predictors).

## Phased plan

- **Phase 0 — model-free, cheap. ✅ SHIPPED 2026-07-18.** `src/classifiers/org_extraction.py` composing the regex extractor (reference-span exclusion + email-domain ownership ranking + `cleanco` canonicalization + gazetteer hook), wired at `ContentClassifier.extract_company_names`. Fixes both failure modes, **no model**, 629 tests green. See Empirical results.
- **Phase 1 — GLiNER. Benchmarked 2026-07-18 → `gliner_small-v2.1`, windowed only.** Recommended as an *escalation for hard/low-confidence cases* (not a wholesale swap): windowed small hits 138 ms/doc and catches GeneDx; medium and full-text blow the <200 ms budget, and the window's recall trade-off + RSS cost argue against making it the default. Pin v2.1 (never v1). See Empirical results.
- **Phase 2 — optional.** Known-brand gazetteer seeded from `feedback/correction_tracker` (the `known_brands` hook already exists in Phase 0); hosted-API enrichment behind an explicit opt-in flag for low-confidence local extractions only.

## Constraints (weighting the plan)

- Core pipeline must stay **offline-capable** (no mandatory network at classification time).
- **Perf:** org detection runs on text documents (not every image) and is gated by `OrganizationKeywordSignal.applies_to` (text-length threshold), `cost_tier="mid"` — bounded blast radius, but the pipeline is OCR-bound so the window strategy is non-negotiable.
- **Permissive license** (distributable tool): GLiNER v2.1 Apache-2.0, cleanco MIT, spaCy MIT. Avoid GLiNER v1 (CC-BY-NC).

## Empirical results

### Phase 0 — SHIPPED & WIRED (2026-07-18)

`src/classifiers/org_extraction.py` (`extract_organizations(text, *, base_extractor, known_brands=None) -> list[str]`, 6 deterministic layers: reference-span exclusion → base-regex delegation → gazetteer hook → domain-ownership cue with bare-token brand recovery → salience ranking → `cleanco.basename()` canonicalization). Promoted to the primary checkout, `cleanco>=2.3` added to `pyproject.toml` core deps, and wired at the single seam `ContentClassifier.extract_company_names` → `extract_organizations(text, base_extractor=self.entities)`.

End-to-end on the **real GeneDx PDF** (the wired path):
- base regex → `['Medical Genetics and Genomics and the Association']` (garble; misses GeneDx)
- wired Phase-0 → `['GeneDx']` (garble gone; brand recovered via the `genedx.com` cue)

Validation: **629 unit tests green** (org signal, content organizer, golden schemas, scoring, classifier/detector) — no regressions; new `tests/unit/test_org_extraction.py` (7) passes; black clean; `entity_detector.py` untouched (pure composition). Fixes both failure modes with **zero ML**. (Minor follow-ups: `cleanco` is soft-imported with a regex fallback; the domain-cue frequency count uses substring matching, which only ever boosts the already-first owner — harmless.)

### Phase 1 — GLiNER benchmark result (2026-07-18): use `gliner_small-v2.1`, windowed

Benchmarked `gliner_small-v2.1` and `gliner_medium-v2.1` on 8 real `~/Downloads` docs (1.2k–244k chars), CPU, isolated venv (primary venv untouched):

| Model | Variant | mean ms/doc | p50 | fits <200ms? |
|---|---|---|---|---|
| small | window (first 1800 + last 500) | **138** | 137 | **yes** (~50ms headroom) |
| small | full (384-word chunks, unioned) | 2128 | 613 | no (13s on the 244k-char doc) |
| medium | window | 239 | 239 | no (~20–40% over) |
| medium | full | 4196 | 1056 | no (26s worst case) |

- **Accuracy:** both small and medium extract **GeneDx** as `organization` (window + full) — the regex miss is fixed either way. Windowed also caught USAA, Truist, Purdue/UT Austin.
- **Windowing is cleaner, not just faster:** full-text returns 24–29 orgs on the SSRN paper (Springer, arXiv, journal names…) and *small hallucinates generic nouns* ("neuronal networks") as orgs; the **window returns just the 2 real orgs**. This independently confirms the reference-exclusion insight — citation noise lives mid/end-of-doc.
- **Recall trade-off:** the window misses mid-document orgs (resume: 7–8 windowed vs 14–15 full) — fine for picking the primary filing org, insufficient for exhaustive enumeration.
- **Memory:** small ~1.94 GB / medium ~2.34 GB peak RSS (must coexist with the OCR torch/easyocr/docTR footprint → another reason for small); load 3.8s / 4.7s.
- **Gotcha:** `gliner==0.2.27`'s `predict_entities` **silently truncates to 384 words** (~1,800–2,300 chars) — a single call on full OCR text reads only the head. The bounded window (one forward pass over head+footer) sidesteps this by design; full-text coverage requires manual chunking (and blows the latency budget).

**Decision:** Phase 1 = `gliner_small-v2.1`, **windowed only** (first ~1,800 + last ~500 chars, label `["organization"]`), behind the same seam, as an *escalation for hard/low-confidence cases* on top of the shipped Phase-0 heuristics — not a wholesale replacement, given the recall trade-off and the RSS cost alongside OCR.

## Key sources

- [GLiNER repo](https://github.com/urchade/GLiNER) · [v1→non-commercial license note](https://huggingface.co/urchade/gliner_base/discussions/3) · [NuNER Zero (MIT A/B alternative)](https://huggingface.co/numind/NuNER_Zero)
- [cleanco](https://github.com/psolin/cleanco) · [gliner-spacy 300× slowdown report](https://github.com/theirstory/gliner-spacy/discussions/28) · [Sease GLiNER latency benchmark](https://sease.io/2025/10/gliner-as-an-alternative-to-llms-for-query-parsing-evaluation.html)
