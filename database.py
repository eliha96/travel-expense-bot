import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from config import DB_PATH, TURSO_DATABASE_URL, TURSO_AUTH_TOKEN

logger = logging.getLogger(__name__)

def is_turso_enabled() -> bool:
    return bool(TURSO_DATABASE_URL)

def get_turso_client():
    import libsql_client
    return libsql_client.create_client_sync(url=TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)

def get_sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def execute_write(query: str, params: tuple = ()) -> int:
    """Executes an INSERT / UPDATE / DELETE statement and returns last_insert_rowid if available."""
    if is_turso_enabled():
        client = get_turso_client()
        try:
            res = client.execute(query, list(params))
            return res.last_insert_rowid or 0
        finally:
            client.close()
    else:
        with get_sqlite_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid or 0

def execute_read(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Executes a SELECT query and returns a list of dictionaries."""
    if is_turso_enabled():
        client = get_turso_client()
        try:
            res = client.execute(query, list(params))
            return [dict(zip(res.columns, row)) for row in res.rows]
        finally:
            client.close()
    else:
        with get_sqlite_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

def init_db():
    """Initialize database tables for car trips, transit expenses, and user settings."""
    if is_turso_enabled():
        logger.info("Initializing database on Turso Cloud SQLite...")
    else:
        logger.info("Initializing database on local SQLite...")

    # Car trips table
    execute_write("""
        CREATE TABLE IF NOT EXISTS car_trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            destination TEXT NOT NULL,
            distance_km REAL NOT NULL,
            rate_per_km REAL NOT NULL,
            cost REAL NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Public transit table
    execute_write("""
        CREATE TABLE IF NOT EXISTS transit_trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            details TEXT NOT NULL,
            cost REAL NOT NULL,
            image_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Settings / Registered Chat IDs table
    execute_write("""
        CREATE TABLE IF NOT EXISTS registered_chats (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

def save_chat_id(chat_id: int, username: str = "", first_name: str = ""):
    """Saves or updates active chat ID to receive automated reminders and reports."""
    execute_write("""
        INSERT INTO registered_chats (chat_id, username, first_name, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(chat_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            updated_at=CURRENT_TIMESTAMP
    """, (chat_id, username or "", first_name or ""))

def get_registered_chat_ids() -> List[int]:
    """Returns all registered chat IDs that should receive reminders and reports."""
    rows = execute_read("SELECT chat_id FROM registered_chats")
    return [row["chat_id"] for row in rows]

def add_car_trip(date: str, destination: str, distance_km: float, rate_per_km: float, notes: str = "") -> int:
    cost = round(distance_km * rate_per_km, 2)
    return execute_write("""
        INSERT INTO car_trips (date, destination, distance_km, rate_per_km, cost, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (date, destination, distance_km, rate_per_km, cost, notes))

def add_transit_trip(date: str, details: str, cost: float, image_path: Optional[str] = None) -> int:
    return execute_write("""
        INSERT INTO transit_trips (date, details, cost, image_path)
        VALUES (?, ?, ?, ?)
    """, (date, details, round(cost, 2), image_path))

def get_month_trips(year: int, month: int) -> Dict[str, List[Dict[str, Any]]]:
    """Retrieve all car and transit trips for a given year and month (formatted as YYYY-MM)."""
    month_str = f"{year:04d}-{month:02d}"
    car_trips = execute_read("""
        SELECT id, date, destination, distance_km, rate_per_km, cost, notes
        FROM car_trips
        WHERE date LIKE ?
        ORDER BY date ASC, id ASC
    """, (f"{month_str}%",))

    transit_trips = execute_read("""
        SELECT id, date, details, cost, image_path
        FROM transit_trips
        WHERE date LIKE ?
        ORDER BY date ASC, id ASC
    """, (f"{month_str}%",))

    return {
        "car_trips": car_trips,
        "transit_trips": transit_trips
    }

def delete_last_trip(trip_type: str = "car") -> Optional[Dict[str, Any]]:
    table = "car_trips" if trip_type == "car" else "transit_trips"
    rows = execute_read(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 1")
    if rows:
        trip_data = rows[0]
        execute_write(f"DELETE FROM {table} WHERE id = ?", (trip_data["id"],))
        return trip_data
    return None
