import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from attendance_db import AttendanceDB, AttendanceError
from qr_utils import encode_session_payload, save_qr_image


class AttendanceDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = AttendanceDB(Path(self.temp_dir.name) / "attendance.db")
        self.db.create_teacher("teacher1", "Teacher One", "teacher-pass-123")
        self.db.add_student("S001", "Student One", "Class A", "1", "student-pass-123")

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_session(self):
        session = self.db.create_session("teacher1", "Class A", "Math", 30)
        return session, encode_session_payload(session)

    def test_passwords_are_hashed_and_authentication_works(self):
        self.assertEqual(
            self.db.authenticate_teacher("teacher1", "teacher-pass-123")["full_name"],
            "Teacher One",
        )
        self.assertEqual(
            self.db.authenticate_student("S001", "student-pass-123")["class_name"],
            "Class A",
        )
        self.assertIsNone(self.db.authenticate_teacher("teacher1", "incorrect"))

    def test_qr_creation_validation_and_marking(self):
        session, payload = self.make_session()
        self.assertEqual(
            self.db.validate_session_payload(payload)["session_id"], session["session_id"]
        )
        self.assertEqual(self.db.mark_attendance("S001", payload), "Math")
        self.assertIsNotNone(self.db.session_roster(session["session_id"])[0]["marked_at"])

    def test_duplicate_marks_are_rejected(self):
        _session, payload = self.make_session()
        self.db.mark_attendance("S001", payload)
        with self.assertRaisesRegex(AttendanceError, "already been marked"):
            self.db.mark_attendance("S001", payload)

    def test_expired_and_tampered_qrs_are_rejected(self):
        session, _payload = self.make_session()
        expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with self.db._connect() as connection:
            connection.execute(
                "UPDATE sessions SET expires_at = ? WHERE session_id = ?",
                (expired, session["session_id"]),
            )
        expired_payload = json.dumps(
            {
                "version": 1,
                "session_id": session["session_id"],
                "token": session["token"],
                "expires_at": expired,
            }
        )
        with self.assertRaisesRegex(AttendanceError, "expired"):
            self.db.mark_attendance("S001", expired_payload)

        valid_session, valid_payload = self.make_session()
        tampered = json.loads(valid_payload)
        tampered["token"] = "not-the-session-token"
        with self.assertRaisesRegex(AttendanceError, "not found"):
            self.db.validate_session_payload(json.dumps(tampered))

    def test_wrong_class_is_rejected(self):
        _session, payload = self.make_session()
        self.db.add_student("S002", "Other Student", "Class B", "2", "student-pass-456")
        with self.assertRaisesRegex(AttendanceError, "different class"):
            self.db.mark_attendance("S002", payload)

    def test_history_percentage_and_csv_export(self):
        session, payload = self.make_session()
        self.db.mark_attendance("S001", payload)
        _history, present, total = self.db.student_history("S001")
        self.assertEqual((present, total), (1, 1))
        rows = list(csv.reader(self.db.export_session_csv(session["session_id"]).splitlines()))
        self.assertEqual(rows[1][4], "Present")

    def test_qr_image_is_generated_from_session_payload(self):
        _session, payload = self.make_session()
        image_path = Path(self.temp_dir.name) / "session.png"
        save_qr_image(payload, str(image_path))
        self.assertEqual(image_path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
