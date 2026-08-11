"""SSCD descriptor extraction and caching.

The SSCD model itself is a 94 MB download, so ``_get_model`` is replaced with a
stub whose descriptors *identify their source image* (first pixel's red channel
carries through to descriptor[0]). That is what makes the alignment tests below
possible: they assert which path got which descriptor, not merely that some
descriptors came back.
"""

from pathlib import Path

import pytest
from PIL import Image

from src.similarity import descriptors as mod

DIMENSIONS = 4
# Distinct red channels, so a descriptor can be traced back to its source file.
MARKERS = (10, 60, 110, 160, 210)


def write_image(path: Path, marker: int, size=(40, 30)) -> Path:
    Image.new("RGB", size, (marker, 0, 0)).save(path)
    return path


def marker_of(descriptor) -> int:
    """Recover the source image's red channel from a stub descriptor."""
    return int(round(float(descriptor[0]) * 255))


@pytest.fixture
def stub_model(monkeypatch):
    """A model+transform pair that propagates each image's marker pixel."""

    def transform(image):
        import torch

        red = image.getpixel((0, 0))[0] / 255.0
        return torch.full((3, 8, 8), red, dtype=torch.float32)

    class Model:
        def __call__(self, batch):
            import torch

            # One row per input, every component = that image's marker.
            per_image = batch.mean(dim=(1, 2, 3))
            return torch.stack([torch.full((DIMENSIONS,), v) for v in per_image])

    monkeypatch.setattr(mod, "_get_model", lambda: (Model(), transform))
    return Model


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch) -> Path:
    directory = tmp_path / "descriptor-cache"
    monkeypatch.setattr(mod, "DESCRIPTOR_CACHE_DIR", directory)
    return directory


class TestEncodeImagesAlignment:
    """Descriptors must stay bound to the file they came from.

    ``encode_images`` skips unreadable files mid-batch while collecting
    ``tensors`` and ``indices`` in parallel. If those two ever drift, every
    descriptor after the skip is attributed to the wrong path — and a
    near-duplicate report built on that is confidently wrong rather than
    empty, which is the worst failure mode this feature has.
    """

    @pytest.mark.parametrize("bad_position", [0, 1, 2], ids=["first", "middle", "last"])
    def test_unreadable_file_does_not_shift_the_others(self, tmp_path, stub_model, bad_position):
        paths = [write_image(tmp_path / f"img_{i}.png", MARKERS[i]) for i in range(3)]
        # Corrupt one file in place: it is collected, then fails to open.
        paths[bad_position].write_bytes(b"not an image")

        encoded = mod.encode_images(paths)

        assert len(encoded) == 2
        for index, descriptor in encoded:
            assert index != bad_position
            assert marker_of(descriptor) == MARKERS[index], (
                f"descriptor for index {index} carries marker "
                f"{marker_of(descriptor)}, expected {MARKERS[index]}"
            )

    def test_indices_map_to_the_original_sequence_across_batches(
        self, tmp_path, stub_model, monkeypatch
    ):
        """Returned indices are positions in the input, not within a batch."""
        monkeypatch.setattr(mod, "SSCD_BATCH_SIZE", 2)
        paths = [write_image(tmp_path / f"img_{i}.png", MARKERS[i]) for i in range(5)]

        encoded = mod.encode_images(paths)

        assert [index for index, _ in encoded] == [0, 1, 2, 3, 4]
        for index, descriptor in encoded:
            assert marker_of(descriptor) == MARKERS[index]

    def test_every_file_unreadable_yields_nothing(self, tmp_path, stub_model):
        paths = [tmp_path / "a.png", tmp_path / "b.png"]
        for path in paths:
            path.write_bytes(b"junk")

        assert mod.encode_images(paths) == []

    def test_no_paths_yields_nothing(self, stub_model):
        assert mod.encode_images([]) == []

    def test_empty_batch_never_touches_the_model(self, monkeypatch):
        """Regression: _get_model downloads a 94 MB checkpoint on first use.

        encode_images used to call it before checking for work, so a run whose
        descriptors were all cache hits still paid the download on a cold
        process.
        """

        def fail():
            raise AssertionError("_get_model called for an empty batch")

        monkeypatch.setattr(mod, "_get_model", fail)

        assert mod.encode_images([]) == []

    def test_returns_nothing_when_the_model_is_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "_get_model", lambda: (None, None))

        assert mod.encode_images([write_image(tmp_path / "a.png", 10)]) == []


