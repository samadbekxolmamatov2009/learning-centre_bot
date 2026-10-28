from datetime import date, timedelta

from aiogram import Router, F, Bot
from aiogram.filters import Command, Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile, WebAppInfo,
                           MenuButtonWebApp)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import attendance as A
from . import db as D
from .config import WEBAPP_URL
from .pdfgen import attendance_pdf

router = Router()
WEEKDAYS = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]


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


HOME = "🏠 Asosiy menyu"
SECTION_TITLES = {
    "👥 O'quvchilar": "👥 O'quvchilar bo'limi",
    "💰 Moliya": "💰 Moliya bo'limi",
    "🏫 Guruh boshqaruvi": "🏫 Guruh boshqaruvi",
    "📊 Hisobotlar": "📊 Hisobotlar bo'limi",
    "👨‍🏫 Xodimlar": "👨‍🏫 Xodimlar bo'limi",
}


def _full_menu_rows(role: str):
    """Mini App bo'lmagan holatdagi to'liq chat menyusi (WEBAPP_URL o'rnatilmaganda ishlatiladi,
    shuningdek Mini App'da takrorlangan buyruqlarni aniqlash uchun ham kerak)."""
    if role == "teacher":
        return [["✅ Davomat", "📚 Guruhlarim"], ["📋 Qarzdorlarni ko'rish", "💰 Oylikni ko'rish"],
                ["👥 O'quvchilar"]]
    rows = [["📚 Guruhlar", "🔎 Qidirish"], ["👥 O'quvchilar", "💰 Moliya"],
            ["🏫 Guruh boshqaruvi", "📊 Hisobotlar"]]
    if role == "director":
        rows.append(["👨‍🏫 Xodimlar"])
    return rows


def main_menu(role: str):
    if WEBAPP_URL:
        # Mini App ichida davomat, o'quvchilar, oylik, xodimlar - hammasi bitta joyda.
        # Faqat Mini App'da hali yo'q funksiyalar (fayldan yuklash, statistika) chatda qoladi.
        # "📱 Ilovani ochish" oddiy matn tugma - bosilganda webapp_markup() bilan inline tugma yuboriladi
        # (doimiy klaviaturadagi web_app tugmasi ba'zi Telegram mijozlarida eskirgan/noto'g'ri initData
        # berishi mumkin, inline tugma esa har safar yangi va ishonchli).
        row = ["📱 Ilovani ochish", "📤 Fayldan yuklash"]
        if role == "director":
            row.append("📈 Statistika")
        return kb([row])
    return kb(_full_menu_rows(role))


def section_menu(role: str, section: str):
    staff = role in ("admin", "director")
    rows = []
    if section == "👥 O'quvchilar":
        if staff:
            rows = [["➕ O'quvchi", "📤 Fayldan yuklash"], ["🔀 O'quvchini ko'chirish", "🏛 Reyestr belgilash"],
                    ["📞 Telefonni o'zgartirish", "🗑 O'quvchini o'chirish"]]
            if role == "director":
                rows.append(["👁 Reyestr yashirish/ochish"])
        else:
            rows = [["➕ O'quvchi", "📤 Fayldan yuklash"], ["🔎 Qidirish", "📞 Telefonni o'zgartirish"],
                    ["🗑 O'quvchini o'chirish"]]
    elif section == "💰 Moliya" and staff:
        rows = [["💵 To'lov kiritish", "↩️ To'lovni bekor qilish"], ["📋 Qarzdorlar", "📊 Guruh hisobi"]]
        if role == "director":
            rows.append(["💰 Oyliklar"])
    elif section == "🏫 Guruh boshqaruvi" and staff:
        rows = [["➕ Guruh", "🗑 Guruhni o'chirish"], ["🔁 Guruh o'qituvchisini almashtirish", "🗓 Dars jadvali"]]
    elif section == "📊 Hisobotlar" and staff:
        rows = [["📅 Hisobot", "📥 Excel"]]
        if WEBAPP_URL:
            rows.append(["🖥 Panel"])
        if role == "director":
            rows.append(["📈 Statistika"])
    elif section == "👨‍🏫 Xodimlar" and role == "director":
        rows = [["👨‍🏫 O'qituvchi qo'shish", "✏️ O'qituvchini tahrirlash"],
                ["🗑 O'qituvchini o'chirish", "🛡 Admin qo'shish"], ["🗑 Adminni o'chirish"]]
    rows.append([HOME])
    return kb(rows)


