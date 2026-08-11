#!/usr/bin/env python3
"""
Image Content Analyzer - Generate CSV report of all detected objects in images.

Uses CLIP to analyze images and outputs unique objects with IDs, categories,
descriptions, and confidence scores.
"""

import argparse
import csv
import uuid
from pathlib import Path
from typing import List, Tuple, Dict

from shared.clip_utils import CLIPClassifier, CLIP_AVAILABLE

# Namespace for UUID v5 generation (deterministic IDs)
OBJECT_NAMESPACE = uuid.UUID("a3f5b8c2-1d4e-4f6a-9b8c-7d2e3f4a5b6c")


def generate_object_id(category: str) -> str:
    """Generate deterministic UUID v5 for an object category."""
    return str(uuid.uuid5(OBJECT_NAMESPACE, category.lower()))


# Object categories with descriptions (excluding room types)
OBJECT_CATALOG: Dict[str, Dict] = {
    # Seating
    "sofa": {
        "category": "Furniture/Seating",
        "description": "Upholstered multi-seat couch for sitting",
    },
    "couch": {
        "category": "Furniture/Seating",
        "description": "Padded seating furniture for multiple people",
    },
    "sectional": {
        "category": "Furniture/Seating",
        "description": "L-shaped or modular sofa configuration",
    },
    "chair": {
        "category": "Furniture/Seating",
        "description": "Single-person seating with back support",
    },
    "armchair": {"category": "Furniture/Seating", "description": "Upholstered chair with armrests"},
    "recliner": {
        "category": "Furniture/Seating",
        "description": "Chair with adjustable back and footrest",
    },
    "ottoman": {"category": "Furniture/Seating", "description": "Padded footstool or low seat"},
    "bench": {"category": "Furniture/Seating", "description": "Long seat for multiple people"},
    # Tables
    "table": {
        "category": "Furniture/Tables",
        "description": "Flat-topped furniture piece with legs",
    },
    "coffee table": {
        "category": "Furniture/Tables",
        "description": "Low table for living room seating area",
    },
    "dining table": {"category": "Furniture/Tables", "description": "Table for eating meals"},
    "desk": {"category": "Furniture/Tables", "description": "Table for work or study with storage"},
    "nightstand": {"category": "Furniture/Tables", "description": "Small bedside table"},
    # Storage
    "bookshelf": {
        "category": "Furniture/Storage",
        "description": "Shelving unit for books and items",
    },
    "cabinet": {
        "category": "Furniture/Storage",
        "description": "Enclosed storage furniture with doors",
    },
    "dresser": {"category": "Furniture/Storage", "description": "Chest of drawers for clothing"},
    # Beds
    "bed": {"category": "Furniture/Beds", "description": "Furniture for sleeping"},
    # Lighting
    "lamp": {"category": "Lighting", "description": "Light fixture, typically portable"},
    "floor lamp": {"category": "Lighting", "description": "Tall standing lamp"},
    "arc lamp": {
        "category": "Lighting",
        "description": "Floor lamp with curved arm extending over seating",
    },
    # Textiles
    "rug": {"category": "Textiles/Floor", "description": "Fabric floor covering"},
    "carpet": {"category": "Textiles/Floor", "description": "Wall-to-wall floor covering"},
    "curtains": {"category": "Textiles/Window", "description": "Fabric window covering"},
    "throw blanket": {
        "category": "Textiles/Accessories",
        "description": "Decorative blanket draped on furniture",
    },
    "blanket": {"category": "Textiles/Accessories", "description": "Fabric covering for warmth"},
    "pillow": {
        "category": "Textiles/Accessories",
        "description": "Soft cushion for comfort or support",
    },
    "cushion": {
        "category": "Textiles/Accessories",
        "description": "Padded fabric accessory for seating",
    },
    # Decor
    "mirror": {"category": "Decor", "description": "Reflective glass surface"},
    "fireplace": {
        "category": "Decor/Heating",
        "description": "Built-in heating feature with hearth",
    },
    "plant": {"category": "Decor/Plants", "description": "Living greenery"},
    "houseplant": {"category": "Decor/Plants", "description": "Indoor potted plant"},
    "art": {"category": "Decor/Art", "description": "Artistic work or piece"},
    "painting": {"category": "Decor/Art", "description": "Artwork created with paint"},
    "photograph": {"category": "Decor/Art", "description": "Framed photographic image"},
    "sculpture": {"category": "Decor/Art", "description": "Three-dimensional artwork"},
    "drawing": {"category": "Decor/Art", "description": "Artwork created with pencil or pen"},
    "illustration": {"category": "Decor/Art", "description": "Drawn or digital artwork"},
    "poster": {"category": "Decor/Art", "description": "Printed artwork or advertisement"},
    "wall art": {"category": "Decor/Art", "description": "Decorative piece hung on wall"},
    "decoration": {"category": "Decor", "description": "Ornamental item"},
    # Electronics
    "television": {"category": "Electronics", "description": "Display screen for video content"},
    "computer": {"category": "Electronics", "description": "Desktop computing device"},
    "laptop": {"category": "Electronics", "description": "Portable computer"},
    "phone": {"category": "Electronics", "description": "Telephone device"},
    "smartphone": {"category": "Electronics", "description": "Mobile phone with touchscreen"},
    "tablet": {"category": "Electronics", "description": "Portable touchscreen device"},
    "camera": {"category": "Electronics", "description": "Device for capturing images"},
    "headphones": {"category": "Electronics", "description": "Audio listening device worn on head"},
    "speaker": {"category": "Electronics", "description": "Audio output device"},
    "electronics": {"category": "Electronics", "description": "Electronic device or gadget"},
    # Materials & Styles
    "leather furniture": {
        "category": "Materials",
        "description": "Furniture upholstered in leather",
    },
    "fabric furniture": {"category": "Materials", "description": "Furniture upholstered in fabric"},
    "wooden furniture": {
        "category": "Materials",
        "description": "Furniture made primarily of wood",
    },
    "modern style": {"category": "Style", "description": "Contemporary design aesthetic"},
    "traditional style": {"category": "Style", "description": "Classic or conventional design"},
    "minimalist style": {"category": "Style", "description": "Simple, uncluttered design approach"},
    "rustic style": {"category": "Style", "description": "Natural, countryside-inspired design"},
    "industrial style": {
        "category": "Style",
        "description": "Raw, factory-inspired design aesthetic",
    },
    # People
    "portrait": {"category": "People", "description": "Image focused on a person's face"},
    "selfie": {"category": "People", "description": "Self-portrait photograph"},
    "group photo": {"category": "People", "description": "Photograph of multiple people"},
    "family photo": {"category": "People", "description": "Photograph of family members"},
    "headshot": {
        "category": "People",
        "description": "Professional portrait of face and shoulders",
    },
    "person": {"category": "People", "description": "Human individual"},
    "people": {"category": "People", "description": "Multiple human individuals"},
    "crowd": {"category": "People", "description": "Large gathering of people"},
    "child": {"category": "People", "description": "Young person"},
    "baby": {"category": "People", "description": "Infant or very young child"},
    "elderly person": {"category": "People", "description": "Senior adult"},
    # Pets & Animals
    "dog": {"category": "Animals/Pets", "description": "Domestic canine"},
    "cat": {"category": "Animals/Pets", "description": "Domestic feline"},
    "bird": {"category": "Animals/Pets", "description": "Feathered animal"},
    "fish": {"category": "Animals/Pets", "description": "Aquatic animal"},
    "rabbit": {"category": "Animals/Pets", "description": "Long-eared mammal"},
    "hamster": {"category": "Animals/Pets", "description": "Small rodent pet"},
    "pet": {"category": "Animals/Pets", "description": "Domesticated animal companion"},
    "puppy": {"category": "Animals/Pets", "description": "Young dog"},
    "kitten": {"category": "Animals/Pets", "description": "Young cat"},
    "golden retriever": {
        "category": "Animals/Dogs",
        "description": "Large golden-coated dog breed",
    },
    "labrador": {"category": "Animals/Dogs", "description": "Popular retriever dog breed"},
    "german shepherd": {"category": "Animals/Dogs", "description": "Large working dog breed"},
    # Food & Drinks
    "food": {"category": "Food", "description": "Edible items"},
    "meal": {"category": "Food", "description": "Prepared food for eating"},
    "breakfast": {"category": "Food/Meals", "description": "Morning meal"},
    "lunch": {"category": "Food/Meals", "description": "Midday meal"},
    "dinner": {"category": "Food/Meals", "description": "Evening meal"},
    "dessert": {"category": "Food/Meals", "description": "Sweet course after meal"},
    "coffee": {"category": "Food/Drinks", "description": "Caffeinated beverage"},
    "tea": {"category": "Food/Drinks", "description": "Brewed leaf beverage"},
    "wine": {"category": "Food/Drinks", "description": "Fermented grape beverage"},
    "beer": {"category": "Food/Drinks", "description": "Fermented grain beverage"},
    "cocktail": {"category": "Food/Drinks", "description": "Mixed alcoholic drink"},
    "cooking": {"category": "Food/Activity", "description": "Food preparation activity"},
    "baking": {"category": "Food/Activity", "description": "Oven-based food preparation"},
    "kitchen appliance": {"category": "Appliances", "description": "Device for food preparation"},
    # Nature & Outdoors
    "landscape": {"category": "Nature/Scenery", "description": "Wide view of natural terrain"},
    "mountain": {"category": "Nature/Terrain", "description": "Large elevated landform"},
    "beach": {"category": "Nature/Water", "description": "Sandy shore by water"},
    "ocean": {"category": "Nature/Water", "description": "Large body of saltwater"},
    "sea": {"category": "Nature/Water", "description": "Large body of saltwater"},
    "forest": {"category": "Nature/Vegetation", "description": "Dense area of trees"},
    "trees": {"category": "Nature/Vegetation", "description": "Tall woody plants"},
    "flowers": {"category": "Nature/Vegetation", "description": "Flowering plants"},
    "park": {"category": "Nature/Outdoor", "description": "Public green space"},
    "lake": {"category": "Nature/Water", "description": "Inland body of water"},
    "river": {"category": "Nature/Water", "description": "Flowing body of water"},
    "waterfall": {"category": "Nature/Water", "description": "Falling water over rocks"},
    "sunset": {"category": "Nature/Sky", "description": "Evening sun descent"},
    "sunrise": {"category": "Nature/Sky", "description": "Morning sun appearance"},
    "sky": {"category": "Nature/Sky", "description": "Atmosphere above"},
    "clouds": {"category": "Nature/Sky", "description": "Water vapor formations in sky"},
    "snow": {"category": "Nature/Weather", "description": "Frozen precipitation"},
    "rain": {"category": "Nature/Weather", "description": "Water precipitation"},
    # Architecture & Buildings
    "building": {"category": "Architecture", "description": "Constructed structure"},
    "architecture": {"category": "Architecture", "description": "Building design or structure"},
    "house": {"category": "Architecture/Residential", "description": "Residential dwelling"},
    "apartment": {
        "category": "Architecture/Residential",
        "description": "Unit in multi-dwelling building",
    },
    "city": {"category": "Architecture/Urban", "description": "Large urban area"},
    "street": {"category": "Architecture/Urban", "description": "Public road in urban area"},
    "road": {
        "category": "Architecture/Infrastructure",
        "description": "Paved pathway for vehicles",
    },
    "bridge": {
        "category": "Architecture/Infrastructure",
        "description": "Structure spanning obstacle",
    },
    "landmark": {
        "category": "Architecture/Notable",
        "description": "Recognizable notable structure",
    },
    "monument": {"category": "Architecture/Notable", "description": "Commemorative structure"},
    "church": {"category": "Architecture/Religious", "description": "Christian place of worship"},
    "museum": {"category": "Architecture/Cultural", "description": "Building housing artifacts"},
    # Vehicles
    "car": {"category": "Vehicles/Auto", "description": "Passenger automobile"},
    "truck": {"category": "Vehicles/Auto", "description": "Large cargo vehicle"},
    "motorcycle": {"category": "Vehicles/Auto", "description": "Two-wheeled motor vehicle"},
    "bicycle": {"category": "Vehicles/Bike", "description": "Human-powered two-wheeled vehicle"},
    "bus": {"category": "Vehicles/Transit", "description": "Large passenger vehicle"},
    "train": {"category": "Vehicles/Transit", "description": "Rail-based vehicle"},
    "airplane": {"category": "Vehicles/Air", "description": "Fixed-wing aircraft"},
    "boat": {"category": "Vehicles/Water", "description": "Watercraft"},
    "ship": {"category": "Vehicles/Water", "description": "Large watercraft"},
    # Documents
    "document": {"category": "Documents", "description": "Written or printed paper"},
    "paper": {"category": "Documents", "description": "Sheet material for writing"},
    "book": {"category": "Documents/Reading", "description": "Bound written work"},
    "magazine": {"category": "Documents/Reading", "description": "Periodical publication"},
    "newspaper": {"category": "Documents/Reading", "description": "Daily news publication"},
    "screenshot": {"category": "Documents/Digital", "description": "Captured screen image"},
    "receipt": {"category": "Documents/Financial", "description": "Transaction record"},
    "menu": {"category": "Documents", "description": "List of food or options"},
    "sign": {"category": "Documents/Signage", "description": "Displayed information"},
}

