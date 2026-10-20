"""SQLite persistence and validation for the device-local attendance app."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

PBKDF2_ITERATIONS = 310_000


class AttendanceError(ValueError):
    """An expected, user-actionable account or attendance error."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise AttendanceError("Password must be at least 8 characters.")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (TypeError, ValueError):
        return False


class AttendanceDB:
    """Local SQLite store. It does not synchronize records between devices."""

    def __init__(self, path: str | Path = "attendance.db") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS teachers (
                    username TEXT PRIMARY KEY COLLATE NOCASE,
                    full_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS students (
                    student_id TEXT PRIMARY KEY COLLATE NOCASE,
                    full_name TEXT NOT NULL,
                    class_name TEXT NOT NULL,
                    roll_number TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (class_name, roll_number)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    token TEXT NOT NULL UNIQUE,
                    teacher_username TEXT NOT NULL REFERENCES teachers(username),
                    class_name TEXT NOT NULL,
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attendance (
                    attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    student_id TEXT NOT NULL REFERENCES students(student_id),
                    marked_at TEXT NOT NULL,
                    UNIQUE (session_id, student_id)
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_class ON sessions(class_name, created_at);
                CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance(student_id, marked_at);
                """
            )

    def has_teachers(self) -> bool:
        with self._connect() as db:
            return db.execute("SELECT 1 FROM teachers LIMIT 1").fetchone() is not None

    def create_teacher(self, username: str, full_name: str, password: str) -> None:
        username, full_name = username.strip(), full_name.strip()
        if not username or not full_name:
            raise AttendanceError("Teacher name and username are required.")
        encoded = hash_password(password)
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO teachers VALUES (?, ?, ?, ?)",
                    (username, full_name, encoded, _iso()),
                )
        except sqlite3.IntegrityError as exc:
            raise AttendanceError("That teacher username is already registered.") from exc

    def authenticate_teacher(self, username: str, password: str) -> dict[str, str] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT username, full_name, password_hash FROM teachers WHERE username = ?",
                (username.strip(),),
            ).fetchone()
        if row and verify_password(password, row["password_hash"]):
            return {"username": row["username"], "full_name": row["full_name"]}
        return None

    def add_student(
        self, student_id: str, full_name: str, class_name: str, roll_number: str, password: str
    ) -> None:
        fields = [value.strip() for value in (student_id, full_name, class_name, roll_number)]
        if not all(fields):
            raise AttendanceError("Student ID, name, class, and roll number are required.")
        encoded = hash_password(password)
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO students VALUES (?, ?, ?, ?, ?, ?)",
                    (*fields, encoded, _iso()),
                )
        except sqlite3.IntegrityError as exc:
            raise AttendanceError("Student ID or class/roll number is already in use.") from exc

    def authenticate_student(self, student_id: str, password: str) -> dict[str, str] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT student_id, full_name, class_name, roll_number, password_hash "
                "FROM students WHERE student_id = ?",
                (student_id.strip(),),
            ).fetchone()
        if row and verify_password(password, row["password_hash"]):
            return {
                key: row[key]
                for key in ("student_id", "full_name", "class_name", "roll_number")
            }
        return None

    def create_session(
        self, teacher_username: str, class_name: str, label: str, duration_minutes: int
    ) -> dict[str, str]:
        class_name, label = class_name.strip(), label.strip()
        if not class_name or not label:
            raise AttendanceError("Class and session title are required.")
        if not 1 <= duration_minutes <= 240:
            raise AttendanceError("Session duration must be between 1 and 240 minutes.")
        created = _now()
        session = {
            "session_id": str(uuid.uuid4()),
            "token": secrets.token_urlsafe(32),
            "class_name": class_name,
            "label": label,
            "created_at": _iso(created),
            "expires_at": _iso(created + timedelta(minutes=duration_minutes)),
        }
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        session["session_id"],
                        session["token"],
                        teacher_username,
                        class_name,
                        label,
                        session["created_at"],
                        session["expires_at"],
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise AttendanceError(
                "Sign in as a registered teacher before creating a session."
            ) from exc
        return session

    def validate_session_payload(self, payload_text: str) -> dict[str, Any]:
        try:
            payload = json.loads(payload_text)
            if not isinstance(payload, dict) or payload.get("version") != 1:
                raise ValueError
            session_id, token, expiry = (
                payload["session_id"],
                payload["token"],
                payload["expires_at"],
            )
            if not all(isinstance(value, str) for value in (session_id, token, expiry)):
                raise ValueError
        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            raise AttendanceError("This is not a valid attendance QR code.") from exc

        with self._connect() as db:
            row = db.execute(
                "SELECT session_id, token, class_name, label, expires_at "
                "FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None or not hmac.compare_digest(row["token"], token):
            raise AttendanceError("Attendance session not found on this device.")
        try:
            stored_expiry = datetime.fromisoformat(row["expires_at"])
            qr_expiry = datetime.fromisoformat(expiry)
        except ValueError as exc:
            raise AttendanceError("Attendance session has an invalid expiry.") from exc
        if stored_expiry != qr_expiry or _now() >= stored_expiry:
            raise AttendanceError("This attendance session has expired or is invalid.")
        return dict(row)

    def mark_attendance(self, student_id: str, payload_text: str) -> str:
        session = self.validate_session_payload(payload_text)
        try:
            with self._connect() as db:
                student = db.execute(
                    "SELECT class_name FROM students WHERE student_id = ?", (student_id,)
                ).fetchone()
                if student is None:
                    raise AttendanceError("Student account was not found.")
                if student["class_name"].casefold() != session["class_name"].casefold():
                    raise AttendanceError("This session is for a different class.")
                db.execute(
                    "INSERT INTO attendance(session_id, student_id, marked_at) VALUES (?, ?, ?)",
                    (session["session_id"], student_id, _iso()),
                )
        except sqlite3.IntegrityError as exc:
            raise AttendanceError(
                "Attendance has already been marked for this session."
            ) from exc
        return session["label"]

    def session_roster(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT s.student_id, s.full_name, s.class_name, s.roll_number, a.marked_at
                FROM students s
                JOIN sessions se ON se.session_id = ?
                LEFT JOIN attendance a ON a.session_id = se.session_id
                    AND a.student_id = s.student_id
                WHERE s.class_name = se.class_name COLLATE NOCASE
                ORDER BY s.roll_number, s.full_name
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def student_history(self, student_id: str) -> tuple[list[dict[str, Any]], int, int]:
        with self._connect() as db:
            student = db.execute(
                "SELECT class_name FROM students WHERE student_id = ?", (student_id,)
            ).fetchone()
            if student is None:
                raise AttendanceError("Student account was not found.")
            rows = db.execute(
                """
                SELECT se.session_id, se.label, se.class_name, se.created_at, se.expires_at,
                       a.marked_at
                FROM sessions se LEFT JOIN attendance a
                    ON a.session_id = se.session_id AND a.student_id = ?
                WHERE se.class_name = ? COLLATE NOCASE
                ORDER BY se.created_at DESC
                """,
                (student_id, student["class_name"]),
            ).fetchall()
        history = [dict(row) for row in rows]
        present = sum(row["marked_at"] is not None for row in history)
        return history, present, len(history)

    def export_session_csv(self, session_id: str) -> str:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            ["Student ID", "Name", "Class", "Roll Number", "Status", "Marked At (UTC)"]
        )
        for row in self.session_roster(session_id):
            writer.writerow(
                [
                    row["student_id"],
                    row["full_name"],
                    row["class_name"],
                    row["roll_number"],
                    "Present" if row["marked_at"] else "Absent",
                    row["marked_at"] or "",
                ]
            )
        return output.getvalue()
