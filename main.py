"""Kivy UI for Smart Student Attendance System."""

from __future__ import annotations

import os

from attendance_db import AttendanceDB, AttendanceError
from qr_utils import encode_session_payload, save_qr_image

try:
    from kivy.app import App
    from kivy.clock import Clock
    from kivy.metrics import dp
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.image import Image
    from kivy.uix.label import Label
    from kivy.uix.popup import Popup
    from kivy.uix.screenmanager import Screen, ScreenManager
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.textinput import TextInput
except ImportError:
    App = None


if App is not None:
    from kivy.utils import platform

    def _label(text: str, height: int = 42, size: int = 16) -> Label:
        return Label(
            text=text,
            size_hint_y=None,
            height=dp(height),
            font_size=size,
            color=(0.12, 0.16, 0.22, 1),
            halign="left",
            valign="middle",
        )

    def _button(text: str, callback, height: int = 48) -> Button:
        button = Button(text=text, size_hint_y=None, height=dp(height))
        button.bind(on_release=callback)
        return button

    def _input(hint: str, password: bool = False) -> TextInput:
        return TextInput(
            hint_text=hint,
            password=password,
            multiline=False,
            size_hint_y=None,
            height=dp(48),
            padding=(dp(12), dp(12)),
        )

    class FormScreen(Screen):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.form = BoxLayout(
                orientation="vertical", padding=dp(18), spacing=dp(9), size_hint_y=None
            )
            self.form.bind(minimum_height=self.form.setter("height"))
            scroll = ScrollView()
            scroll.add_widget(self.form)
            self.add_widget(scroll)

        def title(self, text: str) -> None:
            self.form.add_widget(_label(text, 58, 23))

        def note(self, text: str) -> None:
            self.form.add_widget(_label(text, 64, 14))

        def field(self, hint: str, password: bool = False) -> TextInput:
            value = _input(hint, password)
            self.form.add_widget(value)
            return value

        def action(self, text: str, callback, height: int = 48) -> None:
            self.form.add_widget(_button(text, callback, height))

    class AttendanceApp(App):
        title = "Smart Student Attendance"

        def build(self):
            os.makedirs(self.user_data_dir, exist_ok=True)
            self.db = AttendanceDB(os.path.join(self.user_data_dir, "attendance.db"))
            self.teacher = None
            self.student = None
            self.current_session = None
            self.preview = None
            self.scan_processed = False
            self.screens = ScreenManager()
            self._build_login()
            self._build_teacher_setup()
            self._build_teacher_dashboard()
            self._build_student_dashboard()
            self._build_scanner()
            self.screens.current = "login"
            return self.screens

        def alert(self, message: str, title: str = "Smart Attendance") -> None:
            popup = Popup(
                title=title,
                content=Label(text=message, halign="center", valign="middle"),
                size_hint=(0.88, None),
                height=dp(190),
            )
            popup.open()

        def _build_login(self):
            screen = FormScreen(name="login")
            screen.title("Smart Student Attendance")
            screen.note("Select your role and sign in.")
            self.role = "teacher"
            roles = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
            roles.add_widget(_button("Teacher", lambda *_: self._set_role("teacher")))
            roles.add_widget(_button("Student", lambda *_: self._set_role("student")))
            screen.form.add_widget(roles)
            self.login_id = screen.field("Teacher username or student ID")
            self.login_password = screen.field("Password", True)
            screen.action("Sign in", self._login)
            screen.action("Create first teacher account", self._go_teacher_setup)
            screen.note(
                "This app stores records on this device only. A student must use the same "
                "device/database that created the teacher's session QR."
            )
            self.screens.add_widget(screen)

        def _set_role(self, role: str):
            self.role = role
            self.login_id.hint_text = "Teacher username" if role == "teacher" else "Student ID"

        def _go_teacher_setup(self, *_):
            if self.db.has_teachers():
                self.alert("A teacher account already exists. Sign in as teacher to add students.")
            else:
                self.screens.current = "teacher_setup"

        def _build_teacher_setup(self):
            screen = FormScreen(name="teacher_setup")
            screen.title("Create teacher account")
            screen.note("Create the first teacher login on this device.")
            self.teacher_name = screen.field("Full name")
            self.teacher_username = screen.field("Username")
            self.teacher_password = screen.field("Password (at least 8 characters)", True)
            screen.action("Create account", self._create_teacher)
            screen.action("Back to sign in", lambda *_: setattr(self.screens, "current", "login"))
            self.screens.add_widget(screen)

        def _create_teacher(self, *_):
            try:
                if self.db.has_teachers():
                    raise AttendanceError("A teacher account already exists.")
                self.db.create_teacher(
                    self.teacher_username.text,
                    self.teacher_name.text,
                    self.teacher_password.text,
                )
                self.alert("Teacher account created. You can now sign in.")
                self.screens.current = "login"
            except AttendanceError as exc:
                self.alert(str(exc), "Account not created")

        def _login(self, *_):
            if self.role == "teacher":
                self.teacher = self.db.authenticate_teacher(
                    self.login_id.text, self.login_password.text
                )
                if self.teacher:
                    self.teacher_greeting.text = f"Signed in: {self.teacher['full_name']}"
                    self.screens.current = "teacher"
                    return
            else:
                self.student = self.db.authenticate_student(
                    self.login_id.text, self.login_password.text
                )
                if self.student:
                    self.refresh_student()
                    self.screens.current = "student"
                    return
            self.alert("Check your role, username/ID, and password.", "Sign in failed")

        def _build_teacher_dashboard(self):
            screen = FormScreen(name="teacher")
            screen.title("Teacher dashboard")
            self.teacher_greeting = _label("")
            screen.form.add_widget(self.teacher_greeting)
            screen.note("Add a student and provide them their ID and temporary password.")
            self.student_id = screen.field("Student ID")
            self.student_name = screen.field("Student full name")
            self.student_class = screen.field("Class / section")
            self.student_roll = screen.field("Roll number")
            self.student_password = screen.field("Student password (8+ characters)", True)
            screen.action("Add student", self._add_student)
            screen.note("Create a short-lived session QR for a class and lesson.")
            self.session_class = screen.field("Class / section")
            self.session_label = screen.field("Session title")
            self.session_duration = screen.field("Expiry in minutes (1-240)")
            screen.action("Create and display QR session", self._create_session)
            self.qr_area = BoxLayout(
                orientation="vertical", size_hint_y=None, height=dp(320), spacing=dp(4)
            )
            screen.form.add_widget(self.qr_area)
            self.roster = _label("", 120, 14)
            screen.form.add_widget(self.roster)
            screen.action("Refresh present / absent list", self.refresh_roster)
            screen.action("Export latest session CSV", self.export_csv)
            screen.action("Sign out", self._logout)
            self.screens.add_widget(screen)

        def _add_student(self, *_):
            try:
                self.db.add_student(
                    self.student_id.text,
                    self.student_name.text,
                    self.student_class.text,
                    self.student_roll.text,
                    self.student_password.text,
                )
                for field in (
                    self.student_id,
                    self.student_name,
                    self.student_class,
                    self.student_roll,
                    self.student_password,
                ):
                    field.text = ""
                self.alert("Student account added.")
            except AttendanceError as exc:
                self.alert(str(exc), "Unable to add student")

        def _create_session(self, *_):
            try:
                duration = int(self.session_duration.text)
                session = self.db.create_session(
                    self.teacher["username"],
                    self.session_class.text,
                    self.session_label.text,
                    duration,
                )
                qr_path = os.path.join(self.user_data_dir, "attendance-session.png")
                save_qr_image(encode_session_payload(session), qr_path)
                self.current_session = session
                self.qr_area.clear_widgets()
                self.qr_area.add_widget(
                    Image(source=qr_path, allow_stretch=True, keep_ratio=True)
                )
                self.qr_area.add_widget(
                    _label(f"Expires {session['expires_at']} UTC", 32, 12)
                )
                self.refresh_roster()
            except (AttendanceError, ValueError, RuntimeError) as exc:
                self.alert(str(exc), "Unable to create session")

        def refresh_roster(self, *_):
            if not self.current_session:
                self.roster.text = "Create a session to see the attendance list."
                return
            rows = self.db.session_roster(self.current_session["session_id"])
            present = sum(row["marked_at"] is not None for row in rows)
            lines = [
                f"{row['roll_number']}  {row['full_name']}  "
                f"{'PRESENT' if row['marked_at'] else 'ABSENT'}"
                for row in rows
            ]
            self.roster.text = f"Present: {present}   Absent: {len(rows) - present}\n" + (
                "\n".join(lines) or "No students in this class."
            )
            self.roster.height = dp(max(75, 36 * (len(rows) + 1)))

        def export_csv(self, *_):
            if not self.current_session:
                self.alert("Create a session before exporting attendance.")
                return
            destination = os.path.join(
                self.user_data_dir,
                f"attendance-{self.current_session['session_id'][:8]}.csv",
            )
            try:
                with open(destination, "w", encoding="utf-8-sig", newline="") as file:
                    file.write(self.db.export_session_csv(self.current_session["session_id"]))
            except OSError as exc:
                self.alert(f"Could not save CSV: {exc}", "Export failed")
                return
            self.alert(f"CSV saved to app storage:\n{destination}")

        def _build_student_dashboard(self):
            screen = FormScreen(name="student")
            screen.title("Student dashboard")
            self.student_greeting = _label("")
            screen.form.add_widget(self.student_greeting)
            screen.action("Scan attendance QR", self._request_camera)
            self.manual_payload = screen.field("Paste QR payload (shared-device use)")
            screen.action("Mark attendance from pasted QR", self._mark_pasted)
            self.attendance_summary = _label("")
            screen.form.add_widget(self.attendance_summary)
            self.history = _label("", 180, 14)
            screen.form.add_widget(self.history)
            screen.action("Refresh history", lambda *_: self.refresh_student())
            screen.action("Sign out", self._logout)
            screen.note(
                "A session QR is a bearer pass: anyone who photographs or receives it may "
                "use it before expiry. Limit display time and supervise scanning."
            )
            self.screens.add_widget(screen)

        def refresh_student(self):
            self.student_greeting.text = (
                f"{self.student['full_name']} · {self.student['class_name']}"
            )
            records, present, total = self.db.student_history(self.student["student_id"])
            percent = (present * 100 / total) if total else 0
            self.attendance_summary.text = (
                f"Attendance: {present}/{total} sessions ({percent:.1f}%)"
            )
            entries = [
                f"{row['label']} — "
                f"{'Present: ' + row['marked_at'] if row['marked_at'] else 'Absent'}"
                for row in records[:10]
            ]
            self.history.text = "\n".join(entries) or "No attendance sessions yet."
            self.history.height = dp(max(60, 30 * len(entries)))

        def _mark_pasted(self, *_):
            self._mark_attendance(self.manual_payload.text.strip())

        def _mark_attendance(self, payload: str):
            try:
                label = self.db.mark_attendance(self.student["student_id"], payload)
                self.manual_payload.text = ""
                self.refresh_student()
                self.alert(f"Attendance marked for {label}.")
                self.screens.current = "student"
            except AttendanceError as exc:
                self.alert(str(exc), "Attendance not marked")

        def _request_camera(self, *_):
            if platform == "android":
                try:
                    from android.permissions import Permission, request_permissions

                    request_permissions([Permission.CAMERA], self._camera_permission_result)
                except ImportError:
                    self._scanner_message("Android camera permission API is unavailable.")
            else:
                self._start_scanner()

        def _camera_permission_result(self, _permissions, grants):
            if grants and all(grants):
                Clock.schedule_once(lambda _dt: self._start_scanner(), 0)
            else:
                Clock.schedule_once(
                    lambda _dt: self._scanner_message(
                        "Camera permission denied. Return to the dashboard to paste QR text."
                    ),
                    0,
                )

        def _build_scanner(self):
            screen = FormScreen(name="scanner")
            screen.title("Scan attendance QR")
            self.scanner_status = _label("Preparing camera…", 52, 15)
            screen.form.add_widget(self.scanner_status)
            self.camera_area = BoxLayout(size_hint_y=None, height=dp(360))
            screen.form.add_widget(self.camera_area)
            screen.action("Cancel", lambda *_: self._stop_scanner())
            self.screens.add_widget(screen)

        def _scanner_message(self, message: str):
            self.scanner_status.text = message
            self.screens.current = "scanner"

        def _start_scanner(self):
            self.screens.current = "scanner"
            self.scan_processed = False
            try:
                from PIL import Image as PILImage
                from pyzbar.pyzbar import ZBarSymbol, decode
                from camera4kivy import Preview
            except (ImportError, OSError) as exc:
                self._scanner_message(
                    f"Camera scanner unavailable ({exc}). Use paste-QR instead."
                )
                return

            app = self

            class QRPreview(Preview):
                def analyze_pixels_callback(
                    preview_self, pixels, image_size, _image_pos, _image_scale, _mirror
                ):
                    if app.scan_processed:
                        return
                    image = PILImage.frombytes("RGBA", image_size, pixels).convert("RGB")
                    codes = decode(image, symbols=[ZBarSymbol.QRCODE])
                    if codes and not app.scan_processed:
                        app.scan_processed = True
                        payload = codes[0].data.decode("utf-8", errors="replace")
                        Clock.schedule_once(lambda _dt: app._scanner_decoded(payload), 0)

            try:
                self.camera_area.clear_widgets()
                self.preview = QRPreview(aspect_ratio="16:9")
                self.camera_area.add_widget(self.preview)
                self.preview.connect_camera(
                    enable_analyze_pixels=True,
                    analyze_pixels_callback=self.preview.analyze_pixels_callback,
                )
                self.scanner_status.text = "Point the camera at an active attendance QR."
            except (RuntimeError, ValueError) as exc:
                self.preview = None
                self._scanner_message(
                    f"Could not start camera ({exc}). Use paste-QR instead."
                )

        def _scanner_decoded(self, payload: str):
            self._stop_scanner(return_to_dashboard=False)
            self._mark_attendance(payload)

        def _stop_scanner(self, return_to_dashboard: bool = True):
            if self.preview is not None:
                preview, self.preview = self.preview, None
                preview.disconnect_camera()
            if return_to_dashboard:
                self.screens.current = "student"

        def _logout(self, *_):
            if self.preview is not None:
                self._stop_scanner(return_to_dashboard=False)
            self.teacher = None
            self.student = None
            self.current_session = None
            self.screens.current = "login"

    def main():
        AttendanceApp().run()

else:
    def main():
        raise RuntimeError("Install Kivy dependencies from requirements.txt to run the app.")


if __name__ == "__main__":
    main()
