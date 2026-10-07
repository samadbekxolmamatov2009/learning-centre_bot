from datetime import date

from aiogram import Router, F, Bot
from aiogram.filters import Command, Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import db as D
from .pdfgen import attendance_pdf

router = Router()


def money(x) -> str:
    return f"{int(round(x)):,}".replace(",", " ") + " so'm"


class Role(Filter):
    def __init__(self, *roles):
        self.roles = roles

    async def __call__(self, event, db) -> bool:
        return await D.get_role(db, event.from_user.id) in self.roles


STAFF = Role("admin", "director")
DIRECTOR = Role("director")
TEACHER = Role("teacher")
ANYONE = Role("admin", "director", "teacher")


def normalize_phone(text: str):
    """'+998901234567' ko'rinishiga keltiradi. '-' yoki bo'sh => ''. Noto'g'ri bo'lsa None."""
    t = text.strip()
    if t in ("-", ""):
        return ""
    digits = "".join(ch for ch in t if ch.isdigit())
    if len(digits) == 9:
        digits = "998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        return "+" + digits
    return None


def with_phone(s) -> str:
    return f" 📞 {s['phone']}" if s.get("phone") else ""


def kb(rows):
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in r] for r in rows],
                               resize_keyboard=True)


MENU_ADMIN = kb([["➕ O'quvchi", "➕ Guruh"], ["💵 To'lov kiritish", "📋 Qarzdorlar"],
                 ["📊 Guruh hisobi", "🗑 O'quvchini o'chirish"],
                 ["🗑 Guruhni o'chirish", "🗑 O'qituvchini o'chirish"],
                 ["🔁 Guruh o'qituvchisini almashtirish", "🔀 O'quvchini ko'chirish"],
                 ["↩️ To'lovni bekor qilish", "📅 Hisobot"],
                 ["📞 Telefonni o'zgartirish", "🔎 Qidirish"],
                 ["📥 Excel"]])
MENU_DIRECTOR = kb([["➕ O'quvchi", "➕ Guruh"], ["💵 To'lov kiritish", "📋 Qarzdorlar"],
                    ["📊 Guruh hisobi", "👨‍🏫 O'qituvchi qo'shish"],
                    ["🛡 Admin qo'shish", "💰 Oyliklar"],
                    ["🗑 O'quvchini o'chirish", "🗑 Guruhni o'chirish"],
                    ["🗑 O'qituvchini o'chirish", "🔁 Guruh o'qituvchisini almashtirish"],
                    ["🔀 O'quvchini ko'chirish", "↩️ To'lovni bekor qilish"],
                    ["📅 Hisobot", "📞 Telefonni o'zgartirish"],
                    ["🔎 Qidirish", "📥 Excel"], ["📈 Statistika", "🗑 Adminni o'chirish"]])
MENU_TEACHER = kb([["✅ Davomat", "➕ O'quvchi"],
                   ["💰 Oylikni ko'rish", "📋 Qarzdorlarni ko'rish"],
                   ["🗑 O'quvchini o'chirish", "📞 Telefonni o'zgartirish"],
                   ["🔎 Qidirish"]])


MENU_TEXTS = {b.text for m in (MENU_ADMIN, MENU_DIRECTOR, MENU_TEACHER)
              for row in m.keyboard for b in row}


@router.message.outer_middleware()
async def menu_resets_state(handler, event: Message, data):
    """Kutilayotgan savol vaqtida menyu tugmasi bosilsa, holatni tozalaydi
    (aks holda tugma matni ism/guruh nomi sifatida saqlanib qoladi)."""
    if event.text in MENU_TEXTS and data.get("state"):
        await data["state"].clear()
    return await handler(event, data)


async def menu_for(db, uid):
    return {"director": MENU_DIRECTOR, "admin": MENU_ADMIN,
            "teacher": MENU_TEACHER}.get(await D.get_role(db, uid))


