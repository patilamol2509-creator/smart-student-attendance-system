"""Attendance QR payload and image helpers."""

from __future__ import annotations

import json
from typing import Any


def encode_session_payload(session: dict[str, Any]) -> str:
    return json.dumps(
        {
            "version": 1,
            "session_id": session["session_id"],
            "token": session["token"],
            "expires_at": session["expires_at"],
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def save_qr_image(payload: str, destination: str) -> None:
    try:
        import qrcode
    except ImportError as exc:
        raise RuntimeError("QR image support requires qrcode and Pillow.") from exc
    qrcode.make(payload).save(destination)
