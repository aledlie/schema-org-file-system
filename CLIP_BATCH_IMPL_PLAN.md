# Batch CLIP Inference — Implementation Plan

**Date:** 2026-03-29
**Scope:** Fix cache layer + route main pipeline through it to unlock batch inference
**Audit ref:** `docs/deep-learning-analysis-03-27-2026.md` — open item: "Single-image inference"

---

## Background

Two problems block the 4–8× speedup:

1. The main pipeline (`ContentBasedFileOrganizer`) calls `transformers.CLIPModel` directly, one image at a time, with no cache and no connection to `clip_utils.py`.
2. `clip_cache.py:get_cached_embedding()` calls single-image `classify()` — `joblib.Memory.cache()` has no "probe without execute" API, making batch cache-miss collection impossible without replacing it.

---

## Phase 1 — Replace joblib with a manual pickle cache in `clip_cache.py`

**File:** `scripts/shared/clip_cache.py`

**Why replace joblib:** `joblib.Memory` wraps a function and caches its return value by arguments. It provides no way to check whether a result is cached without calling the function, so you cannot collect N cache misses and batch-infer them — each miss triggers an individual `classify()` call.

**Changes:**

Remove:
- `import joblib`, `_memory = joblib.Memory(...)`, `_memory.cache(_classify_by_hash)`

Add three private helpers:

```python
def _cache_key(content_hash: str, labels: list[str], prompt_prefix: str) -> str:
    labels_str = "|".join(sorted(labels)) + "|" + prompt_prefix
    return content_hash + "_" + hashlib.sha256(labels_str.encode()).hexdigest()[:12]

def _cache_path(key: str) -> Path:
    return _CACHE_DIR / key[:2] / f"{key}.pkl"

def _load(path: Path) -> list | None:
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None

def _save(path: Path, result: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(result, f)
```

Rewrite `get_cached_embedding()` (same external contract):

```python
def get_cached_embedding(
    image_path: Path,
    labels: list[str],
    prompt_prefix: str = "a photo of ",
) -> list[tuple[str, float]]:
    from shared.clip_utils import get_clip_classifier
    if not CLIP_CACHE_AVAILABLE:
        return get_clip_classifier().classify(image_path, labels, prompt_prefix)
    key = _cache_key(_sha256(image_path), labels, prompt_prefix)
    cached = _load(_cache_path(key))
    if cached is not None:
        return cached
    result = get_clip_classifier().classify(image_path, labels, prompt_prefix)
    _save(_cache_path(key), result)
    return result
```

Add `get_cached_embeddings_batch()`:

```python
def get_cached_embeddings_batch(
    image_paths: list[Path],
    labels: list[str],
    prompt_prefix: str = "a photo of ",
) -> list[list[tuple[str, float]]]:
    from shared.clip_utils import get_clip_classifier
    hashes = [_sha256(p) for p in image_paths]
    keys = [_cache_key(h, labels, prompt_prefix) for h in hashes]

    output: dict[int, list] = {}
    miss_indices: list[int] = []
    miss_paths: list[Path] = []

    for i, key in enumerate(keys):
        cached = _load(_cache_path(key))
        if cached is not None:
            output[i] = cached
        else:
            miss_indices.append(i)
            miss_paths.append(image_paths[i])

    if miss_paths:
        classifier = get_clip_classifier()
        batch_results = classifier.classify_batch(miss_paths, labels, prompt_prefix)
        for i, result in zip(miss_indices, batch_results):
            _save(_cache_path(keys[i]), result)
            output[i] = result

    return [output[i] for i in range(len(image_paths))]
```

**Export:** add `get_cached_embeddings_batch` to `scripts/shared/__init__.py`.

---

## Phase 2 — Add `CLIP_BATCH_SIZE` constant

**File:** `scripts/shared/constants.py`

Add alongside existing `CLIP_*` constants:

```python
CLIP_BATCH_SIZE: int = 32
```

Update `scripts/shared/clip_utils.py:CLIPClassifier._DEFAULT_BATCH_SIZE` to import and reference `CLIP_BATCH_SIZE` instead of the hardcoded `16`.

---

## Phase 3 — Route `classify_image_content()` through `clip_cache.py`

**Files:**
- `scripts/file_organizer_content_based.py` (lines 1069–1130 and 3089–3149)
- `src/analyzers/image_analyzer.py` (lines 124–160)

