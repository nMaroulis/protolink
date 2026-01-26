import json
import sqlite3
from typing import Any

from protolink.storage.base import Storage


class SQLiteStorage(Storage):
    """SQLite-based storage implementation.

    Stores data as JSON in a SQLite database. Each instance is bound to a specific
    'namespace' (key) which acts as the primary identifier for the data.
    """

    def __init__(
        self,
        db_path: str = "storage.db",
        table_name: str = "storage",
        namespace: str = "default",
    ):
        """Initializes the SQLite storage.

        Args:
            db_path: Path to the SQLite database file.
            table_name: Name of the table to store data in.
            namespace: Unique identifier for this storage instance's data.
        """
        self.db_path = db_path
        self.table_name = table_name
        self.namespace = namespace
        self._init_db()

    def _init_db(self) -> None:
        """Initializes the database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            conn.commit()

    def save(self, data: Any) -> None:
        """Saves data to the storage.

        Data is serialized to JSON before storage.
        """
        serialized_data = json.dumps(data)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {self.table_name} (key, value) VALUES (?, ?)",
                (self.namespace, serialized_data),
            )
            conn.commit()

    def load(self) -> Any:
        """Loads data from the storage.

        Returns:
            The loaded data deserialized from JSON, or None if not found.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(f"SELECT value FROM {self.table_name} WHERE key = ?", (self.namespace,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None

    def update(self, data: Any) -> None:
        """Updates existing data in the storage.

        Functionally equivalent to save() for this dictionary-style storage.
        """
        self.save(data)

    def delete(self) -> None:
        """Deletes the data from the storage."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"DELETE FROM {self.table_name} WHERE key = ?", (self.namespace,))
            conn.commit()
