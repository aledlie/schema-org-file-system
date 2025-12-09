#!/usr/bin/env python3
"""
Data Preprocessing Pipeline for File Organization ML

This module provides comprehensive data preprocessing for training
ML models on file categorization:

1. Feature extraction from filenames, paths, and metadata
2. Text normalization and tokenization
3. Train/test splitting with stratification
4. Data validation and quality metrics
5. Feature engineering for pattern learning
"""

import os
import re
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from collections import Counter, defaultdict
import unicodedata


class FileFeatureExtractor:
    """Extract ML features from file metadata."""

    # Common patterns for categorization
    SCREENSHOT_PATTERNS = [
        r'screenshot',
        r'screen\s*shot',
        r'screen_\d+',
        r'capture',
        r'snip',
    ]

    GAME_ASSET_PATTERNS = [
        r'sprite', r'frame', r'tile', r'texture',
        r'audio', r'sfx', r'bgm', r'music',
        r'icon', r'button', r'ui_',
    ]

    DOCUMENT_PATTERNS = [
        r'invoice', r'receipt', r'contract',
        r'report', r'statement', r'tax',
        r'resume', r'cv', r'letter',
    ]

    def __init__(self):
        self.extension_map = self._build_extension_map()

    def _build_extension_map(self) -> Dict[str, str]:
        """Build mapping of extensions to general categories."""
        return {
            # Images
            '.jpg': 'image', '.jpeg': 'image', '.png': 'image',
            '.gif': 'image', '.bmp': 'image', '.webp': 'image',
            '.heic': 'image', '.heif': 'image', '.svg': 'image',
            '.tiff': 'image', '.ico': 'image',
            # Videos
            '.mp4': 'video', '.mov': 'video', '.avi': 'video',
            '.mkv': 'video', '.webm': 'video', '.m4v': 'video',
            # Audio
            '.mp3': 'audio', '.wav': 'audio', '.ogg': 'audio',
            '.flac': 'audio', '.aac': 'audio', '.m4a': 'audio',
            # Documents
            '.pdf': 'document', '.doc': 'document', '.docx': 'document',
            '.txt': 'text', '.rtf': 'document', '.odt': 'document',
            # Spreadsheets
            '.xls': 'spreadsheet', '.xlsx': 'spreadsheet', '.csv': 'data',
            # Code
            '.py': 'code', '.js': 'code', '.ts': 'code', '.jsx': 'code',
            '.tsx': 'code', '.html': 'code', '.css': 'code', '.json': 'data',
            '.xml': 'data', '.yaml': 'data', '.yml': 'data',
            # Archives
            '.zip': 'archive', '.tar': 'archive', '.gz': 'archive',
            '.rar': 'archive', '.7z': 'archive',
        }

    def extract_features(self, file_record: Dict) -> Dict[str, Any]:
        """Extract all features from a file record."""
        filename = file_record.get('schema', {}).get('name', '')
        filepath = file_record.get('source', '')
        category = file_record.get('category', 'uncategorized')
        subcategory = file_record.get('subcategory', '')

        features = {
            # Basic features
            'filename': filename,
            'filename_lower': filename.lower(),
            'filepath': filepath,
            'category': category,
            'subcategory': subcategory,

            # Extension features
            'extension': self._get_extension(filename),
            'extension_category': self._get_extension_category(filename),

            # Filename pattern features
            'filename_tokens': self._tokenize_filename(filename),
            'filename_length': len(filename),
            'has_numbers': bool(re.search(r'\d', filename)),
            'has_underscores': '_' in filename,
            'has_dashes': '-' in filename,
            'has_spaces': ' ' in filename,
            'starts_with_date': self._starts_with_date(filename),

            # Pattern detection
            'is_screenshot': self._matches_patterns(filename, self.SCREENSHOT_PATTERNS),
            'is_game_asset': self._matches_patterns(filename, self.GAME_ASSET_PATTERNS),
            'is_document': self._matches_patterns(filename, self.DOCUMENT_PATTERNS),

            # Metadata features
            'has_extracted_text': file_record.get('extracted_text_length', 0) > 0,
            'extracted_text_length': file_record.get('extracted_text_length', 0),
            'has_company_name': file_record.get('company_name') is not None,
            'has_people_names': len(file_record.get('people_names', [])) > 0,
            'people_count': len(file_record.get('people_names', [])),

            # Image metadata features
            'has_datetime': file_record.get('image_metadata', {}).get('datetime') is not None,
            'has_gps': file_record.get('image_metadata', {}).get('gps_coordinates') is not None,
            'has_location': file_record.get('image_metadata', {}).get('location_name') is not None,

            # Path features
            'path_depth': filepath.count('/') if filepath else 0,
            'parent_folder': self._get_parent_folder(filepath),

            # Derived features
            'filename_hash': self._hash_filename(filename),
        }

        return features

    def _get_extension(self, filename: str) -> str:
        """Get lowercase file extension."""
        return Path(filename).suffix.lower()

    def _get_extension_category(self, filename: str) -> str:
        """Get category based on extension."""
        ext = self._get_extension(filename)
        return self.extension_map.get(ext, 'other')

    def _tokenize_filename(self, filename: str) -> List[str]:
        """Tokenize filename into meaningful parts."""
        # Remove extension
        name = Path(filename).stem

        # Normalize unicode
        name = unicodedata.normalize('NFKD', name)

        # Split on common delimiters
        tokens = re.split(r'[_\-\s\.]+', name)

        # Split camelCase
        expanded_tokens = []
        for token in tokens:
            # Split on camelCase boundaries
            parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+', token)
            expanded_tokens.extend(parts if parts else [token])

        # Lowercase and filter
        return [t.lower() for t in expanded_tokens if t and len(t) > 1]

    def _starts_with_date(self, filename: str) -> bool:
        """Check if filename starts with a date pattern."""
        date_patterns = [
            r'^\d{8}',  # YYYYMMDD
            r'^\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'^\d{2}-\d{2}-\d{4}',  # MM-DD-YYYY
            r'^20\d{2}\d{4}',  # 20YYMMDD
        ]
        return any(re.match(p, filename) for p in date_patterns)

    def _matches_patterns(self, filename: str, patterns: List[str]) -> bool:
        """Check if filename matches any of the patterns."""
        filename_lower = filename.lower()
        return any(re.search(p, filename_lower) for p in patterns)

    def _get_parent_folder(self, filepath: str) -> str:
        """Get immediate parent folder name."""
        if not filepath:
            return ''
        parts = Path(filepath).parts
        return parts[-2] if len(parts) >= 2 else ''

    def _hash_filename(self, filename: str) -> str:
        """Create a hash of the filename for deduplication."""
        return hashlib.md5(filename.encode()).hexdigest()[:8]


