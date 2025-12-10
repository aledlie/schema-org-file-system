"""
Sentry Error Tracking Module

Provides comprehensive error tracking and performance monitoring
for the Schema.org File Organization System using Sentry SDK v2.

Usage:
    from error_tracking import init_sentry, capture_error, track_operation

    # Initialize at app startup
    init_sentry()

    # Capture errors
    try:
        process_file(path)
    except Exception as e:
        capture_error(e, context={'file_path': path})

    # Track performance
    with track_operation('classify_image', file_path=path):
        result = classifier.classify(image)
"""

import os
import functools
from typing import Optional, Dict, Any, Callable
from contextlib import contextmanager

# Sentry SDK import with graceful degradation
try:
    import sentry_sdk
    from sentry_sdk import capture_exception, capture_message, set_tag, set_context
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    # Stub implementations
    def capture_exception(*args, **kwargs): pass
    def capture_message(*args, **kwargs): pass
    def set_tag(*args, **kwargs): pass
    def set_context(*args, **kwargs): pass


# Error severity levels
class ErrorLevel:
    FATAL = 'fatal'      # System unusable
    ERROR = 'error'      # Operation failed
    WARNING = 'warning'  # Recoverable issue
    INFO = 'info'        # Informational
    DEBUG = 'debug'      # Debug only


def init_sentry(
    dsn: Optional[str] = None,
    environment: Optional[str] = None,
    traces_sample_rate: float = 0.1,
    profiles_sample_rate: float = 0.1,
    enable_logs: bool = True
) -> bool:
    """
    Initialize Sentry error tracking.

    Args:
        dsn: Sentry DSN (defaults to SENTRY_DSN env var)
        environment: Environment name (defaults to NODE_ENV or 'development')
        traces_sample_rate: Percentage of transactions to trace (0.0-1.0)
        profiles_sample_rate: Percentage of transactions to profile (0.0-1.0)
        enable_logs: Whether to enable Sentry logs

    Returns:
        True if Sentry initialized successfully, False otherwise
    """
    if not SENTRY_AVAILABLE:
        print("Warning: sentry-sdk not installed. Error tracking disabled.")
        print("Install with: pip install sentry-sdk")
        return False

    dsn = dsn or os.environ.get('SENTRY_DSN')
    if not dsn:
        print("Warning: SENTRY_DSN not set. Error tracking disabled.")
        return False

    environment = environment or os.environ.get('NODE_ENV', 'development')

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=traces_sample_rate,
            profiles_sample_rate=profiles_sample_rate,
            send_default_pii=False,  # Don't send PII by default
            attach_stacktrace=True,
            # Release tracking
            release=os.environ.get('APP_VERSION', '1.2.0'),
        )

        # Set default tags
        set_tag('service', 'schema-org-file-system')
        set_tag('python_version', os.sys.version.split()[0])

        print(f"Sentry initialized for environment: {environment}")
        return True

    except Exception as e:
        print(f"Warning: Failed to initialize Sentry: {e}")
        return False


def capture_error(
    error: Exception,
    level: str = ErrorLevel.ERROR,
    context: Optional[Dict[str, Any]] = None,
    tags: Optional[Dict[str, str]] = None,
    user_id: Optional[str] = None
) -> Optional[str]:
    """
    Capture an error to Sentry with full context.

    Args:
        error: The exception to capture
        level: Error severity level
        context: Additional context data
        tags: Additional tags for filtering
        user_id: User identifier if available

    Returns:
        Sentry event ID if captured, None otherwise
    """
    if not SENTRY_AVAILABLE:
        # Fallback to console logging
        print(f"[{level.upper()}] {type(error).__name__}: {error}")
        if context:
            print(f"  Context: {context}")
        return None

    with sentry_sdk.push_scope() as scope:
        # Set severity level
        scope.level = level

        # Set user if provided
        if user_id:
            scope.set_user({'id': user_id})

        # Add tags
        if tags:
            for key, value in tags.items():
                scope.set_tag(key, value)

        # Add context
        if context:
            scope.set_context('error_context', context)

        # Capture the exception
        event_id = sentry_sdk.capture_exception(error)
        return event_id


def capture_warning(
    message: str,
    context: Optional[Dict[str, Any]] = None,
    tags: Optional[Dict[str, str]] = None
) -> Optional[str]:
    """Capture a warning message to Sentry."""
    if not SENTRY_AVAILABLE:
        print(f"[WARNING] {message}")
        return None

    with sentry_sdk.push_scope() as scope:
        scope.level = ErrorLevel.WARNING
        if tags:
            for key, value in tags.items():
                scope.set_tag(key, value)
        if context:
            scope.set_context('warning_context', context)
        return sentry_sdk.capture_message(message)


