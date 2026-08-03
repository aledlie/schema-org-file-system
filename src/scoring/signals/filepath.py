"""FilepathSignal — extension/filename → Technical/* path mapping (§4 row 14).

Extracted from ``ContentOrganizer.classify_by_filepath`` /
``extract_project_name`` plus the ``filepath_patterns`` table built in its
``__init__`` (now the :data:`FILEPATH_PATTERNS` module constant; the organizer
takes a per-instance ``dict(FILEPATH_PATTERNS)`` copy so instance mutation
stays safe). :func:`classify_filepath_match` reproduces the legacy lookup
exactly and additionally reports the extracted project name;
:func:`classify_filepath` / :func:`extract_project_name` are the spec-shaped
wrappers the organizer delegates to.

Behavior divergences from the legacy chain (by design):

- The legacy chain runs this tier after game assets and before media, winning
  by order; the signal competes by weight (``W_PATH`` = 0.6), so e.g. a
  ``.zip`` named "Photos" loses to content signals instead of being routed by
  extension (§4 row 14).
- The legacy method called ``self.extract_project_name`` (an override point);
  the pure :func:`classify_filepath` calls the module-level function, so only
  the ``filepath_patterns`` instance attribute remains a subclass
  customization point (no in-repo subclass overrode the method).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import FileContext

from pathlib import Path
from typing import Dict, List, Mapping, NamedTuple, Optional, cast

from ..types import CategoryScore
from ..weights import W_PATH

# Extension/filename lookups are precise for code artifacts; the low W_PATH
# prior keeps content signals in charge for content-bearing formats.
FILEPATH_MATCH_CONFIDENCE = 0.9

# ``get_destination_path`` treats this category specially: the subcategory
# carries the full relative path (e.g. "Technical/Python/MyProject").
FILEPATH_CATEGORY = "filepath"

# Signal-local evidence key.
EVIDENCE_PROJECT_NAME = "project_name"

# Filepath-based classification table (moved verbatim from
# ContentOrganizer.__init__). Keys are exact filenames, extensions, or double
# extensions; values are relative destination paths.
FILEPATH_PATTERNS: Dict[str, str] = {
    # Log files
    ".log": "Technical/Logs",
    ".log.gz": "Technical/Logs",
    ".out": "Technical/Logs",
    # Python
    ".py": "Technical/Python",
    ".pyc": "Technical/Python/Compiled",
    ".pyw": "Technical/Python",
    ".pyx": "Technical/Python",
    ".pyd": "Technical/Python",
    # JavaScript/TypeScript
    ".js": "Technical/JavaScript",
    ".jsx": "Technical/JavaScript",
    ".mjs": "Technical/JavaScript",
    ".cjs": "Technical/JavaScript",
    ".ts": "Technical/TypeScript",
    ".tsx": "Technical/TypeScript",
    # Web
    ".html": "Technical/Web",
    ".htm": "Technical/Web",
    ".css": "Technical/Web",
    ".scss": "Technical/Web",
    ".sass": "Technical/Web",
    ".less": "Technical/Web",
    # Shell scripts
    ".sh": "Technical/Shell",
    ".bash": "Technical/Shell",
    ".zsh": "Technical/Shell",
    ".fish": "Technical/Shell",
    # Config files
    ".json": "Technical/Config",
    ".yaml": "Technical/Config",
    ".yml": "Technical/Config",
    ".toml": "Technical/Config",
    ".ini": "Technical/Config",
    ".conf": "Technical/Config",
    ".config": "Technical/Config",
    ".env": "Technical/Config",
    # Database
    ".sql": "Technical/Database",
    ".db": "Technical/Database",
    ".sqlite": "Technical/Database",
    ".sqlite3": "Technical/Database",
    # Java/Kotlin
    ".java": "Technical/Java",
    ".class": "Technical/Java/Compiled",
    ".jar": "Technical/Java/Archives",
    ".kt": "Technical/Kotlin",
    ".kts": "Technical/Kotlin",
    # C/C++
    ".c": "Technical/C",
    ".cpp": "Technical/C++",
    ".cc": "Technical/C++",
    ".cxx": "Technical/C++",
    ".h": "Technical/C/Headers",
    ".hpp": "Technical/C++/Headers",
    # Go
    ".go": "Technical/Go",
    # Rust
    ".rs": "Technical/Rust",
    # Ruby
    ".rb": "Technical/Ruby",
    ".rake": "Technical/Ruby",
    # PHP
    ".php": "Technical/PHP",
    # Swift
    ".swift": "Technical/Swift",
    # Markdown and docs
    ".md": "Technical/Documentation",
    ".markdown": "Technical/Documentation",
    ".rst": "Technical/Documentation",
    ".adoc": "Technical/Documentation",
    # Version control
    ".gitignore": "Technical/VersionControl",
    ".gitattributes": "Technical/VersionControl",
    # Build/Package files
    "Makefile": "Technical/Build",
    "Dockerfile": "Technical/Build",
    "docker-compose.yml": "Technical/Build",
    "package.json": "Technical/Build",
    "package-lock.json": "Technical/Build",
    "yarn.lock": "Technical/Build",
    "Cargo.toml": "Technical/Build",
    "go.mod": "Technical/Build",
    "requirements.txt": "Technical/Build",
    "Pipfile": "Technical/Build",
    "pyproject.toml": "Technical/Build",
}

# Common non-project directories skipped during project-name extraction
# (moved verbatim from the legacy extract_project_name).
PROJECT_SKIP_DIRS = frozenset(
    {
        "src",
        "lib",
        "bin",
        "dist",
        "build",
        "out",
        "target",
        "node_modules",
        "venv",
        ".venv",
        "env",
        "__pycache__",
        "scripts",
        "tests",
        "test",
        "docs",
        "doc",
        "examples",
        "static",
        "public",
        "assets",
        "resources",
        "config",
        "home",
        "users",
        "documents",
        "downloads",
        "desktop",
        "code",
        "projects",
        "dev",
        "work",
        "repos",
        "git",
    }
)

# Parents that introduce per-user directories: /Users/<name> or /home/<name>.
USER_CONTAINER_DIRS = frozenset({"users", "home"})

# Path segments that are filesystem roots or empty (never project names).
ROOT_PATH_SEGMENTS = ("/", "\\", "")

HIDDEN_DIR_PREFIX = "."

# Number of trailing suffixes forming a recognized double extension (.log.gz).
DOUBLE_EXTENSION_PARTS = 2


def extract_project_name(path: Path) -> Optional[str]:
    """Extract a likely project-directory name from a file path.

    Reproduces ``ContentOrganizer.extract_project_name`` exactly: walks the
    parent directories backwards, skipping common non-project directories,
    hidden directories, filesystem roots, the running user's home-directory
    name (resolved at call time), and any direct child of /Users or /home.
    Returns the first remaining segment with original case, or ``None``.
    """
    # Skip the running user's home-directory name so files organized straight
    # out of ~/Downloads don't produce paths like Technical/Python/<username>.
    home_name = Path.home().name.lower()

    parts = path.parts

    # Look backwards from the file for a likely project directory
    for i in range(len(parts) - 2, -1, -1):  # Skip the filename itself
        dir_name = parts[i].lower()

        if dir_name in PROJECT_SKIP_DIRS:
            continue

        if dir_name.startswith(HIDDEN_DIR_PREFIX):
            continue

        if parts[i] in ROOT_PATH_SEGMENTS:
            continue

        if dir_name == home_name:
            continue

        # Skip any direct child of /Users or /home (other user directories)
        if i > 0 and parts[i - 1].lower() in USER_CONTAINER_DIRS:
            continue

        # Found a likely project directory — original case preserved
        return cast(Optional[str], parts[i])

    return None


class FilepathMatch(NamedTuple):
    """A filepath classification plus the project name it embedded (if any)."""

    path: str
    project_name: Optional[str]


def classify_filepath_match(path: Path, patterns: Mapping[str, str]) -> Optional[FilepathMatch]:
    """Classify a file by filepath patterns, reporting the project name.

    Reproduces ``ContentOrganizer.classify_by_filepath`` exactly: exact
    filename matches first, then extension (with project-name subdirectory),
    then double extensions (e.g. ``.log.gz``).
    """
    filename = path.name
    if filename in patterns:
        return FilepathMatch(patterns[filename], None)

    ext = path.suffix.lower()
    if ext in patterns:
        base_path = patterns[ext]
        project_name = extract_project_name(path)
        if project_name:
            # Add project subdirectory (e.g., Technical/Python/MyProject)
            return FilepathMatch(f"{base_path}/{project_name}", project_name)
        return FilepathMatch(base_path, None)

    if len(path.suffixes) >= DOUBLE_EXTENSION_PARTS:
        double_ext = "".join(path.suffixes[-DOUBLE_EXTENSION_PARTS:]).lower()
        if double_ext in patterns:
            return FilepathMatch(patterns[double_ext], None)

    return None


def classify_filepath(path: Path, patterns: Mapping[str, str]) -> Optional[str]:
    """Legacy-shaped wrapper: the category path string or ``None``."""
    match = classify_filepath_match(path, patterns)
    return match.path if match is not None else None


class FilepathSignal:
    """Extension/filename lookup emitting the special ``filepath`` category."""

    name = "filepath"
    weight = W_PATH
    cost_tier = "cheap"

    def __init__(self, patterns: Optional[Mapping[str, str]] = None) -> None:
        self._patterns: Dict[str, str] = dict(FILEPATH_PATTERNS if patterns is None else patterns)

    def applies_to(self, ctx: FileContext) -> bool:
        return True

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        match = classify_filepath_match(ctx.path, self._patterns)
        if match is None:
            return []
        evidence: Dict[str, str] = {}
        if match.project_name:
            evidence[EVIDENCE_PROJECT_NAME] = match.project_name
        return [
            CategoryScore(
                category=FILEPATH_CATEGORY,
                subcategory=match.path,
                confidence=FILEPATH_MATCH_CONFIDENCE,
                signal_name=self.name,
                evidence=evidence,
            )
        ]
