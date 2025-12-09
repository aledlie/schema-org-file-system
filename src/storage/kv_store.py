#!/usr/bin/env python3
"""
Key-Value storage for flexible, schema-less data.

Provides a Redis-like interface using SQLite for persistence.
Supports namespacing, TTL, and JSON values.

Design allows easy migration to Redis/Memcached in the future.
"""

import json
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union
from contextlib import contextmanager

from sqlalchemy import create_engine, event, func, and_
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, KeyValueStore


class KeyValueStorage:
    """
    Key-Value storage with namespace support.

    Features:
    - Namespace isolation (like Redis databases)
    - TTL support for automatic expiration
    - JSON value serialization
    - Atomic increment/decrement operations
    - Pattern-based key scanning

    Can be swapped with Redis by implementing the same interface.
    """

    # Default namespaces
    NAMESPACE_CACHE = 'cache'           # Temporary cached data
    NAMESPACE_CONFIG = 'config'         # Configuration values
    NAMESPACE_METADATA = 'metadata'     # File metadata overflow
    NAMESPACE_STATS = 'stats'           # Statistics and counters
    NAMESPACE_SESSION = 'session'       # Session-specific data
    NAMESPACE_FEATURE = 'feature'       # Feature flags

    def __init__(self, db_path: str = 'results/file_organization.db'):
        """
        Initialize key-value storage.

        Args:
            db_path: Path to SQLite database (shared with graph store)
        """
        self.db_path = db_path
        self.engine = create_engine(f'sqlite:///{db_path}', echo=False)

        # SQLite optimizations
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        # Create tables
        Base.metadata.create_all(self.engine)

        self.SessionLocal = sessionmaker(bind=self.engine)

    def get_session(self) -> Session:
        """Get a database session."""
        return self.SessionLocal()

    @contextmanager
    def session_scope(self):
        """Provide a transactional scope around a series of operations."""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # =========================================================================
    # Basic Operations
    # =========================================================================

    def get(
        self,
        key: str,
        namespace: str = NAMESPACE_CACHE,
        default: Any = None
    ) -> Any:
        """
        Get a value by key.

        Args:
            key: The key to retrieve
            namespace: Namespace for the key
            default: Default value if key doesn't exist

        Returns:
            The value or default
        """
        with self.session_scope() as session:
            record = session.query(KeyValueStore).filter(
                and_(
                    KeyValueStore.namespace == namespace,
                    KeyValueStore.key == key
                )
            ).first()

            if not record:
                return default

            # Check TTL
            if record.expires_at and record.expires_at < datetime.utcnow():
                session.delete(record)
                return default

            return record.value

    def set(
        self,
        key: str,
        value: Any,
        namespace: str = NAMESPACE_CACHE,
        ttl_seconds: int = None,
        file_id: str = None
    ) -> bool:
        """
        Set a value.

        Args:
            key: The key to set
            value: The value (will be JSON serialized)
            namespace: Namespace for the key
            ttl_seconds: Time-to-live in seconds (None for permanent)
            file_id: Optional file association

        Returns:
            True if successful
        """
        with self.session_scope() as session:
            # Calculate expiration
            expires_at = None
            if ttl_seconds:
                expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)

            # Determine value type
            value_type = self._get_value_type(value)

            # Check if exists
            record = session.query(KeyValueStore).filter(
                and_(
                    KeyValueStore.namespace == namespace,
                    KeyValueStore.key == key
                )
            ).first()

            if record:
                record.value = value
                record.value_type = value_type
                record.expires_at = expires_at
                record.file_id = file_id
                record.updated_at = datetime.utcnow()
            else:
                record = KeyValueStore(
                    namespace=namespace,
                    key=key,
                    value=value,
                    value_type=value_type,
                    expires_at=expires_at,
                    file_id=file_id
                )
                session.add(record)

            return True

    def delete(self, key: str, namespace: str = NAMESPACE_CACHE) -> bool:
        """
        Delete a key.

        Args:
            key: The key to delete
            namespace: Namespace for the key

        Returns:
            True if key existed and was deleted
        """
        with self.session_scope() as session:
            result = session.query(KeyValueStore).filter(
                and_(
                    KeyValueStore.namespace == namespace,
                    KeyValueStore.key == key
                )
            ).delete()
            return result > 0

    def exists(self, key: str, namespace: str = NAMESPACE_CACHE) -> bool:
        """
        Check if a key exists.

        Args:
            key: The key to check
            namespace: Namespace for the key

        Returns:
            True if key exists and hasn't expired
        """
        with self.session_scope() as session:
            record = session.query(KeyValueStore).filter(
                and_(
                    KeyValueStore.namespace == namespace,
                    KeyValueStore.key == key
                )
            ).first()

            if not record:
                return False

            # Check TTL
            if record.expires_at and record.expires_at < datetime.utcnow():
                session.delete(record)
                return False

            return True

    # =========================================================================
    # Batch Operations
    # =========================================================================

    def mget(
        self,
        keys: List[str],
        namespace: str = NAMESPACE_CACHE
    ) -> Dict[str, Any]:
        """
        Get multiple values at once.

        Args:
            keys: List of keys to retrieve
            namespace: Namespace for the keys

        Returns:
            Dictionary of key -> value (missing keys omitted)
        """
        with self.session_scope() as session:
            records = session.query(KeyValueStore).filter(
                and_(
                    KeyValueStore.namespace == namespace,
                    KeyValueStore.key.in_(keys)
                )
            ).all()

            now = datetime.utcnow()
            result = {}

            for record in records:
                if record.expires_at and record.expires_at < now:
                    session.delete(record)
                    continue
                result[record.key] = record.value

            return result

    def mset(
        self,
        mapping: Dict[str, Any],
        namespace: str = NAMESPACE_CACHE,
        ttl_seconds: int = None
    ) -> bool:
        """
        Set multiple values at once.

        Args:
            mapping: Dictionary of key -> value
            namespace: Namespace for the keys
            ttl_seconds: Optional TTL for all keys

        Returns:
            True if successful
        """
        for key, value in mapping.items():
            self.set(key, value, namespace, ttl_seconds)
        return True

    # =========================================================================
    # Counter Operations
    # =========================================================================

    def incr(
        self,
        key: str,
        amount: int = 1,
        namespace: str = NAMESPACE_STATS
    ) -> int:
        """
        Increment a counter.

        Args:
            key: The counter key
            amount: Amount to increment by
            namespace: Namespace for the counter

        Returns:
            New counter value
        """
        with self.session_scope() as session:
            record = session.query(KeyValueStore).filter(
                and_(
                    KeyValueStore.namespace == namespace,
                    KeyValueStore.key == key
                )
            ).first()

            if record:
                current = record.value or 0
                record.value = current + amount
                record.updated_at = datetime.utcnow()
                return record.value
            else:
                record = KeyValueStore(
                    namespace=namespace,
                    key=key,
                    value=amount,
                    value_type='int'
                )
                session.add(record)
                return amount

    def decr(
        self,
        key: str,
        amount: int = 1,
        namespace: str = NAMESPACE_STATS
    ) -> int:
        """
        Decrement a counter.

        Args:
            key: The counter key
            amount: Amount to decrement by
            namespace: Namespace for the counter

        Returns:
            New counter value
        """
        return self.incr(key, -amount, namespace)

    def incrby_float(
        self,
        key: str,
        amount: float,
        namespace: str = NAMESPACE_STATS
    ) -> float:
        """
        Increment a float counter.

        Args:
            key: The counter key
            amount: Amount to increment by
            namespace: Namespace for the counter

        Returns:
            New counter value
        """
        with self.session_scope() as session:
            record = session.query(KeyValueStore).filter(
                and_(
                    KeyValueStore.namespace == namespace,
                    KeyValueStore.key == key
                )
            ).first()

            if record:
                current = float(record.value or 0)
                record.value = current + amount
                record.value_type = 'float'
                record.updated_at = datetime.utcnow()
                return record.value
            else:
                record = KeyValueStore(
                    namespace=namespace,
                    key=key,
                    value=amount,
                    value_type='float'
                )
                session.add(record)
                return amount

    # =========================================================================
    # Scan and Pattern Matching
    # =========================================================================

    def keys(
        self,
        pattern: str = '*',
        namespace: str = NAMESPACE_CACHE
    ) -> List[str]:
        """
        Get all keys matching a pattern.

        Args:
            pattern: Glob-style pattern (* for wildcard)
            namespace: Namespace to search

        Returns:
            List of matching keys
        """
        with self.session_scope() as session:
            query = session.query(KeyValueStore.key).filter(
                KeyValueStore.namespace == namespace
            )

            if pattern != '*':
                # Convert glob to SQL LIKE
                sql_pattern = pattern.replace('*', '%').replace('?', '_')
                query = query.filter(KeyValueStore.key.like(sql_pattern))

            return [row[0] for row in query.all()]

    def scan(
        self,
        namespace: str = NAMESPACE_CACHE,
        match: str = None,
        count: int = 100,
        cursor: int = 0
    ) -> tuple:
        """
        Incrementally iterate over keys.

        Args:
            namespace: Namespace to scan
            match: Optional pattern to match
            count: Number of keys to return
            cursor: Position to start from

        Returns:
            Tuple of (next_cursor, list of keys)
        """
        with self.session_scope() as session:
            query = session.query(KeyValueStore.key, KeyValueStore.id).filter(
                KeyValueStore.namespace == namespace
            )

            if match:
                sql_pattern = match.replace('*', '%').replace('?', '_')
                query = query.filter(KeyValueStore.key.like(sql_pattern))

            query = query.filter(KeyValueStore.id > cursor)\
                .order_by(KeyValueStore.id)\
                .limit(count)

            results = query.all()

            if not results:
                return (0, [])

            keys = [row[0] for row in results]
            next_cursor = results[-1][1]

            # Check if there are more
            more = session.query(KeyValueStore.id).filter(
                and_(
                    KeyValueStore.namespace == namespace,
                    KeyValueStore.id > next_cursor
                )
            ).first()

            if not more:
                next_cursor = 0

            return (next_cursor, keys)

    # =========================================================================
    # Hash Operations (nested dictionaries)
    # =========================================================================

    def hget(
        self,
        name: str,
        key: str,
        namespace: str = NAMESPACE_METADATA
    ) -> Any:
        """
        Get a field from a hash.

        Args:
            name: Hash name
            key: Field key
            namespace: Namespace

        Returns:
            Field value or None
        """
        hash_key = f"{name}:{key}"
        return self.get(hash_key, namespace)

    def hset(
        self,
        name: str,
        key: str,
        value: Any,
        namespace: str = NAMESPACE_METADATA
    ) -> bool:
        """
        Set a field in a hash.

        Args:
            name: Hash name
            key: Field key
            value: Field value
            namespace: Namespace

        Returns:
            True if successful
        """
        hash_key = f"{name}:{key}"
        return self.set(hash_key, value, namespace)

    def hgetall(
        self,
        name: str,
        namespace: str = NAMESPACE_METADATA
    ) -> Dict[str, Any]:
        """
        Get all fields from a hash.

        Args:
            name: Hash name
            namespace: Namespace

        Returns:
            Dictionary of field -> value
        """
        pattern = f"{name}:*"
        keys = self.keys(pattern, namespace)

        result = {}
        for key in keys:
            field = key[len(name) + 1:]  # Remove "name:" prefix
            result[field] = self.get(key, namespace)

        return result

    def hdel(
        self,
        name: str,
        *keys: str,
        namespace: str = NAMESPACE_METADATA
    ) -> int:
        """
        Delete fields from a hash.

        Args:
            name: Hash name
            *keys: Field keys to delete
            namespace: Namespace

        Returns:
            Number of fields deleted
        """
        count = 0
        for key in keys:
            hash_key = f"{name}:{key}"
            if self.delete(hash_key, namespace):
                count += 1
        return count

    # =========================================================================
    # TTL Operations
    # =========================================================================

    def ttl(self, key: str, namespace: str = NAMESPACE_CACHE) -> Optional[int]:
        """
        Get remaining TTL for a key.

        Args:
            key: The key
            namespace: Namespace

        Returns:
            Seconds remaining, -1 if no TTL, None if key doesn't exist
        """
        with self.session_scope() as session:
            record = session.query(KeyValueStore).filter(
                and_(
                    KeyValueStore.namespace == namespace,
                    KeyValueStore.key == key
                )
            ).first()

            if not record:
                return None

            if not record.expires_at:
                return -1

            remaining = (record.expires_at - datetime.utcnow()).total_seconds()
            return max(0, int(remaining))

    def expire(
        self,
        key: str,
        seconds: int,
        namespace: str = NAMESPACE_CACHE
    ) -> bool:
        """
        Set TTL on an existing key.

        Args:
            key: The key
            seconds: TTL in seconds
            namespace: Namespace

        Returns:
            True if key exists and TTL was set
        """
        with self.session_scope() as session:
            record = session.query(KeyValueStore).filter(
                and_(
                    KeyValueStore.namespace == namespace,
                    KeyValueStore.key == key
                )
            ).first()

            if not record:
                return False

            record.expires_at = datetime.utcnow() + timedelta(seconds=seconds)
            return True

    def persist(self, key: str, namespace: str = NAMESPACE_CACHE) -> bool:
        """
        Remove TTL from a key, making it permanent.

        Args:
            key: The key
            namespace: Namespace

        Returns:
            True if key exists and TTL was removed
        """
        with self.session_scope() as session:
            record = session.query(KeyValueStore).filter(
                and_(
                    KeyValueStore.namespace == namespace,
                    KeyValueStore.key == key
                )
            ).first()

            if not record:
                return False

            record.expires_at = None
            return True

    # =========================================================================
    # Cleanup Operations
    # =========================================================================

    def cleanup_expired(self) -> int:
        """
        Remove all expired keys.

        Returns:
            Number of keys removed
        """
        with self.session_scope() as session:
            result = session.query(KeyValueStore).filter(
                and_(
                    KeyValueStore.expires_at.isnot(None),
                    KeyValueStore.expires_at < datetime.utcnow()
                )
            ).delete()
            return result

    def flush_namespace(self, namespace: str) -> int:
        """
        Delete all keys in a namespace.

        Args:
            namespace: Namespace to flush

        Returns:
            Number of keys deleted
        """
        with self.session_scope() as session:
            result = session.query(KeyValueStore).filter(
                KeyValueStore.namespace == namespace
            ).delete()
            return result

    def flush_all(self) -> int:
        """
        Delete all keys in all namespaces.

        Returns:
            Number of keys deleted
        """
        with self.session_scope() as session:
            result = session.query(KeyValueStore).delete()
            return result

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _get_value_type(self, value: Any) -> str:
        """Determine the type of a value."""
        if isinstance(value, bool):
            return 'bool'
        elif isinstance(value, int):
            return 'int'
        elif isinstance(value, float):
            return 'float'
        elif isinstance(value, str):
            return 'string'
        elif isinstance(value, (dict, list)):
            return 'json'
        else:
            return 'json'

    def info(self) -> Dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dictionary with stats
        """
        with self.session_scope() as session:
            total = session.query(func.count(KeyValueStore.id)).scalar()

            by_namespace = session.query(
                KeyValueStore.namespace,
                func.count(KeyValueStore.id)
            ).group_by(KeyValueStore.namespace).all()

            expired = session.query(func.count(KeyValueStore.id)).filter(
                and_(
                    KeyValueStore.expires_at.isnot(None),
                    KeyValueStore.expires_at < datetime.utcnow()
                )
            ).scalar()

            return {
                'total_keys': total,
                'by_namespace': {ns: count for ns, count in by_namespace},
                'expired_keys': expired
            }


# Convenience functions for common operations
def get_kv_store(db_path: str = 'results/file_organization.db') -> KeyValueStorage:
    """Get a KeyValueStorage instance."""
    return KeyValueStorage(db_path)