@contextmanager
def track_operation(
    operation_name: str,
    op_type: str = 'task',
    **attributes
):
    """
    Context manager for tracking operation performance.

    Usage:
        with track_operation('classify_image', file_path='/path/to/file.jpg'):
            result = classifier.classify(image)

    Args:
        operation_name: Name of the operation
        op_type: Type of operation (task, db, http, etc.)
        **attributes: Additional attributes to attach
    """
    if not SENTRY_AVAILABLE:
        yield
        return

    with sentry_sdk.start_span(op=op_type, name=operation_name) as span:
        for key, value in attributes.items():
            span.set_data(key, str(value) if value is not None else None)
        try:
            yield span
        except Exception as e:
            span.set_status('error')
            capture_error(e, context={'operation': operation_name, **attributes})
            raise


def track_error(
    operation: str = None,
    level: str = ErrorLevel.ERROR,
    reraise: bool = True
) -> Callable:
    """
    Decorator for automatic error tracking.

    Usage:
        @track_error('process_file')
        def process_file(path):
            # ... your code

        @track_error('classify', reraise=False)
        def classify(image):
            # Errors are captured but not re-raised
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            op_name = operation or func.__name__
            try:
                with track_operation(op_name, op_type='function'):
                    return func(*args, **kwargs)
            except Exception as e:
                capture_error(
                    e,
                    level=level,
                    context={
                        'function': func.__name__,
                        'args_count': len(args),
                        'kwargs_keys': list(kwargs.keys())
                    }
                )
                if reraise:
                    raise
                return None
        return wrapper
    return decorator


class FileProcessingErrorTracker:
    """
    Specialized error tracker for file processing operations.

    Usage:
        tracker = FileProcessingErrorTracker()

        for file in files:
            with tracker.track_file(file.path):
                process_file(file)

        tracker.print_summary()
    """

    def __init__(self):
        self.processed = 0
        self.succeeded = 0
        self.failed = 0
        self.errors: list[Dict[str, Any]] = []

    @contextmanager
    def track_file(self, file_path: str, category: Optional[str] = None):
        """Track processing of a single file."""
        self.processed += 1
        context = {
            'file_path': file_path,
            'file_number': self.processed,
            'category': category
        }

        try:
            with track_operation('process_file', op_type='file', **context):
                yield
            self.succeeded += 1
        except Exception as e:
            self.failed += 1
            error_info = {
                'file_path': file_path,
                'error_type': type(e).__name__,
                'error_message': str(e),
                'category': category
            }
            self.errors.append(error_info)

            capture_error(
                e,
                level=ErrorLevel.WARNING,  # File errors are usually recoverable
                context=context,
                tags={'error_type': type(e).__name__}
            )
            # Don't re-raise - continue processing other files

    def print_summary(self):
        """Print processing summary."""
        print(f"\nFile Processing Summary:")
        print(f"  Processed: {self.processed}")
        print(f"  Succeeded: {self.succeeded} ({self.succeeded/max(self.processed,1)*100:.1f}%)")
        print(f"  Failed: {self.failed}")

        if self.errors:
            # Group errors by type
            error_types: Dict[str, int] = {}
            for error in self.errors:
                error_type = error['error_type']
                error_types[error_type] = error_types.get(error_type, 0) + 1

            print(f"\nError breakdown:")
            for error_type, count in sorted(error_types.items(), key=lambda x: -x[1]):
                print(f"  {error_type}: {count}")

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics as dict."""
        return {
            'processed': self.processed,
            'succeeded': self.succeeded,
            'failed': self.failed,
            'success_rate': self.succeeded / max(self.processed, 1),
            'errors': self.errors
        }


# Singleton tracker for the application
_file_tracker: Optional[FileProcessingErrorTracker] = None


def get_file_tracker() -> FileProcessingErrorTracker:
    """Get or create the singleton file tracker."""
    global _file_tracker
    if _file_tracker is None:
        _file_tracker = FileProcessingErrorTracker()
    return _file_tracker


def reset_file_tracker() -> FileProcessingErrorTracker:
    """Reset the file tracker for a new processing run."""
    global _file_tracker
    _file_tracker = FileProcessingErrorTracker()
    return _file_tracker


# Test function
def test_sentry_connection() -> bool:
    """
    Test Sentry connection by sending a test message.

    Returns:
        True if message sent successfully
    """
    if not SENTRY_AVAILABLE:
        print("Sentry SDK not available")
        return False

    try:
        event_id = sentry_sdk.capture_message(
            "Test message from schema-org-file-system",
            level="info"
        )
        print(f"Test message sent to Sentry. Event ID: {event_id}")
        return True
    except Exception as e:
        print(f"Failed to send test message: {e}")
        return False


if __name__ == "__main__":
    # Test the module
    import argparse

    parser = argparse.ArgumentParser(description="Test Sentry error tracking")
    parser.add_argument('--test', action='store_true', help="Send test message to Sentry")
    parser.add_argument('--dsn', help="Sentry DSN (or set SENTRY_DSN env var)")
    args = parser.parse_args()

    if args.dsn:
        os.environ['SENTRY_DSN'] = args.dsn

    if init_sentry():
        print("Sentry initialized successfully!")
        if args.test:
            test_sentry_connection()
    else:
        print("Sentry initialization failed or disabled")
