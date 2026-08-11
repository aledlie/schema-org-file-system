"""Shared constants for file organization scripts."""

# Suffixes browsers append to the asset folder created by "Save Page As".
# A page saved as "foo.html" yields a sibling "foo_files/" (locale-dependent)
# full of hashed-name JS/CSS/image cruft. Each asset is meaningless on its own,
# so organizers skip the whole sidecar folder during scanning rather than
# scatter it across categories. Compared against lowercased directory names.
SIDECAR_DIR_SUFFIXES = (
    "_files",       # en
    "-dateien",     # de
    "_archivos",    # es
    "_fichiers",    # fr
    "_bestanden",   # nl
)

# Image extensions -- used by 6+ scripts
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".bmp"}
IMAGE_EXTENSIONS_WIDE = IMAGE_EXTENSIONS | {".tiff", ".tif", ".svg", ".ico", ".raw"}

# Archive extensions -- single source shared by filename_classifier and mime_classifier
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".rar", ".7z", ".bz2"}

# Software extensions -- single source shared by filename_classifier (content mode)
# and mime_classifier (canonical format classifier). The installer/package split
# drives type-mode Software/Installers vs Software/Packages; their union is the set
# filename_classifier files under technical/software_packages.
SOFTWARE_INSTALLER_EXTENSIONS = {".dmg", ".pkg", ".exe", ".msi", ".app"}
SOFTWARE_PACKAGE_EXTENSIONS = {".deb", ".rpm", ".snap", ".flatpak", ".appimage"}

# Plain-text extensions the TextExtractor reads directly (UTF-8, capped at
# _MAX_TEXT_BYTES) so their *content* — not just their extension — drives
# classification. Limited to formats where content classifies better than the
# extension alone: prose/markup, personal-data text (vCard/calendar/email), and
# structured descriptors (Steam/Valve manifests, Linux launchers). Deliberately
# excludes source code and bulk data (.json/.xml/.yaml) — those already route to
# technical/data by extension and reading them only risks keyword false matches.
TEXT_EXTENSIONS = {
    ".txt", ".text", ".md", ".markdown", ".mdown", ".mkd", ".csv",
    ".rst", ".adoc", ".asciidoc", ".org", ".tex", ".log", ".vtt", ".srt",
    ".vcf", ".ics", ".eml",
    ".mod", ".vdf", ".acf", ".desktop",
}

# CLIP content labels -- canonical list used by analyze_renamed_files, organize_by_content, etc.
CLIP_CONTENT_LABELS = [
    "a landscape or nature scene",
    "a cityscape or urban scene",
    "an interior room",
    "food or a meal",
    "people or portrait",
    "an animal or pet",
    "a document or text",
    "artwork or illustration",
    "a product or object",
    "a vehicle or transportation",
    "screenshot: a computer screen",
    "screenshot: a mobile phone",
    "a building or architecture",
    "an event or celebration",
    "sports or physical activity",
    "a game or entertainment",
    "a diagram or chart",
    "a meme or social media image",
    "a logo or brand image",
    "abstract art or pattern",
]

# CLIP content labels that indicate a text-bearing image — one where OCR is
# worth running. Used by the optional CLIP-based OCR gate
# (FileContext.ensure_ocr, --ocr-clip-gate): when the summed CLIP probability
# over these labels falls below the gate, OCR is skipped because the image is
# almost certainly a text-free photo. Keep in sync with CLIP_CONTENT_LABELS.
CLIP_TEXT_BEARING_LABELS = frozenset(
    {
        "a document or text",
        "screenshot: a computer screen",
        "screenshot: a mobile phone",
        "a diagram or chart",
        "a meme or social media image",
        "a logo or brand image",
    }
)

# Labels that CLIP handles better without "a photo of" prefix.
_NO_PHOTO_PREFIX = {
    "a diagram or chart",
    "a meme or social media image",
    "a logo or brand image",
    "abstract art or pattern",
}


def _make_clip_prompt(label: str) -> str:
    """Convert a CLIP_CONTENT_LABELS entry to a full CLIP text prompt."""
    if label.startswith("screenshot: "):
        return "a screenshot of " + label[len("screenshot: ") :]
    if label in _NO_PHOTO_PREFIX:
        return label
    return "a photo of " + label


# CLIP prompts derived from CLIP_CONTENT_LABELS — do not edit separately.
# Callers that need raw prompts should use this list; callers that need
# canonical label keys should strip prefixes or use CLIP_CONTENT_LABELS directly.
CLIP_CATEGORY_PROMPTS: list[str] = [_make_clip_prompt(lbl) for lbl in CLIP_CONTENT_LABELS]