MENU_ADMIN, MENU_DIRECTOR, MENU_TEACHER = main_menu("admin"), main_menu("director"), main_menu("teacher")
MENU_TEXTS = {b.text for r in ("admin", "director", "teacher")
              for m in [main_menu(r)] + [section_menu(r, sec) for sec in SECTION_TITLES]
              for row in m.keyboard for b in row} | {"🖥 Panel", "🗓 Dars jadvali"}

# Mini App ichida takrorlangan eski chat buyruqlari (WEBAPP_URL o'rnatilganda butunlay o'chiriladi).
# Mini App'da hali yo'q funksiyalar (Fayldan yuklash, Statistika) va Asosiy menyu bundan mustasno.
_EXEMPT_LEGACY = {"📤 Fayldan yuklash", "📈 Statistika", HOME}
LEGACY_DUPLICATED = ({t for r in ("admin", "director", "teacher") for row in _full_menu_rows(r) for t in row} |
                     {b.text for r in ("admin", "director", "teacher") for sec in SECTION_TITLES
                      for row in section_menu(r, sec).keyboard for b in row} |
                     {"🖥 Panel", "🗓 Dars jadvali"}) - _EXEMPT_LEGACY


@router.message.outer_middleware()
async def menu_resets_state(handler, event: Message, data):
    """Kutilayotgan savol vaqtida menyu tugmasi bosilsa, holatni tozalaydi
    (aks holda tugma matni ism/guruh nomi sifatida saqlanib qoladi)."""
    if event.text in MENU_TEXTS and data.get("state"):
        await data["state"].clear()
    if WEBAPP_URL and event.text in LEGACY_DUPLICATED:
        await event.answer('Bu funksiya endi Mini App ichida. Pastdagi "📱 Ilovani ochish" tugmasini bosing.')
        return
    return await handler(event, data)


async def menu_for(db, uid):
    return {"director": MENU_DIRECTOR, "admin": MENU_ADMIN,
            "teacher": MENU_TEACHER}.get(await D.get_role(db, uid))


@router.message(Command("start"))
@router.message(Command("menu"))
@router.message(F.text == HOME)
async def start(m: Message, db, state: FSMContext, bot: Bot):
    await state.clear()
    args = (m.text or "").split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("p"):
        return await start_parent(m, db, args[1])
    menu = await menu_for(db, m.from_user.id)
    if not menu:
        return await m.answer(f"Siz ro'yxatda yo'qsiz. Direktorga ID ingizni bering: {m.from_user.id}")
    await m.answer("Asosiy menyu 👇", reply_markup=menu)
    if WEBAPP_URL and m.chat.type == "private":
        role = await D.get_role(db, m.from_user.id)
        try:  # chap pastdagi "Menu" tugmasi Mini App'ni ochadi
            await bot.set_chat_menu_button(chat_id=m.chat.id, menu_button=MenuButtonWebApp(
                text="Davomat" if role == "teacher" else "Panel", web_app=WebAppInfo(url=f"{WEBAPP_URL}/app")))
        except Exception:
            pass


async def start_parent(m: Message, db, payload: str):
    """Ota-ona havolasi: /start p<student_id>_<imzo>."""
    from .ptoken import verify
    sid = verify(payload)
    if sid is None:
        return await m.answer("Havola yaroqsiz. Markazdan yangi havola so'rang.")
    s = await D.fetchone(db, "SELECT s.*, g.name AS gname FROM students s JOIN groups g ON g.id=s.group_id "
                             "WHERE s.id=?", (sid,))
    if not s:
        return await m.answer("O'quvchi topilmadi. Ehtimol o'chirilgan.")
    await db.execute("INSERT OR IGNORE INTO parent_links(parent_tg_id, student_id) VALUES(?,?)",
                     (m.from_user.id, sid))
    text = f"👪 Siz <b>{s['last_name']} {s['first_name']}</b> ({s['gname']} guruhi) ota-onasi sifatida bog'landingiz."
    if WEBAPP_URL:
        await m.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="👪 Farzandim haqida", web_app=WebAppInfo(url=f"{WEBAPP_URL}/parent"))]]))
    else:
        await m.answer(text, parse_mode="HTML")