class TestOpenRgb:
    def test_missing_file_returns_none(self, tmp_path):
        assert mod._open_rgb(tmp_path / "absent.png") is None

    def test_corrupt_file_returns_none(self, tmp_path):
        path = tmp_path / "broken.png"
        path.write_bytes(b"not an image")

        assert mod._open_rgb(path) is None

    def test_restores_the_decompression_bomb_limit(self, tmp_path):
        """The limit is a Pillow global; leaking it disarms the guard process-wide."""
        before = Image.MAX_IMAGE_PIXELS

        mod._open_rgb(write_image(tmp_path / "ok.png", 10))

        assert Image.MAX_IMAGE_PIXELS == before

    def test_restores_the_limit_even_when_opening_fails(self, tmp_path):
        before = Image.MAX_IMAGE_PIXELS
        path = tmp_path / "broken.png"
        path.write_bytes(b"not an image")

        assert mod._open_rgb(path) is None
        assert Image.MAX_IMAGE_PIXELS == before

    def test_oversized_image_still_opens(self, tmp_path, monkeypatch):
        """Guard is lifted deliberately: the transform downscales to 320px."""
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)

        assert mod._open_rgb(write_image(tmp_path / "big.png", 10, size=(50, 50))) is not None

    def test_converts_to_rgb(self, tmp_path):
        path = tmp_path / "gray.png"
        Image.new("L", (20, 20), 128).save(path)

        assert mod._open_rgb(path).mode == "RGB"

    def test_heic_opens(self, tmp_path):
        """Regression: HEIC needs register_heif_opener() in this module.

        Without it Image.open fails and .heic files silently vanish from a
        scan, despite being advertised in IMAGE_EXTENSIONS.
        """
        pytest.importorskip("pillow_heif")
        path = tmp_path / "photo.heic"
        Image.new("RGB", (40, 30), (77, 0, 0)).save(path)

        opened = mod._open_rgb(path)

        assert opened is not None
        assert opened.mode == "RGB"

    def test_pdf_rasterises_the_first_page_only(self, tmp_path):
        pytest.importorskip("pdf2image")
        first = Image.new("RGB", (60, 40), (200, 0, 0))
        second = Image.new("RGB", (60, 40), (0, 200, 0))
        path = tmp_path / "two_pages.pdf"
        first.save(path, "PDF", save_all=True, append_images=[second])

        opened = mod._open_rgb(path)

        assert opened is not None
        # Red page 1, not green page 2.
        red, green, _blue = opened.convert("RGB").getpixel((30, 20))
        assert red > green

    def test_corrupt_pdf_returns_none(self, tmp_path):
        path = tmp_path / "broken.pdf"
        path.write_bytes(b"%PDF-1.4 truncated")

        assert mod._open_rgb(path) is None


class TestCacheIdentity:
    def test_same_file_yields_a_stable_key(self, tmp_path):
        path = write_image(tmp_path / "a.png", 10)

        assert mod._file_identity(path) == mod._file_identity(path)

    def test_key_changes_when_content_size_changes(self, tmp_path):
        path = write_image(tmp_path / "a.png", 10)
        before = mod._file_identity(path)

        write_image(path, 10, size=(200, 200))

        assert mod._file_identity(path) != before

    def test_key_changes_when_mtime_changes(self, tmp_path):
        import os

        path = write_image(tmp_path / "a.png", 10)
        before = mod._file_identity(path)
        stat = path.stat()

        os.utime(path, (stat.st_atime, stat.st_mtime + 100))

        assert mod._file_identity(path) != before

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(OSError):
            mod._file_identity(tmp_path / "absent.png")

    def test_cache_path_shards_on_the_key_prefix(self, cache_dir):
        path = mod._cache_path("abcdef1234")

        assert path.parent == cache_dir / "ab"
        assert path.name == "abcdef1234.npy"