# Content type -> Schema.org type mapping (from organize_by_content.py)
CONTENT_TO_SCHEMA: dict[str, tuple[str, str]] = {
    "an animal or pet": ("ImageObject", "Animal"),
    "a meme or social media image": ("CreativeWork", "SocialMediaPosting"),
    "a logo or brand image": ("CreativeWork", "Brand"),
    "a game or entertainment": ("CreativeWork", "GameAsset"),
    "artwork or illustration": ("CreativeWork", "VisualArtwork"),
    "a document or text": ("DigitalDocument", "Document"),
    "screenshot: a computer screen": ("ImageObject", "Screenshot"),
    "screenshot: a mobile phone": ("ImageObject", "MobileScreenshot"),
    "a diagram or chart": ("CreativeWork", "Diagram"),
    "people or portrait": ("ImageObject", "Portrait"),
    "a product or object": ("Product", "ProductImage"),
    "an interior room": ("RealEstateListing", "Interior"),
    "food or a meal": ("ImageObject", "FoodPhoto"),
    "a landscape or nature scene": ("ImageObject", "Landscape"),
    "a cityscape or urban scene": ("ImageObject", "Cityscape"),
    "a vehicle or transportation": ("ImageObject", "Vehicle"),
    "a building or architecture": ("ImageObject", "Architecture"),
    "an event or celebration": ("ImageObject", "Event"),
    "sports or physical activity": ("ImageObject", "Sports"),
    "abstract art or pattern": ("CreativeWork", "AbstractArt"),
}

# Content type -> existing folder path (from organize_to_existing.py)
CONTENT_TO_EXISTING_FOLDER: dict[str, str] = {
    "an animal or pet": "ImageObject/Photograph",
    "a meme or social media image": "CreativeWork/SocialMediaPosting",
    "a logo or brand image": "CreativeWork/Brand",
    "a game or entertainment": "CreativeWork/GameAsset/Sprites",
    "artwork or illustration": "CreativeWork/VisualArtwork",
    "a document or text": "DigitalDocument/Document",
    "screenshot: a computer screen": "ImageObject/Screenshot",
    "screenshot: a mobile phone": "ImageObject/Screenshot",
    "a diagram or chart": "CreativeWork/Diagram",
    "people or portrait": "ImageObject/Photograph",
    "a product or object": "Product",
    "an interior room": "RealEstateListing",
    "food or a meal": "ImageObject/Photograph",
    "a landscape or nature scene": "ImageObject/Photograph",
    "a cityscape or urban scene": "ImageObject/Photograph",
    "a vehicle or transportation": "ImageObject/Photograph",
    "a building or architecture": "ImageObject/Photograph",
    "an event or celebration": "ImageObject/Photograph",
    "sports or physical activity": "ImageObject/Photograph",
    "abstract art or pattern": "CreativeWork/VisualArtwork",
}

# --- Enhanced image classification for weak results ---
# Maps CLIP content labels to organizer (category, subcategory) tuples.
# Used by enhance_weak_image_classification() to rescue photos_other / uncategorized images.
CLIP_LABEL_TO_ORGANIZER: dict[str, tuple[str, str]] = {
    "a landscape or nature scene": ("media", "photos_nature"),
    "an animal or pet": ("media", "photos_nature"),
    "a cityscape or urban scene": ("media", "photos_travel"),
    "a building or architecture": ("media", "photos_travel"),
    "food or a meal": ("media", "photos_lifestyle"),
    "sports or physical activity": ("media", "photos_lifestyle"),
    "people or portrait": ("media", "photos_social"),
    "screenshot: a computer screen": ("media", "photos_screenshots_other"),
    "screenshot: a mobile phone": ("media", "photos_screenshots_other"),
    "a document or text": ("media", "photos_documents"),
    "a diagram or chart": ("technical", "data_visualization"),
    "a logo or brand image": ("creative", "branding"),
    "artwork or illustration": ("creative", "design"),
    "abstract art or pattern": ("creative", "design"),
    "a game or entertainment": ("game_assets", "sprites"),
    "an interior room": ("property_management", "other"),
    "an event or celebration": ("media", "photos_events"),
    "a product or object": ("media", "photos_products"),
    "a vehicle or transportation": ("media", "photos_other"),
    "a meme or social media image": ("media", "photos_social"),
}

# easyocr language configuration
# The easyocr Reader is built once per process with a fixed language list.
# Override via OCR_EASYOCR_LANGS env var (comma-separated ISO 639-1 codes).
# Each additional language downloads ~50–100 MB of recognition weights and
# increases model load time. See ocr_easyocr._resolve_languages().
EASYOCR_DEFAULT_LANGUAGE = "en"

CLIP_BATCH_SIZE: int = 32

# Canonical CLIP confidence thresholds (single source of truth).
CLIP_OCR_FALLBACK_THRESHOLD = 0.10  # min CLIP confidence before OCR fallback
CLIP_REFINEMENT_MIN_CONFIDENCE = 0.15  # min confidence to attempt refinement
CLIP_REFINEMENT_ACCEPT_CONFIDENCE = 0.30  # min confidence to accept refinement

