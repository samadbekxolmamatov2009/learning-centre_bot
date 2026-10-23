import asyncio
import calendar
import io
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from openpyxl import Workbook
from openpyxl.styles import Font

from . import db as D
from .config import TZ_OFFSET, REMINDER_HOUR, WEBAPP_URL
from .importer import parse_file
from .handlers import (webapp_markup, Role, STAFF, ANYONE, DIRECTOR, prev_months, with_phone, student_pager, group_picker, confirm_kb, money, months_markup, debtors_text,
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
    mk, n = await student_pager(db, int(c.data[3:]), 0, "ms2")
    await c.message.answer("Qaysi o'quvchi?" if n else "Guruhda o'quvchi yo'q.", reply_markup=mk)
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
    mk, n = await student_pager(db, gid, 0, "ph")
    await c.message.answer("Qaysi o'quvchi?" if n else "Guruhda o'quvchi yo'q.", reply_markup=mk)
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
    mk, n = await student_pager(db, int(c.data[3:]), 0, "cs")
    await c.message.answer("Qaysi o'quvchi?" if n else "Guruhda o'quvchi yo'q.", reply_markup=mk)
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
        reg = sum(1 for s in studs if s["is_registry"])
        paid = sum(1 for s in studs if s["paid"]) - reg
        income = await D.group_income(db, g["id"], month)
        total += income
        out.append(f"• {g['name']}: {money(income)} | to'lagan {paid}, "
                   + (f"reyestr {reg}, " if reg else "") + f"qarzdor {len(studs) - paid - reg}")
    reg_total = await D.registry_total(db, month)
    out.append(f"Jami tushum: {money(total)}")
    if reg_total:
        out.append(f"🏛 Reyestr (davlat to'lovi, o'qituvchilarga to'liq): {money(reg_total)}")
    out += ["", "O'qituvchilar oyligi:"]
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


async def check_attendance_reminders(bot: Bot, db):
    """Dars vaqtidan 20 daqiqa o'tib davomat olinmagan bo'lsa o'qituvchiga, 2 soatdan keyin adminga xabar."""
    now = D.now_local()
    today = now.date().isoformat()
    for g in await db.fetchall("SELECT g.id, g.name, g.teacher_id, g.lesson_days, g.lesson_time, u.full_name tname "
                               "FROM groups g LEFT JOIN users u ON u.tg_id=g.teacher_id "
                               "WHERE g.lesson_days<>'' AND g.lesson_time<>'' AND g.teacher_id IS NOT NULL"):
        if str(now.isoweekday()) not in g["lesson_days"].split(","):
            continue
        try:
            hh, mm = map(int, g["lesson_time"].split(":"))
        except ValueError:
            continue
        late = (now - now.replace(hour=hh, minute=mm, second=0, microsecond=0)).total_seconds() / 60
        if late < 20 or late > 8 * 60:
            continue
        if await db.fetchone("SELECT 1 FROM attendance WHERE group_id=? AND day=? LIMIT 1", (g["id"], today)):
            continue
        k1, k2 = f"attrem-{g['id']}-{today}", f"attadm-{g['id']}-{today}"
        if not await db.fetchone("SELECT 1 FROM notices WHERE key=?", (k1,)):
            await db.execute("INSERT OR IGNORE INTO notices(key) VALUES(?)", (k1,))
            kb_ = (webapp_markup("📝 Davomatni ochish") if WEBAPP_URL else
                   InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                       text="📝 Davomat olish", callback_data=f"ag:{g['id']}")]]))
            try:
                await bot.send_message(g["teacher_id"], f"⏰ {g['name']} guruhi ({g['lesson_time']}) davomati hali "
                                       "olinmadi. Iltimos, belgilab yuboring.", reply_markup=kb_)
            except Exception:
                log.warning("Eslatma yuborilmadi: %s", g["teacher_id"])
        if late >= 120 and not await db.fetchone("SELECT 1 FROM notices WHERE key=?", (k2,)):
            await db.execute("INSERT OR IGNORE INTO notices(key) VALUES(?)", (k2,))
            for u in await db.fetchall("SELECT tg_id FROM users WHERE role IN ('admin','director')"):
                try:
                    await bot.send_message(u["tg_id"], f"⚠️ {g['name']} ({g['tname']}) guruhi davomati olinmadi "
                                           f"(dars {g['lesson_time']} da edi).")
                except Exception:
                    pass