class TestGetDescriptors:
    def test_describes_and_caches(self, tmp_path, cache_dir, stub_model):
        path = write_image(tmp_path / "a.png", MARKERS[0])

        described = mod.get_descriptors([path])

        assert [p for p, _ in described] == [path]
        assert marker_of(described[0][1]) == MARKERS[0]
        assert list(cache_dir.rglob("*.npy"))

    def test_second_call_reads_the_cache_instead_of_encoding(
        self, tmp_path, cache_dir, stub_model, monkeypatch
    ):
        path = write_image(tmp_path / "a.png", MARKERS[1])
        first = mod.get_descriptors([path])

        def fail(_paths):
            raise AssertionError("cache miss: encode_images should not be called")

        monkeypatch.setattr(mod, "encode_images", fail)
        second = mod.get_descriptors([path])

        assert marker_of(second[0][1]) == marker_of(first[0][1])

    def test_pairs_stay_bound_to_their_path_when_one_file_fails(
        self, tmp_path, cache_dir, stub_model
    ):
        good_a = write_image(tmp_path / "a.png", MARKERS[0])
        broken = tmp_path / "b.png"
        broken.write_bytes(b"junk")
        good_b = write_image(tmp_path / "c.png", MARKERS[2])

        described = mod.get_descriptors([good_a, broken, good_b])

        assert [p for p, _ in described] == [good_a, good_b]
        assert marker_of(described[0][1]) == MARKERS[0]
        assert marker_of(described[1][1]) == MARKERS[2]

    def test_unencodable_files_are_omitted_entirely(self, tmp_path, cache_dir, stub_model):
        broken = tmp_path / "b.png"
        broken.write_bytes(b"junk")

        assert mod.get_descriptors([broken]) == []

    def test_missing_paths_are_skipped_not_raised(self, tmp_path, cache_dir, stub_model):
        assert mod.get_descriptors([tmp_path / "absent.png"]) == []

    def test_no_paths_yields_nothing(self, cache_dir, stub_model):
        assert mod.get_descriptors([]) == []

    def test_degrades_to_empty_when_dependencies_are_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DESCRIPTORS_AVAILABLE", False)

        assert mod.get_descriptors([write_image(tmp_path / "a.png", 10)]) == []


class TestModelDownload:
    def test_existing_checkpoint_is_reused_without_network(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "SSCD_MODEL_DIR", tmp_path)
        checkpoint = tmp_path / f"{mod.SSCD_MODEL_NAME}.torchscript.pt"
        checkpoint.write_bytes(b"pretend weights")

        def no_network(*_args, **_kwargs):
            raise AssertionError("should not download when the checkpoint exists")

        monkeypatch.setattr("requests.get", no_network)

        assert mod.ensure_model_downloaded() == checkpoint

    def test_failed_download_leaves_no_partial_checkpoint(self, tmp_path, monkeypatch):
        """A truncated .pt would fail torch.jit.load confusingly, much later."""
        monkeypatch.setattr(mod, "SSCD_MODEL_DIR", tmp_path)

        def explode(*_args, **_kwargs):
            raise OSError("connection reset")

        monkeypatch.setattr("requests.get", explode)

        assert mod.ensure_model_downloaded(progress=False) is None
        assert list(tmp_path.iterdir()) == []

    def test_checkpoint_path_is_named_for_the_configured_model(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "SSCD_MODEL_DIR", tmp_path)

        assert mod.model_checkpoint_path().name.startswith(mod.SSCD_MODEL_NAME)


class TestDescriptorContract:
    def test_disc_weights_not_imagenet(self):
        """ImageNet-trained variants reopen a settled licensing question."""
        assert "imagenet" not in mod.SSCD_MODEL_NAME
        assert "imagenet" not in mod.SSCD_MODEL_URL

    def test_cache_is_separate_from_the_clip_cache(self):
        """Both are 512-d and not interchangeable; sharing a dir would mix them."""
        assert "clip" not in str(mod.DESCRIPTOR_CACHE_DIR)
