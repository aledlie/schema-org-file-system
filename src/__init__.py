"""
Schema.org Structured Data System for Intelligent File Organization

A comprehensive, production-ready system for generating, validating, and managing
Schema.org structured data for various file types.
"""

__version__ = "1.0.0"
__author__ = "File Organization System"

from .base import SchemaOrgBase, SchemaContext
from .generators import (
    DocumentGenerator,
    ImageGenerator,
    VideoGenerator,
    AudioGenerator,
    CodeGenerator,
    DatasetGenerator,
    ArchiveGenerator
)
from .validator import SchemaValidator, ValidationReport
from .integration import SchemaIntegration, OutputFormat
from .enrichment import MetadataEnricher

__all__ = [
    'SchemaOrgBase',
    'SchemaContext',
    'DocumentGenerator',
    'ImageGenerator',
    'VideoGenerator',
    'AudioGenerator',
    'CodeGenerator',
    'DatasetGenerator',
    'ArchiveGenerator',
    'SchemaValidator',
    'ValidationReport',
    'SchemaIntegration',
    'OutputFormat',
    'MetadataEnricher'
]