async def scheduler(bot: Bot, db):
    while True:
        for job in (send_month_end_notice, check_attendance_reminders):
            try:
                await job(bot, db)
            except Exception:
                log.exception("Rejali ishda xato: %s", job.__name__)
        await asyncio.sleep(300)


# ---------------- Adminni o'chirish (faqat direktor) ----------------
@router.message(F.text == "🗑 Adminni o'chirish", DIRECTOR)
async def xa_start(m: Message, db):
    admins = await db.fetchall("SELECT tg_id, full_name FROM users WHERE role='admin' ORDER BY full_name")
    if not admins:
        return await m.answer("Adminlar yo'q.")
    b = InlineKeyboardBuilder()
    for a in admins:
        b.button(text=f"{a['full_name']} ({a['tg_id']})", callback_data=f"xa:{a['tg_id']}")
    b.adjust(1)
    await m.answer("Qaysi admin o'chirilsin?", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("xa:"), DIRECTOR)
async def xa_ask(c: CallbackQuery, db):
    a = await db.fetchone("SELECT * FROM users WHERE tg_id=? AND role='admin'", (int(c.data[3:]),))
    if not a:
        return await c.answer("Topilmadi", show_alert=True)
    await c.message.answer(f"⚠️ Admin {a['full_name']} o'chirilsinmi? Botdan foydalanish huquqi olinadi.",
                           reply_markup=confirm_kb(f"xay:{a['tg_id']}"))
    await c.answer()


@router.callback_query(F.data.startswith("xay:"), DIRECTOR)
async def xa_do(c: CallbackQuery, db):
    a = await db.fetchone("SELECT * FROM users WHERE tg_id=? AND role='admin'", (int(c.data[4:]),))
    if not a:
        return await c.answer("Topilmadi", show_alert=True)
    await db.execute("DELETE FROM users WHERE tg_id=? AND role='admin'", (a["tg_id"],))
    await c.message.edit_text(f"🗑 Admin {a['full_name']} o'chirildi.")
    await c.answer()


# ---------------- Reyestr belgilash (admin, direktor) ----------------
@router.message(F.text == "🏛 Reyestr belgilash", STAFF)
async def rx_start(m: Message, db):
    mk = await group_picker(db, "rxg")
    await m.answer("Qaysi guruh?", reply_markup=mk) if mk else await m.answer("Guruhlar yo'q.")


@router.callback_query(F.data.startswith("rxg:"), STAFF)
async def rx_group(c: CallbackQuery, db):
    mk, n = await student_pager(db, int(c.data[4:]), 0, "rxs")
    await c.message.answer("O'quvchini bosing - reyestr / oddiy holati almashadi (🏛 - reyestr):"
                           if n else "Guruhda o'quvchi yo'q.", reply_markup=mk)
    await c.answer()


@router.callback_query(F.data.startswith("rxs:"), STAFF)
async def rx_toggle(c: CallbackQuery, db):
    s = await db.fetchone("SELECT * FROM students WHERE id=?", (int(c.data[4:]),))
    if not s:
        return await c.answer("Topilmadi", show_alert=True)
    if s["is_registry"]:
        await db.execute("UPDATE students SET is_registry=0, hidden=0 WHERE id=?", (s["id"],))
        txt = "oddiy o'quvchi qilindi"
    else:
        hidden = 1 if await D.get_setting(db, "registry_hidden") == "1" else 0
        await db.execute("UPDATE students SET is_registry=1, hidden=? WHERE id=?", (hidden, s["id"]))
        txt = "reyestr qilindi" + (" (hozir yashirin)" if hidden else "")
    await c.message.answer(f"✅ {s['last_name']} {s['first_name']} {txt}.")
    await c.answer()


# ---------------- Reyestr o'quvchilarni yashirish / ochish (faqat direktor) ----------------
async def _reg_stats(db):
    r = await db.fetchone("SELECT COUNT(*) n, COALESCE(SUM(hidden),0) h FROM students WHERE is_registry=1")
    return r["n"], r["h"]


