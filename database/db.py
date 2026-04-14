from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class DatabaseManager:
    """SQLite helper for raw WhatsApp messages, parsed carpools, and cached locations."""

    def __init__(self, db_path: str | None = None) -> None:
        root = Path(__file__).resolve().parent.parent
        self.db_path = Path(db_path) if db_path else root / "carpool_ai.sqlite3"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    processed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(sender, message_text, timestamp)
                );

                CREATE TABLE IF NOT EXISTS carpools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT,
                    ride_type TEXT,
                    pickup_location TEXT,
                    dropoff_location TEXT,
                    time TEXT,
                    seats INTEGER,
                    pickup_lat REAL,
                    pickup_lon REAL,
                    dropoff_lat REAL,
                    dropoff_lon REAL,
                    raw_message_id INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(raw_message_id) REFERENCES messages(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS location_cache (
                    location_name TEXT PRIMARY KEY,
                    display_name TEXT,
                    lat REAL,
                    lon REAL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # Lightweight migration for existing databases created before ride_type existed.
            try:
                connection.execute("ALTER TABLE carpools ADD COLUMN ride_type TEXT")
            except sqlite3.OperationalError:
                pass

    def insert_message(self, sender: str, message_text: str, timestamp: str) -> tuple[int, bool]:
        """Insert a raw WhatsApp message and return (message_id, was_inserted)."""

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO messages (sender, message_text, timestamp)
                VALUES (?, ?, ?)
                """,
                (sender, message_text, timestamp),
            )

            if cursor.lastrowid:
                return int(cursor.lastrowid), True

            row = connection.execute(
                """
                SELECT id
                FROM messages
                WHERE sender = ? AND message_text = ? AND timestamp = ?
                """,
                (sender, message_text, timestamp),
            ).fetchone()

            if row is None:
                raise RuntimeError("Failed to insert or retrieve message record.")

            return int(row["id"]), False

    def insert_carpool(
        self,
        sender: str,
        ride_type: str | None,
        pickup_location: str | None,
        dropoff_location: str | None,
        time_text: str | None,
        seats: int | None,
        raw_message_id: int,
        pickup_coords: tuple[float, float] | None = None,
        dropoff_coords: tuple[float, float] | None = None,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO carpools (
                    sender,
                    ride_type,
                    pickup_location,
                    dropoff_location,
                    time,
                    seats,
                    pickup_lat,
                    pickup_lon,
                    dropoff_lat,
                    dropoff_lon,
                    raw_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sender,
                    ride_type,
                    pickup_location,
                    dropoff_location,
                    time_text,
                    seats,
                    pickup_coords[0] if pickup_coords else None,
                    pickup_coords[1] if pickup_coords else None,
                    dropoff_coords[0] if dropoff_coords else None,
                    dropoff_coords[1] if dropoff_coords else None,
                    raw_message_id,
                ),
            )
            return int(cursor.lastrowid)

    def get_recent_carpools(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT carpools.*, messages.message_text AS raw_message_text
                FROM carpools
                LEFT JOIN messages ON messages.id = carpools.raw_message_id
                ORDER BY COALESCE(carpools.created_at, carpools.id) DESC, carpools.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_all_carpools(self) -> list[dict[str, Any]]:
        return self.get_recent_carpools(limit=500)

    def cache_location(
        self,
        location_name: str,
        display_name: str,
        lat: float,
        lon: float,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO location_cache (location_name, display_name, lat, lon, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(location_name) DO UPDATE SET
                    display_name = excluded.display_name,
                    lat = excluded.lat,
                    lon = excluded.lon,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (location_name.strip().lower(), display_name, lat, lon),
            )

    def cache_location_failure(self, location_name: str, reason: str = "NOT_FOUND") -> None:
        """Cache failed lookups so we do not repeatedly hit free geocoding APIs."""

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO location_cache (location_name, display_name, lat, lon, updated_at)
                VALUES (?, ?, NULL, NULL, CURRENT_TIMESTAMP)
                ON CONFLICT(location_name) DO UPDATE SET
                    display_name = excluded.display_name,
                    lat = NULL,
                    lon = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (location_name.strip().lower(), reason),
            )

    def get_cached_location(self, location_name: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT location_name, display_name, lat, lon, updated_at
                FROM location_cache
                WHERE location_name = ?
                """,
                (location_name.strip().lower(),),
            ).fetchone()
            return dict(row) if row else None