@router.message(F.text.in_(set(SECTION_TITLES)))
async def open_section(m: Message, db):
    role = await D.get_role(db, m.from_user.id)
    if not role:
        return
    await m.answer(SECTION_TITLES[m.text], reply_markup=section_menu(role, m.text))


@router.message(Command("cancel"))
async def cancel(m: Message, db, state: FSMContext):
    await state.clear()
    await m.answer("Bekor qilindi.", reply_markup=await menu_for(db, m.from_user.id))


PAGE = 10
PICKER_LABELS = {
    "ps": lambda s: f"{'🏛' if s['is_registry'] else ('✅' if s['paid'] else '❌')} {s['last_name']} {s['first_name']}",
    "xs": lambda s: f"{s['last_name']} {s['first_name']} ({s['grade']})",
    "ms2": lambda s: f"{s['last_name']} {s['first_name']} ({s['grade']})",
    "cs": lambda s: f"{s['last_name']} {s['first_name']}",
    "ph": lambda s: f"{s['last_name']} {s['first_name']} {s['phone'] or '(raqam yoq)'}",
    "rxs": lambda s: f"{'🏛' if s['is_registry'] else '▫️'} {s['last_name']} {s['first_name']}",
}


async def student_pager(db, gid: int, page: int, kind: str):
    """O'quvchilar tugmalari (10 tadan sahifalab). -> (markup yoki None, jami soni)"""
    studs = await D.group_students(db, gid)
    pages = max(1, -(-len(studs) // PAGE))
    page = max(0, min(page, pages - 1))
    b = InlineKeyboardBuilder()
    for s in studs[page * PAGE:(page + 1) * PAGE]:
        b.button(text=PICKER_LABELS[kind](s), callback_data=f"{kind}:{s['id']}")
    b.adjust(1)
    if pages > 1:
        b.row(InlineKeyboardButton(text="◀️" if page else "·", callback_data=f"sp:{kind}:{gid}:{page - 1}" if page else "noop"),
              InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"),
              InlineKeyboardButton(text="▶️" if page < pages - 1 else "·",
                                   callback_data=f"sp:{kind}:{gid}:{page + 1}" if page < pages - 1 else "noop"))
    return (b.as_markup() if studs else None), len(studs)


@router.callback_query(F.data == "noop")
async def noop(c: CallbackQuery):
    await c.answer()


@router.callback_query(F.data.startswith("sp:"))
async def pager_nav(c: CallbackQuery, db):
    _, kind, gid, page = c.data.split(":")
    if kind not in PICKER_LABELS or not await can_access_group(db, c.from_user.id, int(gid)):
        return await c.answer("Ruxsat yo'q", show_alert=True)
    mk, _ = await student_pager(db, int(gid), int(page), kind)
    await c.message.edit_reply_markup(reply_markup=mk)
    await c.answer()


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
    mk, n = await student_pager(db, gid, 0, "xs")
    await c.message.answer("O'chiriladigan o'quvchini tanlang:" if n else "Guruhda o'quvchi yo'q.", reply_markup=mk)
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
    await D.archive_or_delete_student(db, s["id"])
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
    await D.archive_or_delete_group_students(db, gid)
    await db.execute("DELETE FROM groups WHERE id=?", (gid,))
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
    tg_id = State(); name = State(); pay_type = State(); value = State(); reg_rate = State()


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
    await m.answer("Foiz (masalan 40):" if pt == "percent" else "Bir o'quvchi uchun summa (so'm).\nMasalan 200000: o'quvchi 400000 gacha to'lasa "
        "o'qituvchi to'lovning 40% ini oladi, undan ko'p to'lasa 200000.")


@router.message(AddTeacher.value)
async def t_value(m: Message, db, state: FSMContext):
    try:
        v = float(m.text.replace(" ", "").replace(",", "."))
        assert v > 0
    except Exception:
        return await m.answer("Musbat son kiriting.")
    await state.update_data(value=v)
    await state.set_state(AddTeacher.reg_rate)
    await m.answer("Reyestr o'quvchilar uchun bitta dars narxi (so'm) - o'qituvchi reyestr o'quvchisi "
                   "darsga kelganda shuncha oladi (100%). Reyestr bo'lmasa 0 yozing:")


@router.message(AddTeacher.reg_rate)
async def t_reg(m: Message, db, state: FSMContext):
    try:
        reg = int((m.text or "").replace(" ", ""))
        assert reg >= 0
    except Exception:
        return await m.answer("0 yoki musbat butun son kiriting.")
    d = await state.get_data()
    await db.batch([
        ("INSERT INTO users(tg_id,full_name,role) VALUES(?,?,'teacher') "
         "ON CONFLICT(tg_id) DO UPDATE SET full_name=excluded.full_name, role='teacher'",
         (d["tg_id"], d["name"])),
        ("INSERT INTO teachers(tg_id,pay_type,pay_value,registry_rate) VALUES(?,?,?,?) "
         "ON CONFLICT(tg_id) DO UPDATE SET pay_type=excluded.pay_type, pay_value=excluded.pay_value, "
         "registry_rate=excluded.registry_rate",
         (d["tg_id"], d["pay_type"], d["value"], reg))])
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
    first = State(); last = State(); grade = State(); phone = State()
    registry = State(); group = State()


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


async def ask_group(msg: Message, db, state: FSMContext, uid: int):
    mk = await group_picker(db, "sg", uid if await D.get_role(db, uid) == "teacher" else None)
    if not mk:
        await state.clear()
        return await msg.answer("Avval guruh yarating.")
    await state.set_state(AddStudent.group)
    await msg.answer("Guruhni tanlang:", reply_markup=mk)


@router.message(AddStudent.phone)
async def s_phone(m: Message, db, state: FSMContext):
    phone = normalize_phone(m.text or "")
    if phone is None:
        return await m.answer("Raqam noto'g'ri. Masalan: 90 123 45 67 (yoki - yuboring).")
    await state.update_data(phone=phone, is_registry=0, reg_rate=0)
    uid = m.from_user.id
    if await D.get_role(db, uid) in ("admin", "director"):
        # Reyestr o'quvchisi o'qituvchi oyligiga ta'sir qiladi, shuning uchun uni faqat admin/direktor belgilaydi
        await state.set_state(AddStudent.registry)
        return await m.answer("O'quvchi reyestrdami (kam ta'minlangan oila, davlat to'laydi)?",
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                  InlineKeyboardButton(text="🏛 Reyestr", callback_data="reg:y"),
                                  InlineKeyboardButton(text="Oddiy o'quvchi", callback_data="reg:n")]]))
    await ask_group(m, db, state, uid)


