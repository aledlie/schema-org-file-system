"""
Test suite for Schema.org generators.

Tests all generator classes for proper Schema.org compliance.
"""

import sys
sys.path.insert(0, '/Users/alyshialedlie/schema-org-file-system/src')

import unittest
from datetime import datetime
from generators import (
    DocumentGenerator,
    ImageGenerator,
    VideoGenerator,
    AudioGenerator,
    CodeGenerator,
    DatasetGenerator,
    ArchiveGenerator
)
from validator import SchemaValidator


class TestDocumentGenerator(unittest.TestCase):
    """Test DocumentGenerator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = DocumentGenerator()
        self.validator = SchemaValidator()

    def test_basic_document_creation(self):
        """Test creating a basic document schema."""
        doc = self.generator.set_basic_info(
            name="Sample Document",
            description="A test document",
            abstract="This is an abstract"
        ).set_file_info(
            encoding_format="application/pdf",
            url="https://example.com/doc.pdf",
            content_size=102400
        )

        data = doc.to_dict()
        self.assertEqual(data["@type"], "DigitalDocument")
        self.assertEqual(data["name"], "Sample Document")
        self.assertEqual(data["encodingFormat"], "application/pdf")
        self.assertIn("contentSize", data)

    def test_document_with_author(self):
        """Test document with author information."""
        doc = self.generator.set_basic_info(
            name="Research Paper"
        ).add_person(
            "author",
            "John Doe",
            email="john@example.com",
            affiliation="Example University"
        )

        data = doc.to_dict()
        self.assertIn("author", data)
        self.assertEqual(data["author"]["@type"], "Person")
        self.assertEqual(data["author"]["name"], "John Doe")

    def test_document_validation(self):
        """Test document validation."""
        doc = self.generator.set_basic_info(
            name="Test Document"
        ).set_file_info(
            encoding_format="application/pdf",
            url="https://example.com/test.pdf"
        )

        report = self.validator.validate(doc.to_dict())
        self.assertTrue(report.is_valid())

    def test_scholarly_article(self):
        """Test scholarly article creation."""
        article = DocumentGenerator("ScholarlyArticle")
        article.set_basic_info(
            name="AI Research"
        ).set_scholarly_info(
            doi="10.1234/example",
            publication="Nature"
        )

        data = article.to_dict()
        self.assertEqual(data["@type"], "ScholarlyArticle")
        self.assertIn("sameAs", data)


class TestImageGenerator(unittest.TestCase):
    """Test ImageGenerator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = ImageGenerator()
        self.validator = SchemaValidator()

    def test_basic_image_creation(self):
        """Test creating a basic image schema."""
        img = self.generator.set_basic_info(
            name="Sample Image",
            content_url="https://example.com/image.jpg",
            encoding_format="image/jpeg",
            description="A test image"
        ).set_dimensions(1920, 1080)

        data = img.to_dict()
        self.assertEqual(data["@type"], "ImageObject")
        self.assertEqual(data["width"], 1920)
        self.assertEqual(data["height"], 1080)

    def test_image_with_exif(self):
        """Test image with EXIF data."""
        exif = {
            "Make": "Canon",
            "Model": "EOS 5D",
            "DateTime": "2024-01-15 10:30:00"
        }
        img = self.generator.set_basic_info(
            name="Photo",
            content_url="https://example.com/photo.jpg",
            encoding_format="image/jpeg"
        ).set_exif_data(exif)

        data = img.to_dict()
        self.assertIn("exifData", data)
        self.assertIn("dateCreated", data)

    def test_photograph_type(self):
        """Test photograph type."""
        photo = ImageGenerator("Photograph")
        photo.set_basic_info(
            name="Portrait",
            content_url="https://example.com/portrait.jpg",
            encoding_format="image/jpeg"
        ).add_person("creator", "Jane Smith")

        data = photo.to_dict()
        self.assertEqual(data["@type"], "Photograph")


