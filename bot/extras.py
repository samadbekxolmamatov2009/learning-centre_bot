import asyncio
import calendar
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import db as D
from .config import TZ_OFFSET, REMINDER_HOUR
from .handlers import (STAFF, ANYONE, group_picker, confirm_kb, money, months_markup, debtors_text,
                       can_access_group, normalize_phone)

router = Router()
log = logging.getLogger(__name__)


# ---------------- O'quvchini boshqa guruhga ko'chirish ----------------
@router.message(F.text == "🔀 O'quvchini ko'chirish", STAFF)
async def mv_start(m: Message, db):
    mk = await group_picker(db, "mg")
    await m.answer("Qaysi guruhdan?", reply_markup=mk) if mk else await m.answer("Guruhlar yo'q.")


@router.callback_query(F.data.startswith("mg:"), STAFF)
async def mv_group(c: CallbackQuery, db):
    studs = await D.group_students(db, int(c.data[3:]))
    b = InlineKeyboardBuilder()
    for s in studs:
        b.button(text=f"{s['last_name']} {s['first_name']} ({s['grade']})", callback_data=f"ms2:{s['id']}")
    b.adjust(1)
    await c.message.answer("Qaysi o'quvchi?" if studs else "Guruhda o'quvchi yo'q.",
                           reply_markup=b.as_markup() if studs else None)
    await c.answer()


@router.callback_query(F.data.startswith("ms2:"), STAFF)
async def mv_student(c: CallbackQuery, db):
    sid = int(c.data[4:])
    s = await db.fetchone("SELECT * FROM students WHERE id=?", (sid,))
    if not s:
        return await c.answer("Topilmadi", show_alert=True)
    groups = await db.fetchall("SELECT * FROM groups WHERE id<>? ORDER BY name", (s["group_id"],))
    if not groups:
        return await c.answer("Boshqa guruh yo'q", show_alert=True)
    b = InlineKeyboardBuilder()
    for g in groups:
        b.button(text=g["name"], callback_data=f"mt:{sid}:{g['id']}")
    b.adjust(2)
    await c.message.answer(f"{s['last_name']} {s['first_name']} qaysi guruhga ko'chirilsin?",
                           reply_markup=b.as_markup())
    await c.answer()


@router.callback_query(F.data.startswith("mt:"), STAFF)
async def mv_do(c: CallbackQuery, db):
    _, sid, gid = c.data.split(":")
    s = await db.fetchone("SELECT * FROM students WHERE id=?", (int(sid),))
    g = await db.fetchone("SELECT * FROM groups WHERE id=?", (int(gid),))
    if not s or not g:
        return await c.answer("Topilmadi", show_alert=True)
    # Joriy oy to'lovlari ham o'quvchi bilan ko'chadi: tushum va oylik yangi guruhga o'tadi,
    # ikkala o'qituvchida bir xil o'quvchi ikki marta hisoblanmaydi. Eski oylar o'zgarmaydi.
    await db.batch([("UPDATE students SET group_id=? WHERE id=?", (g["id"], s["id"])),
                    ("UPDATE payments SET group_id=? WHERE student_id=? AND month=?",
                     (g["id"], s["id"], D.current_month()))])
    await c.message.edit_text(f"✅ {s['last_name']} {s['first_name']} {g['name']} guruhiga ko'chirildi.")
    await c.answer()


# ---------------- Telefon raqamini kiritish / o'zgartirish ----------------
class EditPhone(StatesGroup):
    value = State()


@router.message(F.text == "📞 Telefonni o'zgartirish", ANYONE)
async def ph_start(m: Message, db):
    uid = m.from_user.id
    mk = await group_picker(db, "pg2", uid if await D.get_role(db, uid) == "teacher" else None)
    await m.answer("Qaysi guruh?", reply_markup=mk) if mk else await m.answer("Guruhlar yo'q.")


