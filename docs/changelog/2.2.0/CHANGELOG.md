# Changelog

## [2.2.0] - 2026-07-25

### Fixed

- **`PHOTO_PROPERTY_CONFIDENCE` re-tune — resolved by SceneSignal swap completion** — `PhotoCompositionSignal`'s `is_property_mgmt` branch (and `PHOTO_PROPERTY_CONFIDENCE` constant) was retired with the SceneSignal swap completion (2026-07-18). Interior detection is now exclusively handled by the trained scene probe (`scene.py`, artifact committed + health-checked as `scene_probe`), so the under-committing fixed-confidence vote this item tracked no longer exists. Resolution decision: retirement rather than re-tune (MEDIA_EXTERIORS_PLAN decision #5). Probe availability is now reported by `organize-files health` (`scene_probe` feature); missing/unreadable artifacts surface with a retrain hint instead of silently degrading. Historical analysis preserved in the original backlog item.

- **`redact_pii.py` leaks barcodes + alphabetic sensitive terms — barcode detection + `--redact-terms` flag shipped** — `scripts/redact_pii.py` previously rasterized inputs to PNG and used OCR-token redaction only, which failed on barcodes (not detected as words by docTR) and alphabetic PII (no OCR keywords). Reproduced on real files: Texas driver's-license back with PDF417 barcode + rotated DOB, SNPedia health-condition screenshot. Shipped 2026-07-18: (1) barcode detection via `cv2.barcode_BarcodeDetector` + `cv2.QRCodeDetector` in `detect_and_cover_barcodes`; (2) `--redact-terms` flag for user-supplied alphabetic PII (health conditions, org names, repeatable); (3) manifest records `barcode_detected`/`barcode_covered`/`barcode_unredacted`; (4) non-zero exit when a barcode is detected but not localized; (5) 27-test suite in `tests/unit/test_redact_pii.py`. Residual gaps (lower value vs. complexity): ID-shape fail-loud heuristic (deferred — barcode presence already triggers loudest warning), rotated-text OCR recall (docTR orientation detection not enabled; documented as known limitation), multi-word `--redact-terms` (each OCR token checked independently; documented in test comments).

### Backlog Resolved (from 2026-07-25 session)

- **Content organizer misclassifies diverse/screenshot sources — item 1 shipped 2026-07-24** — Review gate was keying on decision-confidence, which the scene probe inflates (interior probe votes ~0.99 confidence even when OCR/label confidence is 1–12%). Added corroboration guard in `ContentOrganizer._reroute_screenshot_scene`: when `SceneSignal` is the sole entry in `winning_signals` AND the file is screenshot-named, decision routes to `photos_screenshots_other` instead of the scene-class bucket. 14 new/updated tests in `TestScreenshotSceneReroute`; 2241 unit tests pass. (Items 2–5 shipped 2026-07-18; item 1 was re-analyzed and resolved post-SceneSignal swap.)

---