class TestVideoGenerator(unittest.TestCase):
    """Test VideoGenerator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = VideoGenerator()

    def test_basic_video_creation(self):
        """Test creating a basic video schema."""
        video = self.generator.set_basic_info(
            name="Sample Video",
            content_url="https://example.com/video.mp4",
            upload_date=datetime(2024, 1, 15),
            description="A test video",
            thumbnail_url="https://example.com/thumb.jpg"
        ).set_media_details(
            duration="PT5M30S",
            width=1920,
            height=1080,
            encoding_format="video/mp4"
        )

        data = video.to_dict()
        self.assertEqual(data["@type"], "VideoObject")
        self.assertEqual(data["duration"], "PT5M30S")
        self.assertEqual(data["width"], 1920)

    def test_video_with_stats(self):
        """Test video with interaction statistics."""
        video = self.generator.set_basic_info(
            name="Popular Video",
            content_url="https://example.com/video.mp4",
            upload_date=datetime.now()
        ).set_interaction_stats(
            view_count=10000,
            comment_count=250
        )

        data = video.to_dict()
        self.assertIn("interactionStatistic", data)
        self.assertEqual(len(data["interactionStatistic"]), 2)


class TestAudioGenerator(unittest.TestCase):
    """Test AudioGenerator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = AudioGenerator()

    def test_basic_audio_creation(self):
        """Test creating a basic audio schema."""
        audio = self.generator.set_basic_info(
            name="Sample Audio",
            content_url="https://example.com/audio.mp3",
            duration="PT3M45S"
        )

        data = audio.to_dict()
        self.assertEqual(data["@type"], "AudioObject")
        self.assertEqual(data["duration"], "PT3M45S")

    def test_music_recording(self):
        """Test music recording creation."""
        music = AudioGenerator("MusicRecording")
        music.set_basic_info(
            name="Great Song",
            content_url="https://example.com/song.mp3"
        ).set_music_info(
            album="Best Album",
            artist="Famous Artist",
            genre="Rock",
            isrc="USRC12345678"
        )

        data = music.to_dict()
        self.assertEqual(data["@type"], "MusicRecording")
        self.assertIn("inAlbum", data)
        self.assertIn("byArtist", data)
        self.assertEqual(data["isrcCode"], "USRC12345678")

    def test_podcast_episode(self):
        """Test podcast episode creation."""
        podcast = AudioGenerator("PodcastEpisode")
        podcast.set_basic_info(
            name="Episode 42",
            content_url="https://example.com/episode42.mp3"
        ).set_podcast_info(
            episode_number=42,
            series="Tech Talk"
        )

        data = podcast.to_dict()
        self.assertEqual(data["@type"], "PodcastEpisode")
        self.assertEqual(data["episodeNumber"], 42)