@router.callback_query(AddStudent.registry, F.data.in_({"reg:y", "reg:n"}))
async def s_registry(c: CallbackQuery, db, state: FSMContext):
    await c.answer()
    if c.data == "reg:n":
        await c.message.edit_text("Oddiy o'quvchi.")
    else:
        await state.update_data(is_registry=1)
        await c.message.edit_text("🏛 Reyestr o'quvchisi (dars narxi o'qituvchi ma'lumotidagi reyestr narxidan olinadi).")
    await ask_group(c.message, db, state, c.from_user.id)


@router.callback_query(AddStudent.group, F.data.startswith("sg:"))
async def s_group(c: CallbackQuery, db, state: FSMContext):
    d = await state.get_data()
    if not await can_access_group(db, c.from_user.id, int(c.data[3:])):
        return await c.answer("Bu sizning guruhingiz emas", show_alert=True)
    reg = d.get("is_registry", 0)
    hidden = 1 if (reg and await D.get_setting(db, "registry_hidden") == "1") else 0
    await db.execute("INSERT INTO students(first_name,last_name,grade,phone,is_registry,hidden,group_id) "
                     "VALUES(?,?,?,?,?,?,?)",
                     (d["first"], d["last"], d["grade"], d.get("phone", ""), reg, hidden, int(c.data[3:])))
    await state.clear()
    extra = (" 🏛 Reyestr." + (" Hozir yashirin, 'Reyestr yashirish/ochish' orqali ochilganda ko'rinadi." if hidden else "")) if reg else ""
    await c.message.answer(f"✅ {d['first']} {d['last']} qo'shildi.{extra}")
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
    mk, n = await student_pager(db, int(c.data[3:]), 0, "ps")
    await c.message.answer("O'quvchini tanlang (✅ to'lagan, ❌ qarzdor, 🏛 reyestr):" if n else "Guruhda o'quvchi yo'q.",
                           reply_markup=mk)
    await c.answer()


