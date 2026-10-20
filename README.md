# Smart Student Attendance System Using QR Code

A Python 3 / Kivy Android application demonstrating teacher and student attendance workflows, QR session creation and scanning, SQLite persistence, CSV export, and a GitHub Actions debug-APK build.

## Important deployment and trust limitation

This repository is a **single-device, offline prototype**, not a multi-device attendance service. Teacher accounts, student accounts, session tokens, and attendance are in one SQLite database on one device. Consequently, a student login on a different phone cannot validate the teacher phone's QR code: the session is not in that phone's database. For the scan-and-submit flow, create the teacher and student accounts and scan the displayed QR using the same app installation (or enter its QR payload on the student dashboard).

A production multi-phone deployment needs a trusted online service (or an equivalent securely provisioned verification system) to authenticate teachers, issue and validate sessions, record attendance, and synchronize class data. A QR code is a bearer pass: anyone who photographs, screenshots, or receives it can attempt to mark attendance before it expires. Short expiry, supervised display, and duplicate checks reduce casual misuse but cannot prove who physically scanned it. Local-only storage and a device clock also cannot provide server-grade tamper resistance or trustworthy cross-device records.

Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes; session IDs and tokens use cryptographically secure randomness; expiry, token, class, and duplicate checks are enforced by SQLite-backed logic. These measures do not remove the offline trust limitations above.

## Features

- Teacher first-run account setup and teacher/student login.
- Teacher creates student accounts with ID, name, class, roll number, and password.
- Teacher creates a class attendance session with a 1–240 minute expiry and displays a QR code.
- Students scan with the Android camera or enter QR payload text for same-device testing.
- Session token and expiry validation, class matching, and a database uniqueness constraint prevent duplicate marks for a student/session pair.
- Student attendance history and percentage; teacher present/absent roster and CSV export.
- Camera permission is requested when scanning on Android. A denied or unavailable camera is reported and the student can return to manual QR entry.

## Run on a computer

Use Python 3.10 or newer. In the repository root:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

For tests, install the project requirements, then run:

```bash
python -m compileall -q main.py attendance_db.py qr_utils.py tests
python -m unittest discover -s tests -v
```

The database is created in the app's user data directory (or the current directory when using the database module directly). The first run lets you create the initial teacher account; add student accounts from the teacher dashboard.

## Build an Android debug APK with GitHub Actions

1. Create a GitHub repository and upload/push the project files while preserving their directories. Include `main.py`, `attendance_db.py`, `qr_utils.py`, `requirements.txt`, `buildozer.spec`, `README.md`, `tests/test_attendance_db.py`, and `.github/workflows/build.yml`. The repository also includes `.gitignore`; keep the `!buildozer.spec` exception so Git tracks the spec file.
2. In GitHub, open **Actions** and enable workflows if prompted.
3. Push to the `main` branch or open a pull request to start the workflow. You can also choose **Actions → Build Android APK → Run workflow**.
4. Wait for the `test-and-build` job. It runs Python syntax checks and unit tests, installs Java 17 and Buildozer dependencies on Ubuntu 22.04, then runs `buildozer -v android debug`.
5. On a successful run, open the workflow run's **Artifacts** section and download `smart-student-attendance-debug-apk`. The uploaded file is the debug APK from `bin/*.apk`.
6. Transfer the APK to an Android device, allow installation from the file manager/source when Android asks, and install it. Android may show an unsigned-debug-build warning; this is not a Play Store release APK.

The workflow checks out the CameraX provider required by Camera4Kivy, then Buildozer downloads the Android SDK/NDK and compiles native dependencies; the first run can take a long time. The Android dependency list pins `charset-normalizer` to a pure-Python wheel to avoid an incompatible platform wheel being installed in the Buildozer target directory. Check the Actions log if the toolchain or a native dependency fails. The APK artifact is not committed into this source tree, and this app has not been tested on a physical Android device.

## Build locally (Linux)

Install Java 17, gettext/autopoint, the Android build tools required by Buildozer, and Buildozer 1.5.0 with Cython 0.29.36 in a suitable Python environment. From the repository root, add the CameraX provider expected by `buildozer.spec`:

```bash
git clone --depth 1 https://github.com/Android-for-Python/camerax_provider.git
python -m pip install "Cython==0.29.36" "buildozer==1.5.0"
buildozer -v android debug
```

The debug APK is emitted in `bin/`. Buildozer's first invocation downloads its Android toolchain. The included GitHub Actions workflow is the recommended repeatable cloud build path.

## Project layout

```text
main.py                         Kivy UI, roles, dashboard, Android camera QR scanner
attendance_db.py                SQLite schema, password hashing, session/attendance logic
qr_utils.py                     QR payload serialization and image generation
tests/test_attendance_db.py     Database, QR validation, expiry, duplicates, CSV tests
requirements.txt                Desktop Python dependencies
buildozer.spec                  Android package and python-for-android requirements
.github/workflows/build.yml     Tests and debug APK artifact workflow
```