class DataPreprocessor:
    """Main preprocessing pipeline for file organization data."""

    def __init__(self, report_path: str = None):
        """Initialize preprocessor.

        Args:
            report_path: Path to organization report JSON
        """
        self.report_path = report_path
        self.feature_extractor = FileFeatureExtractor()
        self.data = None
        self.features = None
        self.statistics = {}

    def load_data(self, report_path: str = None) -> Dict:
        """Load organization report data."""
        path = report_path or self.report_path
        if not path:
            raise ValueError("No report path provided")

        with open(path, 'r') as f:
            self.data = json.load(f)

        self.statistics['total_records'] = len(self.data.get('results', []))
        self.statistics['load_time'] = datetime.now().isoformat()
        return self.data

    def extract_all_features(self) -> List[Dict]:
        """Extract features from all records."""
        if not self.data:
            raise ValueError("No data loaded. Call load_data() first.")

        results = self.data.get('results', [])
        self.features = []

        for record in results:
            features = self.feature_extractor.extract_features(record)
            self.features.append(features)

        self.statistics['features_extracted'] = len(self.features)
        return self.features

    def compute_statistics(self) -> Dict:
        """Compute dataset statistics."""
        if not self.features:
            raise ValueError("No features extracted. Call extract_all_features() first.")

        # Category distribution
        categories = Counter(f['category'] for f in self.features)
        subcategories = Counter(f['subcategory'] for f in self.features)

        # Extension distribution
        extensions = Counter(f['extension'] for f in self.features)

        # Pattern counts
        screenshots = sum(1 for f in self.features if f['is_screenshot'])
        game_assets = sum(1 for f in self.features if f['is_game_asset'])
        documents = sum(1 for f in self.features if f['is_document'])

        # Metadata availability
        has_text = sum(1 for f in self.features if f['has_extracted_text'])
        has_datetime = sum(1 for f in self.features if f['has_datetime'])
        has_gps = sum(1 for f in self.features if f['has_gps'])

        # Filename analysis
        avg_filename_length = sum(f['filename_length'] for f in self.features) / len(self.features)
        token_counts = Counter()
        for f in self.features:
            token_counts.update(f['filename_tokens'])

        self.statistics.update({
            'category_distribution': dict(categories),
            'subcategory_distribution': dict(subcategories.most_common(20)),
            'extension_distribution': dict(extensions.most_common(20)),
            'pattern_counts': {
                'screenshots': screenshots,
                'game_assets': game_assets,
                'documents': documents,
            },
            'metadata_availability': {
                'has_text': has_text,
                'has_datetime': has_datetime,
                'has_gps': has_gps,
            },
            'filename_analysis': {
                'avg_length': round(avg_filename_length, 2),
                'top_tokens': dict(token_counts.most_common(30)),
            },
        })

        return self.statistics

    def create_train_test_split(
        self,
        test_ratio: float = 0.2,
        stratify_by: str = 'category',
        random_seed: int = 42
    ) -> Tuple[List[Dict], List[Dict]]:
        """Create stratified train/test split.

        Args:
            test_ratio: Fraction of data for testing
            stratify_by: Field to stratify by ('category' or 'subcategory')
            random_seed: Random seed for reproducibility

        Returns:
            Tuple of (train_features, test_features)
        """
        import random
        random.seed(random_seed)

        if not self.features:
            raise ValueError("No features extracted. Call extract_all_features() first.")

        # Group by stratification field
        groups = defaultdict(list)
        for f in self.features:
            key = f.get(stratify_by, 'unknown')
            groups[key].append(f)

        train_data = []
        test_data = []

        for key, items in groups.items():
            random.shuffle(items)
            split_idx = int(len(items) * (1 - test_ratio))
            train_data.extend(items[:split_idx])
            test_data.extend(items[split_idx:])

        # Shuffle final results
        random.shuffle(train_data)
        random.shuffle(test_data)

        self.statistics['train_test_split'] = {
            'train_size': len(train_data),
            'test_size': len(test_data),
            'test_ratio': round(len(test_data) / len(self.features), 3),
            'stratify_by': stratify_by,
        }

        return train_data, test_data

    def get_vocabulary(self, min_freq: int = 5) -> Dict[str, int]:
        """Build vocabulary from filename tokens.

        Args:
            min_freq: Minimum frequency for a token to be included

        Returns:
            Dictionary mapping tokens to indices
        """
        if not self.features:
            raise ValueError("No features extracted. Call extract_all_features() first.")

        token_counts = Counter()
        for f in self.features:
            token_counts.update(f['filename_tokens'])

        # Filter by frequency and create vocabulary
        vocab = {'<PAD>': 0, '<UNK>': 1}
        idx = 2
        for token, count in token_counts.most_common():
            if count >= min_freq:
                vocab[token] = idx
                idx += 1

        self.statistics['vocabulary'] = {
            'size': len(vocab),
            'min_freq': min_freq,
        }

        return vocab

    def get_label_encoder(self) -> Tuple[Dict[str, int], Dict[int, str]]:
        """Create label encoders for categories.

        Returns:
            Tuple of (label_to_id, id_to_label)
        """
        if not self.features:
            raise ValueError("No features extracted. Call extract_all_features() first.")

        categories = sorted(set(f['category'] for f in self.features))
        label_to_id = {cat: i for i, cat in enumerate(categories)}
        id_to_label = {i: cat for i, cat in enumerate(categories)}

        self.statistics['label_encoding'] = {
            'num_classes': len(categories),
            'classes': categories,
        }

        return label_to_id, id_to_label

    def validate_data_quality(self) -> Dict[str, Any]:
        """Validate data quality and identify issues."""
        if not self.features:
            raise ValueError("No features extracted. Call extract_all_features() first.")

        issues = {
            'missing_category': [],
            'empty_filename': [],
            'duplicate_filenames': [],
            'suspicious_extensions': [],
        }

        filename_counts = Counter(f['filename'] for f in self.features)

        for f in self.features:
            # Check for missing categories
            if not f['category'] or f['category'] == 'uncategorized':
                issues['missing_category'].append(f['filename'])

            # Check for empty filenames
            if not f['filename']:
                issues['empty_filename'].append(f['filepath'])

            # Check for suspicious extensions
            if f['extension'] and f['extension'] not in self.feature_extractor.extension_map:
                issues['suspicious_extensions'].append((f['filename'], f['extension']))

        # Find duplicates
        issues['duplicate_filenames'] = [
            name for name, count in filename_counts.items() if count > 1
        ]

        # Summarize
        quality_report = {
            'total_records': len(self.features),
            'uncategorized_count': len(issues['missing_category']),
            'empty_filename_count': len(issues['empty_filename']),
            'duplicate_count': len(issues['duplicate_filenames']),
            'unknown_extension_count': len(issues['suspicious_extensions']),
            'quality_score': self._compute_quality_score(issues),
            'issues_sample': {
                'uncategorized': issues['missing_category'][:10],
                'duplicates': issues['duplicate_filenames'][:10],
                'unknown_extensions': list(set(ext for _, ext in issues['suspicious_extensions']))[:10],
            }
        }

        self.statistics['data_quality'] = quality_report
        return quality_report

    def _compute_quality_score(self, issues: Dict) -> float:
        """Compute overall data quality score (0-100)."""
        total = len(self.features)
        if total == 0:
            return 0.0

        # Penalize based on issues
        penalties = 0
        penalties += len(issues['missing_category']) * 0.5
        penalties += len(issues['empty_filename']) * 1.0
        penalties += len(issues['duplicate_filenames']) * 0.1
        penalties += len(issues['suspicious_extensions']) * 0.05

        score = max(0, 100 - (penalties / total * 100))
        return round(score, 2)

    def export_for_training(
        self,
        output_dir: str,
        include_test_split: bool = True
    ) -> Dict[str, str]:
        """Export preprocessed data for ML training.

        Args:
            output_dir: Directory to save files
            include_test_split: Whether to create train/test split

        Returns:
            Dictionary of output file paths
        """
        os.makedirs(output_dir, exist_ok=True)
        output_files = {}

        # Export all features
        features_path = os.path.join(output_dir, 'features.json')
        with open(features_path, 'w') as f:
            json.dump(self.features, f, indent=2)
        output_files['features'] = features_path

        # Export vocabulary
        vocab = self.get_vocabulary()
        vocab_path = os.path.join(output_dir, 'vocabulary.json')
        with open(vocab_path, 'w') as f:
            json.dump(vocab, f, indent=2)
        output_files['vocabulary'] = vocab_path

        # Export label encoders
        label_to_id, id_to_label = self.get_label_encoder()
        labels_path = os.path.join(output_dir, 'labels.json')
        with open(labels_path, 'w') as f:
            json.dump({
                'label_to_id': label_to_id,
                'id_to_label': {str(k): v for k, v in id_to_label.items()},
            }, f, indent=2)
        output_files['labels'] = labels_path

        # Export train/test split
        if include_test_split:
            train_data, test_data = self.create_train_test_split()

            train_path = os.path.join(output_dir, 'train.json')
            with open(train_path, 'w') as f:
                json.dump(train_data, f, indent=2)
            output_files['train'] = train_path

            test_path = os.path.join(output_dir, 'test.json')
            with open(test_path, 'w') as f:
                json.dump(test_data, f, indent=2)
            output_files['test'] = test_path

        # Export statistics
        stats_path = os.path.join(output_dir, 'statistics.json')
        with open(stats_path, 'w') as f:
            json.dump(self.statistics, f, indent=2)
        output_files['statistics'] = stats_path

        return output_files

    def generate_report(self) -> str:
        """Generate a human-readable preprocessing report."""
        if not self.statistics:
            self.compute_statistics()
            self.validate_data_quality()

        report = []
        report.append("=" * 60)
        report.append("FILE ORGANIZATION DATA PREPROCESSING REPORT")
        report.append("=" * 60)
        report.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # Dataset Overview
        report.append("-" * 40)
        report.append("DATASET OVERVIEW")
        report.append("-" * 40)
        report.append(f"Total Records: {self.statistics.get('total_records', 0):,}")
        report.append(f"Features Extracted: {self.statistics.get('features_extracted', 0):,}")

        # Category Distribution
        report.append("\n" + "-" * 40)
        report.append("CATEGORY DISTRIBUTION")
        report.append("-" * 40)
        cats = self.statistics.get('category_distribution', {})
        for cat, count in sorted(cats.items(), key=lambda x: -x[1])[:15]:
            pct = (count / self.statistics.get('total_records', 1)) * 100
            report.append(f"  {cat:20} {count:8,} ({pct:5.1f}%)")

        # Pattern Detection
        report.append("\n" + "-" * 40)
        report.append("PATTERN DETECTION")
        report.append("-" * 40)
        patterns = self.statistics.get('pattern_counts', {})
        for name, count in patterns.items():
            report.append(f"  {name:20} {count:8,}")

        # Metadata Availability
        report.append("\n" + "-" * 40)
        report.append("METADATA AVAILABILITY")
        report.append("-" * 40)
        meta = self.statistics.get('metadata_availability', {})
        for name, count in meta.items():
            pct = (count / self.statistics.get('total_records', 1)) * 100
            report.append(f"  {name:20} {count:8,} ({pct:5.1f}%)")

        # Top Tokens
        report.append("\n" + "-" * 40)
        report.append("TOP FILENAME TOKENS")
        report.append("-" * 40)
        tokens = self.statistics.get('filename_analysis', {}).get('top_tokens', {})
        for token, count in list(tokens.items())[:15]:
            report.append(f"  {token:20} {count:8,}")

        # Data Quality
        report.append("\n" + "-" * 40)
        report.append("DATA QUALITY")
        report.append("-" * 40)
        quality = self.statistics.get('data_quality', {})
        report.append(f"  Quality Score: {quality.get('quality_score', 0):.1f}/100")
        report.append(f"  Uncategorized: {quality.get('uncategorized_count', 0):,}")
        report.append(f"  Duplicates: {quality.get('duplicate_count', 0):,}")
        report.append(f"  Unknown Extensions: {quality.get('unknown_extension_count', 0):,}")

        # Train/Test Split
        if 'train_test_split' in self.statistics:
            report.append("\n" + "-" * 40)
            report.append("TRAIN/TEST SPLIT")
            report.append("-" * 40)
            split = self.statistics['train_test_split']
            report.append(f"  Train Size: {split['train_size']:,}")
            report.append(f"  Test Size: {split['test_size']:,}")
            report.append(f"  Test Ratio: {split['test_ratio']:.1%}")

        # Vocabulary
        if 'vocabulary' in self.statistics:
            report.append("\n" + "-" * 40)
            report.append("VOCABULARY")
            report.append("-" * 40)
            vocab = self.statistics['vocabulary']
            report.append(f"  Size: {vocab['size']:,}")
            report.append(f"  Min Frequency: {vocab['min_freq']}")

        report.append("\n" + "=" * 60)

        return "\n".join(report)


