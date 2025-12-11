#!/usr/bin/env python3
"""
Regenerate Schema.org metadata for all files in the database.

This script updates all schema_data in the files table to include the new @id field
based on the file's canonical_id. It uses the updated generators from src/base.py.

Usage:
    python scripts/regenerate_schemas.py --db-path results/file_organization.db
    python scripts/regenerate_schemas.py --dry-run  # Show what would be done
    python scripts/regenerate_schemas.py --limit 100  # Process only first 100
"""

import argparse
import sqlite3
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from urllib.parse import quote

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from generators import (
    DocumentGenerator,
    ImageGenerator,
    VideoGenerator,
    AudioGenerator,
    CodeGenerator,
    DatasetGenerator,
    ArchiveGenerator
)
from base import PropertyType
from enrichment import MetadataEnricher


def get_generator_for_type(schema_type: str, entity_id: str):
    """Get the appropriate generator for a schema type with @id."""
    # Generators that take schema_type as first argument
    type_generators = {
        'ImageObject': lambda: ImageGenerator('ImageObject', entity_id=entity_id),
        'Photograph': lambda: ImageGenerator('Photograph', entity_id=entity_id),
        'DigitalDocument': lambda: DocumentGenerator('DigitalDocument', entity_id=entity_id),
        'Article': lambda: DocumentGenerator('Article', entity_id=entity_id),
        'Report': lambda: DocumentGenerator('Report', entity_id=entity_id),
        'VideoObject': lambda: VideoGenerator('VideoObject', entity_id=entity_id),
        'MovieClip': lambda: VideoGenerator('MovieClip', entity_id=entity_id),
        'AudioObject': lambda: AudioGenerator('AudioObject', entity_id=entity_id),
        'MusicRecording': lambda: AudioGenerator('MusicRecording', entity_id=entity_id),
        'PodcastEpisode': lambda: AudioGenerator('PodcastEpisode', entity_id=entity_id),
        # These generators don't take schema_type
        'SoftwareSourceCode': lambda: CodeGenerator(entity_id=entity_id),
        'Dataset': lambda: DatasetGenerator(entity_id=entity_id),
        'Archive': lambda: ArchiveGenerator(entity_id=entity_id),
    }

    generator_factory = type_generators.get(
        schema_type,
        lambda: DocumentGenerator('DigitalDocument', entity_id=entity_id)
    )
    return generator_factory()


def regenerate_schema(
    file_id: str,
    canonical_id: str,
    current_path: str,
    schema_type: str,
    existing_schema: Dict[str, Any],
    enricher: MetadataEnricher
) -> Dict[str, Any]:
    """
    Regenerate Schema.org metadata for a file with @id.

    Args:
        file_id: Internal file ID (SHA-256 hash)
        canonical_id: Public canonical ID for @id
        current_path: Current file path
        schema_type: Schema.org type (e.g., 'ImageObject')
        existing_schema: Existing schema data to preserve
        enricher: MetadataEnricher instance

    Returns:
        Updated schema dictionary with @id
    """
    # Use canonical_id as entity_id (it's already in urn:sha256:... format)
    entity_id = canonical_id if canonical_id else f"urn:sha256:{file_id}"

    # Create generator with @id
    generator = get_generator_for_type(schema_type or 'DigitalDocument', entity_id)

    # Try to get file stats if file exists
    file_path = Path(current_path) if current_path else None
    if file_path and file_path.exists():
        try:
            stats = file_path.stat()
            mime_type = enricher.detect_mime_type(str(file_path))
            file_url = f"https://localhost/files/{quote(file_path.name)}"

            # Set basic info based on type
            if schema_type == 'ImageObject':
                generator.set_basic_info(
                    name=file_path.name,
                    content_url=file_url,
                    encoding_format=mime_type or 'image/png',
                    description=existing_schema.get('description', file_path.name)
                )
            else:
                generator.set_basic_info(
                    name=file_path.name,
                    description=existing_schema.get('description', file_path.name)
                )
                if hasattr(generator, 'set_file_info'):
                    generator.set_file_info(
                        encoding_format=mime_type or 'application/octet-stream',
                        url=file_url,
                        content_size=stats.st_size
                    )

            # Set dates
            generator.set_dates(
                created=datetime.fromtimestamp(stats.st_ctime),
                modified=datetime.fromtimestamp(stats.st_mtime)
            )

            # Add file path
            generator.set_property('filePath', str(file_path.absolute()), PropertyType.TEXT)

        except Exception as e:
            # If we can't access the file, use existing schema data
            pass

    # Preserve existing properties that we don't regenerate
    schema = generator.to_dict()

    # Preserve these properties from existing schema if present
    preserve_keys = ['abstract', 'text', 'keywords', 'author', 'creator',
                     'width', 'height', 'duration', 'bitrate']
    for key in preserve_keys:
        if key in existing_schema and key not in schema:
            schema[key] = existing_schema[key]

    return schema


