import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional
from config import DB_PATH

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables for car trips, transit expenses, and user settings."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Car trips table
        cursor.execute("""
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
        cursor.execute("""
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS registered_chats (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def save_chat_id(chat_id: int, username: str = "", first_name: str = ""):
    """Saves or updates active chat ID to receive automated reminders and reports."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO registered_chats (chat_id, username, first_name, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                updated_at=CURRENT_TIMESTAMP
        """, (chat_id, username or "", first_name or ""))
        conn.commit()

def get_registered_chat_ids() -> List[int]:
    """Returns all registered chat IDs that should receive reminders and reports."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM registered_chats")
        rows = cursor.fetchall()
        return [row["chat_id"] for row in rows]

def add_car_trip(date: str, destination: str, distance_km: float, rate_per_km: float, notes: str = "") -> int:
    cost = round(distance_km * rate_per_km, 2)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO car_trips (date, destination, distance_km, rate_per_km, cost, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (date, destination, distance_km, rate_per_km, cost, notes))
        conn.commit()
        return cursor.lastrowid

def add_transit_trip(date: str, details: str, cost: float, image_path: Optional[str] = None) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO transit_trips (date, details, cost, image_path)
            VALUES (?, ?, ?, ?)
        """, (date, details, round(cost, 2), image_path))
        conn.commit()
        return cursor.lastrowid

def get_month_trips(year: int, month: int) -> Dict[str, List[Dict[str, Any]]]:
    """Retrieve all car and transit trips for a given year and month (formatted as YYYY-MM)."""
    month_str = f"{year:04d}-{month:02d}"
    with get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, date, destination, distance_km, rate_per_km, cost, notes
            FROM car_trips
            WHERE date LIKE ?
            ORDER BY date ASC, id ASC
        """, (f"{month_str}%",))
        car_trips = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT id, date, details, cost, image_path
            FROM transit_trips
            WHERE date LIKE ?
            ORDER BY date ASC, id ASC
        """, (f"{month_str}%",))
        transit_trips = [dict(row) for row in cursor.fetchall()]
        
    return {
        "car_trips": car_trips,
        "transit_trips": transit_trips
    }

def delete_last_trip(trip_type: str = "car") -> Optional[Dict[str, Any]]:
    table = "car_trips" if trip_type == "car" else "transit_trips"
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            trip_data = dict(row)
            cursor.execute(f"DELETE FROM {table} WHERE id = ?", (trip_data["id"],))
            conn.commit()
            return trip_data
        return None