# Minimum top-1/top-2 ratio for a CLIP label to be trusted as a *filename*.
# Absolute confidence cannot serve here: scores are a softmax over raw cosine
# similarities with no logit scaling, so they sit just above the uniform floor
# (94-label photo vocab: floor 1.064%, winners 1.13-1.16%) and every label
# clears or misses an absolute gate together. The *relative* separation does
# discriminate -- measured on 8 hand-labelled Downloads photos, correct labels
# scored 1.0154-1.0376 and wrong/marginal ones 1.0020-1.0088, so 1.012 sits in
# the gap and separated all 8. Only applied per-profile via
# RenamerProfile.min_label_margin: the screenshot vocab puts 75% of a 20-file
# sample below this ratio while still agreeing with their filed folders, so
# enabling it there needs its own labelled eval first.
CLIP_MIN_LABEL_MARGIN_RATIO = 1.012

CLIP_ENHANCE_THRESHOLD = CLIP_REFINEMENT_MIN_CONFIDENCE  # min confidence to use CLIP result
CLIP_ENHANCE_HIGH_THRESHOLD = CLIP_REFINEMENT_ACCEPT_CONFIDENCE  # confidence to skip OCR fallback

# Content type -> short abbreviation (from add_content_descriptions.py)
CONTENT_ABBREVIATIONS: dict[str, str] = {
    "an animal or pet": "pet",
    "a meme or social media image": "meme",
    "a logo or brand image": "logo",
    "a game or entertainment": "game",
    "artwork or illustration": "art",
    "a document or text": "doc",
    "screenshot: a computer screen": "screenshot",
    "screenshot: a mobile phone": "mobile",
    "a diagram or chart": "chart",
    "people or portrait": "portrait",
    "a product or object": "product",
    "an interior room": "interior",
    "food or a meal": "food",
    "a landscape or nature scene": "landscape",
    "a cityscape or urban scene": "cityscape",
    "a vehicle or transportation": "vehicle",
    "a building or architecture": "building",
    "an event or celebration": "event",
    "sports or physical activity": "sports",
    "abstract art or pattern": "abstract",
}

# Game asset keywords -- consolidated from file_organizer.py, evaluate_model.py, etc.
GAME_SPRITE_KEYWORDS = [
    "frame",
    "leg",
    "arm",
    "head",
    "torso",
    "wing",
    "tail",
    "face",
    "hand",
    "wall",
    "floor",
    "door",
    "tree",
    "rock",
    "grass",
    "sprite",
    "sword",
    "shield",
    "armor",
    "potion",
    "scroll",
    "coin",
    "gem",
    "item",
    "tile",
    "character",
    "enemy",
    "npc",
    "player",
    "walk",
    "run",
    "idle",
    "attack",
    "hurt",
    "dead",
    "angry",
    "happy",
    "sad",
    "shoulder",
    "body",
    "feet",
    "hair",
    "eye",
    "mouth",
    "foot",
    "ceiling",
    "stairs",
    "helmet",
    "boot",
    "glove",
    "wand",
    "staff",
    "ring",
    "amulet",
    "monster",
    "hero",
    "hud",
    "particle",
    "effect",
    "explosion",
    "smoke",
    "blood",
    "btn",
    "talent",
    "texture",
    "2h_axe",
    "2h_hammer",
    "1h_sword",
    "1h_axe",
    "crossbow",
    "assassins_deed",
    "atonement",
    "backstab",
    "cleave",
    "arrow_v",
    "arrow_h",
    "_grey",
    "_gray",
    "_disabled",
    "_hover",
    "_active",
    "_pressed",
    "rug",
    "glow",
    "mee",
    "gelf",
    "salamander",
    "blob",
    "bubble",
    "lever",
    "spine",
    "mandible",
    "pupils",
    "beard",
    "bling",
    "hiero",
    "mustache",
    "scar",
    "tattoo",
    "earring",
    "necklace",
    "bracelet",
    "glasses",
    "mask",
    "hood",
    "water",
    "lava",
    "crystal",
    "ore",
    "metal",
    "wood",
    "descend",
    "ascend",
    "mad_carpenter",
    "no_more",
    "bedroom",
    "alive",
    "sleeping",
    "female",
    "male",
    "silver",
    "gold",
    "bronze",
    "iron",
    "steel",
    "mithril",
    "hills",
    "road",
    "path",
    "gate",
    "fence",
    "tentacle",
    "shadow",
    "altar",
    "dungeon",
    "throne",
    "torch",
    "cloak",
    "champion",
    "curse",
    "decal",
    "column",
    "banner",
    "sewer",
    "statue",
    "pillar",
    "orc",
    "dwarf",
    "elf",
    "hurth",
    "helf",
    "troll",
    "goblin",
    "fire",
    "ice",
    "sand",
    "mount",
    "tmount",
    "deco",
    "entrance",
    "shoulders",
    "stunned",
    "poisoned",
    "blind",
    "deaf",
    "slowed",
    "levitating",
    "hungry",
    "strained",
    "psf",
    "inventory",
    "longbow",
    "dagger",
    "mace",
    "flail",
    "spear",
    "halberd",
    "scimitar",
    "smite",
    "fireball",
    "lightning",
    "heal",
    "buff",
    "debuff",
    "aura",
    "_selected",
    "_normal",
    "_highlight",
    "_glow",
    "_dark",
    "_light",
]

