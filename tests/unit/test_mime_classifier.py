"""Unit tests for src/organizers/mime_classifier.py.

classify_by_mime is the lowest-priority fallback in the classification
cascade and classify_font the font-extension map — both extracted from the
retired scripts/file_organizer.py. These tests were re-pointed here from
tests/unit/test_file_organizer.py when that script (and its test suite)
was deleted.
"""

from pathlib import Path

import pytest

from src.organizers.mime_classifier import classify_by_mime, classify_font


class TestClassifyFont:
    @pytest.mark.parametrize("ext,expected", [
        (".ttf", ("fonts", "truetype", "DigitalDocument")),
        (".otf", ("fonts", "opentype", "DigitalDocument")),
        (".woff", ("fonts", "web", "DigitalDocument")),
        (".woff2", ("fonts", "web", "DigitalDocument")),
        (".eot", ("fonts", "web", "DigitalDocument")),
        (".fon", ("fonts", "other", "DigitalDocument")),
        (".fnt", ("fonts", "other", "DigitalDocument")),
    ])
    def test_font_extensions(self, ext, expected):
        assert classify_font(ext) == expected

    def test_non_font_returns_none(self):
        assert classify_font(".txt") is None

    def test_case_insensitive(self):
        assert classify_font(".TTF") == ("fonts", "truetype", "DigitalDocument")


class TestClassifyByMime:
    @pytest.mark.parametrize("path,mime,expected", [
        # Images: screenshot name, photo extensions, everything else graphics
        ("Screenshot 2026-01-01.png", "image/png", ("images", "screenshots", "ImageObject")),
        ("screen_capture.png", "image/png", ("images", "screenshots", "ImageObject")),
        ("vacation.jpg", "image/jpeg", ("images", "photos", "Photograph")),
        ("portrait.heic", "image/heic", ("images", "photos", "Photograph")),
        ("diagram.png", "image/png", ("images", "graphics", "ImageObject")),
        # Documents
        ("report.pdf", "application/pdf", ("documents", "pdf", "DigitalDocument")),
        ("report.pdf", None, ("documents", "pdf", "DigitalDocument")),
        ("letter.docx",
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         ("documents", "word", "DigitalDocument")),
        ("sheet.xlsx",
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         ("documents", "spreadsheets", "DigitalDocument")),
        ("deck.pptx",
         "application/vnd.openxmlformats-officedocument.presentationml.presentation",
         ("documents", "presentations", "DigitalDocument")),
        ("README.md", None, ("documents", "markdown", "Article")),
        ("notes.txt", "text/plain", ("documents", "text", "DigitalDocument")),
        # Documents via extension only (mime=None)
        ("letter.docx", None, ("documents", "word", "DigitalDocument")),
        ("sheet.xlsx", None, ("documents", "spreadsheets", "DigitalDocument")),
        ("deck.pptx", None, ("documents", "presentations", "DigitalDocument")),
        ("notes.txt", None, ("documents", "text", "DigitalDocument")),
        # Images via extension only (mime=None): jpg/jpeg/heic photos, rest graphics
        ("vacation.jpg", None, ("images", "photos", "Photograph")),
        ("diagram.png", None, ("images", "graphics", "ImageObject")),
        ("vector.svg", None, ("images", "graphics", "ImageObject")),
        # Media
        ("clip.mp4", "video/mp4", ("media", "videos", "VideoObject")),
        ("clip.mov", None, ("media", "videos", "VideoObject")),
        ("track.mp3", "audio/mpeg", ("media", "music", "MusicRecording")),
        ("track.mp3", None, ("media", "music", "MusicRecording")),
        ("voicemail.ogg", "audio/ogg", ("media", "audio", "AudioObject")),
        ("voicemail.wav", None, ("media", "audio", "AudioObject")),
        # Fonts route through classify_by_mime too
        ("Roboto.ttf", None, ("fonts", "truetype", "DigitalDocument")),
        # Archives
        ("bundle.zip", "application/zip", ("archives", "zip", "DigitalDocument")),
        ("bundle.zip", None, ("archives", "zip", "DigitalDocument")),
        ("backup.tar", None, ("archives", "other", "DigitalDocument")),
        # Software: installer vs package split
        ("installer.dmg", None, ("software", "installers", "SoftwareApplication")),
        ("setup.exe", None, ("software", "installers", "SoftwareApplication")),
        ("MyApp.app", None, ("software", "installers", "SoftwareApplication")),
        ("pkg.deb", None, ("software", "packages", "SoftwareApplication")),
        ("pkg.rpm", None, ("software", "packages", "SoftwareApplication")),
        ("app.flatpak", None, ("software", "packages", "SoftwareApplication")),
        # Code
        ("script.py", None, ("code", "python", "SoftwareSourceCode")),
        ("app.ts", None, ("code", "typescript", "SoftwareSourceCode")),
        ("app.tsx", None, ("code", "typescript", "SoftwareSourceCode")),
        ("app.js", None, ("code", "javascript", "SoftwareSourceCode")),
        ("bundle.mjs", None, ("code", "javascript", "SoftwareSourceCode")),
        ("deploy.sh", None, ("code", "shell", "SoftwareSourceCode")),
        ("index.html", None, ("code", "web", "SoftwareSourceCode")),
        # Data
        ("data.json", None, ("data", "json", "Dataset")),
        ("data.csv", None, ("data", "csv", "Dataset")),
        ("config.yaml", None, ("data", "yaml", "Dataset")),
        ("feed.xml", None, ("data", "xml", "Dataset")),
        ("settings.ini", None, ("data", "config", "Dataset")),
        ("app.sqlite3", None, ("data", "databases", "Dataset")),
        # Fallback
        ("unknown.xyz", None, ("other", "other", "CreativeWork")),
        ("unknown.xyz", "application/octet-stream", ("other", "other", "CreativeWork")),
    ])
    def test_classification_table(self, path, mime, expected):
        assert classify_by_mime(Path(f"/downloads/{path}"), mime) == expected

    def test_pdf_in_research_directory(self):
        result = classify_by_mime(Path("/home/research/paper.pdf"), "application/pdf")
        assert result == ("research", "papers", "ScholarlyArticle")

    def test_markdown_in_research_directory(self):
        result = classify_by_mime(Path("/home/research/notes.md"), None)
        assert result == ("research", "notes", "Article")

    def test_music_keyword_in_filename(self):
        result = classify_by_mime(Path("/audio/music_theme.wav"), "audio/wav")
        assert result == ("media", "music", "MusicRecording")