# Room types to exclude
ROOM_TYPES = {
    "living room",
    "bedroom",
    "kitchen",
    "bathroom",
    "office",
    "patio",
    "porch",
    "deck",
    "balcony",
    "dining room",
    "garage",
    "backyard",
    "garden",
    "front yard",
    "basement",
    "attic",
    "restaurant",
    "hotel",
    "airport",
    "train station",
}


def analyze_image(image_path: Path, classifier: CLIPClassifier) -> List[Tuple[str, float]]:
    """
    Analyze image and return all object categories with confidence scores.
    Excludes room types.

    Returns:
        List of (object_name, confidence) tuples sorted by confidence descending
    """
    object_names = list(OBJECT_CATALOG.keys())
    return classifier.classify(image_path, object_names)


def generate_csv(image_path: Path, output_path: Path, min_confidence: float = 0.0):
    """Generate CSV report of image content analysis with unique IDs."""

    if not CLIP_AVAILABLE:
        print("Error: CLIP not available")
        return

    classifier = CLIPClassifier.get_instance()

    print(f"\nAnalyzing: {image_path.name}")
    results = analyze_image(image_path, classifier)

    # Filter by minimum confidence
    if min_confidence > 0:
        results = [(obj, conf) for obj, conf in results if conf >= min_confidence]

    # Write CSV with ID, category, description, confidence
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["id", "object", "category", "description", "confidence", "confidence_percent"]
        )

        for obj_name, confidence in results:
            obj_info = OBJECT_CATALOG.get(obj_name, {})
            obj_id = generate_object_id(obj_name)
            category = obj_info.get("category", "Unknown")
            description = obj_info.get("description", "")

            writer.writerow(
                [obj_id, obj_name, category, description, f"{confidence:.6f}", f"{confidence:.2%}"]
            )

    print(f"✓ CSV saved to: {output_path}")
    print("\nTop 10 detected objects:")
    print("-" * 80)
    print(f"{'Object':<20} {'Category':<25} {'Confidence':>10}")
    print("-" * 80)
    for obj_name, confidence in results[:10]:
        obj_info = OBJECT_CATALOG.get(obj_name, {})
        category = obj_info.get("category", "Unknown")
        bar = "█" * int(confidence * 30)
        print(f"{obj_name:<20} {category:<25} {confidence:>8.2%} {bar}")

    print(f"\nTotal objects analyzed: {len(OBJECT_CATALOG)}")
    print(f"Objects in CSV: {len(results)}")


def main():
    parser = argparse.ArgumentParser(description="Generate CSV report of image content analysis")
    parser.add_argument("image", type=str, help="Path to image file")
    parser.add_argument(
        "--output", "-o", type=str, help="Output CSV path (default: {image_stem}_content.csv)"
    )
    parser.add_argument(
        "--min-confidence", type=float, default=0.0, help="Minimum confidence threshold (0.0-1.0)"
    )

    args = parser.parse_args()

    image_path = Path(args.image).expanduser()
    if not image_path.exists():
        print(f"Error: Image not found: {image_path}")
        return

    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        output_path = image_path.parent / f"{image_path.stem}_content.csv"

    generate_csv(image_path, output_path, args.min_confidence)


if __name__ == "__main__":
    main()
