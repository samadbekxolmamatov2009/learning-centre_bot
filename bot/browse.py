"""Guruhlarni ko'rish: o'qituvchi -> guruh -> o'quvchi -> kartochka (bitta xabarni tahrirlab)."""
import html

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import attendance as A
from . import db as D
from .handlers import Role, STAFF, PAGE, can_access_group, money, with_phone

router = Router()
TEACHER_ONLY = Role("teacher")
DAYS = {"1": "Du", "2": "Se", "3": "Ch", "4": "Pa", "5": "Ju", "6": "Sh", "7": "Ya"}


def e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def schedule_text(g) -> str:
    days = " ".join(DAYS[d] for d in (g["lesson_days"] or "").split(",") if d in DAYS)
    return (days + (" " + g["lesson_time"] if g["lesson_time"] else "")).strip()


async def safe_edit(c: CallbackQuery, text: str, markup=None):
    try:
        await c.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest as ex:
        if "not modified" not in str(ex):
            raise


def btn(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


# ---------------- ro'yxatlar ----------------
async def groups_markup(db, teacher_id, back_to=None):
    """teacher_id=0/None - o'qituvchisiz guruhlar."""
    if teacher_id:
        groups = await db.fetchall("SELECT * FROM groups WHERE teacher_id=? ORDER BY name", (teacher_id,))
    else:
        groups = await db.fetchall("SELECT * FROM groups WHERE teacher_id IS NULL ORDER BY name")
    counts = {r["group_id"]: r["n"] for r in await db.fetchall(
        "SELECT group_id, COUNT(*) n FROM students WHERE hidden=0 GROUP BY group_id")}
    b = InlineKeyboardBuilder()
    for g in groups:
        b.button(text=f"{g['name']} · {counts.get(g['id'], 0)} ta", callback_data=f"gl:g:{g['id']}:0")
    b.adjust(2)
    if back_to:
        b.row(btn("⬅️ O'qituvchilar", back_to))
    return b.as_markup(), len(groups)


async def teachers_markup(db):
    teachers = await db.fetchall(
        "SELECT u.tg_id, u.full_name, (SELECT COUNT(*) FROM groups g WHERE g.teacher_id=u.tg_id) n "
        "FROM users u JOIN teachers t ON t.tg_id=u.tg_id ORDER BY u.full_name")
    b = InlineKeyboardBuilder()
    for t in teachers:
        b.button(text=f"👨‍🏫 {t['full_name']} · {t['n']} guruh", callback_data=f"gl:t:{t['tg_id']}")
    b.adjust(1)
    orphan = (await db.fetchone("SELECT COUNT(*) n FROM groups WHERE teacher_id IS NULL"))["n"]
    if orphan:
        b.row(btn(f"⚠️ O'qituvchisiz guruhlar · {orphan}", "gl:t:0"))
    return (b.as_markup() if (teachers or orphan) else None)


@router.message(F.text == "📚 Guruhlarim", TEACHER_ONLY)
async def my_groups(m: Message, db):
    mk, n = await groups_markup(db, m.from_user.id)
    await m.answer("📚 <b>Guruhlaringiz</b>\nGuruhni tanlang 👇" if n else "Sizda hali guruh yo'q.",
                   reply_markup=mk if n else None, parse_mode="HTML")


@router.message(F.text == "📚 Guruhlar", STAFF)
async def all_groups(m: Message, db):
    mk = await teachers_markup(db)
    await m.answer("👨‍🏫 <b>O'qituvchini tanlang</b>" if mk else "Guruhlar yo'q.", reply_markup=mk, parse_mode="HTML")


@router.callback_query(F.data == "gl:back", STAFF)
async def gl_back(c: CallbackQuery, db):
    await safe_edit(c, "👨‍🏫 <b>O'qituvchini tanlang</b>", await teachers_markup(db))
    await c.answer()


@router.callback_query(F.data == "gl:mine", TEACHER_ONLY)
async def gl_mine(c: CallbackQuery, db):
    mk, n = await groups_markup(db, c.from_user.id)
    await safe_edit(c, "📚 <b>Guruhlaringiz</b>\nGuruhni tanlang 👇", mk)
    await c.answer()


@router.callback_query(F.data.startswith("gl:t:"), STAFF)
async def gl_teacher(c: CallbackQuery, db):
    tid = int(c.data[5:])
    mk, n = await groups_markup(db, tid, back_to="gl:back")
    if tid:
        t = await db.fetchone("SELECT full_name FROM users WHERE tg_id=?", (tid,))
        title = f"👨‍🏫 <b>{e(t['full_name'] if t else '')}</b> guruhlari"
    else:
        title = "⚠️ <b>O'qituvchisiz guruhlar</b>"
    await safe_edit(c, title + ("" if n else "\nGuruh yo'q."), mk)
    await c.answer()


# ---------------- guruh ----------------
async def group_view(db, uid, gid, page):
    role = await D.get_role(db, uid)
    g = await db.fetchone("SELECT g.*, u.full_name AS tname FROM groups g "
                          "LEFT JOIN users u ON u.tg_id=g.teacher_id WHERE g.id=?", (gid,))
    studs = await D.group_students(db, gid)
    reg = sum(1 for s in studs if s["is_registry"])
    paid = sum(1 for s in studs if s["paid"]) - reg
    debt = len(studs) - paid - reg
    days, hist = await A.history(db, gid, n=3)
    last = ""
    if days:
        ld = days[-1]
        absent = sum(1 for sid, h in hist.items() if h.get(ld) in ("absent", "excused"))
        last = f"\n📋 Oxirgi davomat: {A.fmt_day(ld)} — kelmagan {absent} ta"
    sched = schedule_text(g)
    text = (f"📚 <b>{e(g['name'])}</b>" + (f" · 👨‍🏫 {e(g['tname'])}" if g["tname"] else " · ⚠️ o'qituvchisiz") +
            (f"\n🗓 {sched}" if sched else "") +
            f"\n👥 {len(studs)} o'quvchi · ✅ {paid} · ❌ {debt}" + (f" · 🏛 {reg}" if reg else "") + last)
    pages = max(1, -(-len(studs) // PAGE))
    page = max(0, min(page, pages - 1))
    b = InlineKeyboardBuilder()
    for s in studs[page * PAGE:(page + 1) * PAGE]:
        mark = "🏛" if s["is_registry"] else ("✅" if s["paid"] else "❌")
        b.button(text=f"{mark} {s['last_name']} {s['first_name']}  {A.marks(days, hist.get(s['id']))}".strip(),
                 callback_data=f"gl:s:{s['id']}:{page}")
    b.adjust(1)
    if pages > 1:
        b.row(btn("◀️" if page else "·", f"gl:g:{gid}:{page - 1}" if page else "noop"),
              btn(f"{page + 1}/{pages}", "noop"),
              btn("▶️" if page < pages - 1 else "·", f"gl:g:{gid}:{page + 1}" if page < pages - 1 else "noop"))
    back = "gl:mine" if role == "teacher" else f"gl:t:{g['teacher_id'] or 0}"
    b.row(btn("📋 Matn ro'yxati", f"gl:txt:{gid}"), btn("⬅️ Orqaga", back))
    if studs:
        text += "\n\nO'quvchini bosing 👇" + ("\n<i>Ismdan keyingi belgilar — oxirgi 3 ta dars davomati</i>" if days else "")
    else:
        text += "\n\nGuruhda o'quvchi yo'q."
    return text, b.as_markup()


@router.callback_query(F.data.startswith("gl:g:"))
async def gl_group(c: CallbackQuery, db):
    parts = c.data.split(":")
    gid, page = int(parts[2]), int(parts[3]) if len(parts) > 3 else 0
    if not await can_access_group(db, c.from_user.id, gid):
        return await c.answer("Bu sizning guruhingiz emas", show_alert=True)
    text, mk = await group_view(db, c.from_user.id, gid, page)
    await safe_edit(c, text, mk)
    await c.answer()


@router.callback_query(F.data.startswith("gl:txt:"))
async def gl_text(c: CallbackQuery, db):
    gid = int(c.data[7:])
    if not await can_access_group(db, c.from_user.id, gid):
        return await c.answer("Bu sizning guruhingiz emas", show_alert=True)
    g = await db.fetchone("SELECT name FROM groups WHERE id=?", (gid,))
    studs = await D.group_students(db, gid)
    lines = [f"{i}. {'🏛' if s['is_registry'] else ('✅' if s['paid'] else '❌')} {s['last_name']} {s['first_name']} "
             f"({s['grade']}-sinf){with_phone(s)}" for i, s in enumerate(studs, 1)]
    text = f"📚 {g['name']} — {len(studs)} ta o'quvchi\n\n" + "\n".join(lines or ["Guruhda o'quvchi yo'q."])
    for i in range(0, len(text), 4000):
        await c.message.answer(text[i:i + 4000])
    await c.answer()


# ---------------- o'quvchi kartochkasi ----------------
async def student_card(db, uid, sid, page):
    role = await D.get_role(db, uid)
    s = await db.fetchone("SELECT s.*, g.name AS gname, g.teacher_id, u.full_name AS tname FROM students s "
                          "JOIN groups g ON g.id=s.group_id LEFT JOIN users u ON u.tg_id=g.teacher_id "
                          "WHERE s.id=?", (sid,))
    if not s:
        return None, None, None
    gid, mo = s["group_id"], D.current_month()
    paid = await db.fetchone("SELECT COALESCE(SUM(amount),0) t, COUNT(*) n FROM payments "
                             "WHERE student_id=? AND month=?", (sid, mo))
    if s["is_registry"]:
        pay = "🏛 reyestr (davlat to'laydi)"
    elif paid["n"]:
        pay = f"✅ to'lagan — {money(paid['t'])}"
    else:
        pay = "❌ qarzdor"
    days, hist = await A.history(db, gid, n=10)
    mine = hist.get(sid, {})
    last3 = "  ".join(f"{A.fmt_day(d)} {A.STATUSES[mine[d]][0]}" if d in mine else f"{A.fmt_day(d)} ▫️"
                      for d in days[-3:])
    missed = A.missed_dates(days, mine)
    text = (f"👤 <b>{e(s['last_name'])} {e(s['first_name'])}</b>\n"
            f"🏫 {e(s['grade'])}-sinf · 📚 {e(s['gname'])}" + (f" · 👨‍🏫 {e(s['tname'])}" if s["tname"] else "") + "\n" +
            (f"📞 {e(s['phone'])}\n" if s["phone"] else "📞 raqam kiritilmagan\n") +
            f"💳 Shu oy ({mo}): {pay}\n"
            f"📅 Oxirgi darslar: {last3 or 'hali davomat olinmagan'}\n" +
            (f"⚠️ Kelmagan kunlar: <b>{', '.join(missed)}</b>" if missed else "👍 Oxirgi darslarga qatnashgan"))
    rows = []
    if role in ("admin", "director"):
        rows.append([btn("💵 To'lov kiritish", f"ps:{sid}"), btn("📞 Telefon", f"ph:{sid}")])
        rows.append([btn("🔀 Ko'chirish", f"ms2:{sid}"), btn("🗑 O'chirish", f"xs:{sid}")])
    else:
        rows.append([btn("📞 Telefon", f"ph:{sid}"), btn("🗑 O'chirish", f"xs:{sid}")])
    rows.append([btn("📅 Davomat tarixi", f"gl:h:{sid}:{page}")])
    rows.append([btn("⬅️ Guruhga qaytish", f"gl:g:{gid}:{page}")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows), gid


@router.callback_query(F.data.startswith("gl:s:"))
async def gl_student(c: CallbackQuery, db):
    parts = c.data.split(":")
    sid, page = int(parts[2]), int(parts[3]) if len(parts) > 3 else 0
    text, mk, gid = await student_card(db, c.from_user.id, sid, page)
    if not text:
        return await c.answer("O'quvchi topilmadi", show_alert=True)
    if not await can_access_group(db, c.from_user.id, gid):
        return await c.answer("Bu sizning guruhingiz emas", show_alert=True)
    await safe_edit(c, text, mk)
    await c.answer()


@router.callback_query(F.data.startswith("gl:h:"))
async def gl_history(c: CallbackQuery, db):
    parts = c.data.split(":")
    sid, page = int(parts[2]), int(parts[3]) if len(parts) > 3 else 0
    s = await db.fetchone("SELECT first_name, last_name, group_id FROM students WHERE id=?", (sid,))
    if not s or not await can_access_group(db, c.from_user.id, s["group_id"]):
        return await c.answer("Ruxsat yo'q", show_alert=True)
    days, hist = await A.history(db, s["group_id"], n=15)
    mine = hist.get(sid, {})
    lines = [f"{A.fmt_day(d)}  {A.STATUSES[mine[d]][0]} {A.STATUSES[mine[d]][1]}" if d in mine
             else f"{A.fmt_day(d)}  ▫️ yozuv yo'q" for d in reversed(days)]
    cnt = {k: sum(1 for v in mine.values() if v == k) for k in A.STATUSES}
    text = (f"📅 <b>{e(s['last_name'])} {e(s['first_name'])}</b> — oxirgi {len(days)} ta dars\n\n" +
            ("\n".join(lines) if lines else "Hali davomat olinmagan.") +
            (f"\n\nKeldi {cnt['present']} · Kelmadi {cnt['absent']} · Kechikdi {cnt['late']} · Sababli {cnt['excused']}"
             if mine else ""))
    await safe_edit(c, text, InlineKeyboardMarkup(inline_keyboard=[[btn("⬅️ Kartochka", f"gl:s:{sid}:{page}")]]))
    await c.answer()
