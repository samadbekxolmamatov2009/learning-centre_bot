"""Fayl yuklab olish uchun qisqa muddatli imzolangan token.

Telegram'ning ichki brauzeri blob: havolalarni "havolani ochish" deb so'raydi,
haqiqiy yuklab olmaydi. Shuning uchun fayl havolasi alohida (tashqi) brauzerda
ochiladi - bunda maxsus X-Init-Data header yubora olmaymiz, shuning uchun
o'rniga URL ichida shu qisqa muddatli token ishlatiladi.
"""
import hashlib
import hmac
import time

from .config import BOT_TOKEN

TTL = 120  # soniya


def make(uid: int) -> str:
    exp = int(time.time()) + TTL
    msg = f"{uid}.{exp}"
    sig = hmac.new(BOT_TOKEN.encode(), msg.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{uid}.{exp}.{sig}"


def verify(token: str):
    try:
        uid_s, exp_s, sig = token.split(".")
        uid, exp = int(uid_s), int(exp_s)
        msg = f"{uid}.{exp}"
        calc = hmac.new(BOT_TOKEN.encode(), msg.encode(), hashlib.sha256).hexdigest()[:24]
        if not hmac.compare_digest(calc, sig) or time.time() > exp:
            return None
        return uid
    except Exception:
        return None
