"""Ota-ona havolasi uchun imzolangan, holatsiz token (baza yoki muddatga bog'liq emas)."""
import hashlib
import hmac

from .config import BOT_TOKEN


def make(student_id: int) -> str:
    sig = hmac.new(BOT_TOKEN.encode(), str(student_id).encode(), hashlib.sha256).hexdigest()[:12]
    return f"p{student_id}_{sig}"


def verify(payload: str):
    """-> student_id yoki None."""
    if not payload or not payload.startswith("p") or "_" not in payload:
        return None
    try:
        sid_str, sig = payload[1:].rsplit("_", 1)
        sid = int(sid_str)
    except (ValueError, IndexError):
        return None
    expect = hmac.new(BOT_TOKEN.encode(), str(sid).encode(), hashlib.sha256).hexdigest()[:12]
    return sid if hmac.compare_digest(expect, sig) else None
