"""
Schema.org Structured Data System for Intelligent File Organization

A comprehensive, production-ready system for generating, validating, and managing
Schema.org structured data for various file types.
"""

__version__ = "1.2.0"
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
from .health_check import (
    SystemHealthChecker,
    check_system,
    get_health_checker,
    require_feature
)
from .error_tracking import (
    init_sentry,
    capture_error,
    capture_warning,
    track_operation,
    track_error,
    FileProcessingErrorTracker,
    ErrorLevel
)

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
    'MetadataEnricher',
    'SystemHealthChecker',
    'check_system',
    'get_health_checker',
    'require_feature',
    'init_sentry',
    'capture_error',
    'capture_warning',
    'track_operation',
    'track_error',
    'FileProcessingErrorTracker',
    'ErrorLevel'
]