def process_files(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    limit: Optional[int] = None,
    batch_size: int = 1000
) -> int:
    """Process all files and regenerate their schemas."""
    enricher = MetadataEnricher()

    # Get total count
    cursor = conn.execute("SELECT COUNT(*) FROM files")
    total_count = cursor.fetchone()[0]

    if limit:
        total_count = min(total_count, limit)

    print(f"Processing {total_count} files...")

    # Process in batches
    processed = 0
    errors = 0
    offset = 0

    while processed < total_count:
        # Fetch batch
        query = """
            SELECT id, canonical_id, current_path, schema_type, schema_data
            FROM files
            ORDER BY id
            LIMIT ? OFFSET ?
        """
        cursor = conn.execute(query, (batch_size, offset))
        rows = cursor.fetchall()

        if not rows:
            break

        for file_id, canonical_id, current_path, schema_type, schema_data_json in rows:
            if limit and processed >= limit:
                break

            try:
                # Parse existing schema
                existing_schema = {}
                if schema_data_json:
                    try:
                        existing_schema = json.loads(schema_data_json)
                    except json.JSONDecodeError:
                        pass

                # Regenerate schema with @id
                new_schema = regenerate_schema(
                    file_id=file_id,
                    canonical_id=canonical_id,
                    current_path=current_path or '',
                    schema_type=schema_type or 'DigitalDocument',
                    existing_schema=existing_schema,
                    enricher=enricher
                )

                if dry_run:
                    if processed < 3:  # Show first 3 examples
                        print(f"\n  Example {processed + 1}:")
                        print(f"    File: {current_path or file_id[:16]}...")
                        print(f"    @id: {new_schema.get('@id', 'MISSING')}")
                else:
                    # Update database
                    conn.execute(
                        "UPDATE files SET schema_data = ? WHERE id = ?",
                        (json.dumps(new_schema), file_id)
                    )

                processed += 1

            except Exception as e:
                errors += 1
                if errors <= 5:  # Show first 5 errors
                    print(f"  Error processing {file_id[:16]}...: {e}")

        offset += batch_size

        # Commit batch
        if not dry_run:
            conn.commit()

        # Progress update
        pct = (processed / total_count) * 100
        print(f"  Progress: {processed}/{total_count} ({pct:.1f}%) - Errors: {errors}")

    return processed


def verify_schemas(conn: sqlite3.Connection) -> bool:
    """Verify that schemas have @id field."""
    print("\n=== Verification ===\n")

    # Check a sample of schemas
    cursor = conn.execute("""
        SELECT schema_data FROM files
        WHERE schema_data IS NOT NULL
        LIMIT 100
    """)

    has_id = 0
    missing_id = 0

    for (schema_data_json,) in cursor.fetchall():
        try:
            schema = json.loads(schema_data_json)
            if '@id' in schema:
                has_id += 1
            else:
                missing_id += 1
        except:
            missing_id += 1

    total = has_id + missing_id
    if total == 0:
        print("  No schemas found to verify")
        return False

    pct = (has_id / total) * 100
    print(f"  Sample of 100 schemas:")
    print(f"    With @id: {has_id} ({pct:.1f}%)")
    print(f"    Missing @id: {missing_id}")

    if missing_id > 0:
        # Show an example of missing @id
        cursor = conn.execute("""
            SELECT id, schema_data FROM files
            WHERE schema_data IS NOT NULL
            AND schema_data NOT LIKE '%"@id"%'
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            print(f"\n  Example missing @id: {row[0][:16]}...")

    return missing_id == 0


def main():
    parser = argparse.ArgumentParser(
        description="Regenerate Schema.org metadata with @id for all files"
    )
    parser.add_argument(
        '--db-path',
        default='results/file_organization.db',
        help='Path to SQLite database'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of files to process'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Batch size for processing'
    )

    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    print(f"Schema Regeneration Script")
    print(f"==========================")
    print(f"Database: {db_path}")
    print(f"Dry run: {args.dry_run}")
    print(f"Limit: {args.limit or 'None'}")
    print(f"Started: {datetime.now().isoformat()}")

    conn = sqlite3.connect(str(db_path))

    try:
        print("\n=== Regenerating Schemas ===\n")

        processed = process_files(
            conn,
            dry_run=args.dry_run,
            limit=args.limit,
            batch_size=args.batch_size
        )

        if not args.dry_run:
            success = verify_schemas(conn)
        else:
            print("\n=== Dry Run Complete ===")
            print("Run without --dry-run to apply changes")
            success = True

        print(f"\n=== Summary ===")
        print(f"Files processed: {processed}")
        print(f"Status: {'SUCCESS' if success else 'INCOMPLETE - run again'}")
        print(f"Completed: {datetime.now().isoformat()}")

    finally:
        conn.close()


if __name__ == '__main__':
    main()