# Single source of truth (also consumed by ContentOrganizer). Union of the
# historical script and ContentOrganizer lists; uses "spellcast" rather than
# "cast" so that podcast/broadcast filenames do not match.
GAME_AUDIO_KEYWORDS = [
    "bolt",
    "spell",
    "magic",
    "sword",
    "dagger",
    "arrow",
    "attack",
    "damage",
    "lightning",
    "fire",
    "ice",
    "acid",
    "poison",
    "heal",
    "summon",
    "dispel",
    "door",
    "chest",
    "coin",
    "pickup",
    "unlock",
    "lock",
    "fiddle",
    "lute",
    "mandoline",
    "glockenspiel",
    "sfx",
    "sound",
    "effect",
    "ambient",
    "spellcast",
    "chirp",
    "crossbow",
    "bow",
    "potion",
    "explosion",
    "blast",
    "petrification",
    "neutralize",
    "slow",
    "darkness",
    "achievement",
    "quest",
    "hit",
    "death",
    "footstep",
    "jump",
    "land",
    "monster",
    "creature",
    "enemy",
    "boss",
    "battle",
    "combat",
    "starving",
    "hunger",
    "thirst",
    "eat",
    "drink",
    "sleep",
    "instrument",
    "identify",
    "greater",
    "mental",
]

# Single source of truth (also consumed by ContentOrganizer). Union of the
# historical script and ContentOrganizer lists.
GAME_MUSIC_KEYWORDS = [
    "battle",
    "boss",
    "dungeon",
    "castle",
    "forest",
    "town",
    "cave",
    "temple",
    "victory",
    "defeat",
    "chaos",
    "hope",
    "despair",
    "triumph",
    "mysterious",
    "drakalor",
    "altar",
    "dwarven",
    "elven",
    "clockwork",
    "theme",
    "bgm",
    "soundtrack",
    "music",
    "loop",
    "village",
    "ruins",
    "mountain",
    "ocean",
    "desert",
    "snow",
    "menu",
    "credits",
    "intro",
    "outro",
    "dark",
    "light",
    "epic",
    "calm",
    "peaceful",
    "tension",
    "march",
    "symphony",
    "monotony",
    "lawful",
    "chaotic",
    "neutral",
    "alignment",
    "orcish",
    "halls",
    "abandon",
    "corrupting",
    "breeze",
    "knowledge",
    "oddisey",
    "final",
    "welcome",
]

# Single source of truth (also consumed by ContentOrganizer).
GAME_FONT_KEYWORDS = [
    "broguefont",
    "gamefont",
    "pixelfont",
    "bitfont",
    "font_",
    "_font",
    "fontsheet",
    "font_atlas",
    "fontatlas",
    "charset",
    "glyphs",
    "tilefont",
    "asciifont",
    "ascii_font",
]

# Filename patterns for detection (from data_preprocessing.py, evaluate_model.py, etc.)
SCREENSHOT_PATTERNS = [
    r"screenshot",
    r"screen\s*shot",
    r"screen_\d+",
    r"capture",
    r"snip",
]

DOCUMENT_PATTERNS = [
    r"invoice",
    r"receipt",
    r"contract",
    r"report",
    r"statement",
    r"tax",
    r"resume",
    r"cv",
    r"letter",
]

# Camera-vendor prefix patterns.  Single-homed here so both
# filename_utils._GENERIC_FILENAME_PATTERNS (case-folds stem before matching)
# and name_organizer.py camera_photos (uses re.IGNORECASE) stay in sync when
# new device vendors appear.  All patterns are lowercase anchored-start regexes.
CAMERA_VENDOR_PREFIX_PATTERNS: tuple[str, ...] = (
    r"^img_\d+",   # IMG_1234 (Apple / Android camera roll)
    r"^pxl_\d+",   # PXL_20250425 (Google Pixel)
    r"^dsc_?\d+",  # DSC_1234 / DSC1234 (Sony / Nikon; optional underscore)
    r"^dcim_\d+",  # DCIM_1234 (generic DCIM roll)
)