@router.message(Command("start"))
async def start(m: Message, db, state: FSMContext):
    await state.clear()
    menu = await menu_for(db, m.from_user.id)
    if not menu:
        return await m.answer(f"Siz ro'yxatda yo'qsiz. Direktorga ID ingizni bering: {m.from_user.id}")
    await m.answer("Asosiy menyu", reply_markup=menu)


@router.message(Command("cancel"))
async def cancel(m: Message, db, state: FSMContext):
    await state.clear()
    await m.answer("Bekor qilindi.", reply_markup=await menu_for(db, m.from_user.id))


async def group_picker(db, prefix, teacher_id=None):
    if teacher_id:
        groups = await D.fetchall(db, "SELECT * FROM groups WHERE teacher_id=?", (teacher_id,))
    else:
        groups = await D.fetchall(db, "SELECT * FROM groups ORDER BY name")
    b = InlineKeyboardBuilder()
    for g in groups:
        b.button(text=g["name"], callback_data=f"{prefix}:{g['id']}")
    b.adjust(2)
    return b.as_markup() if groups else None


async def can_access_group(db, uid, gid) -> bool:
    """Admin/direktor - hamma guruh, o'qituvchi - faqat o'zining guruhi."""
    role = await D.get_role(db, uid)
    g = await D.fetchone(db, "SELECT teacher_id FROM groups WHERE id=?", (gid,))
    if not g or role is None:
        return False
    return role in ("admin", "director") or g["teacher_id"] == uid


def confirm_kb(yes, no="x:no"):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=yes),
        InlineKeyboardButton(text="❌ Yo'q", callback_data=no)]])


@router.callback_query(F.data == "x:no")
async def x_no(c: CallbackQuery):
    await c.message.edit_text("Bekor qilindi.")
    await c.answer()


# ---------------- O'chirish: o'quvchi (hamma), guruh va o'qituvchi (admin/direktor) ----------------
@router.message(F.text == "🗑 O'quvchini o'chirish", ANYONE)
async def xs_start(m: Message, db):
    uid = m.from_user.id
    mk = await group_picker(db, "xg", uid if await D.get_role(db, uid) == "teacher" else None)
    await m.answer("Qaysi guruhdan?", reply_markup=mk) if mk else await m.answer("Guruhlar yo'q.")


@router.callback_query(F.data.startswith("xg:"))
async def xs_group(c: CallbackQuery, db):
    gid = int(c.data[3:])
    if not await can_access_group(db, c.from_user.id, gid):
        return await c.answer("Bu sizning guruhingiz emas", show_alert=True)
    studs = await D.group_students(db, gid)
    b = InlineKeyboardBuilder()
    for s in studs:
        b.button(text=f"{s['last_name']} {s['first_name']} ({s['grade']})", callback_data=f"xs:{s['id']}")
    b.adjust(1)
    await c.message.answer("O'chiriladigan o'quvchini tanlang:" if studs else "Guruhda o'quvchi yo'q.",
                           reply_markup=b.as_markup() if studs else None)
    await c.answer()


async def _student_if_allowed(db, uid, sid):
    s = await D.fetchone(db, "SELECT * FROM students WHERE id=?", (sid,))
    return s if s and await can_access_group(db, uid, s["group_id"]) else None


@router.callback_query(F.data.startswith("xs:"))
async def xs_ask(c: CallbackQuery, db):
    s = await _student_if_allowed(db, c.from_user.id, int(c.data[3:]))
    if not s:
        return await c.answer("Ruxsat yo'q yoki topilmadi", show_alert=True)
    await c.message.answer(f"{s['last_name']} {s['first_name']} o'chirilsinmi?",
                           reply_markup=confirm_kb(f"xsy:{s['id']}"))
    await c.answer()


@router.callback_query(F.data.startswith("xsy:"))
async def xs_do(c: CallbackQuery, db):
    s = await _student_if_allowed(db, c.from_user.id, int(c.data[4:]))
    if not s:
        return await c.answer("Ruxsat yo'q yoki topilmadi", show_alert=True)
    await db.execute("DELETE FROM students WHERE id=?", (s["id"],))
    await db.commit()
    await c.message.edit_text(f"🗑 {s['last_name']} {s['first_name']} o'chirildi.")
    await c.answer()


