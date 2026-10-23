"""Davomat: statuslar, tarix va saqlash (bot va Mini App uchun umumiy)."""
from datetime import date

from aiogram import Bot
from aiogram.types import BufferedInputFile

from . import db as D
from .pdfgen import attendance_pdf

# status: (belgi, nomi, kelgan hisoblanadimi)
STATUSES = {
    "present": ("✅", "Keldi", 1),
    "absent": ("❌", "Kelmadi", 0),
    "late": ("🕒", "Kechikdi", 1),
    "excused": ("📝", "Sababli", 0),
}
CYCLE = ["present", "absent", "late", "excused"]


def norm_status(status: str, present) -> str:
    if status in STATUSES:
        return status
    return "present" if present else "absent"


def fmt_day(day: str) -> str:
    """2026-10-14 -> 14.10"""
    return f"{day[8:10]}.{day[5:7]}"


async def lesson_days(db, gid: int, n: int = 3, before: str | None = None) -> list[str]:
    """Guruhda davomat olingan oxirgi n ta kun (yangisi birinchi). before - shu kundan oldingilar."""
    sql = "SELECT DISTINCT day FROM attendance WHERE group_id=?"
    args = [gid]
    if before:
        sql += " AND day<?"
        args.append(before)
    sql += " ORDER BY day DESC LIMIT ?"
    args.append(n)
    return [r["day"] for r in await db.fetchall(sql, tuple(args))]


async def history(db, gid: int, before: str | None = None, n: int = 3):
    """-> (kunlar eskidan yangiga, {student_id: {day: status}})"""
    days = await lesson_days(db, gid, n, before)
    if not days:
        return [], {}
    ph = ",".join("?" * len(days))
    rows = await db.fetchall(
        f"SELECT student_id, day, present, status FROM attendance WHERE group_id=? AND day IN ({ph})",
        (gid, *days))
    hist: dict[int, dict[str, str]] = {}
    for r in rows:
        hist.setdefault(r["student_id"], {})[r["day"]] = norm_status(r["status"], r["present"])
    return sorted(days), hist


def marks(days: list[str], per_student: dict[str, str] | None) -> str:
    """['2026-10-12','2026-10-14'] -> '✅❌' ; yozuv yo'q kun - ▫️"""
    per_student = per_student or {}
    return "".join(STATUSES[per_student[d]][0] if d in per_student else "▫️" for d in days)


def missed_dates(days: list[str], per_student: dict[str, str] | None) -> list[str]:
    per_student = per_student or {}
    return [fmt_day(d) for d in days if per_student.get(d) in ("absent", "excused")]


async def day_statuses(db, gid: int, day: str) -> dict[int, str]:
    rows = await db.fetchall("SELECT student_id, present, status FROM attendance WHERE group_id=? AND day=?",
                             (gid, day))
    return {r["student_id"]: norm_status(r["status"], r["present"]) for r in rows}


async def save_attendance(db, bot: Bot | None, uid: int, gid: int, day: date, statuses: dict) -> dict:
    """Davomatni saqlaydi, adminlarga PDF yuboradi. statuses: {student_id: status}.
    Ko'rsatilmagan o'quvchi 'keldi' deb olinadi."""
    g = await db.fetchone("SELECT * FROM groups WHERE id=?", (gid,))
    teacher_name = (await db.fetchone("SELECT full_name FROM users WHERE tg_id=?", (uid,)) or {}).get("full_name", "-")
    trow = await db.fetchone("SELECT registry_rate FROM teachers WHERE tg_id=?", (g["teacher_id"],)) \
        if g["teacher_id"] else None
    reg_price = trow["registry_rate"] if trow else 0
    iso = day.isoformat()
    stmts, rows, absent_lines, counts, no_price = [], [], [], {k: 0 for k in STATUSES}, False
    for s in await D.group_students(db, gid):
        st = statuses.get(s["id"]) or statuses.get(str(s["id"])) or "present"
        if st not in STATUSES:
            st = "present"
        present = STATUSES[st][2]
        counts[st] += 1
        rate = reg_price if (present and s["is_registry"]) else 0  # dars paytidagi stavka saqlanadi
        if present and s["is_registry"] and not reg_price:
            no_price = True
        stmts.append(("INSERT INTO attendance(group_id,day,student_id,present,rate,status) VALUES(?,?,?,?,?,?) "
                      "ON CONFLICT(group_id,day,student_id) DO UPDATE SET "
                      "present=excluded.present, rate=excluded.rate, status=excluded.status",
                      (gid, iso, s["id"], present, rate, st)))
        rows.append((f"{s['last_name']} {s['first_name']}", s["grade"], s.get("phone") or "", st))
        if st in ("absent", "excused"):
            phone = f" 📞 {s['phone']}" if s.get("phone") else ""
            absent_lines.append(f"• {s['last_name']} {s['first_name']}{phone}" + (" (sababli)" if st == "excused" else ""))
    for i in range(0, len(stmts), 300):
        await db.batch(stmts[i:i + 300])

    sent = 0
    if bot is not None:
        pdf = attendance_pdf(g["name"], teacher_name, f"{day:%d.%m.%Y}", rows)
        caption = (f"📋 {g['name']} davomati ({teacher_name}) {day:%d.%m.%Y}\n"
                   f"Kelmagan: {counts['absent'] + counts['excused']}, kechikkan: {counts['late']}")
        if absent_lines:
            caption = (caption + "\n" + "\n".join(absent_lines))[:900]
        if no_price:
            caption += "\n⚠️ Reyestr o'quvchilar bor, lekin o'qituvchiga reyestr narxi kiritilmagan (0)."
        for a in await db.fetchall("SELECT tg_id FROM users WHERE role IN ('admin','director')"):
            try:
                await bot.send_document(a["tg_id"], BufferedInputFile(pdf, f"davomat_{g['name']}_{iso}.pdf"),
                                        caption=caption)
                sent += 1
            except Exception:
                pass
    return {"counts": counts, "no_price": no_price, "sent": sent, "total": len(rows)}