async def _reg_panel(db):
    n, h = await _reg_stats(db)
    mode = await D.get_setting(db, "registry_hidden") == "1"
    mode_txt = ("YOQILGAN (yangi qo'shiladigan reyestr o'quvchilar ham yashirin bo'ladi)" if mode
                else "o'chirilgan")
    text = (f"🏛 Reyestr o'quvchilar: {n} ta (ochiq {n - h}, yashirin {h})\n"
            f"Yashirin rejim: {mode_txt}\n\n"
            "Yashirin o'quvchilar ro'yxatlarda, davomatda, qarzdorlarda va hisobda ko'rinmaydi va hisoblanmaydi. "
            "Ochilgan kundan boshlab davomatga kiradi va hisoblanadi.")
    kb_ = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙈 Hammasini yashirish", callback_data="rh:hide")],
        [InlineKeyboardButton(text="👁 Hammasini ochish", callback_data="rh:show")],
        [InlineKeyboardButton(text="📋 Yashirinlar ro'yxati", callback_data="rh:list")]])
    return text, kb_


@router.message(F.text == "👁 Reyestr yashirish/ochish", DIRECTOR)
async def rh_start(m: Message, db):
    text, kb_ = await _reg_panel(db)
    await m.answer(text, reply_markup=kb_)


@router.callback_query(F.data.in_({"rh:hide", "rh:show"}), DIRECTOR)
async def rh_toggle(c: CallbackQuery, db):
    hide = c.data == "rh:hide"
    await db.batch([("UPDATE students SET hidden=? WHERE is_registry=1", (int(hide),)),
                    ("INSERT INTO settings(key,value) VALUES('registry_hidden',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("1" if hide else "0",))])
    text, kb_ = await _reg_panel(db)
    await c.message.edit_text(("🙈 Hammasi yashirildi.\n\n" if hide else "👁 Hammasi ochildi.\n\n") + text,
                              reply_markup=kb_)
    await c.answer()


@router.callback_query(F.data == "rh:list", DIRECTOR)
async def rh_list(c: CallbackQuery, db):
    rows = await db.fetchall("SELECT s.*, g.name AS gname FROM students s JOIN groups g ON g.id=s.group_id "
                             "WHERE s.is_registry=1 AND s.hidden=1 ORDER BY g.name, s.last_name")
    text = "Yashirin reyestr o'quvchilar yo'q." if not rows else "🙈 Yashirin reyestr o'quvchilar:\n" + "\n".join(
        f"{i}. {r['last_name']} {r['first_name']} ({r['grade']}-sinf) | {r['gname']}{with_phone(r)}"
        for i, r in enumerate(rows, 1))
    for i in range(0, len(text), 4000):
        await c.message.answer(text[i:i + 4000])
    await c.answer()


# ---------------- O'qituvchi ma'lumotlarini tahrirlash (faqat direktor) ----------------
class EditTeacher(StatesGroup):
    name = State(); value = State(); reg = State()


async def _teacher_card(db, tid):
    t = await db.fetchone("SELECT u.full_name, t.* FROM users u JOIN teachers t ON t.tg_id=u.tg_id "
                          "WHERE u.tg_id=?", (tid,))
    if not t:
        return None, None
    how = (f"{t['pay_value']:g}% (to'lovdan)" if t["pay_type"] == "percent" else
           f"{money(t['pay_value'])} / o'quvchi ({money(t['pay_value'] * D.LOW_PAY_MULT)} gacha to'lasa to'lovning "
           f"{D.LOW_PAY_PERCENT}%)")
    text = (f"👨‍🏫 {t['full_name']} (ID {tid})\n💼 Oylik: {how}\n"
            f"🏛 Reyestr, bitta dars: {money(t['registry_rate']) if t['registry_rate'] else 'kiritilmagan'}")
    kb_ = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Ismni o'zgartirish", callback_data=f"etn:{tid}")],
        [InlineKeyboardButton(text="💼 Oylik turi / qiymati", callback_data=f"etp:{tid}")],
        [InlineKeyboardButton(text="🏛 Reyestr dars narxi", callback_data=f"etr:{tid}")]])
    return text, kb_


@router.message(F.text == "✏️ O'qituvchini tahrirlash", DIRECTOR)
async def et_start(m: Message, db):
    ts = await db.fetchall("SELECT u.tg_id, u.full_name FROM users u JOIN teachers t ON t.tg_id=u.tg_id "
                           "ORDER BY u.full_name")
    if not ts:
        return await m.answer("O'qituvchilar yo'q.")
    b = InlineKeyboardBuilder()
    for t in ts:
        b.button(text=t["full_name"], callback_data=f"et:{t['tg_id']}")
    b.adjust(1)
    await m.answer("Qaysi o'qituvchi?", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("et:"), DIRECTOR)
async def et_pick(c: CallbackQuery, db):
    text, kb_ = await _teacher_card(db, int(c.data[3:]))
    if not text:
        return await c.answer("Topilmadi", show_alert=True)
    await c.message.answer(text, reply_markup=kb_)
    await c.answer()


@router.callback_query(F.data.startswith("etn:"), DIRECTOR)
async def et_name(c: CallbackQuery, state: FSMContext):
    await state.set_state(EditTeacher.name)
    await state.update_data(tid=int(c.data[4:]))
    await c.message.answer("Yangi ism familiya:")
    await c.answer()


@router.message(EditTeacher.name)
async def et_name_save(m: Message, db, state: FSMContext):
    name = (m.text or "").strip()
    if len(name) < 2:
        return await m.answer("Ism familiyani yozing.")
    tid = (await state.get_data())["tid"]
    await db.execute("UPDATE users SET full_name=? WHERE tg_id=?", (name, tid))
    await state.clear()
    text, kb_ = await _teacher_card(db, tid)
    await m.answer("✅ Saqlandi.\n" + text, reply_markup=kb_)


@router.callback_query(F.data.startswith("etp:"), DIRECTOR)
async def et_pay(c: CallbackQuery):
    tid = c.data[4:]
    await c.message.answer("Oylik turi:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Foiz (%)", callback_data=f"etpt:{tid}:percent"),
        InlineKeyboardButton(text="O'quvchi boshiga", callback_data=f"etpt:{tid}:per_student")]]))
    await c.answer()