def main():
    """Run preprocessing pipeline."""
    import sys
    import argparse

    parser = argparse.ArgumentParser(description='Preprocess file organization data for ML')
    parser.add_argument('--input', '-i', required=True, help='Path to organization report JSON')
    parser.add_argument('--output', '-o', default='./ml_data', help='Output directory for processed data')
    parser.add_argument('--test-ratio', type=float, default=0.2, help='Test set ratio (default: 0.2)')
    parser.add_argument('--min-freq', type=int, default=5, help='Minimum token frequency for vocabulary')
    parser.add_argument('--report-only', action='store_true', help='Only generate report, no export')

    args = parser.parse_args()

    print("Initializing Data Preprocessor...")
    preprocessor = DataPreprocessor()

    print(f"Loading data from: {args.input}")
    preprocessor.load_data(args.input)

    print("Extracting features...")
    preprocessor.extract_all_features()

    print("Computing statistics...")
    preprocessor.compute_statistics()

    print("Validating data quality...")
    preprocessor.validate_data_quality()

    # Generate report
    report = preprocessor.generate_report()
    print(report)

    if not args.report_only:
        print(f"\nExporting data to: {args.output}")
        output_files = preprocessor.export_for_training(
            args.output,
            include_test_split=True
        )

        print("\nGenerated files:")
        for name, path in output_files.items():
            size = os.path.getsize(path)
            print(f"  {name:15} {path} ({size:,} bytes)")

    print("\nPreprocessing complete!")


if __name__ == "__main__":
    main()