@router.message(F.text == "🗑 Guruhni o'chirish", STAFF)
async def xgr_start(m: Message, db):
    mk = await group_picker(db, "xgr")
    await m.answer("Qaysi guruh o'chirilsin?", reply_markup=mk) if mk else await m.answer("Guruhlar yo'q.")


@router.callback_query(F.data.startswith("xgr:"), STAFF)
async def xgr_ask(c: CallbackQuery, db):
    g = await D.fetchone(db, "SELECT * FROM groups WHERE id=?", (int(c.data[4:]),))
    if not g:
        return await c.answer("Topilmadi", show_alert=True)
    n = (await D.fetchone(db, "SELECT COUNT(*) n FROM students WHERE group_id=?", (g["id"],)))["n"]
    await c.message.answer(f"⚠️ {g['name']} guruhi va undagi {n} ta o'quvchi o'chiriladi. Davom etasizmi?",
                           reply_markup=confirm_kb(f"xgry:{g['id']}"))
    await c.answer()


@router.callback_query(F.data.startswith("xgry:"), STAFF)
async def xgr_do(c: CallbackQuery, db):
    gid = int(c.data[5:])
    g = await D.fetchone(db, "SELECT name FROM groups WHERE id=?", (gid,))
    if not g:
        return await c.answer("Topilmadi", show_alert=True)
    await db.batch([("DELETE FROM students WHERE group_id=?", (gid,)),
                    ("DELETE FROM groups WHERE id=?", (gid,))])
    await c.message.edit_text(f"🗑 Guruh {g['name']} o'chirildi.")
    await c.answer()


@router.message(F.text == "🗑 O'qituvchini o'chirish", STAFF)
async def xt_start(m: Message, db):
    ts = await D.fetchall(db, "SELECT u.tg_id, u.full_name FROM users u JOIN teachers t ON t.tg_id=u.tg_id")
    if not ts:
        return await m.answer("O'qituvchilar yo'q.")
    b = InlineKeyboardBuilder()
    for t in ts:
        b.button(text=t["full_name"], callback_data=f"xt:{t['tg_id']}")
    b.adjust(1)
    await m.answer("Qaysi o'qituvchi o'chirilsin?", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("xt:"), STAFF)
async def xt_ask(c: CallbackQuery, db):
    t = await D.fetchone(db, "SELECT * FROM users WHERE tg_id=? AND role='teacher'", (int(c.data[3:]),))
    if not t:
        return await c.answer("Topilmadi", show_alert=True)
    gs = await D.fetchall(db, "SELECT name FROM groups WHERE teacher_id=?", (t["tg_id"],))
    note = (f"\nGuruhlari ({', '.join(g['name'] for g in gs)}) o'qituvchisiz qoladi."
            if gs else "")
    await c.message.answer(f"⚠️ {t['full_name']} o'chirilsinmi?{note}",
                           reply_markup=confirm_kb(f"xty:{t['tg_id']}"))
    await c.answer()


@router.callback_query(F.data.startswith("xty:"), STAFF)
async def xt_do(c: CallbackQuery, db):
    tid = int(c.data[4:])
    t = await D.fetchone(db, "SELECT full_name FROM users WHERE tg_id=? AND role='teacher'", (tid,))
    if not t:
        return await c.answer("Topilmadi", show_alert=True)
    await db.batch([("UPDATE groups SET teacher_id=NULL WHERE teacher_id=?", (tid,)),
                    ("DELETE FROM teachers WHERE tg_id=?", (tid,)),
                    ("DELETE FROM users WHERE tg_id=?", (tid,))])
    await c.message.edit_text(f"🗑 {t['full_name']} o'chirildi. Guruhlariga yangi o'qituvchi biriktiring.")
    await c.answer()