@router.callback_query(F.data.startswith("ps:"), STAFF)
async def p_student(c: CallbackQuery, state: FSMContext):
    await state.set_state(Pay.amount)
    await state.update_data(student_id=int(c.data[3:]))
    await c.message.answer("To'lov summasi (so'm):")
    await c.answer()


@router.message(Pay.amount)
async def p_amount(m: Message, db, state: FSMContext, bot: Bot):
    try:
        amt = int(m.text.replace(" ", ""))
        assert amt > 0
    except Exception:
        return await m.answer("Musbat butun son kiriting.")
    sid = (await state.get_data())["student_id"]
    s = await D.fetchone(db, "SELECT * FROM students WHERE id=?", (sid,))
    mo = D.current_month()
    await db.execute("INSERT INTO payments(student_id,group_id,amount,month) VALUES(?,?,?,?)",
                     (sid, s["group_id"], amt, mo))
    await state.clear()
    await m.answer(f"✅ {s['last_name']} {s['first_name']}: {money(amt)} qabul qilindi. "
                   f"Bu oy uchun qarzdor emas.")
    row = await D.fetchone(db, "SELECT id FROM payments WHERE student_id=? AND month=? ORDER BY id DESC LIMIT 1",
                           (sid, mo))
    if row:
        from .receipts import send_receipt
        await send_receipt(bot, db, row["id"], m.from_user.id)


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
    today = D.today_local()
    y, m = today.year, today.month
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
    how = (f"{pv:g}% (to'lovdan)" if pt == "percent" else
           f"{money(pv)} / o'quvchi ({money(pv * D.LOW_PAY_MULT)} gacha to'lasa - "
           f"to'lovning {D.LOW_PAY_PERCENT}%)")
    out = [f"💰 Oylik ({month})", f"Tizim: {how}", ""]
    for name, income, cnt in rows:
        out.append(f"• {name}: tushum {money(income)}, to'laganlar {cnt} ta")
    reg = await D.registry_rows(db, tid, month)
    if reg:
        out += ["", "🏛 Reyestr o'quvchilari (100%):"]
        out += [f"• {name}: {lessons} ta dars = {money(total_)}" for name, lessons, total_ in reg]
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


# ---------------- O'qituvchi: davomat (chat ichida; Mini App bo'lmasa shu ishlaydi) ----------------
def webapp_markup(text="📝 Davomatni ochish", path=""):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, web_app=WebAppInfo(url=f"{WEBAPP_URL}/app{path}"))]])


@router.message(F.text == "📱 Ilovani ochish", ANYONE)
async def open_app(m: Message):
    if not WEBAPP_URL:
        return
    await m.answer("👇 Tugmani bosing:", reply_markup=webapp_markup("📱 Ilovani ochish"))


@router.message(F.text == "✅ Davomat", TEACHER)
@router.message(Command("davomat"), TEACHER)
async def att_start(m: Message, db):
    if WEBAPP_URL:
        kb_ = webapp_markup()
        kb_.inline_keyboard.append([InlineKeyboardButton(text="💬 Chatda belgilash", callback_data="att:chat")])
        return await m.answer("Davomat uchun tugmani bosing 👇", reply_markup=kb_)
    mk = await group_picker(db, "ag", m.from_user.id)
    await m.answer("Guruhni tanlang:", reply_markup=mk) if mk else await m.answer("Sizda guruh yo'q.")


@router.callback_query(F.data == "att:chat", TEACHER)
async def att_chat(c: CallbackQuery, db):
    mk = await group_picker(db, "ag", c.from_user.id)
    await c.message.answer("Guruhni tanlang:", reply_markup=mk) if mk else await c.message.answer("Sizda guruh yo'q.")
    await c.answer()


async def att_markup(db, gid, day, statuses):
    """statuses: {student_id(str): status}. Har o'quvchi yonida oldingi 3 ta darsi."""
    days, hist = await A.history(db, gid, before=day, n=3)
    b = InlineKeyboardBuilder()
    for s in await D.group_students(db, gid):
        st = statuses.get(str(s["id"]), "present")
        hm = A.marks(days, hist.get(s["id"]))
        b.button(text=f"{A.STATUSES[st][0]} {s['last_name']} {s['first_name']}  {hm}".strip(),
                 callback_data=f"at:{s['id']}")
    b.adjust(1)
    b.row(InlineKeyboardButton(text="📅 Boshqa kun", callback_data="ad:pick"),
          InlineKeyboardButton(text="📤 Yuborish", callback_data="ad"))
    return b.as_markup()