@router.callback_query(F.data.startswith("pg2:"))
async def ph_group(c: CallbackQuery, db):
    gid = int(c.data[4:])
    if not await can_access_group(db, c.from_user.id, gid):
        return await c.answer("Bu sizning guruhingiz emas", show_alert=True)
    studs = await D.group_students(db, gid)
    b = InlineKeyboardBuilder()
    for s in studs:
        phone = s["phone"] or "(raqam yo'q)"
        b.button(text=f"{s['last_name']} {s['first_name']} {phone}", callback_data=f"ph:{s['id']}")
    b.adjust(1)
    await c.message.answer("Qaysi o'quvchi?" if studs else "Guruhda o'quvchi yo'q.",
                           reply_markup=b.as_markup() if studs else None)
    await c.answer()


@router.callback_query(F.data.startswith("ph:"))
async def ph_student(c: CallbackQuery, db, state: FSMContext):
    sid = int(c.data[3:])
    s = await db.fetchone("SELECT * FROM students WHERE id=?", (sid,))
    if not s or not await can_access_group(db, c.from_user.id, s["group_id"]):
        return await c.answer("Ruxsat yo'q yoki topilmadi", show_alert=True)
    await state.set_state(EditPhone.value)
    await state.update_data(student_id=sid)
    await c.message.answer(f"{s['last_name']} {s['first_name']} uchun yangi telefon raqam (masalan 90 123 45 67):")
    await c.answer()


@router.message(EditPhone.value)
async def ph_save(m: Message, db, state: FSMContext):
    phone = normalize_phone(m.text or "")
    if phone is None:
        return await m.answer("Raqam noto'g'ri. Masalan: 90 123 45 67")
    sid = (await state.get_data())["student_id"]
    await db.execute("UPDATE students SET phone=? WHERE id=?", (phone, sid))
    await state.clear()
    await m.answer(f"✅ Saqlandi: {phone or 'raqamsiz'}")


# ---------------- To'lovni bekor qilish ----------------
@router.message(F.text == "↩️ To'lovni bekor qilish", STAFF)
async def cp_start(m: Message, db):
    mk = await group_picker(db, "cg")
    await m.answer("Qaysi guruh?", reply_markup=mk) if mk else await m.answer("Guruhlar yo'q.")


@router.callback_query(F.data.startswith("cg:"), STAFF)
async def cp_group(c: CallbackQuery, db):
    studs = await D.group_students(db, int(c.data[3:]))
    b = InlineKeyboardBuilder()
    for s in studs:
        b.button(text=f"{s['last_name']} {s['first_name']}", callback_data=f"cs:{s['id']}")
    b.adjust(1)
    await c.message.answer("Qaysi o'quvchi?" if studs else "Guruhda o'quvchi yo'q.",
                           reply_markup=b.as_markup() if studs else None)
    await c.answer()


@router.callback_query(F.data.startswith("cs:"), STAFF)
async def cp_student(c: CallbackQuery, db):
    sid = int(c.data[3:])
    pays = await db.fetchall("SELECT * FROM payments WHERE student_id=? ORDER BY id DESC LIMIT 10", (sid,))
    if not pays:
        return await c.answer("Bu o'quvchida to'lov yo'q", show_alert=True)
    b = InlineKeyboardBuilder()
    for p in pays:
        b.button(text=f"{p['month']} | {money(p['amount'])} | {str(p['created_at'])[:16]}",
                 callback_data=f"cp:{p['id']}")
    b.adjust(1)
    await c.message.answer("Qaysi to'lov bekor qilinsin? (oxirgi 10 ta)", reply_markup=b.as_markup())
    await c.answer()


@router.callback_query(F.data.startswith("cp:"), STAFF)
async def cp_ask(c: CallbackQuery, db):
    p = await db.fetchone("SELECT * FROM payments WHERE id=?", (int(c.data[3:]),))
    if not p:
        return await c.answer("Topilmadi", show_alert=True)
    await c.message.answer(f"⚠️ {p['month']} oyi uchun {money(p['amount'])} to'lov bekor qilinsinmi?",
                           reply_markup=confirm_kb(f"cpy:{p['id']}"))
    await c.answer()