@router.message(F.text == "🔁 Guruh o'qituvchisini almashtirish", STAFF)
async def rg_start(m: Message, db):
    mk = await group_picker(db, "rg")
    await m.answer("Qaysi guruh?", reply_markup=mk) if mk else await m.answer("Guruhlar yo'q.")


@router.callback_query(F.data.startswith("rg:"), STAFF)
async def rg_group(c: CallbackQuery, db):
    ts = await D.fetchall(db, "SELECT u.tg_id, u.full_name FROM users u JOIN teachers t ON t.tg_id=u.tg_id")
    if not ts:
        return await c.answer("O'qituvchilar yo'q", show_alert=True)
    b = InlineKeyboardBuilder()
    for t in ts:
        b.button(text=t["full_name"], callback_data=f"rt:{c.data[3:]}:{t['tg_id']}")
    b.adjust(1)
    await c.message.answer("Yangi o'qituvchi:", reply_markup=b.as_markup())
    await c.answer()


@router.callback_query(F.data.startswith("rt:"), STAFF)
async def rg_teacher(c: CallbackQuery, db):
    _, gid, tid = c.data.split(":")
    await db.execute("UPDATE groups SET teacher_id=? WHERE id=?", (int(tid), int(gid)))
    await db.commit()
    await c.message.edit_text("✅ Guruh o'qituvchisi almashtirildi.")
    await c.answer()


# ---------------- Director: o'qituvchi / admin qo'shish ----------------
class AddTeacher(StatesGroup):
    tg_id = State(); name = State(); pay_type = State(); value = State()


class AddAdmin(StatesGroup):
    tg_id = State(); name = State()


@router.message(F.text == "👨‍🏫 O'qituvchi qo'shish", DIRECTOR)
async def t_add(m: Message, state: FSMContext):
    await state.set_state(AddTeacher.tg_id)
    await m.answer("O'qituvchining Telegram ID sini yuboring (/cancel - bekor):")


@router.message(AddTeacher.tg_id)
async def t_id(m: Message, state: FSMContext):
    if not (m.text or "").strip().isdigit():
        return await m.answer("ID faqat raqam bo'lishi kerak.")
    await state.update_data(tg_id=int(m.text))
    await state.set_state(AddTeacher.name)
    await m.answer("Ism familiyasi:")


@router.message(AddTeacher.name)
async def t_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await state.set_state(AddTeacher.pay_type)
    await m.answer("Oylik turi:", reply_markup=kb([["Foiz (%)", "O'quvchi boshiga"]]))


@router.message(AddTeacher.pay_type, F.text.in_({"Foiz (%)", "O'quvchi boshiga"}))
async def t_type(m: Message, state: FSMContext):
    pt = "percent" if m.text.startswith("Foiz") else "per_student"
    await state.update_data(pay_type=pt)
    await state.set_state(AddTeacher.value)
    await m.answer("Foiz (masalan 40):" if pt == "percent" else "Bir o'quvchi uchun summa (so'm):")


@router.message(AddTeacher.value)
async def t_value(m: Message, db, state: FSMContext):
    try:
        v = float(m.text.replace(" ", "").replace(",", "."))
        assert v > 0
    except Exception:
        return await m.answer("Musbat son kiriting.")
    d = await state.get_data()
    await db.batch([
        ("INSERT INTO users(tg_id,full_name,role) VALUES(?,?,'teacher') "
         "ON CONFLICT(tg_id) DO UPDATE SET full_name=excluded.full_name, role='teacher'",
         (d["tg_id"], d["name"])),
        ("INSERT INTO teachers(tg_id,pay_type,pay_value) VALUES(?,?,?) "
         "ON CONFLICT(tg_id) DO UPDATE SET pay_type=excluded.pay_type, pay_value=excluded.pay_value",
         (d["tg_id"], d["pay_type"], v))])
    await state.clear()
    await m.answer(f"✅ O'qituvchi {d['name']} qo'shildi.", reply_markup=MENU_DIRECTOR)


