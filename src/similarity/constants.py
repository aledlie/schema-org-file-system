"""Near-duplicate detection constants — single source of truth.

Kept at the feature's owner (mirrors ``src/scoring/weights.py``) rather than in
``src/constants.py``: every value here is tuned against the descriptor model
below and is meaningless without it.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- #
# SSCD descriptor model                                                        #
# --------------------------------------------------------------------------- #

# TorchScript checkpoint — standalone, needs no sscd-copy-detection install.
# The DISC-trained variant is deliberate: the sibling ``sscd_imagenet_*``
# weights are ImageNet-trained, which reopens the research-only-dataset
# question this project has already settled against. Both emit 512-d
# descriptors, so the choice costs nothing.
SSCD_MODEL_NAME = "sscd_disc_mixup"
SSCD_MODEL_URL = "https://dl.fbaipublicfiles.com/sscd-copy-detection/sscd_disc_mixup.torchscript.pt"
SSCD_MODEL_DIR = _REPO_ROOT / ".cache" / "sscd_models"
SSCD_DESCRIPTOR_DIM = 512

# Upstream publishes two inference transforms (sscd-copy-detection README,
# "Preprocessing"): ``small_288`` resizes the small edge to 288 preserving
# aspect ratio, and ``skew_320`` resizes to a square 320x320, deliberately
# skewing. We use skew_320 because it is the one that batches: aspect-preserving
# resize produces ragged tensors ([3,339,288] vs [3,340,288]) that torch.stack
# rejects, so small_288 forces a batch size of 1. Upstream recommends the square
# form for exactly this reason. Both sides of a comparison get the same skew, so
# duplicate detection is unaffected. Do not change these without re-encoding the
# descriptor cache — old and new descriptors are not comparable.
SSCD_RESIZE_SQUARE = (320, 320)
SSCD_NORMALIZE_MEAN = (0.485, 0.456, 0.406)
SSCD_NORMALIZE_STD = (0.229, 0.224, 0.225)

# Images per forward pass. CPU-bound (~45 ms/image on an M-series core), so this
# trades peak memory for a modest batching win, not a large one.
SSCD_BATCH_SIZE = 16

# Descriptor cache. Versioned like the CLIP cache so a model or preprocessing
# change is a directory bump, not a silent mixed-vintage cache. NOT
# interchangeable with .cache/clip_embeddings_v2 despite both being 512-d.
DESCRIPTOR_CACHE_DIR = _REPO_ROOT / ".cache" / "sscd_descriptors_v1"

# --------------------------------------------------------------------------- #
# Index + grouping                                                             #
# --------------------------------------------------------------------------- #

# Cosine similarity at or above which two files are proposed as near-duplicates.
# Descriptors are L2-normalised, so faiss inner product IS cosine. 0.85 is the
# conservative default: it is a *report* threshold, tuned to keep the review
# queue readable rather than to maximise recall. Lower it to widen the net.
DEFAULT_SIMILARITY_THRESHOLD = 0.85

# Neighbours retrieved per file before thresholding. A file's duplicate set is
# almost always tiny; this caps the k-NN cost and the pair explosion when a
# corpus contains a large block of identical assets.
DEFAULT_MAX_NEIGHBORS = 10

# Smallest group worth reporting. A "group" of one is just a file.
MIN_GROUP_SIZE = 2

# --------------------------------------------------------------------------- #
# Input handling                                                               #
# --------------------------------------------------------------------------- #

# Raster formats fed to the descriptor model directly.
IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".heic", ".heif"}
)

# PDFs are rasterised (first page only) so a scanned/exported document can match
# its image twin — the motivating case is a PDF and a PNG of the same map. First
# page only is a deliberate limit: it makes multi-page documents match on their
# cover, which is right for "same document" and wrong for "same content buried
# on page 7". See the BACKLOG entry.
PDF_EXTENSION = ".pdf"
PDF_RASTER_DPI = 100
PDF_RASTER_FIRST_PAGE = 1
