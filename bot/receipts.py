"""To'lov kiritilganda chek (PDF) yaratish va yuborish: kim kiritgan bo'lsa unga,
va agar o'quvchiga bog'langan ota-onalar bo'lsa ularga ham."""
import logging

from aiogram.types import BufferedInputFile

from . import db as D
from .config import CENTER_NAME
from .pdfgen import receipt_pdf

log = logging.getLogger(__name__)


async def send_receipt(bot, db, payment_id: int, entered_by_uid=None):
    """payment_id - payments jadvalidagi yangi yozuv id'si."""
    if not bot:
        return
    row = await db.fetchone(
        "SELECT p.id, p.amount, p.month, p.created_at, s.first_name, s.last_name, s.grade, s.id AS sid, "
        "g.name AS gname FROM payments p JOIN students s ON s.id=p.student_id "
        "JOIN groups g ON g.id=p.group_id WHERE p.id=?", (payment_id,))
    if not row:
        return
    entered_name = "-"
    if entered_by_uid:
        u = await db.fetchone("SELECT full_name FROM users WHERE tg_id=?", (entered_by_uid,))
        entered_name = u["full_name"] if u else "-"
    pdf = receipt_pdf(CENTER_NAME, f"{row['last_name']} {row['first_name']}", row["grade"], row["gname"],
                      row["amount"], row["month"], str(row["created_at"])[:16], entered_name, row["id"])
    fname = f"chek_{row['last_name']}_{row['month']}.pdf"
    caption = (f"🧾 To'lov cheki: {row['last_name']} {row['first_name']} — "
              f"{int(row['amount']):,}".replace(",", " ") + f" so'm ({row['month']})")
    targets = set()
    if entered_by_uid:
        targets.add(entered_by_uid)
    for p in await db.fetchall("SELECT parent_tg_id FROM parent_links WHERE student_id=?", (row["sid"],)):
        targets.add(p["parent_tg_id"])
    for uid in targets:
        try:
            await bot.send_document(uid, BufferedInputFile(pdf, fname), caption=caption)
        except Exception:
            log.warning("Chek yuborilmadi: %s", uid)
