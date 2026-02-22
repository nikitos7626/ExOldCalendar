from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import mysql.connector
from mysql.connector import pooling


@dataclass(slots=True)
class BookingRequest:
    id: str
    user_id: int
    username: str
    full_name: str
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    status: str  # pending|confirmed|declined|cancelled_by_client|cancelled_by_trainer
    created_at: str


class BookingStore:
    """MySQL storage for booking requests."""

    def __init__(self, settings):
        self._pool = None
        self._settings = settings
        self._init_database()
        self._lock = threading.Lock()

    def _get_connection(self):
        if self._pool is None:
            self._pool = pooling.MySQLConnectionPool(
                pool_name="booking_pool",
                pool_size=5,
                host=self._settings.mysql_host,
                port=self._settings.mysql_port,
                user=self._settings.mysql_user,
                password=self._settings.mysql_password,
                database=self._settings.mysql_database,
                autocommit=False
            )
        return self._pool.get_connection()

    def _init_database(self) -> None:
        """Create database and table if not exists."""
        conn = mysql.connector.connect(
            host=self._settings.mysql_host,
            port=self._settings.mysql_port,
            user=self._settings.mysql_user,
            password=self._settings.mysql_password
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self._settings.mysql_database}")
        cursor.execute(f"USE {self._settings.mysql_database}")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id VARCHAR(36) PRIMARY KEY,
                user_id BIGINT NOT NULL,
                username VARCHAR(255),
                full_name VARCHAR(255) NOT NULL,
                date DATE NOT NULL,
                time TIME NOT NULL,
                status VARCHAR(50) NOT NULL,
                created_at DATETIME NOT NULL,
                INDEX idx_user_id (user_id),
                INDEX idx_date_time (date, time),
                INDEX idx_status (status)
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()

    def get_slot_state(self, date_str: str, time_str: str) -> Optional[str]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT status FROM bookings 
                WHERE date = %s AND time = %s AND status IN ('pending', 'confirmed')
                LIMIT 1
                """,
                (date_str, time_str)
            )
            result = cursor.fetchone()
            return result[0] if result else None
        finally:
            cursor.close()
            conn.close()

    def create_request(
        self,
        *,
        user_id: int,
        username: str | None,
        full_name: str,
        date_str: str,
        time_str: str,
    ) -> BookingRequest:
        with self._lock:
            if self.get_slot_state(date_str, time_str):
                raise ValueError("Slot already requested or confirmed")
            
            request = BookingRequest(
                id=str(uuid.uuid4()),
                user_id=user_id,
                username=username or "",
                full_name=full_name,
                date=date_str,
                time=time_str,
                status="pending",
                created_at=datetime.utcnow().isoformat(),
            )
            
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO bookings (id, user_id, username, full_name, date, time, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        request.id,
                        request.user_id,
                        request.username,
                        request.full_name,
                        request.date,
                        request.time,
                        request.status,
                        request.created_at
                    )
                )
                conn.commit()
                return request
            finally:
                cursor.close()
                conn.close()

    def update_status(self, request_id: str, status: str) -> BookingRequest:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "UPDATE bookings SET status = %s WHERE id = %s",
                    (status, request_id)
                )
                conn.commit()
                return self.get_request(request_id)
            finally:
                cursor.close()
                conn.close()

    def get_request(self, request_id: str) -> BookingRequest:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM bookings WHERE id = %s", (request_id,))
            row = cursor.fetchone()
            if row:
                return BookingRequest(
                    id=row[0],
                    user_id=row[1],
                    username=row[2] or "",
                    full_name=row[3],
                    date=str(row[4]),
                    time=str(row[5]),
                    status=row[6],
                    created_at=str(row[7])
                )
            raise KeyError(request_id)
        finally:
            cursor.close()
            conn.close()

    def list_day_states(self, date_str: str) -> Dict[str, str]:
        """Return map time -> status for slots with any activity."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT time, status FROM bookings WHERE date = %s",
                (date_str,)
            )
            return {str(row[0]): row[1] for row in cursor.fetchall()}
        finally:
            cursor.close()
            conn.close()

    def list_user_requests(self, user_id: int) -> List[BookingRequest]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT * FROM bookings WHERE user_id = %s ORDER BY date, time",
                (user_id,)
            )
            return [
                BookingRequest(
                    id=row[0],
                    user_id=row[1],
                    username=row[2] or "",
                    full_name=row[3],
                    date=str(row[4]),
                    time=str(row[5]),
                    status=row[6],
                    created_at=str(row[7])
                )
                for row in cursor.fetchall()
            ]
        finally:
            cursor.close()
            conn.close()

    def list_all_requests(self) -> List[BookingRequest]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM bookings ORDER BY date, time")
            return [
                BookingRequest(
                    id=row[0],
                    user_id=row[1],
                    username=row[2] or "",
                    full_name=row[3],
                    date=str(row[4]),
                    time=str(row[5]),
                    status=row[6],
                    created_at=str(row[7])
                )
                for row in cursor.fetchall()
            ]
        finally:
            cursor.close()
            conn.close()

    def cleanup_expired(self, now: datetime) -> None:
        """Remove requests that finished before 'now'."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                now_str = now.strftime("%Y-%m-%d %H:%M")
                cursor.execute(
                    "DELETE FROM bookings WHERE CONCAT(date, ' ', time) < %s",
                    (now_str,)
                )
                conn.commit()
            finally:
                cursor.close()
                conn.close()
