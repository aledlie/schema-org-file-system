"""Unit tests for scripts/file_organizer_by_type.py.

FileTypeOrganizer.get_category_for_file resolves a destination folder from
name/structure pre-checks plus the canonical classify_by_mime format
classifier mapped through CATEGORY_PATHS. These assertions pin the folder each
file type lands in, including the type-mode taxonomy adopted when type_mapping
was retired.
"""

import sys
from pathlib import Path

import pytest

# scripts/ on sys.path so the module (and its `shared` imports) resolve.
_SCRIPTS = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from file_organizer_by_type import FileTypeOrganizer  # noqa: E402


@pytest.fixture(scope="module")
def organizer():
    return FileTypeOrganizer(base_path="/tmp/does-not-matter")


@pytest.mark.parametrize(
    "name,expected",
    [
        # Name/structure pre-checks
        ("Screenshot 2026-01-01.png", "Images/Photos/Screenshots"),
        ("frame_01.png", "Images/Photos/GameAssets"),
        ("America", "Data/Timezones"),  # extension-less single token
        # Images: jpg/jpeg/heic photos, rest graphics
        ("vacation.jpg", "Images/Photos"),
        ("portrait.heic", "Images/Photos"),
        ("diagram.png", "Images/Graphics"),
        ("vector.svg", "Images/Graphics"),
        # Documents
        ("report.pdf", "Documents/PDFs"),
        ("letter.docx", "Documents/Word"),
        ("budget.xlsx", "Documents/Spreadsheets"),
        ("rows.csv", "Data/CSV"),
        ("deck.pptx", "Documents/Presentations"),
        ("notes.txt", "Documents/Text"),
        ("README.md", "Documents/Markdown"),
        # Code
        ("script.py", "Code/Python"),
        ("app.ts", "Code/TypeScript"),
        ("app.js", "Code/JavaScript"),
        ("deploy.sh", "Code/Shell"),
        ("index.html", "Code/Web"),
        # Data
        ("data.json", "Data/JSON"),
        ("config.yaml", "Data/YAML"),
        ("feed.xml", "Data/XML"),
        ("settings.ini", "Data/Config"),
        ("app.sqlite3", "Data/Databases"),
        # Media
        ("track.mp3", "Media/Music"),
        ("voicemail.wav", "Media/Audio"),
        ("clip.mp4", "Media/Videos"),
        # Archives
        ("bundle.zip", "Archives/Compressed"),
        ("backup.tar", "Archives/Other"),
        # Fonts
        ("Roboto.ttf", "CreativeWork/Fonts/TrueType"),
        ("Roboto.woff2", "CreativeWork/Fonts/Web"),
        # Software: installer vs package split
        ("installer.dmg", "Software/Installers"),
        ("MyApp.app", "Software/Installers"),
        ("setup.msi", "Software/Installers"),
        ("pkg.deb", "Software/Packages"),
        ("app.flatpak", "Software/Packages"),
        # Miscellaneous known formats -> Other; truly-unknown -> Uncategorized
        ("template.tpl", "Other"),
        ("notes.rst", "Other"),
        ("mystery.xyz", "Uncategorized"),
    ],
)
def test_get_category_for_file(organizer, name, expected):
    assert organizer.get_category_for_file(Path("/src") / name) == expected