@router.message(F.text == "🛡 Admin qo'shish", DIRECTOR)
async def a_add(m: Message, state: FSMContext):
    await state.set_state(AddAdmin.tg_id)
    await m.answer("Adminning Telegram ID si:")


@router.message(AddAdmin.tg_id)
async def a_id(m: Message, state: FSMContext):
    if not (m.text or "").strip().isdigit():
        return await m.answer("ID faqat raqam bo'lishi kerak.")
    await state.update_data(tg_id=int(m.text))
    await state.set_state(AddAdmin.name)
    await m.answer("Ism familiyasi:")


@router.message(AddAdmin.name)
async def a_name(m: Message, db, state: FSMContext):
    d = await state.get_data()
    await db.execute("INSERT INTO users(tg_id,full_name,role) VALUES(?,?,'admin') "
                     "ON CONFLICT(tg_id) DO UPDATE SET full_name=excluded.full_name, role='admin'",
                     (d["tg_id"], m.text.strip()))
    await db.commit()
    await state.clear()
    await m.answer("✅ Admin qo'shildi.", reply_markup=MENU_DIRECTOR)


@router.message(F.text == "💰 Oyliklar", DIRECTOR)
async def salaries(m: Message, db):
    out = [f"💰 Oyliklar ({D.current_month()}):"]
    for t in await D.fetchall(db, "SELECT u.tg_id, u.full_name FROM users u JOIN teachers t ON t.tg_id=u.tg_id"):
        res = await D.teacher_salary(db, t["tg_id"])
        out.append(f"• {t['full_name']}: {money(res[3])}")
    await m.answer("\n".join(out) if len(out) > 1 else "O'qituvchilar yo'q.")


# ---------------- Admin/Director: guruh ----------------
class AddGroup(StatesGroup):
    name = State(); teacher = State()


@router.message(F.text == "➕ Guruh", STAFF)
async def g_add(m: Message, state: FSMContext):
    await state.set_state(AddGroup.name)
    await m.answer("Guruh nomi (masalan A1):")


@router.message(AddGroup.name)
async def g_name(m: Message, db, state: FSMContext):
    await state.update_data(name=m.text.strip())
    ts = await D.fetchall(db, "SELECT u.tg_id, u.full_name FROM users u JOIN teachers t ON t.tg_id=u.tg_id")
    if not ts:
        await state.clear()
        return await m.answer("Avval direktor o'qituvchi qo'shishi kerak.")
    b = InlineKeyboardBuilder()
    for t in ts:
        b.button(text=t["full_name"], callback_data=f"gt:{t['tg_id']}")
    b.adjust(1)
    await state.set_state(AddGroup.teacher)
    await m.answer("O'qituvchini tanlang:", reply_markup=b.as_markup())


@router.callback_query(AddGroup.teacher, F.data.startswith("gt:"))
async def g_teacher(c: CallbackQuery, db, state: FSMContext):
    d = await state.get_data()
    try:
        await db.execute("INSERT INTO groups(name, teacher_id) VALUES(?,?)",
                         (d["name"], int(c.data[3:])))
        await db.commit()
        await c.message.answer(f"✅ Guruh {d['name']} yaratildi.")
    except Exception:
        await c.message.answer("Bunday nomli guruh mavjud.")
    await state.clear()
    await c.answer()


# ---------------- Admin/Director: o'quvchi ----------------
class AddStudent(StatesGroup):
    first = State(); last = State(); grade = State(); phone = State(); group = State()


@router.message(F.text == "➕ O'quvchi", ANYONE)
async def s_add(m: Message, state: FSMContext):
    await state.set_state(AddStudent.first)
    await m.answer("O'quvchi ismi:")


@router.message(AddStudent.first)
async def s_first(m: Message, state: FSMContext):
    await state.update_data(first=m.text.strip())
    await state.set_state(AddStudent.last)
    await m.answer("Familiyasi:")