class TestCodeGenerator(unittest.TestCase):
    """Test CodeGenerator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = CodeGenerator()

    def test_basic_code_creation(self):
        """Test creating a basic code schema."""
        code = self.generator.set_basic_info(
            name="example.py",
            programming_language="Python",
            description="Example Python script"
        )

        data = code.to_dict()
        self.assertEqual(data["@type"], "SoftwareSourceCode")
        self.assertEqual(data["programmingLanguage"], "Python")

    def test_code_with_repository(self):
        """Test code with repository information."""
        code = self.generator.set_basic_info(
            name="main.py",
            programming_language="Python"
        ).set_repository_info(
            repository_url="https://github.com/user/repo",
            branch="main",
            commit="abc123"
        )

        data = code.to_dict()
        self.assertEqual(data["codeRepository"], "https://github.com/user/repo")
        self.assertIn("identifier", data)

    def test_code_with_dependencies(self):
        """Test code with dependencies."""
        code = self.generator.set_basic_info(
            name="app.js",
            programming_language="JavaScript"
        ).add_dependency("react", "18.2.0").add_dependency("axios", "1.4.0")

        data = code.to_dict()
        self.assertIn("dependencies", data)
        self.assertEqual(len(data["dependencies"]), 2)


class TestDatasetGenerator(unittest.TestCase):
    """Test DatasetGenerator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = DatasetGenerator()

    def test_basic_dataset_creation(self):
        """Test creating a basic dataset schema."""
        dataset = self.generator.set_basic_info(
            name="Sales Data",
            description="Annual sales dataset",
            url="https://example.com/data.csv"
        )

        data = dataset.to_dict()
        self.assertEqual(data["@type"], "Dataset")
        self.assertEqual(data["name"], "Sales Data")

    def test_dataset_with_distribution(self):
        """Test dataset with distribution."""
        dataset = self.generator.set_basic_info(
            name="Weather Data",
            description="Historical weather data"
        ).add_distribution(
            content_url="https://example.com/weather.csv",
            encoding_format="text/csv",
            content_size=1024000
        )

        data = dataset.to_dict()
        self.assertIn("distribution", data)
        self.assertEqual(data["distribution"][0]["@type"], "DataDownload")

    def test_dataset_with_variables(self):
        """Test dataset with measured variables."""
        dataset = self.generator.set_basic_info(
            name="Experiment Results",
            description="Scientific experiment data"
        ).add_variable_measured(
            "temperature",
            "Temperature in Celsius"
        ).add_variable_measured("pressure")

        data = dataset.to_dict()
        self.assertIn("variableMeasured", data)
        self.assertEqual(len(data["variableMeasured"]), 2)


class TestArchiveGenerator(unittest.TestCase):
    """Test ArchiveGenerator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = ArchiveGenerator()

    def test_basic_archive_creation(self):
        """Test creating a basic archive schema."""
        archive = self.generator.set_basic_info(
            name="backup.zip",
            encoding_format="application/zip",
            description="System backup archive",
            content_size=10485760
        )

        data = archive.to_dict()
        self.assertEqual(data["@type"], "DigitalDocument")
        self.assertEqual(data["additionalType"], "Archive")

    def test_archive_with_contents(self):
        """Test archive with contained files."""
        doc = DocumentGenerator()
        doc.set_basic_info(name="readme.txt")

        archive = self.generator.set_basic_info(
            name="files.zip",
            encoding_format="application/zip"
        ).add_contained_file(doc)

        data = archive.to_dict()
        self.assertIn("hasPart", data)
        self.assertEqual(len(data["hasPart"]), 1)


class TestSchemaIntegration(unittest.TestCase):
    """Test cross-generator integration."""

    def test_json_ld_generation(self):
        """Test JSON-LD generation."""
        doc = DocumentGenerator()
        doc.set_basic_info("Test").set_file_info(
            "application/pdf",
            "https://example.com/test.pdf"
        )

        json_ld = doc.to_json_ld()
        self.assertIn('"@context"', json_ld)
        self.assertIn('"@type"', json_ld)

    def test_nested_schemas(self):
        """Test nested schema relationships."""
        article = DocumentGenerator("Article")
        article.set_basic_info(name="News Article")
        article.add_person("author", "John Doe", email="john@example.com")
        article.add_organization("publisher", "News Corp", url="https://news.example.com")

        data = article.to_dict()
        self.assertEqual(data["author"]["@type"], "Person")
        self.assertEqual(data["publisher"]["@type"], "Organization")

    def test_completion_score(self):
        """Test completion score calculation."""
        doc = DocumentGenerator()
        score_before = doc.get_completion_score()

        doc.set_basic_info("Complete Document").set_file_info(
            "application/pdf",
            "https://example.com/doc.pdf"
        ).add_person("author", "Jane Doe").set_dates(created=datetime.now())

        score_after = doc.get_completion_score()
        self.assertGreater(score_after, score_before)


def run_tests():
    """Run all tests."""
    unittest.main(argv=[''], verbosity=2, exit=False)


if __name__ == '__main__':
    run_tests()
