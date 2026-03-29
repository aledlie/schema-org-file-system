"""Shared constants for file organization scripts."""

# Image extensions -- used by 6+ scripts
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.gif', '.bmp'}
IMAGE_EXTENSIONS_WIDE = IMAGE_EXTENSIONS | {'.tiff', '.tif', '.svg', '.ico', '.raw'}

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
    return "a screenshot of " + label[len("screenshot: "):]
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
  "an animal or pet":            ("media", "photos_nature"),
  "a cityscape or urban scene":  ("media", "photos_travel"),
  "a building or architecture":  ("media", "photos_travel"),
  "food or a meal":              ("media", "photos_lifestyle"),
  "sports or physical activity": ("media", "photos_lifestyle"),
  "people or portrait":          ("media", "photos_social"),
  "screenshot: a computer screen": ("media", "photos_screenshots_other"),
  "screenshot: a mobile phone":  ("media", "photos_screenshots_other"),
  "a document or text":          ("media", "photos_documents"),
  "a diagram or chart":          ("technical", "data_visualization"),
  "a logo or brand image":       ("creative", "branding"),
  "artwork or illustration":     ("creative", "design"),
  "abstract art or pattern":     ("creative", "design"),
  "a game or entertainment":     ("game_assets", "sprites"),
  "an interior room":            ("property_management", "other"),
  "an event or celebration":     ("media", "photos_events"),
  "a product or object":         ("media", "photos_products"),
  "a vehicle or transportation": ("media", "photos_other"),
  "a meme or social media image": ("media", "photos_social"),
}

CLIP_BATCH_SIZE: int = 32
CLIP_ENHANCE_THRESHOLD = 0.15      # min confidence to use CLIP result
CLIP_ENHANCE_HIGH_THRESHOLD = 0.30  # confidence to skip OCR fallback

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
  'frame', 'leg', 'arm', 'head', 'torso', 'wing', 'tail', 'face', 'hand',
  'wall', 'floor', 'door', 'window', 'tree', 'rock', 'grass', 'sprite',
  'sword', 'shield', 'armor', 'potion', 'scroll', 'coin', 'gem', 'item',
  'icon', 'button', 'menu', 'cursor', 'bar', 'container', 'tile',
  'character', 'enemy', 'npc', 'player', 'walk', 'run', 'idle', 'attack',
  'hurt', 'dead', 'angry', 'happy', 'sad', 'shoulder', 'body', 'feet',
  'hair', 'eye', 'mouth', 'foot', 'ceiling', 'stairs', 'helmet', 'boot',
  'glove', 'wand', 'staff', 'ring', 'amulet', 'monster', 'hero',
  'ui', 'hud', 'particle', 'effect', 'explosion', 'smoke', 'blood',
  'corner', 'edge', 'border', 'btn', 'talent', 'segment', 'texture',
  '2h_axe', '2h_hammer', '1h_sword', '1h_axe', 'crossbow',
  'assassins_deed', 'atonement', 'backstab', 'cleave',
  'arrow_v', 'arrow_h', 'checkbox', 'radio', 'toggle', 'add',
  '_grey', '_gray', '_disabled', '_hover', '_active', '_pressed',
]

GAME_AUDIO_KEYWORDS = [
  'bolt', 'spell', 'magic', 'sword', 'dagger', 'arrow', 'attack', 'damage',
  'lightning', 'fire', 'ice', 'acid', 'poison', 'heal', 'summon', 'dispel',
  'door', 'chest', 'coin', 'pickup', 'unlock', 'lock', 'fiddle', 'lute',
  'mandoline', 'glockenspiel', 'sfx', 'sound', 'effect', 'ambient',
]

GAME_MUSIC_KEYWORDS = [
  'battle', 'boss', 'dungeon', 'castle', 'forest', 'town', 'cave', 'temple',
  'victory', 'defeat', 'chaos', 'hope', 'despair', 'triumph', 'mysterious',
  'drakalor', 'altar', 'dwarven', 'elven', 'clockwork', 'theme', 'bgm',
  'soundtrack', 'music', 'loop',
]

GAME_FONT_KEYWORDS = [
  'broguefont', 'gamefont', 'pixelfont', 'bitfont', 'font_',
  '_font', 'fontsheet', 'font_atlas', 'fontatlas', 'charset',
  'glyphs', 'tilefont', 'asciifont', 'ascii_font',
]

# Filename patterns for detection (from data_preprocessing.py, evaluate_model.py, etc.)
SCREENSHOT_PATTERNS = [
  r'screenshot',
  r'screen\s*shot',
  r'screen_\d+',
  r'capture',
  r'snip',
]

DOCUMENT_PATTERNS = [
  r'invoice', r'receipt', r'contract',
  r'report', r'statement', r'tax',
  r'resume', r'cv', r'letter',
]