Both classes currently load `transformers.CLIPModel.from_pretrained("openai/clip-vit-base-patch32")` in `__init__` and call it inline per image. `CLIPClassifier` in `clip_utils.py` loads the same weights via `sentence-transformers`.

**Changes to `classify_image_content()` in both files:**

Replace the inline `transformers` forward pass:

```python
# Before
inputs = self.processor(text=labels, images=image, return_tensors="pt", padding=True)
with torch.no_grad():
    probs = self.model(**inputs).logits_per_image.softmax(dim=1)
scores = {label: float(probs[0][i]) for i, label in enumerate(labels)}
```

With:

```python
# After
from shared.clip_cache import get_cached_embedding, CLIP_CACHE_AVAILABLE
if CLIP_CACHE_AVAILABLE:
    results = get_cached_embedding(image_path, labels)
    scores = {label: conf for label, conf in results}
else:
    # existing transformers fallback
    ...
```

**Changes to `__init__`:** guard `self.model` / `self.processor` load behind `not CLIP_CACHE_AVAILABLE` — if `clip_cache` is available, the `CLIPClassifier` singleton replaces them.

**Changes to `enhance_weak_image_classification()` (line 3089):** same replacement — call `get_cached_embedding(file_path, CLIP_CONTENT_LABELS)` instead of the inline `self.image_analyzer.processor/model` call.

---

## Phase 4 — Pre-warm cache before per-file loop in `BatchProcessor`

**File:** `src/pipeline/batch_processor.py`

**Change:** insert a pre-warm block after `all_files` is assembled (after line 85), before the `for file_path in all_files` loop (line 90):

```python
_IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tiff", ".tif",
})

try:
    from shared.clip_cache import get_cached_embeddings_batch, CLIP_CACHE_AVAILABLE
    from shared.constants import CLIP_CONTENT_LABELS, CLIP_BATCH_SIZE
    _BATCH_PREWARM_AVAILABLE = CLIP_CACHE_AVAILABLE
except ImportError:
    _BATCH_PREWARM_AVAILABLE = False

# --- pre-warm block ---
if _BATCH_PREWARM_AVAILABLE:
    image_paths = [p for p in all_files if p.suffix.lower() in _IMAGE_EXTENSIONS]
    if image_paths:
        print(f"\nPre-warming CLIP cache: {len(image_paths)} images (batch={CLIP_BATCH_SIZE})")
        for chunk_start in range(0, len(image_paths), CLIP_BATCH_SIZE):
            chunk = image_paths[chunk_start : chunk_start + CLIP_BATCH_SIZE]
            get_cached_embeddings_batch(chunk, CLIP_CONTENT_LABELS)
        print("CLIP cache pre-warm complete\n")
```

The existing `for file_path in all_files` loop is **unchanged**. After pre-warm, every `get_cached_embedding()` call inside `classify_image_content()` is a pickle read — no model inference in the loop.

---

## Files changed

| File | Change |
|------|--------|
| `scripts/shared/clip_cache.py` | Replace joblib with manual pickle cache; add `get_cached_embeddings_batch()` |
| `scripts/shared/__init__.py` | Export `get_cached_embeddings_batch` |
| `scripts/shared/constants.py` | Add `CLIP_BATCH_SIZE = 32` |
| `scripts/shared/clip_utils.py` | Reference `CLIP_BATCH_SIZE` constant instead of hardcoded `16` |
| `scripts/file_organizer_content_based.py` | Route `classify_image_content()` + `enhance_weak_image_classification()` through `get_cached_embedding()` |
| `src/analyzers/image_analyzer.py` | Route `classify_image_content()` through `get_cached_embedding()` |
| `src/pipeline/batch_processor.py` | Add pre-warm block before per-file loop |

---

## Testing

```bash
# Unit — cache round-trip, batch vs single consistency
pytest tests/unit/ -k clip

# Smoke — dry run on a folder of images, watch for "Pre-warming CLIP cache" log line
organize-files content --source ~/Downloads --dry-run --limit 50

# Perf — before/after wall time on 100 images
time organize-files content --source ~/Downloads --dry-run --limit 100
```

---

## What this does NOT change

- `CLIPClassifier._run_batch()` in `clip_utils.py` — already correct
- The per-file loop in `BatchProcessor` — unchanged
- Existing joblib cache files — old format will be silently skipped (treated as miss), rebuilt on first access

---

## Follow-on: migrate to `open-clip-torch`

See `docs/BACKLOG.md` — "Migrate CLIP backend to `open-clip-torch`". Depends on this plan landing first.