@router.callback_query(F.data.startswith("etpt:"), DIRECTOR)
async def et_pay_type(c: CallbackQuery, state: FSMContext):
    _, tid, pt = c.data.split(":")
    await state.set_state(EditTeacher.value)
    await state.update_data(tid=int(tid), pay_type=pt)
    await c.message.answer("Foiz (masalan 40):" if pt == "percent" else
                           "Bir o'quvchi uchun summa (so'm), masalan 200000:")
    await c.answer()


@router.message(EditTeacher.value)
async def et_pay_save(m: Message, db, state: FSMContext):
    try:
        v = float((m.text or "").replace(" ", "").replace(",", "."))
        assert v > 0
    except Exception:
        return await m.answer("Musbat son kiriting.")
    d = await state.get_data()
    await db.execute("UPDATE teachers SET pay_type=?, pay_value=? WHERE tg_id=?", (d["pay_type"], v, d["tid"]))
    await state.clear()
    text, kb_ = await _teacher_card(db, d["tid"])
    await m.answer("✅ Saqlandi. Oylik hisobi (o'tgan oylar ham) yangi shartga ko'ra qayta hisoblanadi.\n" + text,
                   reply_markup=kb_)


@router.callback_query(F.data.startswith("etr:"), DIRECTOR)
async def et_reg(c: CallbackQuery, state: FSMContext):
    await state.set_state(EditTeacher.reg)
    await state.update_data(tid=int(c.data[4:]))
    await c.message.answer("Reyestr o'quvchi bitta darsga kelganda o'qituvchi oladigan summa (so'm). "
                           "Yo'q bo'lsa 0:")
    await c.answer()


@router.message(EditTeacher.reg)
async def et_reg_save(m: Message, db, state: FSMContext):
    try:
        v = int((m.text or "").replace(" ", ""))
        assert v >= 0
    except Exception:
        return await m.answer("0 yoki musbat butun son kiriting.")
    tid = (await state.get_data())["tid"]
    await db.execute("UPDATE teachers SET registry_rate=? WHERE tg_id=?", (v, tid))
    await state.clear()
    text, kb_ = await _teacher_card(db, tid)
    await m.answer("✅ Saqlandi. Yangi narx faqat keyingi darslarga ta'sir qiladi.\n" + text, reply_markup=kb_)


# ---------------- Excel / Word fayldan o'quvchilarni yuklash (bitta guruhga) ----------------
class Upload(StatesGroup):
    file = State()


