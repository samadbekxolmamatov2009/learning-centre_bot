"""Lidlar (potentsial o'quvchilar): qiziqish bildirgan, lekin hali ro'yxatdan o'tmagan odamlar.
5 kundan beri qaror qilinmagan lidlar haqida admin/direktorga har kuni eslatma boradi
(bot/extras.py::check_stale_leads)."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from . import db as D
from .handlers import STAFF, with_phone, group_picker, can_access_group, normalize_phone

router = Router()

LEAD_SOURCES = ["📷 Instagram", "👥 Tanishlar orqali", "📢 Ko'chadagi reklama", "✍️ Boshqa"]


def lead_line(r) -> str:
    name = f"{r['last_name']} {r['first_name']}".strip()
    extra = f" · {r['grade']}-sinf" if r["grade"] else ""
    return f"{name}{extra}{with_phone(r)}"


def lead_detail_text(r) -> str:
    lines = [f"🧲 <b>{lead_line(r)}</b>", f"Holat: {D.LEAD_STATUS_LABELS[r['status']]}"]
    if r["source"]:
        lines.append(f"Manba: {r['source']}")
    if r["note"]:
        lines.append(f"Izoh: {r['note']}")
    if r["status"] == "lost" and r["lost_reason"]:
        lines.append(f"Sababi: {r['lost_reason']}")
    return "\n".join(lines)


def lead_actions_kb(r) -> InlineKeyboardMarkup | None:
    rows = []
    if r["status"] == "new":
        rows.append([InlineKeyboardButton(text="📞 Bog'landim", callback_data=f"ld_next:{r['id']}")])
    elif r["status"] == "contacted":
        rows.append([InlineKeyboardButton(text="🎓 Sinov darsiga yozildi", callback_data=f"ld_next:{r['id']}")])
    if r["status"] in D.LEAD_OPEN_STATUSES:
        rows.append([InlineKeyboardButton(text="🎉 O'quvchi qilish", callback_data=f"ld_win:{r['id']}"),
                     InlineKeyboardButton(text="❌ Voz kechish", callback_data=f"ld_lose:{r['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


# ---------------- Lid qo'shish ----------------
class AddLead(StatesGroup):
    first = State(); last = State(); grade = State(); phone = State()
    source = State(); source_other = State(); branch = State(); note = State()


@router.message(F.text == "🧲 Lidlar", STAFF)
async def leads_menu(m: Message):
    await m.answer("Lidlar bo'limi:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Lid qo'shish", callback_data="ld_add")],
        [InlineKeyboardButton(text="📋 Ochiq lidlar", callback_data="ld_list")]]))


@router.callback_query(F.data == "ld_add", STAFF)
async def ld_add(c: CallbackQuery, state: FSMContext):
    await state.set_state(AddLead.first)
    await c.message.answer("Lid ismi:")
    await c.answer()


@router.message(AddLead.first)
async def ld_first(m: Message, state: FSMContext):
    await state.update_data(first=m.text.strip())
    await state.set_state(AddLead.last)
    await m.answer("Familiyasi (bilmasangiz - yuboring):")


@router.message(AddLead.last)
async def ld_last(m: Message, state: FSMContext):
    t = m.text.strip()
    await state.update_data(last="" if t == "-" else t)
    await state.set_state(AddLead.grade)
    await m.answer("Qiziqqan sinfi (masalan 7, bilmasangiz - yuboring):")


@router.message(AddLead.grade)
async def ld_grade(m: Message, state: FSMContext):
    t = m.text.strip()
    await state.update_data(grade="" if t == "-" else t)
    await state.set_state(AddLead.phone)
    await m.answer("Telefon raqami (masalan 90 123 45 67, bilmasangiz - yuboring):")


@router.message(AddLead.phone)
async def ld_phone(m: Message, state: FSMContext):
    t = m.text.strip()
    if t == "-":
        phone = ""
    else:
        phone = normalize_phone(t)
        if phone is None:
            return await m.answer("Raqam noto'g'ri. Masalan: 90 123 45 67 (yoki - yuboring).")
    await state.update_data(phone=phone)
    await state.set_state(AddLead.source)
    kb_ = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s, callback_data=f"ldsrc:{s}")]
                                                for s in LEAD_SOURCES])
    await m.answer("Qayerdan bilgan (manba)?", reply_markup=kb_)


@router.callback_query(AddLead.source, F.data.startswith("ldsrc:"))
async def ld_source(c: CallbackQuery, db, state: FSMContext):
    src = c.data[6:]
    await c.answer()
    if src == "✍️ Boshqa":
        await state.set_state(AddLead.source_other)
        return await c.message.answer("Manbani yozing:")
    await state.update_data(source=src)
    await _ask_branch_or_note(c.message, db, state)


@router.message(AddLead.source_other)
async def ld_source_other(m: Message, db, state: FSMContext):
    await state.update_data(source=m.text.strip())
    await _ask_branch_or_note(m, db, state)


async def _ask_branch_or_note(msg: Message, db, state: FSMContext):
    branches = await db.fetchall("SELECT id, name FROM branches ORDER BY name")
    if len(branches) > 1:
        await state.set_state(AddLead.branch)
        kb_ = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=b["name"], callback_data=f"ldbr:{b['id']}")]
                                                     for b in branches])
        return await msg.answer("Qaysi filialga qiziqdi?", reply_markup=kb_)
    await state.update_data(branch_id=branches[0]["id"] if branches else None)
    await state.set_state(AddLead.note)
    await msg.answer("Izoh (ixtiyoriy, bo'lmasa - yuboring):")


@router.callback_query(AddLead.branch, F.data.startswith("ldbr:"))
async def ld_branch(c: CallbackQuery, state: FSMContext):
    await state.update_data(branch_id=int(c.data[5:]))
    await state.set_state(AddLead.note)
    await c.message.answer("Izoh (ixtiyoriy, bo'lmasa - yuboring):")
    await c.answer()


@router.message(AddLead.note)
async def ld_note(m: Message, db, state: FSMContext):
    t = m.text.strip()
    d = await state.get_data()
    await db.execute(
        "INSERT INTO leads(first_name,last_name,phone,grade,source,branch_id,note) VALUES(?,?,?,?,?,?,?)",
        (d["first"], d.get("last", ""), d.get("phone", ""), d.get("grade", ""), d.get("source", ""),
         d.get("branch_id"), "" if t == "-" else t))
    row = await D.fetchone(db, "SELECT * FROM leads WHERE id=(SELECT MAX(id) FROM leads)")
    await state.clear()
    await m.answer(f"✅ Lid qo'shildi.\n\n{lead_detail_text(row)}", parse_mode="HTML",
                   reply_markup=lead_actions_kb(row))


# ---------------- Ro'yxat va holat o'zgartirish ----------------
@router.callback_query(F.data == "ld_list", STAFF)
async def ld_list(c: CallbackQuery, db):
    rows = await db.fetchall(
        "SELECT * FROM leads WHERE status IN ('new','contacted','trial') ORDER BY created_at")
    await c.answer()
    if not rows:
        return await c.message.answer("Ochiq lid yo'q 🎉")
    kb_ = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{D.LEAD_STATUS_LABELS[r['status']][:2]} {lead_line(r)}",
                              callback_data=f"ld_open:{r['id']}")] for r in rows])
    await c.message.answer(f"Ochiq lidlar ({len(rows)}):", reply_markup=kb_)


@router.callback_query(F.data.startswith("ld_open:"), STAFF)
async def ld_open(c: CallbackQuery, db):
    r = await db.fetchone("SELECT * FROM leads WHERE id=?", (int(c.data[8:]),))
    await c.answer()
    if not r:
        return await c.message.answer("Lid topilmadi.")
    await c.message.answer(lead_detail_text(r), parse_mode="HTML", reply_markup=lead_actions_kb(r))


@router.callback_query(F.data.startswith("ld_next:"), STAFF)
async def ld_next(c: CallbackQuery, db):
    lid = int(c.data[8:])
    r = await db.fetchone("SELECT * FROM leads WHERE id=?", (lid,))
    if not r or r["status"] not in D.LEAD_NEXT_STATUS:
        return await c.answer("Bu holatda bo'lmaydi", show_alert=True)
    nxt = D.LEAD_NEXT_STATUS[r["status"]]
    await db.execute("UPDATE leads SET status=? WHERE id=?", (nxt, lid))
    r2 = await db.fetchone("SELECT * FROM leads WHERE id=?", (lid,))
    await c.message.edit_text(lead_detail_text(r2), parse_mode="HTML", reply_markup=lead_actions_kb(r2))
    await c.answer("Holat yangilandi")


@router.callback_query(F.data.startswith("ld_win:"), STAFF)
async def ld_win(c: CallbackQuery, db):
    lid = int(c.data[7:])
    mk = await group_picker(db, f"ldg:{lid}")
    await c.answer()
    await c.message.answer("O'quvchi qaysi guruhga qo'shilsin?" if mk else "Avval guruh yarating.",
                           reply_markup=mk)


@router.callback_query(F.data.startswith("ldg:"), STAFF)
async def ld_win_group(c: CallbackQuery, db):
    _, lid_s, gid_s = c.data.split(":")
    lid, gid = int(lid_s), int(gid_s)
    if not await can_access_group(db, c.from_user.id, gid):
        return await c.answer("Bu sizning guruhingiz emas", show_alert=True)
    r = await db.fetchone("SELECT * FROM leads WHERE id=?", (lid,))
    if not r or r["status"] not in D.LEAD_OPEN_STATUSES:
        return await c.answer("Bu lid allaqachon yopilgan", show_alert=True)
    await db.execute("INSERT INTO students(first_name,last_name,grade,phone,group_id) VALUES(?,?,?,?,?)",
                     (r["first_name"], r["last_name"] or "-", r["grade"], r["phone"], gid))
    await db.execute("UPDATE leads SET status='won', decided_at=CURRENT_TIMESTAMP WHERE id=?", (lid,))
    await c.message.answer(f"🎉 {r['last_name']} {r['first_name']} o'quvchi qilib qo'shildi.")
    await c.answer()


class DeclineLead(StatesGroup):
    reason = State()


@router.callback_query(F.data.startswith("ld_lose:"), STAFF)
async def ld_lose(c: CallbackQuery, state: FSMContext):
    await state.set_state(DeclineLead.reason)
    await state.update_data(lead_id=int(c.data[8:]))
    await c.message.answer("Sababi (ixtiyoriy, bo'lmasa - yuboring):")
    await c.answer()


@router.message(DeclineLead.reason)
async def ld_lose_reason(m: Message, db, state: FSMContext):
    lid = (await state.get_data())["lead_id"]
    t = m.text.strip()
    await db.execute("UPDATE leads SET status='lost', lost_reason=?, decided_at=CURRENT_TIMESTAMP WHERE id=?",
                     ("" if t == "-" else t, lid))
    await state.clear()
    await m.answer("❌ Lid yopildi (voz kechdi).")