def att_title(g, day, days_hint=True):
    t = f"📋 {g['name']} | {date.fromisoformat(day):%d.%m.%Y}\nBosing: ✅ keldi → ❌ kelmadi → 🕒 kechikdi → 📝 sababli."
    return t + "\nO'ng tomonda oldingi 3 ta dars belgisi." if days_hint else t


@router.callback_query(F.data.startswith("ag:"), TEACHER)
async def att_group(c: CallbackQuery, db, state: FSMContext):
    gid = int(c.data[3:])
    g = await D.fetchone(db, "SELECT * FROM groups WHERE id=?", (gid,))
    if g["teacher_id"] != c.from_user.id:
        return await c.answer("Bu sizning guruhingiz emas", show_alert=True)
    day = D.today_local().isoformat()
    st = {str(k): v for k, v in (await A.day_statuses(db, gid, day)).items()}
    await state.update_data(att_group=gid, day=day, st=st)
    await c.message.answer(att_title(g, day), reply_markup=await att_markup(db, gid, day, st))
    await c.answer()


@router.callback_query(F.data == "ad:pick", TEACHER)
async def att_pick_day(c: CallbackQuery, state: FSMContext):
    if "att_group" not in await state.get_data():
        return await c.answer("Davomatni qaytadan boshlang", show_alert=True)
    today = D.today_local()
    b = InlineKeyboardBuilder()
    for i in range(0, 7):
        d = today - timedelta(days=i)
        b.button(text=f"{d:%d.%m} {WEEKDAYS[d.weekday()]}" + (" (bugun)" if i == 0 else ""),
                 callback_data=f"ad:day:{d.isoformat()}")
    b.adjust(2)
    await c.message.answer("Qaysi kun davomati?", reply_markup=b.as_markup())
    await c.answer()


@router.callback_query(F.data.startswith("ad:day:"), TEACHER)
async def att_set_day(c: CallbackQuery, db, state: FSMContext):
    d = await state.get_data()
    if "att_group" not in d:
        return await c.answer("Davomatni qaytadan boshlang", show_alert=True)
    gid, day = d["att_group"], c.data[7:]
    st = {str(k): v for k, v in (await A.day_statuses(db, gid, day)).items()}
    await state.update_data(day=day, st=st)
    g = await D.fetchone(db, "SELECT * FROM groups WHERE id=?", (gid,))
    await c.message.edit_text(att_title(g, day), reply_markup=await att_markup(db, gid, day, st))
    await c.answer()


@router.callback_query(F.data.startswith("at:"), TEACHER)
async def att_toggle(c: CallbackQuery, db, state: FSMContext):
    d = await state.get_data()
    if "att_group" not in d:
        return await c.answer("Davomatni qaytadan boshlang", show_alert=True)
    sid = c.data[3:]
    st = dict(d["st"])
    cur = st.get(sid, "present")
    st[sid] = A.CYCLE[(A.CYCLE.index(cur) + 1) % len(A.CYCLE)]
    await state.update_data(st=st)
    await c.message.edit_reply_markup(reply_markup=await att_markup(db, d["att_group"], d["day"], st))
    await c.answer()


@router.callback_query(F.data == "ad", TEACHER)
async def att_done(c: CallbackQuery, db, state: FSMContext, bot: Bot):
    d = await state.get_data()
    if "att_group" not in d:
        return await c.answer("Davomatni qaytadan boshlang", show_alert=True)
    res = await A.save_attendance(db, bot, c.from_user.id, d["att_group"], date.fromisoformat(d["day"]),
                                  {int(k): v for k, v in d["st"].items()})
    await state.clear()
    await c.message.edit_reply_markup(reply_markup=None)
    cnt = res["counts"]
    await c.message.answer(
        f"✅ Davomat saqlandi va adminga yuborildi.\nKeldi {cnt['present']}, kelmadi {cnt['absent']}, "
        f"kechikdi {cnt['late']}, sababli {cnt['excused']}." +
        ("\n⚠️ Reyestr narxi kiritilmagan, direktorga ayting." if res["no_price"] else ""))
    await c.answer()