UPLOAD_HELP = (
    "📤 Guruh: {name}\n\n"
    "Shu guruh o'quvchilari ro'yxatini Excel (.xlsx) yoki Word (.docx) fayl qilib yuboring.\n\n"
    "Jadval ustunlari (sarlavhasi bilan):\n"
    "Familiya | Ism | Sinf | Telefon\n"
    "yoki bitta ustunda \"Familiya Ism\" ham bo'ladi. Sinf va telefon bo'lmasa ham mayli.\n"
    "Sarlavha yo'q bo'lsa, tartib shunday: Familiya, Ism, Sinf, Telefon.\n"
    "Word'da jadval yoki har qatorga bittadan: Valiyev Ali, 7, 901234567\n\n"
    "Hamma o'quvchilar oddiy (reyestrsiz) bo'lib qo'shiladi. Bekor qilish: /cancel")


@router.message(F.text == "📤 Fayldan yuklash", ANYONE)
async def up_start(m: Message, db):
    uid = m.from_user.id
    mk = await group_picker(db, "ugp", uid if await D.get_role(db, uid) == "teacher" else None)
    await m.answer("Qaysi guruhga yuklaymiz?", reply_markup=mk) if mk else await m.answer("Guruhlar yo'q.")


@router.callback_query(F.data.startswith("ugp:"))
async def up_group(c: CallbackQuery, db, state: FSMContext):
    gid = int(c.data[4:])
    if not await can_access_group(db, c.from_user.id, gid):
        return await c.answer("Bu sizning guruhingiz emas", show_alert=True)
    g = await db.fetchone("SELECT name FROM groups WHERE id=?", (gid,))
    await state.set_state(Upload.file)
    await state.update_data(group_id=gid)
    await c.message.answer(UPLOAD_HELP.format(name=g["name"]))
    await c.answer()


@router.message(Upload.file, ~F.document)
async def up_not_file(m: Message):
    await m.answer("Fayl yuboring (.xlsx yoki .docx) yoki /cancel.")


@router.message(Upload.file, F.document)
async def up_file(m: Message, db, state: FSMContext, bot: Bot):
    doc = m.document
    if (doc.file_size or 0) > 5 * 1024 * 1024:
        return await m.answer("Fayl juda katta (5 MB gacha).")
    gid = (await state.get_data())["group_id"]
    if not await can_access_group(db, m.from_user.id, gid):
        await state.clear()
        return await m.answer("Bu sizning guruhingiz emas.")
    buf = io.BytesIO()
    await bot.download(doc, destination=buf)
    try:
        students, errors = parse_file(doc.file_name or "", buf.getvalue())
    except ValueError as e:
        return await m.answer(f"❌ {e}")
    except Exception:
        log.exception("Fayl o'qilmadi")
        return await m.answer("❌ Faylni o'qib bo'lmadi. Boshqa nomli .xlsx yoki .docx qilib saqlab qayta yuboring.")
    if not students:
        return await m.answer("❌ Faylda o'quvchi topilmadi. Ustun sarlavhalarini tekshiring (Familiya, Ism, Sinf, Telefon).")

    existing = {(r["last_name"].casefold(), r["first_name"].casefold())
                for r in await db.fetchall("SELECT last_name, first_name FROM students WHERE group_id=?", (gid,))}
    stmts, dups, bad_phone, seen = [], [], [], set()
    for st in students:
        key = (st["last"].casefold(), st["first"].casefold())
        if key in existing or key in seen:
            dups.append(f"{st['last']} {st['first']}")
            continue
        seen.add(key)
        phone = normalize_phone(st["phone"]) if st["phone"] else ""
        if phone is None:
            bad_phone.append(f"{st['last']} {st['first']} ({st['phone']})")
            phone = ""
        stmts.append(("INSERT INTO students(first_name,last_name,grade,phone,group_id) VALUES(?,?,?,?,?)",
                      (st["first"], st["last"], st["grade"] or "-", phone, gid)))
    for i in range(0, len(stmts), 300):
        await db.batch(stmts[i:i + 300])
    await state.clear()

    g = await db.fetchone("SELECT name FROM groups WHERE id=?", (gid,))
    out = [f"✅ {g['name']} guruhiga {len(stmts)} ta o'quvchi qo'shildi."]
    if dups:
        out.append(f"⏭ {len(dups)} ta takror (guruhda bor) o'tkazib yuborildi.")
    if errors:
        out.append(f"⚠️ {len(errors)} ta qator o'qilmadi:")
        out += [f"  • {line}-qator: {why}" for line, why in errors[:15]]
    if bad_phone:
        out.append(f"📞 {len(bad_phone)} ta telefon noto'g'ri (raqamsiz qo'shildi):")
        out += [f"  • {x}" for x in bad_phone[:15]]
    text = "\n".join(out)
    await m.answer(text[:4000])