@router.message(AddStudent.last)
async def s_last(m: Message, state: FSMContext):
    await state.update_data(last=m.text.strip())
    await state.set_state(AddStudent.grade)
    await m.answer("Sinfi (masalan 7):")


@router.message(AddStudent.grade)
async def s_grade(m: Message, state: FSMContext):
    await state.update_data(grade=m.text.strip())
    await state.set_state(AddStudent.phone)
    await m.answer("Telefon raqami (masalan 90 123 45 67 yoki +998901234567).\n"
                   "Bilmasangiz - yuboring:")


@router.message(AddStudent.phone)
async def s_phone(m: Message, db, state: FSMContext):
    phone = normalize_phone(m.text or "")
    if phone is None:
        return await m.answer("Raqam noto'g'ri. Masalan: 90 123 45 67 (yoki - yuboring).")
    await state.update_data(phone=phone)
    uid = m.from_user.id
    mk = await group_picker(db, "sg", uid if await D.get_role(db, uid) == "teacher" else None)
    if not mk:
        await state.clear()
        return await m.answer("Avval guruh yarating.")
    await state.set_state(AddStudent.group)
    await m.answer("Guruhni tanlang:", reply_markup=mk)


@router.callback_query(AddStudent.group, F.data.startswith("sg:"))
async def s_group(c: CallbackQuery, db, state: FSMContext):
    d = await state.get_data()
    if not await can_access_group(db, c.from_user.id, int(c.data[3:])):
        return await c.answer("Bu sizning guruhingiz emas", show_alert=True)
    await db.execute("INSERT INTO students(first_name,last_name,grade,phone,group_id) VALUES(?,?,?,?,?)",
                     (d["first"], d["last"], d["grade"], d.get("phone", ""), int(c.data[3:])))
    await db.commit()
    await state.clear()
    await c.message.answer(f"✅ {d['first']} {d['last']} qo'shildi.")
    await c.answer()


# ---------------- Admin/Director: to'lov ----------------
class Pay(StatesGroup):
    amount = State()


@router.message(F.text == "💵 To'lov kiritish", STAFF)
async def p_start(m: Message, db):
    mk = await group_picker(db, "pg")
    await m.answer("Guruhni tanlang:", reply_markup=mk) if mk else await m.answer("Guruhlar yo'q.")


@router.callback_query(F.data.startswith("pg:"), STAFF)
async def p_group(c: CallbackQuery, db):
    studs = await D.group_students(db, int(c.data[3:]))
    b = InlineKeyboardBuilder()
    for s in studs:
        mark = "✅" if s["paid"] else "❌"
        b.button(text=f"{mark} {s['last_name']} {s['first_name']}", callback_data=f"ps:{s['id']}")
    b.adjust(1)
    await c.message.answer("O'quvchini tanlang (✅ - bu oy to'lagan):" if studs else "Guruhda o'quvchi yo'q.",
                           reply_markup=b.as_markup() if studs else None)
    await c.answer()


@router.callback_query(F.data.startswith("ps:"), STAFF)
async def p_student(c: CallbackQuery, state: FSMContext):
    await state.set_state(Pay.amount)
    await state.update_data(student_id=int(c.data[3:]))
    await c.message.answer("To'lov summasi (so'm):")
    await c.answer()


@router.message(Pay.amount)
async def p_amount(m: Message, db, state: FSMContext):
    try:
        amt = int(m.text.replace(" ", ""))
        assert amt > 0
    except Exception:
        return await m.answer("Musbat butun son kiriting.")
    sid = (await state.get_data())["student_id"]
    s = await D.fetchone(db, "SELECT * FROM students WHERE id=?", (sid,))
    await db.execute("INSERT INTO payments(student_id,group_id,amount,month) VALUES(?,?,?,?)",
                     (sid, s["group_id"], amt, D.current_month()))
    await db.commit()
    await state.clear()
    await m.answer(f"✅ {s['last_name']} {s['first_name']}: {money(amt)} qabul qilindi. "
                   f"Bu oy uchun qarzdor emas.")


