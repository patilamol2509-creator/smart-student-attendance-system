[app]
title = Smart Student Attendance System
package.name = smartattendance
package.domain = org.creator
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt
version = 1.0.0
requirements = python3,kivy==2.3.1,camera4kivy,gestures4kivy,pyzbar,libzbar,pillow,qrcode,charset-normalizer==3.4.2
orientation = portrait
fullscreen = 0
android.permissions = CAMERA
android.api = 33
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
p4a.hook = camerax_provider/gradle_options.py

[buildozer]
log_level = 2
warn_on_root = 1