# ---------------- Dars jadvali (admin, direktor) ----------------
class Schedule(StatesGroup):
    time = State()


WD_NAMES = [("1", "Du"), ("2", "Se"), ("3", "Ch"), ("4", "Pa"), ("5", "Ju"), ("6", "Sh"), ("7", "Ya")]


async def _schedule_card(db, gid):
    g = await db.fetchone("SELECT * FROM groups WHERE id=?", (gid,))
    days = set((g["lesson_days"] or "").split(","))
    b = InlineKeyboardBuilder()
    for n, name in WD_NAMES:
        b.button(text=("✅ " if n in days else "") + name, callback_data=f"sd:{gid}:{n}")
    b.adjust(4)
    b.row(InlineKeyboardButton(text=f"⏰ Vaqt: {g['lesson_time'] or 'kiritilmagan'}", callback_data=f"sdt:{gid}"))
    text = (f"🗓 <b>{g['name']}</b> dars jadvali\nKunlarni bosib belgilang va vaqtni kiriting.\n"
            "Shunda dars vaqtidan keyin davomat olinmasa, o'qituvchiga eslatma boradi.")
    return text, b.as_markup()


@router.message(F.text == "🗓 Dars jadvali", STAFF)
async def sch_start(m: Message, db):
    mk = await group_picker(db, "sch")
    await m.answer("Qaysi guruh?", reply_markup=mk) if mk else await m.answer("Guruhlar yo'q.")


@router.callback_query(F.data.startswith("sch:"), STAFF)
async def sch_group(c: CallbackQuery, db):
    text, mk = await _schedule_card(db, int(c.data[4:]))
    await c.message.answer(text, reply_markup=mk, parse_mode="HTML")
    await c.answer()


@router.callback_query(F.data.startswith("sd:"), STAFF)
async def sch_toggle(c: CallbackQuery, db):
    _, gid, n = c.data.split(":")
    g = await db.fetchone("SELECT lesson_days FROM groups WHERE id=?", (int(gid),))
    days = {d for d in (g["lesson_days"] or "").split(",") if d}
    days ^= {n}
    await db.execute("UPDATE groups SET lesson_days=? WHERE id=?", (",".join(sorted(days)), int(gid)))
    text, mk = await _schedule_card(db, int(gid))
    await c.message.edit_text(text, reply_markup=mk, parse_mode="HTML")
    await c.answer()


@router.callback_query(F.data.startswith("sdt:"), STAFF)
async def sch_time(c: CallbackQuery, state: FSMContext):
    await state.set_state(Schedule.time)
    await state.update_data(gid=int(c.data[4:]))
    await c.message.answer("Dars boshlanish vaqti (masalan 15:00). Olib tashlash uchun - yuboring:")
    await c.answer()


@router.message(Schedule.time)
async def sch_time_save(m: Message, db, state: FSMContext):
    t = (m.text or "").strip().replace(".", ":")
    if t == "-":
        t = ""
    else:
        try:
            hh, mm = map(int, t.split(":"))
            assert 0 <= hh < 24 and 0 <= mm < 60
            t = f"{hh:02d}:{mm:02d}"
        except Exception:
            return await m.answer("Vaqt noto'g'ri. Masalan: 15:00")
    gid = (await state.get_data())["gid"]
    await db.execute("UPDATE groups SET lesson_time=? WHERE id=?", (t, gid))
    await state.clear()
    text, mk = await _schedule_card(db, gid)
    await m.answer("✅ Saqlandi.\n" + text, reply_markup=mk, parse_mode="HTML")


# ---------------- Panel (Mini App) ----------------
@router.message(F.text == "🖥 Panel", STAFF)
async def open_panel(m: Message):
    if not WEBAPP_URL:
        return await m.answer("Mini App hali ulanmagan (Render'da Web Service va WEBAPP_URL kerak).")
    await m.answer("📊 Panelni ochish uchun tugmani bosing 👇", reply_markup=webapp_markup("🖥 Panelni ochish"))