@router.callback_query(F.data.startswith("cpy:"), STAFF)
async def cp_do(c: CallbackQuery, db):
    pid = int(c.data[4:])
    p = await db.fetchone("SELECT * FROM payments WHERE id=?", (pid,))
    if not p:
        return await c.answer("Topilmadi", show_alert=True)
    await db.execute("DELETE FROM payments WHERE id=?", (pid,))
    await c.message.edit_text(f"↩️ {money(p['amount'])} to'lov ({p['month']}) bekor qilindi.")
    await c.answer()


# ---------------- Oylik hisobot (o'tgan oylar) ----------------
@router.message(F.text == "📅 Hisobot", STAFF)
async def rp_start(m: Message):
    await m.answer("Qaysi oy uchun hisobot?", reply_markup=months_markup("rp"))


async def report_text(db, month):
    out = [f"📅 Hisobot: {month}", "", "Guruhlar:"]
    total = 0
    for g in await db.fetchall("SELECT * FROM groups ORDER BY name"):
        studs = await D.group_students(db, g["id"], month)
        paid = sum(1 for s in studs if s["paid"])
        income = await D.group_income(db, g["id"], month)
        total += income
        out.append(f"• {g['name']}: {money(income)} | to'lagan {paid}, qarzdor {len(studs) - paid}")
    out += [f"Jami tushum: {money(total)}", "", "O'qituvchilar oyligi:"]
    paid_out = 0
    for t in await db.fetchall("SELECT u.tg_id, u.full_name FROM users u JOIN teachers t ON t.tg_id=u.tg_id "
                               "ORDER BY u.full_name"):
        sal = (await D.teacher_salary(db, t["tg_id"], month))[3]
        paid_out += sal
        out.append(f"• {t['full_name']}: {money(sal)}")
    out.append(f"Jami oyliklar: {money(paid_out)}")
    return "\n".join(out)


@router.callback_query(F.data.startswith("rp:"), STAFF)
async def rp_month(c: CallbackQuery, db):
    await c.message.edit_text(await report_text(db, c.data[3:]) + "\n\nBoshqa oy:",
                              reply_markup=months_markup("rp"))
    await c.answer()


# ---------------- Oy oxirida qarzdorlar haqida avtomatik xabar ----------------
def local_now():
    return datetime.now(timezone(timedelta(hours=TZ_OFFSET)))


async def send_month_end_notice(bot: Bot, db):
    now = local_now()
    last_day = calendar.monthrange(now.year, now.month)[1]
    key = f"debt-{now:%Y-%m}"
    if now.day != last_day or now.hour < REMINDER_HOUR:
        return
    if await db.fetchone("SELECT 1 FROM notices WHERE key=?", (key,)):
        return
    parts = [f"⏰ Oy tugayapti ({now:%Y-%m}). Qarzdor o'quvchilar:"]
    for g in await db.fetchall("SELECT id FROM groups ORDER BY name"):
        parts.append(await debtors_text(db, g["id"]))
    text = "\n\n".join(parts)
    chunks, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > 3800:
            chunks.append(cur)
            cur = ""
        cur += block + "\n\n"
    chunks.append(cur)
    staff = await db.fetchall("SELECT tg_id FROM users WHERE role IN ('admin','director')")
    for u in staff:
        for ch in chunks:
            try:
                await bot.send_message(u["tg_id"], ch.strip())
            except Exception:
                log.warning("Xabar yuborilmadi: %s", u["tg_id"])
    await db.execute("INSERT OR IGNORE INTO notices(key) VALUES(?)", (key,))


async def scheduler(bot: Bot, db):
    while True:
        try:
            await send_month_end_notice(bot, db)
        except Exception:
            log.exception("Oy oxiri xabarida xato")
        await asyncio.sleep(1800)
