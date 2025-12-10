#!/usr/bin/env python3
"""
Rename image files based on metadata for better organization.
Renames generic camera filenames (IMG_*, PXL_*, DSC_*) to human-readable names
using EXIF metadata (date, location) and OCR for screenshots.
"""

import os
import re
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Tuple
from collections import defaultdict

# Import metadata and OCR classes from content-based organizer
import sys
sys.path.append(str(Path(__file__).parent))

try:
    from PIL import Image
    import piexif
    from geopy.geocoders import Nominatim
    import pytesseract
except ImportError as e:
    print(f"Missing required library: {e}")
    print("Install with: pip install Pillow piexif geopy pytesseract pillow-heif")
    sys.exit(1)


class ImageRenamer:
    """Rename images based on metadata."""

    # Patterns that indicate non-human-readable filenames
    GENERIC_PATTERNS = [
        r'^IMG_\d+',           # IMG_1234.jpg
        r'^DSC_\d+',           # DSC_1234.jpg
        r'^PXL_\d+',           # PXL_20250425_023840031.jpg
        r'^DCIM_\d+',          # DCIM_1234.jpg
        r'^\d{8}_\d{6}',       # 20250425_123456.jpg
        r'^\d{4}-\d{2}-\d{2}', # 2025-04-25.jpg
        r'^Screenshot\s+\d{4}', # Screenshot 2025-11-23...
        r'^\d+$',              # 12345.jpg (pure numbers)
        r'^[a-f0-9]{32}',      # MD5-style hashes
        r'^unnamed\(\d+\)',    # unnamed(1).jpg
        r'^image\(\d+\)',      # image(1).jpg
        r'^photo\(\d+\)',      # photo(1).jpg
        r'^file\(\d+\)',       # file(1).jpg
        r'^\d{13}',            # 1715549219720 (Unix timestamps in ms)
        r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', # UUIDs
    ]

    def __init__(self, base_path: str = None):
        """Initialize the renamer."""
        self.base_path = Path(base_path or os.path.expanduser("~/Documents"))
        self.stats = defaultdict(int)
        self.geolocator = Nominatim(user_agent="image_renamer")

        # HEIC support
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
            self.heic_support = True
        except ImportError:
            self.heic_support = False
            print("⚠️  HEIC support not available. Install pillow-heif for HEIC images.")

    def is_generic_filename(self, filename: str) -> bool:
        """Check if filename is generic/non-human-readable."""
        stem = Path(filename).stem.lower()  # Convert to lowercase for case-insensitive matching

        for pattern in self.GENERIC_PATTERNS:
            if re.match(pattern, stem):
                return True

        return False

    def extract_exif_data(self, image_path: Path) -> Optional[Dict]:
        """Extract EXIF data from image."""
        try:
            img = Image.open(image_path)
            if not hasattr(img, '_getexif') or img._getexif() is None:
                # Try piexif for JPEG/HEIC
                exif_dict = piexif.load(str(image_path))
                if exif_dict:
                    return exif_dict
            else:
                return img._getexif()
            return None
        except Exception as e:
            return None

    def extract_datetime(self, image_path: Path) -> Optional[datetime]:
        """Extract datetime from EXIF."""
        try:
            img = Image.open(image_path)
            exif_data = img._getexif()

            if exif_data:
                # Try different datetime tags
                for tag_id in [36867, 36868, 306]:  # DateTimeOriginal, DateTimeDigitized, DateTime
                    if tag_id in exif_data:
                        dt_str = exif_data[tag_id]
                        try:
                            dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
                            return dt
                        except (ValueError, TypeError):
                            continue

            # Try piexif
            exif_dict = piexif.load(str(image_path))
            if exif_dict and piexif.ExifIFD.DateTimeOriginal in exif_dict.get("Exif", {}):
                dt_bytes = exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal]
                dt_str = dt_bytes.decode('utf-8') if isinstance(dt_bytes, bytes) else dt_bytes
                try:
                    dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
                    return dt
                except (ValueError, TypeError):
                    pass

        except Exception:
            pass

        return None

    def extract_gps_coordinates(self, image_path: Path) -> Optional[Tuple[float, float]]:
        """Extract GPS coordinates from EXIF."""
        try:
            exif_dict = piexif.load(str(image_path))
            if not exif_dict or "GPS" not in exif_dict:
                return None

            gps_info = exif_dict["GPS"]

            # Get latitude
            if piexif.GPSIFD.GPSLatitude not in gps_info or piexif.GPSIFD.GPSLatitudeRef not in gps_info:
                return None

            lat = gps_info[piexif.GPSIFD.GPSLatitude]
            lat_ref = gps_info[piexif.GPSIFD.GPSLatitudeRef].decode('utf-8')

            # Get longitude
            if piexif.GPSIFD.GPSLongitude not in gps_info or piexif.GPSIFD.GPSLongitudeRef not in gps_info:
                return None

            lon = gps_info[piexif.GPSIFD.GPSLongitude]
            lon_ref = gps_info[piexif.GPSIFD.GPSLongitudeRef].decode('utf-8')

            # Convert to decimal degrees
            def to_decimal(coord):
                d, m, s = coord
                return d[0]/d[1] + (m[0]/m[1])/60 + (s[0]/s[1])/3600

            latitude = to_decimal(lat)
            if lat_ref == 'S':
                latitude = -latitude

            longitude = to_decimal(lon)
            if lon_ref == 'W':
                longitude = -longitude

            return (latitude, longitude)

        except Exception:
            return None

    def get_location_name(self, coordinates: Tuple[float, float]) -> Optional[str]:
        """Get location name from GPS coordinates."""
        try:
            location = self.geolocator.reverse(coordinates, language='en', timeout=10)
            if location:
                address = location.raw.get('address', {})
                # Try to get city, town, or village
                place = (address.get('city') or
                        address.get('town') or
                        address.get('village') or
                        address.get('county'))
                return place
        except Exception:
            pass
        return None

    def extract_screenshot_text(self, image_path: Path) -> Optional[str]:
        """Extract text from screenshots using OCR."""
        try:
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img)

            # Clean up text - extract first meaningful phrase
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            if lines:
                # Get first line that's not too short
                for line in lines[:3]:
                    if len(line) > 10 and len(line) < 50:
                        # Clean for filename
                        clean_text = re.sub(r'[^\w\s-]', '', line)
                        clean_text = re.sub(r'\s+', '_', clean_text.strip())
                        return clean_text[:40]  # Max 40 chars
        except Exception:
            pass
        return None

    def generate_new_filename(self, image_path: Path) -> Optional[str]:
        """Generate a new human-readable filename based on metadata."""
        ext = image_path.suffix.lower()

        # Check if it's a screenshot
        is_screenshot = 'screenshot' in image_path.stem.lower()

        if is_screenshot:
            # For screenshots, try OCR first
            text = self.extract_screenshot_text(image_path)
            if text:
                return f"Screenshot_{text}{ext}"

            # Fall back to datetime
            dt = self.extract_datetime(image_path)
            if dt:
                return f"Screenshot_{dt.strftime('%Y%m%d_%H%M%S')}{ext}"

            return None

        # For regular photos, use date + location
        dt = self.extract_datetime(image_path)
        coords = self.extract_gps_coordinates(image_path)

        parts = []

        # Add date
        if dt:
            parts.append(dt.strftime('%Y%m%d'))
        else:
            # Fall back to file modification time if no EXIF date
            mod_time = datetime.fromtimestamp(image_path.stat().st_mtime)
            parts.append(mod_time.strftime('%Y%m%d'))
            dt = mod_time  # Use for time part below

        # Add location
        if coords:
            location = self.get_location_name(coords)
            if location:
                # Clean location name for filename
                clean_loc = re.sub(r'[^\w\s-]', '', location)
                clean_loc = re.sub(r'\s+', '_', clean_loc)
                parts.append(clean_loc)

        # Add time if we have date
        if dt:
            parts.append(dt.strftime('%H%M%S'))

        if parts:
            return '_'.join(parts) + ext

        return None

    def rename_file(self, file_path: Path, dry_run: bool = False) -> Dict:
        """Rename a single file based on metadata."""
        result = {
            'source': str(file_path),
            'status': 'skipped',
            'destination': None,
            'reason': None
        }

        # Check if file exists
        if not file_path.exists() or not file_path.is_file():
            result['reason'] = 'Not a file'
            self.stats['skipped'] += 1
            return result

        # Check if filename is already human-readable
        if not self.is_generic_filename(file_path.name):
            result['reason'] = 'Already human-readable'
            result['status'] = 'already_readable'
            self.stats['already_readable'] += 1
            return result

        # Check if it's an image
        if file_path.suffix.lower() not in ['.jpg', '.jpeg', '.png', '.heic', '.gif', '.bmp', '.webp']:
            result['reason'] = 'Not an image file'
            self.stats['skipped'] += 1
            return result

        # Generate new filename
        try:
            new_name = self.generate_new_filename(file_path)

            if not new_name:
                result['reason'] = 'No metadata available'
                result['status'] = 'no_metadata'
                self.stats['no_metadata'] += 1
                return result

            # Create new path in same directory
            new_path = file_path.parent / new_name

            # Handle duplicates
            if new_path.exists() and new_path != file_path:
                counter = 1
                stem = Path(new_name).stem
                ext = Path(new_name).suffix
                while new_path.exists():
                    new_name = f"{stem}_{counter}{ext}"
                    new_path = file_path.parent / new_name
                    counter += 1

            # Perform rename
            if not dry_run:
                file_path.rename(new_path)
                result['status'] = 'renamed'
                print(f"  ✓ Renamed: {file_path.name} → {new_name}")
            else:
                result['status'] = 'would_rename'
                print(f"  → Would rename: {file_path.name} → {new_name}")

            result['destination'] = str(new_path)
            self.stats['renamed'] += 1

        except Exception as e:
            result['status'] = 'error'
            result['reason'] = str(e)
            self.stats['errors'] += 1
            print(f"  ✗ Error renaming {file_path.name}: {e}")

        return result

    def rename_directory(self, source_dir: str, dry_run: bool = False, recursive: bool = False) -> Dict:
        """Rename all generic image files in a directory."""
        results = []
        source_path = Path(source_dir).expanduser()

        print(f"\n{'='*60}")
        print(f"Image Metadata Renamer {'(DRY RUN)' if dry_run else ''}")
        print(f"{'='*60}\n")
        print(f"Scanning: {source_path}")
        print(f"Recursive: {recursive}\n")

        # Collect all image files
        image_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.gif', '.bmp', '.webp'}
        all_files = []

        if recursive:
            for ext in image_extensions:
                all_files.extend(source_path.rglob(f'*{ext}'))
                all_files.extend(source_path.rglob(f'*{ext.upper()}'))
        else:
            for ext in image_extensions:
                all_files.extend(source_path.glob(f'*{ext}'))
                all_files.extend(source_path.glob(f'*{ext.upper()}'))

        # Filter for generic filenames
        generic_files = [f for f in all_files if self.is_generic_filename(f.name)]

        print(f"Total image files: {len(all_files)}")
        print(f"Generic filenames to process: {len(generic_files)}\n")

        # Process each file
        for i, file_path in enumerate(generic_files, 1):
            if i % 50 == 0:
                print(f"[{i}/{len(generic_files)}] Processing...")

            result = self.rename_file(file_path, dry_run=dry_run)
            results.append(result)

        # Generate summary
        summary = {
            'total_images': len(all_files),
            'generic_filenames': len(generic_files),
            'renamed': self.stats['renamed'],
            'already_readable': self.stats['already_readable'],
            'no_metadata': self.stats['no_metadata'],
            'skipped': self.stats['skipped'],
            'errors': self.stats['errors'],
            'dry_run': dry_run,
            'results': results
        }

        return summary

    def print_summary(self, summary: Dict):
        """Print renaming summary."""
        print(f"\n{'='*60}")
        print("Renaming Summary")
        print(f"{'='*60}\n")

        print(f"Total image files: {summary['total_images']}")
        print(f"Generic filenames found: {summary['generic_filenames']}")
        print(f"Successfully renamed: {summary['renamed']}")
        print(f"Already human-readable: {summary['already_readable']}")
        print(f"No metadata available: {summary['no_metadata']}")
        print(f"Skipped: {summary['skipped']}")
        print(f"Errors: {summary['errors']}")

        if summary['dry_run']:
            print("\n⚠️  This was a DRY RUN - no files were renamed")

        # Show breakdown by reason
        if summary['no_metadata'] > 0:
            print(f"\nℹ️  {summary['no_metadata']} files have no EXIF metadata to generate names from")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Rename images with generic filenames using metadata'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate renaming without actually renaming files'
    )
    parser.add_argument(
        '--source',
        default='~/Documents',
        help='Source directory to scan (default: ~/Documents)'
    )
    parser.add_argument(
        '--recursive',
        action='store_true',
        help='Recursively scan subdirectories'
    )

    args = parser.parse_args()

    # Create renamer
    renamer = ImageRenamer()

    # Rename files
    summary = renamer.rename_directory(
        source_dir=args.source,
        dry_run=args.dry_run,
        recursive=args.recursive
    )

    # Print summary
    renamer.print_summary(summary)


if __name__ == '__main__':
    main()