# ---------------- Qarzdorlar / hisob ----------------
async def debtors_text(db, group_id):
    g = await D.fetchone(db, "SELECT name FROM groups WHERE id=?", (group_id,))
    ds = [s for s in await D.group_students(db, group_id) if not s["paid"]]
    head = f"📋 {g['name']} - qarzdorlar ({D.current_month()}):\n"
    if not ds:
        return head + "Qarzdor yo'q 🎉"
    return head + "\n".join(f"{i}. {s['last_name']} {s['first_name']} ({s['grade']}-sinf){with_phone(s)}"
                            for i, s in enumerate(ds, 1))


@router.message(F.text == "📋 Qarzdorlar", STAFF)
async def staff_debtors(m: Message, db):
    mk = await group_picker(db, "dg")
    await m.answer("Guruhni tanlang:", reply_markup=mk) if mk else await m.answer("Guruhlar yo'q.")


@router.message(F.text == "📋 Qarzdorlarni ko'rish", TEACHER)
async def teacher_debtors(m: Message, db):
    groups = await D.fetchall(db, "SELECT id FROM groups WHERE teacher_id=? ORDER BY name",
                              (m.from_user.id,))
    if not groups:
        return await m.answer("Sizda guruh yo'q.")
    for g in groups:
        await m.answer(await debtors_text(db, g["id"]))


@router.callback_query(F.data.startswith("dg:"))
async def debtors_cb(c: CallbackQuery, db):
    gid = int(c.data[3:])
    role = await D.get_role(db, c.from_user.id)
    g = await D.fetchone(db, "SELECT teacher_id FROM groups WHERE id=?", (gid,))
    if role == "teacher" and g["teacher_id"] != c.from_user.id:
        return await c.answer("Bu sizning guruhingiz emas", show_alert=True)
    if role is None:
        return await c.answer()
    await c.message.answer(await debtors_text(db, gid))
    await c.answer()


@router.message(F.text == "📊 Guruh hisobi", STAFF)
async def staff_income(m: Message, db):
    out = [f"📊 Guruhlar tushumi ({D.current_month()}):"]
    for g in await D.fetchall(db, "SELECT * FROM groups ORDER BY name"):
        out.append(f"• {g['name']}: {money(await D.group_income(db, g['id']))}")
    await m.answer("\n".join(out) if len(out) > 1 else "Guruhlar yo'q.")


# ---------------- O'qituvchi: oylik ----------------
def prev_months(n=6):
    y, m = date.today().year, date.today().month
    out = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def months_markup(prefix):
    b = InlineKeyboardBuilder()
    for mo in prev_months():
        b.button(text=mo, callback_data=f"{prefix}:{mo}")
    b.adjust(3)
    return b.as_markup()


async def salary_text(db, tid, month):
    pt, pv, rows, total = await D.teacher_salary(db, tid, month)
    how = f"{pv:g}% (to'lovdan)" if pt == "percent" else f"{money(pv)} / to'lagan o'quvchi"
    out = [f"💰 Oylik ({month})", f"Tizim: {how}", ""]
    for name, income, cnt in rows:
        out.append(f"• {name}: tushum {money(income)}, to'laganlar {cnt} ta")
    out += ["", f"Jami oylik: {money(total)}"]
    return "\n".join(out)


@router.message(F.text == "💰 Oylikni ko'rish", TEACHER)
async def my_salary(m: Message, db):
    await m.answer(await salary_text(db, m.from_user.id, D.current_month()) +
                   "\n\nBoshqa oy:", reply_markup=months_markup("ms"))


@router.callback_query(F.data.startswith("ms:"), TEACHER)
async def my_salary_month(c: CallbackQuery, db):
    await c.message.edit_text(await salary_text(db, c.from_user.id, c.data[3:]) +
                              "\n\nBoshqa oy:", reply_markup=months_markup("ms"))
    await c.answer()


# ---------------- O'qituvchi: davomat ----------------
@router.message(F.text == "✅ Davomat", TEACHER)
async def att_start(m: Message, db):
    mk = await group_picker(db, "ag", m.from_user.id)
    await m.answer("Guruhni tanlang:", reply_markup=mk) if mk else await m.answer("Sizda guruh yo'q.")


async def att_markup(db, gid, absent):
    b = InlineKeyboardBuilder()
    for s in await D.group_students(db, gid):
        mark = "❌ Kelmadi" if s["id"] in absent else "✅"
        b.button(text=f"{mark} {s['last_name']} {s['first_name']}", callback_data=f"at:{s['id']}")
    b.adjust(1)
    b.row(InlineKeyboardButton(text="📤 Belgilab yuborish", callback_data="ad"))
    return b.as_markup()


@router.callback_query(F.data.startswith("ag:"), TEACHER)
async def att_group(c: CallbackQuery, db, state: FSMContext):
    gid = int(c.data[3:])
    g = await D.fetchone(db, "SELECT * FROM groups WHERE id=?", (gid,))
    if g["teacher_id"] != c.from_user.id:
        return await c.answer("Bu sizning guruhingiz emas", show_alert=True)
    await state.update_data(att_group=gid, absent=[])
    await c.message.answer(f"Davomat: {g['name']} ({date.today():%d.%m.%Y})\n"
                           "Kelmagan o'quvchilarni bosib belgilang, so'ng yuboring.",
                           reply_markup=await att_markup(db, gid, set()))
    await c.answer()


@router.callback_query(F.data.startswith("at:"), TEACHER)
async def att_toggle(c: CallbackQuery, db, state: FSMContext):
    d = await state.get_data()
    if "att_group" not in d:
        return await c.answer("Davomatni qaytadan boshlang", show_alert=True)
    sid = int(c.data[3:])
    absent = set(d["absent"])
    absent ^= {sid}
    await state.update_data(absent=list(absent))
    await c.message.edit_reply_markup(reply_markup=await att_markup(db, d["att_group"], absent))
    await c.answer()


@router.callback_query(F.data == "ad", TEACHER)
async def att_done(c: CallbackQuery, db, state: FSMContext, bot: Bot):
    d = await state.get_data()
    if "att_group" not in d:
        return await c.answer("Davomatni qaytadan boshlang", show_alert=True)
    gid, absent = d["att_group"], set(d["absent"])
    today = date.today().isoformat()
    g = await D.fetchone(db, "SELECT * FROM groups WHERE id=?", (gid,))
    teacher = await D.fetchone(db, "SELECT full_name FROM users WHERE tg_id=?", (c.from_user.id,))
    rows, stmts, absent_lines = [], [], []
    for s in await D.group_students(db, gid):
        present = s["id"] not in absent
        stmts.append(("INSERT INTO attendance(group_id,day,student_id,present) VALUES(?,?,?,?) "
                      "ON CONFLICT(group_id,day,student_id) DO UPDATE SET present=excluded.present",
                      (gid, today, s["id"], int(present))))
        rows.append((f"{s['last_name']} {s['first_name']}", s["grade"], s.get("phone") or "", present))
        if not present:
            absent_lines.append(f"• {s['last_name']} {s['first_name']}{with_phone(s)}")
    if stmts:
        await db.batch(stmts)
    caption = f"📋 {g['name']} davomati ({teacher['full_name']}), kelmagan: {len(absent)}"
    if absent_lines:
        caption = (caption + "\n" + "\n".join(absent_lines))[:1000]
    pdf = attendance_pdf(g["name"], teacher["full_name"], f"{date.today():%d.%m.%Y}", rows)
    for a in await D.fetchall(db, "SELECT tg_id FROM users WHERE role IN ('admin','director')"):
        try:
            await bot.send_document(
                a["tg_id"], BufferedInputFile(pdf, f"davomat_{g['name']}_{today}.pdf"),
                caption=caption)
        except Exception:
            pass
    await state.clear()
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer("✅ Davomat yakunlandi va adminga yuborildi.")
    await c.answer()
