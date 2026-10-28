"""Telegram Mini App uchun veb-server: davomat sahifasi va direktor paneli.

Autentifikatsiya: Telegram WebApp initData imzosi (BOT_TOKEN bilan HMAC) tekshiriladi,
rol bazadan olinadi. Hech qanday parol yoki alohida login yo'q.
"""
import asyncio
import hashlib
import hmac
import io
import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from . import attendance as A
from . import db as D
from .config import BOT_TOKEN
from .handlers import normalize_phone, can_access_group

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
MAX_AUTH_AGE = 24 * 3600


def verify_init_data(init_data: str, token: str, max_age: int = MAX_AUTH_AGE):
    """initData to'g'ri imzolangan bo'lsa user dict qaytaradi, aks holda None."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        got = pairs.pop("hash", "")
        if not got:
            return None
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        return json.loads(pairs["user"])
    except Exception:
        return None


@web.middleware
async def errors_mw(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        log.exception("Veb xatosi: %s", request.path)
        return web.json_response({"error": "Server xatosi"}, status=500)


async def auth(request):
    user = verify_init_data(request.headers.get("X-Init-Data", ""), BOT_TOKEN)
    if not user:
        raise web.HTTPUnauthorized(text=json.dumps({"error": "Telegram orqali qayta oching"}),
                                   content_type="application/json")
    db = request.app["db"]
    row = await db.fetchone("SELECT full_name, role FROM users WHERE tg_id=?", (user["id"],))
    if not row:
        raise web.HTTPForbidden(text=json.dumps({"error": "Siz ro'yxatda yo'qsiz"}),
                                content_type="application/json")
    return user["id"], row["role"], row["full_name"]


async def auth_any(request):
    """Faqat Telegram imzosini tekshiradi, users jadvalida bo'lishi shart emas (ota-ona sahifasi uchun)."""
    user = verify_init_data(request.headers.get("X-Init-Data", ""), BOT_TOKEN)
    if not user:
        raise web.HTTPUnauthorized(text=json.dumps({"error": "Telegram orqali qayta oching"}),
                                   content_type="application/json")
    return user["id"]


async def can_access(db, uid, role, gid) -> bool:
    return await can_access_group(db, uid, gid)


async def debtor_counts_by_group(db, paid_ids):
    """Har guruhdagi qarzdorlar soni (reyestrsiz, to'lamagan). paid_ids bo'sh bo'lsa ham to'g'ri ishlaydi
    ('NOT IN ()' SQL'da bo'sh ro'yxat bilan ishlamaydi, shuning uchun shart shart emas bo'lsa qo'shilmaydi)."""
    if paid_ids:
        ph = ",".join("?" * len(paid_ids))
        rows = await db.fetchall(
            f"SELECT group_id, COUNT(*) n FROM students WHERE hidden=0 AND is_registry=0 "
            f"AND id NOT IN ({ph}) GROUP BY group_id", tuple(paid_ids))
    else:
        rows = await db.fetchall(
            "SELECT group_id, COUNT(*) n FROM students WHERE hidden=0 AND is_registry=0 GROUP BY group_id")
    return {r["group_id"]: r["n"] for r in rows}


def bad(msg, status=400):
    return web.json_response({"error": msg}, status=status)


# ---------------- sahifa ----------------
async def index(request):
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


async def parent_index(request):
    return web.FileResponse(STATIC / "parent.html", headers={"Cache-Control": "no-store"})


async def health(request):
    return web.Response(text="ok")


# ---------------- API ----------------
async def api_me(request):
    uid, role, name = await auth(request)
    db = request.app["db"]
    today = D.today_local().isoformat()
    if role == "teacher":
        groups = await db.fetchall("SELECT id, name, lesson_days, lesson_time FROM groups "
                                   "WHERE teacher_id=? ORDER BY name", (uid,))
    else:
        groups = await db.fetchall("SELECT g.id, g.name, g.lesson_days, g.lesson_time FROM groups g ORDER BY g.name")
    counts = {r["group_id"]: r["n"] for r in await db.fetchall(
        "SELECT group_id, COUNT(*) n FROM students WHERE hidden=0 GROUP BY group_id")}
    taken = {r["group_id"] for r in await db.fetchall(
        "SELECT DISTINCT group_id FROM attendance WHERE day=?", (today,))}
    return web.json_response({
        "role": role, "name": name, "today": today,
        "groups": [{"id": g["id"], "name": g["name"], "students": counts.get(g["id"], 0),
                    "taken_today": g["id"] in taken, "days": g["lesson_days"], "time": g["lesson_time"]}
                   for g in groups]})


async def api_attendance_get(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        gid = int(request.query.get("group", ""))
    except ValueError:
        return bad("group kerak")
    if not await can_access(db, uid, role, gid):
        return bad("Bu sizning guruhingiz emas", 403)
    today = D.today_local()
    try:
        day = date.fromisoformat(request.query.get("day") or today.isoformat())
    except ValueError:
        return bad("Sana noto'g'ri")
    g = await db.fetchone("SELECT id, name FROM groups WHERE id=?", (gid,))
    studs = await D.group_students(db, gid)
    days, hist = await A.history(db, gid, before=day.isoformat(), n=20)
    existing = await A.day_statuses(db, gid, day.isoformat())
    recent = await A.lesson_days(db, gid, 8)
    return web.json_response({
        "group": {"id": g["id"], "name": g["name"]}, "day": day.isoformat(), "today": today.isoformat(),
        "has_record": bool(existing), "hist_days": days, "recent_days": recent,
        "students": [{"id": s["id"], "name": f"{s['last_name']} {s['first_name']}", "grade": s["grade"],
                      "phone": s["phone"], "status": existing.get(s["id"], "present"),
                      "hist": hist.get(s["id"], {})} for s in studs]})


async def api_attendance_post(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        body = await request.json()
        gid = int(body["group"])
        day = date.fromisoformat(body["day"])
        statuses = {int(k): v for k, v in body["statuses"].items()}
    except Exception:
        return bad("So'rov noto'g'ri")
    if not await can_access(db, uid, role, gid):
        return bad("Bu sizning guruhingiz emas", 403)
    today = D.today_local()
    if day > today:
        return bad("Kelajak sanasiga davomat olib bo'lmaydi")
    if role == "teacher" and day < today - timedelta(days=30):
        return bad("30 kundan eski davomatni faqat admin o'zgartira oladi")
    if any(v not in A.STATUSES for v in statuses.values()):
        return bad("Holat noto'g'ri")
    res = await A.save_attendance(db, request.app.get("bot"), uid, gid, day, statuses)
    return web.json_response({"ok": True, **res})


async def _gather_salaries(db, month):
    teachers = await db.fetchall("SELECT tg_id FROM teachers")
    res = await asyncio.gather(*(D.teacher_salary(db, t["tg_id"], month) for t in teachers))
    return sum(r[3] for r in res if r)


async def api_dashboard(request):
    uid, role, _ = await auth(request)
    if role not in ("admin", "director"):
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    today = D.today_local()
    cur = D.current_month()
    months, y, m = [], today.year, today.month
    for _ in range(6):
        months.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    ph = ",".join("?" * len(months))
    inc = {r["month"]: r["t"] for r in await db.fetchall(
        f"SELECT month, SUM(amount) t FROM payments WHERE month IN ({ph}) GROUP BY month", tuple(months))}
    reg = {}
    for r in await db.fetchall(
            "SELECT substr(day,1,7) mo, SUM(rate) t FROM attendance WHERE present=1 AND substr(day,1,7) IN "
            f"({ph}) GROUP BY mo", tuple(months)):
        reg[r["mo"]] = r["t"]
    groups = await db.fetchall("""
        SELECT g.id, g.name, u.full_name AS teacher, COUNT(s.id) AS n,
               COALESCE(SUM(CASE WHEN s.is_registry=1 OR EXISTS(
                   SELECT 1 FROM payments p WHERE p.student_id=s.id AND p.month=?) THEN 1 ELSE 0 END),0) AS paid
        FROM groups g LEFT JOIN students s ON s.group_id=g.id AND s.hidden=0
        LEFT JOIN users u ON u.tg_id=g.teacher_id GROUP BY g.id ORDER BY g.name""", (cur,))
    g_inc = {r["group_id"]: r["t"] for r in await db.fetchall(
        "SELECT group_id, SUM(amount) t FROM payments WHERE month=? GROUP BY group_id", (cur,))}
    g_att = {r["group_id"]: (r["p"], r["n"]) for r in await db.fetchall(
        "SELECT group_id, SUM(present) p, COUNT(*) n FROM attendance WHERE day LIKE ? GROUP BY group_id",
        (cur + "-%",))}
    out_groups = []
    for g in groups:
        p, n = g_att.get(g["id"], (0, 0))
        out_groups.append({"name": g["name"], "teacher": g["teacher"] or "-", "students": g["n"],
                           "debtors": g["n"] - g["paid"], "income": g_inc.get(g["id"], 0),
                           "att": round(p * 100 / n) if n else None})
    total_students = sum(g["students"] for g in out_groups)
    total_debtors = sum(g["debtors"] for g in out_groups)
    att_all = await db.fetchone("SELECT COALESCE(SUM(present),0) p, COUNT(*) n FROM attendance WHERE day LIKE ?",
                                (cur + "-%",))
    data = {
        "role": role, "month": cur,
        "months": [{"month": mo, "income": inc.get(mo, 0), "registry": reg.get(mo, 0)} for mo in months],
        "groups": out_groups, "students": total_students, "debtors": total_debtors,
        "att": round(att_all["p"] * 100 / att_all["n"]) if att_all["n"] else None}
    if role == "director":
        sal = await _gather_salaries(db, cur)
        data["salaries"] = round(sal)
        data["remaining"] = round(inc.get(cur, 0) + reg.get(cur, 0) - sal)
    return web.json_response(data)


STUDENT_FIELDS = ("last", "first", "grade", "phone")


def student_out(s, gname=None, paid=None):
    if paid is None:
        paid = bool(s["is_registry"]) or bool(s.get("paid"))
    return {"id": s["id"], "last": s["last_name"], "first": s["first_name"], "grade": s["grade"],
            "phone": s["phone"], "is_registry": bool(s["is_registry"]), "group": s["group_id"],
            "group_name": gname or s.get("gname"), "hidden": bool(s["hidden"]), "paid": paid}


def clean_text(v, maxlen=60):
    return str(v or "").strip()[:maxlen]


async def api_groups(request):
    """Mini App uchun guruhlar ro'yxati: admin/direktorga hammasi + o'qituvchi tanlash, o'qituvchiga o'ziniki."""
    uid, role, _ = await auth(request)
    db = request.app["db"]
    if role == "teacher":
        groups = await db.fetchall("SELECT id, name, lesson_days, lesson_time FROM groups "
                                   "WHERE teacher_id=? ORDER BY name", (uid,))
    else:
        groups = await db.fetchall("SELECT g.id, g.name, g.teacher_id AS teacherId, u.full_name AS teacher, "
                                   "g.lesson_days, g.lesson_time FROM groups g "
                                   "LEFT JOIN users u ON u.tg_id=g.teacher_id ORDER BY g.name")
    counts = {r["group_id"]: r["n"] for r in await db.fetchall(
        "SELECT group_id, COUNT(*) n FROM students WHERE hidden=0 GROUP BY group_id")}
    paid_ids = {r["student_id"] for r in await db.fetchall(
        "SELECT DISTINCT student_id FROM payments WHERE month=?", (D.current_month(),))}
    debt = await debtor_counts_by_group(db, paid_ids)
    out = {"groups": [{**dict(g), "students": counts.get(g["id"], 0), "debtors": debt.get(g["id"], 0)} for g in groups]}
    if role in ("admin", "director"):
        out["teachers"] = [dict(t) for t in await db.fetchall(
            "SELECT u.tg_id AS id, u.full_name AS name FROM users u JOIN teachers t ON t.tg_id=u.tg_id "
            "ORDER BY u.full_name")]
    return web.json_response(out)


async def api_groups_post(request):
    uid, role, _ = await auth(request)
    if role not in ("admin", "director"):
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    try:
        body = await request.json()
        name = clean_text(body.get("name"), 40)
        teacher = body.get("teacher")
        teacher = int(teacher) if teacher else None
    except Exception:
        return bad("So'rov noto'g'ri")
    if not name:
        return bad("Guruh nomini kiriting")
    if teacher and not await db.fetchone("SELECT 1 FROM teachers WHERE tg_id=?", (teacher,)):
        return bad("O'qituvchi topilmadi")
    if await db.fetchone("SELECT 1 FROM groups WHERE name=?", (name,)):
        return bad("Bunday nomli guruh bor")
    await db.execute("INSERT INTO groups(name, teacher_id) VALUES(?,?)", (name, teacher))
    g = await db.fetchone("SELECT id FROM groups WHERE name=?", (name,))
    return web.json_response({"ok": True, "id": g["id"]})


async def api_students_get(request):
    """Guruh tanlansa shu guruh, aks holda (q bilan) ruxsatli guruhlar bo'yicha qidiruv."""
    uid, role, _ = await auth(request)
    db = request.app["db"]
    gid = request.query.get("group")
    q = clean_text(request.query.get("q", ""), 60).casefold()
    if gid:
        gid = int(gid)
        if not await can_access(db, uid, role, gid):
            return bad("Bu sizning guruhingiz emas", 403)
        studs = await D.group_students(db, gid)
        g = await db.fetchone("SELECT name FROM groups WHERE id=?", (gid,))
        return web.json_response({"students": [student_out(s, g["name"], bool(s["paid"])) for s in studs]})
    if not q or len(q) < 2:
        return bad("Qidiruv uchun kamida 2 ta belgi kerak")
    sql = ("SELECT s.*, g.name AS gname FROM students s JOIN groups g ON g.id=s.group_id WHERE s.hidden=0")
    args = []
    if role == "teacher":
        sql += " AND g.teacher_id=?"
        args.append(uid)
    paid_ids = {r["student_id"] for r in await db.fetchall(
        "SELECT DISTINCT student_id FROM payments WHERE month=?", (D.current_month(),))}
    found = []
    for s in await db.fetchall(sql, tuple(args)):
        names = f"{s['first_name']} {s['last_name']} {s['last_name']} {s['first_name']}".casefold()
        digits = "".join(ch for ch in q if ch.isdigit())
        if q in names or (len(digits) >= 3 and digits in "".join(ch for ch in s["phone"] if ch.isdigit())):
            found.append(student_out(s, paid=s["id"] in paid_ids or bool(s["is_registry"])))
    return web.json_response({"students": found[:40]})


async def api_students_post(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        body = await request.json()
        gid = int(body["group"])
    except Exception:
        return bad("Guruh tanlanmagan")
    if not await can_access(db, uid, role, gid):
        return bad("Bu sizning guruhingiz emas", 403)
    last, first = clean_text(body.get("last")), clean_text(body.get("first"))
    grade = clean_text(body.get("grade"), 20) or "-"
    if len(last) < 2 or len(first) < 2:
        return bad("Ism va familiyani to'liq kiriting")
    phone_raw = body.get("phone") or ""
    phone = normalize_phone(phone_raw) if phone_raw.strip() else ""
    if phone is None:
        return bad("Telefon raqami noto'g'ri")
    is_reg = 1 if (body.get("is_registry") and role in ("admin", "director")) else 0
    hidden = 1 if (is_reg and await D.get_setting(db, "registry_hidden") == "1") else 0
    await db.execute("INSERT INTO students(first_name,last_name,grade,phone,is_registry,hidden,group_id) "
                     "VALUES(?,?,?,?,?,?,?)", (first, last, grade, phone, is_reg, hidden, gid))
    row = await db.fetchone("SELECT * FROM students WHERE id=(SELECT MAX(id) FROM students WHERE group_id=?)",
                            (gid,))
    return web.json_response({"ok": True, "student": student_out(row)})


async def _student_access(db, uid, role, sid):
    s = await db.fetchone("SELECT * FROM students WHERE id=?", (sid,))
    if not s or not await can_access(db, uid, role, s["group_id"]):
        return None
    return s


async def api_student_patch(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        sid = int(request.match_info["sid"])
        body = await request.json()
    except Exception:
        return bad("So'rov noto'g'ri")
    s = await _student_access(db, uid, role, sid)
    if not s:
        return bad("Topilmadi yoki ruxsat yo'q", 404)
    sets, args = [], []
    if "last" in body:
        v = clean_text(body["last"])
        if len(v) < 2:
            return bad("Familiya qisqa")
        sets.append("last_name=?"); args.append(v)
    if "first" in body:
        v = clean_text(body["first"])
        if len(v) < 2:
            return bad("Ism qisqa")
        sets.append("first_name=?"); args.append(v)
    if "grade" in body:
        sets.append("grade=?"); args.append(clean_text(body["grade"], 20) or "-")
    if "phone" in body:
        phone = normalize_phone(body["phone"] or "")
        if phone is None:
            return bad("Telefon raqami noto'g'ri")
        sets.append("phone=?"); args.append(phone)
    if "group" in body:
        new_gid = int(body["group"])
        if not await can_access(db, uid, role, new_gid):
            return bad("Yangi guruhga ruxsat yo'q", 403)
        sets.append("group_id=?"); args.append(new_gid)
        await db.execute("UPDATE payments SET group_id=? WHERE student_id=? AND month=?",
                         (new_gid, sid, D.current_month()))
    if "is_registry" in body and role in ("admin", "director"):
        sets.append("is_registry=?"); args.append(1 if body["is_registry"] else 0)
    if not sets:
        return bad("O'zgartiriladigan narsa yo'q")
    args.append(sid)
    await db.execute(f"UPDATE students SET {', '.join(sets)} WHERE id=?", tuple(args))
    row = await db.fetchone("SELECT * FROM students WHERE id=?", (sid,))
    return web.json_response({"ok": True, "student": student_out(row)})


async def api_student_delete(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        sid = int(request.match_info["sid"])
    except Exception:
        return bad("So'rov noto'g'ri")
    s = await _student_access(db, uid, role, sid)
    if not s:
        return bad("Topilmadi yoki ruxsat yo'q", 404)
    await D.archive_or_delete_student(db, sid)
    return web.json_response({"ok": True})


async def api_payment_post(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        body = await request.json()
        sid = int(body["student"])
        amount = int(body["amount"])
        assert amount > 0
    except Exception:
        return bad("Summa noto'g'ri")
    s = await _student_access(db, uid, role, sid)
    if not s:
        return bad("Topilmadi yoki ruxsat yo'q", 404)
    mo = D.current_month()
    await db.execute("INSERT INTO payments(student_id,group_id,amount,month) VALUES(?,?,?,?)",
                     (sid, s["group_id"], amount, mo))
    row = await db.fetchone("SELECT id FROM payments WHERE student_id=? AND month=? ORDER BY id DESC LIMIT 1",
                            (sid, mo))
    if row:
        from .receipts import send_receipt
        await send_receipt(request.app.get("bot"), db, row["id"], uid)
    return web.json_response({"ok": True})


async def api_payments_get(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        sid = int(request.query["student"])
    except Exception:
        return bad("student kerak")
    s = await _student_access(db, uid, role, sid)
    if not s:
        return bad("Topilmadi yoki ruxsat yo'q", 404)
    rows = await db.fetchall("SELECT * FROM payments WHERE student_id=? ORDER BY id DESC LIMIT 10", (sid,))
    return web.json_response({"payments": [{"id": r["id"], "amount": r["amount"], "month": r["month"],
                                            "created_at": str(r["created_at"])} for r in rows]})


async def api_payment_delete(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        pid = int(request.match_info["pid"])
    except Exception:
        return bad("So'rov noto'g'ri")
    if role not in ("admin", "director"):
        return bad("Ruxsat yo'q", 403)
    p = await db.fetchone("SELECT * FROM payments WHERE id=?", (pid,))
    if not p:
        return bad("Topilmadi", 404)
    await db.execute("DELETE FROM payments WHERE id=?", (pid,))
    return web.json_response({"ok": True})


async def api_salary(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    target = uid
    if role in ("admin", "director") and request.query.get("teacher"):
        target = int(request.query["teacher"])
    elif role == "teacher":
        target = uid
    elif role in ("admin", "director"):
        return bad("teacher parametri kerak")
    month = request.query.get("month") or D.current_month()
    res = await D.teacher_salary(db, target, month)
    if not res:
        return bad("O'qituvchi topilmadi", 404)
    pay_type, pay_value, rows, total = res
    reg = await D.registry_rows(db, target, month)
    months = []
    y, m = (int(x) for x in D.current_month().split("-"))
    for _ in range(6):
        months.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12

    groups_out = []
    for g in await db.fetchall("SELECT * FROM groups WHERE teacher_id=? ORDER BY name", (target,)):
        studs = await D.group_students(db, g["id"], month)
        reg_cnt = sum(1 for s in studs if s["is_registry"])
        paid = sum(1 for s in studs if s["paid"]) - reg_cnt
        income = await D.group_income(db, g["id"], month)
        att = await db.fetchone("SELECT COALESCE(SUM(present),0) p, COUNT(*) n FROM attendance "
                                "WHERE group_id=? AND day LIKE ?", (g["id"], month + "-%"))
        groups_out.append({
            "name": g["name"], "income": income, "paid": paid, "students": len(studs),
            "debtors": len(studs) - paid - reg_cnt,
            "att": round(att["p"] * 100 / att["n"]) if att["n"] else None})

    return web.json_response({
        "pay_type": pay_type, "pay_value": pay_value, "month": month, "months": list(reversed(months)),
        "groups": groups_out,
        "registry": [{"group": n, "lessons": l, "total": t} for n, l, t in reg], "total": round(total)})


# ---------------- Nazorat/sinov natijalari ----------------
def exam_out(e, avg=None, count=None):
    return {"id": e["id"], "group": e["group_id"], "title": e["title"], "max_score": e["max_score"],
            "day": e["day"], "avg": avg, "count": count}


async def api_exams_get(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        gid = int(request.query["group"])
    except Exception:
        return bad("group kerak")
    if not await can_access(db, uid, role, gid):
        return bad("Bu sizning guruhingiz emas", 403)
    exams = await db.fetchall("SELECT * FROM exams WHERE group_id=? ORDER BY day DESC, id DESC", (gid,))
    out = []
    for e in exams:
        agg = await db.fetchone("SELECT AVG(score) a, COUNT(*) n FROM exam_scores WHERE exam_id=?", (e["id"],))
        out.append(exam_out(e, round(agg["a"], 1) if agg["a"] is not None else None, agg["n"]))
    return web.json_response({"exams": out})


async def api_exam_post(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        body = await request.json()
        gid = int(body["group"])
        title = clean_text(body.get("title"), 60)
        max_score = int(body["max_score"])
        day = clean_text(body.get("day"), 10) or D.today_local().isoformat()
        assert max_score > 0
    except Exception:
        return bad("So'rov noto'g'ri")
    if not title:
        return bad("Nazorat nomini kiriting")
    if not await can_access(db, uid, role, gid):
        return bad("Bu sizning guruhingiz emas", 403)
    await db.execute("INSERT INTO exams(group_id, title, max_score, day) VALUES(?,?,?,?)",
                     (gid, title, max_score, day))
    e = await db.fetchone("SELECT id FROM exams WHERE group_id=? ORDER BY id DESC LIMIT 1", (gid,))
    return web.json_response({"ok": True, "id": e["id"]})


async def api_exam_get(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        eid = int(request.match_info["eid"])
    except Exception:
        return bad("So'rov noto'g'ri")
    e = await db.fetchone("SELECT * FROM exams WHERE id=?", (eid,))
    if not e or not await can_access(db, uid, role, e["group_id"]):
        return bad("Topilmadi yoki ruxsat yo'q", 404)
    studs = await D.group_students(db, e["group_id"])
    scores = {r["student_id"]: r["score"] for r in await db.fetchall(
        "SELECT student_id, score FROM exam_scores WHERE exam_id=?", (eid,))}
    return web.json_response({
        "exam": exam_out(e),
        "students": [{"id": s["id"], "name": f"{s['last_name']} {s['first_name']}",
                      "score": scores.get(s["id"])} for s in studs]})


async def api_exam_scores_post(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        eid = int(request.match_info["eid"])
        body = await request.json()
        scores = body["scores"]
    except Exception:
        return bad("So'rov noto'g'ri")
    e = await db.fetchone("SELECT * FROM exams WHERE id=?", (eid,))
    if not e or not await can_access(db, uid, role, e["group_id"]):
        return bad("Topilmadi yoki ruxsat yo'q", 404)
    stmts = []
    for sid, sc in scores.items():
        try:
            sid = int(sid)
            if sc is None or sc == "":
                continue
            sc = float(sc)
            assert 0 <= sc <= e["max_score"]
        except Exception:
            return bad("Baho noto'g'ri")
        stmts.append(("INSERT INTO exam_scores(exam_id, student_id, score) VALUES(?,?,?) "
                      "ON CONFLICT(exam_id, student_id) DO UPDATE SET score=excluded.score", (eid, sid, sc)))
    if stmts:
        await db.batch(stmts)
    return web.json_response({"ok": True})


async def api_exam_delete(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        eid = int(request.match_info["eid"])
    except Exception:
        return bad("So'rov noto'g'ri")
    e = await db.fetchone("SELECT * FROM exams WHERE id=?", (eid,))
    if not e or not await can_access(db, uid, role, e["group_id"]):
        return bad("Topilmadi yoki ruxsat yo'q", 404)
    await db.execute("DELETE FROM exam_scores WHERE exam_id=?", (eid,))
    await db.execute("DELETE FROM exams WHERE id=?", (eid,))
    return web.json_response({"ok": True})


async def api_student_exams_get(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        sid = int(request.match_info["sid"])
    except Exception:
        return bad("So'rov noto'g'ri")
    s = await _student_access(db, uid, role, sid)
    if not s:
        return bad("Topilmadi yoki ruxsat yo'q", 404)
    rows = await db.fetchall(
        "SELECT e.id, e.title, e.max_score, e.day, es.score FROM exam_scores es "
        "JOIN exams e ON e.id=es.exam_id WHERE es.student_id=? ORDER BY e.day DESC, e.id DESC LIMIT 10", (sid,))
    return web.json_response({"exams": [dict(r) for r in rows]})


# ---------------- Sertifikatlar ----------------
def cert_student_out(s, certs):
    return {"id": s["id"], "name": f"{s['last_name']} {s['first_name']}", "grade": s["grade"],
            "has_189": bool(s["has_189"]), "cert_count": len(certs),
            "certificates": [{"subject": c["subject"], "grade": c["grade"]} for c in certs]}


async def api_certificates_get(request):
    """Guruh bo'yicha faol (arxivlanmagan) o'quvchilar + ularning sertifikatlari."""
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        gid = int(request.query["group"])
    except Exception:
        return bad("group kerak")
    if not await can_access(db, uid, role, gid):
        return bad("Bu sizning guruhingiz emas", 403)
    studs = await db.fetchall("SELECT * FROM students WHERE group_id=? AND hidden=0 "
                              "ORDER BY last_name, first_name", (gid,))
    out = []
    for s in studs:
        certs = await db.fetchall("SELECT subject, grade FROM certificates WHERE student_id=? ORDER BY subject",
                                  (s["id"],))
        out.append(cert_student_out(s, certs))
    return web.json_response({"students": out, "subjects": D.CERT_SUBJECTS, "grades": D.CERT_GRADES})


async def api_certificates_graduated(request):
    """Guruhdan chiqarilgan (arxivlangan), lekin sertifikat/189 belgisi tufayli saqlangan o'quvchilar."""
    uid, role, _ = await auth(request)
    db = request.app["db"]
    sql = ("SELECT s.*, g.name AS gname FROM students s LEFT JOIN groups g ON g.id=s.group_id "
          "WHERE s.archived=1")
    args = []
    if role == "teacher":
        sql += " AND s.group_id IN (SELECT id FROM groups WHERE teacher_id=?)"
        args.append(uid)
    sql += " ORDER BY s.last_name, s.first_name"
    studs = await db.fetchall(sql, tuple(args))
    out = []
    for s in studs:
        certs = await db.fetchall("SELECT subject, grade FROM certificates WHERE student_id=? ORDER BY subject",
                                  (s["id"],))
        row = cert_student_out(s, certs)
        row["group_name"] = s["gname"] or "(guruh o'chirilgan)"
        out.append(row)
    return web.json_response({"students": out, "subjects": D.CERT_SUBJECTS, "grades": D.CERT_GRADES})


async def api_student_certificates_get(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        sid = int(request.match_info["sid"])
    except Exception:
        return bad("So'rov noto'g'ri")
    s = await _student_access(db, uid, role, sid)
    if not s:
        return bad("Topilmadi yoki ruxsat yo'q", 404)
    certs = await db.fetchall("SELECT subject, grade FROM certificates WHERE student_id=? ORDER BY subject", (sid,))
    return web.json_response({"certificates": [{"subject": c["subject"], "grade": c["grade"]} for c in certs],
                              "has_189": bool(s["has_189"]), "subjects": D.CERT_SUBJECTS, "grades": D.CERT_GRADES})


async def api_student_certificate_post(request):
    """body: {subject, grade} - grade bo'sh/yo'q bo'lsa sertifikat olib tashlanadi."""
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        sid = int(request.match_info["sid"])
        body = await request.json()
        subject = clean_text(body.get("subject"), 40)
        grade = clean_text(body.get("grade"), 4)
    except Exception:
        return bad("So'rov noto'g'ri")
    if subject not in D.CERT_SUBJECTS:
        return bad("Fan noto'g'ri")
    s = await _student_access(db, uid, role, sid)
    if not s:
        return bad("Topilmadi yoki ruxsat yo'q", 404)
    if not grade:
        await db.execute("DELETE FROM certificates WHERE student_id=? AND subject=?", (sid, subject))
    else:
        if grade not in D.CERT_GRADES:
            return bad("Daraja noto'g'ri")
        await db.execute(
            "INSERT INTO certificates(student_id, subject, grade) VALUES(?,?,?) "
            "ON CONFLICT(student_id, subject) DO UPDATE SET grade=excluded.grade", (sid, subject, grade))
    return web.json_response({"ok": True})


async def api_student_cert189_post(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        sid = int(request.match_info["sid"])
        body = await request.json()
        has = bool(body["has_189"])
    except Exception:
        return bad("So'rov noto'g'ri")
    s = await _student_access(db, uid, role, sid)
    if not s:
        return bad("Topilmadi yoki ruxsat yo'q", 404)
    await db.execute("UPDATE students SET has_189=? WHERE id=?", (int(has), sid))
    return web.json_response({"ok": True})


# ---------------- Xodimlar (faqat direktor): o'qituvchilar, adminlar, reyestr sozlamasi ----------------
def teacher_out(t):
    return {"id": t["tg_id"], "name": t["full_name"], "pay_type": t["pay_type"], "pay_value": t["pay_value"],
            "registry_rate": t["registry_rate"], "groups": t.get("groups", 0)}


async def api_teachers(request):
    uid, role, _ = await auth(request)
    if role != "director":
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    rows = await db.fetchall(
        "SELECT u.tg_id, u.full_name, t.pay_type, t.pay_value, t.registry_rate, "
        "(SELECT COUNT(*) FROM groups g WHERE g.teacher_id=u.tg_id) AS groups "
        "FROM users u JOIN teachers t ON t.tg_id=u.tg_id ORDER BY u.full_name")
    return web.json_response({"teachers": [teacher_out(r) for r in rows]})


async def api_teacher_post(request):
    uid, role, _ = await auth(request)
    if role != "director":
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    try:
        body = await request.json()
        tid = int(body["id"])
        name = clean_text(body.get("name"), 80)
        pay_type = body.get("pay_type")
        pay_value = float(body.get("pay_value"))
        reg_rate = int(body.get("registry_rate") or 0)
        assert pay_type in ("percent", "per_student") and pay_value > 0 and reg_rate >= 0
    except Exception:
        return bad("Ma'lumotlar noto'g'ri")
    if len(name) < 2:
        return bad("Ism familiyani to'liq kiriting")
    if await db.fetchone("SELECT 1 FROM users WHERE tg_id=?", (tid,)):
        return bad("Bu ID allaqachon ro'yxatda bor")
    await db.batch([
        ("INSERT INTO users(tg_id,full_name,role) VALUES(?,?,'teacher')", (tid, name)),
        ("INSERT INTO teachers(tg_id,pay_type,pay_value,registry_rate) VALUES(?,?,?,?)",
         (tid, pay_type, pay_value, reg_rate))])
    return web.json_response({"ok": True})


async def api_teacher_patch(request):
    uid, role, _ = await auth(request)
    if role != "director":
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    try:
        tid = int(request.match_info["tid"])
        body = await request.json()
    except Exception:
        return bad("So'rov noto'g'ri")
    t = await db.fetchone("SELECT * FROM teachers WHERE tg_id=?", (tid,))
    if not t:
        return bad("Topilmadi", 404)
    if "name" in body:
        name = clean_text(body["name"], 80)
        if len(name) < 2:
            return bad("Ism familiyani to'liq kiriting")
        await db.execute("UPDATE users SET full_name=? WHERE tg_id=?", (name, tid))
    if "pay_type" in body or "pay_value" in body:
        pt = body.get("pay_type", t["pay_type"])
        try:
            pv = float(body.get("pay_value", t["pay_value"]))
            assert pt in ("percent", "per_student") and pv > 0
        except Exception:
            return bad("Oylik qiymati noto'g'ri")
        await db.execute("UPDATE teachers SET pay_type=?, pay_value=? WHERE tg_id=?", (pt, pv, tid))
    if "registry_rate" in body:
        try:
            rr = int(body["registry_rate"])
            assert rr >= 0
        except Exception:
            return bad("Reyestr narxi noto'g'ri")
        await db.execute("UPDATE teachers SET registry_rate=? WHERE tg_id=?", (rr, tid))
    row = await db.fetchone(
        "SELECT u.tg_id, u.full_name, t.pay_type, t.pay_value, t.registry_rate, "
        "(SELECT COUNT(*) FROM groups g WHERE g.teacher_id=u.tg_id) AS groups "
        "FROM users u JOIN teachers t ON t.tg_id=u.tg_id WHERE u.tg_id=?", (tid,))
    return web.json_response({"ok": True, "teacher": teacher_out(row)})


async def api_teacher_delete(request):
    uid, role, _ = await auth(request)
    if role != "director":
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    try:
        tid = int(request.match_info["tid"])
    except Exception:
        return bad("So'rov noto'g'ri")
    t = await db.fetchone("SELECT full_name FROM users WHERE tg_id=? AND role='teacher'", (tid,))
    if not t:
        return bad("Topilmadi", 404)
    await db.batch([("UPDATE groups SET teacher_id=NULL WHERE teacher_id=?", (tid,)),
                    ("DELETE FROM teachers WHERE tg_id=?", (tid,)),
                    ("DELETE FROM users WHERE tg_id=?", (tid,))])
    return web.json_response({"ok": True})


async def api_admins(request):
    uid, role, _ = await auth(request)
    if role != "director":
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    rows = await db.fetchall("SELECT tg_id, full_name FROM users WHERE role='admin' ORDER BY full_name")
    return web.json_response({"admins": [{"id": r["tg_id"], "name": r["full_name"]} for r in rows]})


async def api_admin_post(request):
    uid, role, _ = await auth(request)
    if role != "director":
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    try:
        body = await request.json()
        aid = int(body["id"])
        name = clean_text(body.get("name"), 80)
    except Exception:
        return bad("Ma'lumotlar noto'g'ri")
    if len(name) < 2:
        return bad("Ism familiyani to'liq kiriting")
    if await db.fetchone("SELECT 1 FROM users WHERE tg_id=?", (aid,)):
        return bad("Bu ID allaqachon ro'yxatda bor")
    await db.execute("INSERT INTO users(tg_id,full_name,role) VALUES(?,?,'admin')", (aid, name))
    return web.json_response({"ok": True})


async def api_admin_delete(request):
    uid, role, _ = await auth(request)
    if role != "director":
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    try:
        aid = int(request.match_info["aid"])
    except Exception:
        return bad("So'rov noto'g'ri")
    a = await db.fetchone("SELECT full_name FROM users WHERE tg_id=? AND role='admin'", (aid,))
    if not a:
        return bad("Topilmadi", 404)
    await db.execute("DELETE FROM users WHERE tg_id=? AND role='admin'", (aid,))
    return web.json_response({"ok": True})


async def api_registry_get(request):
    uid, role, _ = await auth(request)
    if role != "director":
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    r = await db.fetchone("SELECT COUNT(*) n, COALESCE(SUM(hidden),0) h FROM students WHERE is_registry=1 AND archived=0")
    hidden = await D.get_setting(db, "registry_hidden") == "1"
    return web.json_response({"total": r["n"], "hidden_count": r["h"], "hidden_mode": hidden})


async def api_registry_post(request):
    uid, role, _ = await auth(request)
    if role != "director":
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    try:
        body = await request.json()
        hide = bool(body["hide"])
    except Exception:
        return bad("So'rov noto'g'ri")
    await db.batch([("UPDATE students SET hidden=? WHERE is_registry=1 AND archived=0", (int(hide),)),
                    ("INSERT INTO settings(key,value) VALUES('registry_hidden',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("1" if hide else "0",))])
    return web.json_response({"ok": True})


# ---------------- Guruhni boshqarish (o'qituvchi almashtirish, o'chirish) ----------------
async def api_group_patch(request):
    uid, role, _ = await auth(request)
    if role not in ("admin", "director"):
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    try:
        gid = int(request.match_info["gid"])
        body = await request.json()
    except Exception:
        return bad("So'rov noto'g'ri")
    g = await db.fetchone("SELECT * FROM groups WHERE id=?", (gid,))
    if not g:
        return bad("Topilmadi", 404)
    if "teacher" in body:
        tid = body["teacher"]
        tid = int(tid) if tid else None
        if tid and not await db.fetchone("SELECT 1 FROM teachers WHERE tg_id=?", (tid,)):
            return bad("O'qituvchi topilmadi")
        await db.execute("UPDATE groups SET teacher_id=? WHERE id=?", (tid, gid))
    if "name" in body:
        name = clean_text(body["name"], 40)
        if not name:
            return bad("Guruh nomini kiriting")
        if await db.fetchone("SELECT 1 FROM groups WHERE name=? AND id<>?", (name, gid)):
            return bad("Bunday nomli guruh bor")
        await db.execute("UPDATE groups SET name=? WHERE id=?", (name, gid))
    if "lesson_days" in body:
        days = body["lesson_days"] or ""
        if not all(d in "1234567" for d in days.replace(",", "")):
            return bad("Dars kunlari noto'g'ri")
        await db.execute("UPDATE groups SET lesson_days=? WHERE id=?", (days, gid))
    if "lesson_time" in body:
        t = (body["lesson_time"] or "").strip()
        if t:
            try:
                hh, mm = t.split(":")
                assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60
                t = f"{int(hh):02d}:{int(mm):02d}"
            except Exception:
                return bad("Dars vaqti noto'g'ri (masalan 15:00)")
        await db.execute("UPDATE groups SET lesson_time=? WHERE id=?", (t, gid))
    return web.json_response({"ok": True})


async def api_group_delete(request):
    uid, role, _ = await auth(request)
    if role not in ("admin", "director"):
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    try:
        gid = int(request.match_info["gid"])
    except Exception:
        return bad("So'rov noto'g'ri")
    g = await db.fetchone("SELECT name FROM groups WHERE id=?", (gid,))
    if not g:
        return bad("Topilmadi", 404)
    await D.archive_or_delete_group_students(db, gid)
    await db.execute("DELETE FROM groups WHERE id=?", (gid,))
    return web.json_response({"ok": True})


# ---------------- Excel eksport ----------------
async def api_export(request):
    uid, role, _ = await auth(request)
    if role not in ("admin", "director"):
        return bad("Ruxsat yo'q", 403)
    db = request.app["db"]
    from .extras import _sheet, _students_rows, STUD_HEAD
    from openpyxl import Workbook
    kind = request.query.get("type")
    mo = request.query.get("month") or D.current_month()
    wb = Workbook()
    if kind in ("debtors", "students"):
        debt = kind == "debtors"
        _sheet(wb, "Qarzdorlar" if debt else "O'quvchilar", STUD_HEAD, await _students_rows(db, mo, debt), True)
        fname = f"{'qarzdorlar' if debt else 'oquvchilar'}_{mo}.xlsx"
    elif kind == "report":
        grows = []
        for g in await db.fetchall("SELECT * FROM groups ORDER BY name"):
            studs = await D.group_students(db, g["id"], mo)
            reg = sum(1 for s in studs if s["is_registry"])
            paid = sum(1 for s in studs if s["paid"]) - reg
            grows.append([g["name"], await D.group_income(db, g["id"], mo), paid, reg, len(studs) - paid - reg])
        _sheet(wb, "Guruhlar", ["Guruh", "Tushum", "To'laganlar", "Reyestr", "Qarzdorlar"], grows, True)
        trows = []
        for t in await db.fetchall("SELECT u.tg_id, u.full_name FROM users u JOIN teachers t ON t.tg_id=u.tg_id "
                                   "ORDER BY u.full_name"):
            pt, pv, _, total = await D.teacher_salary(db, t["tg_id"], mo)
            trows.append([t["full_name"], "Foiz" if pt == "percent" else "O'quvchi boshiga", pv, round(total)])
        _sheet(wb, "Oyliklar", ["O'qituvchi", "Turi", "Qiymat", "Oylik"], trows)
        _sheet(wb, "O'quvchilar", STUD_HEAD, await _students_rows(db, mo, False))
        fname = f"hisobot_{mo}.xlsx"
    else:
        return bad("Noto'g'ri turi")
    buf = io.BytesIO()
    wb.save(buf)
    return web.Response(body=buf.getvalue(),
                        headers={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 "Content-Disposition": f'attachment; filename="{fname}"'})


# ---------------- Bildirishnomalar ----------------
WD_MAP = {"1": "Du", "2": "Se", "3": "Ch", "4": "Pa", "5": "Ju", "6": "Sh", "7": "Ya"}


async def api_notifications(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    staff = role in ("admin", "director")
    today = D.today_local()
    today_iso = today.isoformat()
    wd = str(today.isoweekday())
    items = []

    if staff:
        groups = await db.fetchall("SELECT g.*, u.full_name AS tname FROM groups g "
                                   "LEFT JOIN users u ON u.tg_id=g.teacher_id ORDER BY g.name")
    else:
        groups = await db.fetchall("SELECT * FROM groups WHERE teacher_id=? ORDER BY name", (uid,))

    taken_today = {r["group_id"] for r in await db.fetchall(
        "SELECT DISTINCT group_id FROM attendance WHERE day=?", (today_iso,))}
    paid_ids = {r["student_id"] for r in await db.fetchall(
        "SELECT DISTINCT student_id FROM payments WHERE month=?", (D.current_month(),))}
    debt_counts = await debtor_counts_by_group(db, paid_ids)

    for g in groups:
        if g["lesson_days"] and wd in g["lesson_days"].split(",") and g["id"] not in taken_today:
            items.append({"kind": "no_attendance", "icon": "⏰", "group": g["id"], "group_name": g["name"],
                         "text": f"{g['name']}: bugungi dars ({g['lesson_time'] or '-'}) davomati hali olinmagan"})
        n = debt_counts.get(g["id"], 0)
        if n:
            items.append({"kind": "debtors", "icon": "❌", "group": g["id"], "group_name": g["name"],
                         "text": f"{g['name']}: {n} ta qarzdor"})

    if staff:
        for t in await db.fetchall(
                "SELECT u.full_name, t.tg_id, t.registry_rate, "
                "(SELECT COUNT(*) FROM students s JOIN groups g ON g.id=s.group_id "
                " WHERE g.teacher_id=t.tg_id AND s.is_registry=1 AND s.hidden=0) AS n "
                "FROM teachers t JOIN users u ON u.tg_id=t.tg_id"):
            if t["n"] and not t["registry_rate"]:
                items.append({"kind": "no_price", "icon": "⚠️", "group": None, "teacher": t["tg_id"],
                             "text": f"{t['full_name']}: reyestr o'quvchilari bor, lekin dars narxi kiritilmagan"})

    order = {"no_price": 0, "no_attendance": 1, "debtors": 2}
    items.sort(key=lambda x: order.get(x["kind"], 9))
    return web.json_response({"items": items, "count": len(items)})


# ---------------- Ota-ona (faqat ko'rish) ----------------
async def api_parent_link_post(request):
    uid, role, _ = await auth(request)
    db = request.app["db"]
    try:
        sid = int(request.match_info["sid"])
    except Exception:
        return bad("So'rov noto'g'ri")
    s = await db.fetchone("SELECT last_name, first_name, phone, group_id FROM students WHERE id=?", (sid,))
    if not s or not await can_access(db, uid, role, s["group_id"]):
        return bad("Topilmadi yoki ruxsat yo'q", 404)
    from . import config as CFG
    from .ptoken import make
    if not CFG.BOT_USERNAME:
        return bad("Bot nomi hali aniqlanmadi, birozdan keyin urinib ko'ring")
    return web.json_response({"url": f"https://t.me/{CFG.BOT_USERNAME}?start={make(sid)}", "phone": s["phone"],
                              "name": f"{s['last_name']} {s['first_name']}"})


async def api_parent_me(request):
    uid = await auth_any(request)
    db = request.app["db"]
    rows = await db.fetchall(
        "SELECT s.*, g.name AS gname, g.id AS gid, u.full_name AS tname FROM parent_links pl "
        "JOIN students s ON s.id=pl.student_id JOIN groups g ON g.id=s.group_id "
        "LEFT JOIN users u ON u.tg_id=g.teacher_id WHERE pl.parent_tg_id=? ORDER BY s.last_name", (uid,))
    if not rows:
        return web.json_response({"linked": False})
    mo = D.current_month()
    children = []
    for s in rows:
        paid = await db.fetchone("SELECT COALESCE(SUM(amount),0) t, COUNT(*) n FROM payments "
                                 "WHERE student_id=? AND month=?", (s["id"], mo))
        days, hist = await A.history(db, s["gid"], n=8)
        mine = hist.get(s["id"], {})
        exams = await db.fetchall(
            "SELECT e.title, e.max_score, e.day, es.score FROM exam_scores es "
            "JOIN exams e ON e.id=es.exam_id WHERE es.student_id=? ORDER BY e.day DESC, e.id DESC LIMIT 5",
            (s["id"],))
        children.append({
            "id": s["id"], "name": f"{s['last_name']} {s['first_name']}", "grade": s["grade"],
            "group": s["gname"], "teacher": s["tname"], "is_registry": bool(s["is_registry"]),
            "paid": bool(s["is_registry"]) or paid["n"] > 0, "paid_sum": paid["t"], "month": mo,
            "history": [{"day": d, "status": mine.get(d, "")} for d in days],
            "exams": [dict(x) for x in exams]})
    return web.json_response({"linked": True, "children": children})


def create_app(db, bot=None) -> web.Application:
    app = web.Application(middlewares=[errors_mw])
    app["db"] = db
    app["bot"] = bot
    app.router.add_get("/", health)
    app.router.add_get("/app", index)
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/attendance", api_attendance_get)
    app.router.add_post("/api/attendance", api_attendance_post)
    app.router.add_get("/api/dashboard", api_dashboard)
    app.router.add_get("/api/groups", api_groups)
    app.router.add_post("/api/groups", api_groups_post)
    app.router.add_get("/api/students", api_students_get)
    app.router.add_post("/api/students", api_students_post)
    app.router.add_patch("/api/students/{sid}", api_student_patch)
    app.router.add_delete("/api/students/{sid}", api_student_delete)
    app.router.add_post("/api/payments", api_payment_post)
    app.router.add_get("/api/payments", api_payments_get)
    app.router.add_delete("/api/payments/{pid}", api_payment_delete)
    app.router.add_get("/api/salary", api_salary)
    app.router.add_get("/api/teachers", api_teachers)
    app.router.add_post("/api/teachers", api_teacher_post)
    app.router.add_patch("/api/teachers/{tid}", api_teacher_patch)
    app.router.add_delete("/api/teachers/{tid}", api_teacher_delete)
    app.router.add_get("/api/admins", api_admins)
    app.router.add_post("/api/admins", api_admin_post)
    app.router.add_delete("/api/admins/{aid}", api_admin_delete)
    app.router.add_get("/api/registry", api_registry_get)
    app.router.add_post("/api/registry", api_registry_post)
    app.router.add_patch("/api/groups/{gid}", api_group_patch)
    app.router.add_delete("/api/groups/{gid}", api_group_delete)
    app.router.add_get("/api/export", api_export)
    app.router.add_get("/api/notifications", api_notifications)
    app.router.add_get("/api/exams", api_exams_get)
    app.router.add_post("/api/exams", api_exam_post)
    app.router.add_get("/api/exams/{eid}", api_exam_get)
    app.router.add_post("/api/exams/{eid}/scores", api_exam_scores_post)
    app.router.add_delete("/api/exams/{eid}", api_exam_delete)
    app.router.add_get("/api/students/{sid}/exams", api_student_exams_get)
    app.router.add_get("/api/certificates", api_certificates_get)
    app.router.add_get("/api/certificates/graduated", api_certificates_graduated)
    app.router.add_get("/api/students/{sid}/certificates", api_student_certificates_get)
    app.router.add_post("/api/students/{sid}/certificates", api_student_certificate_post)
    app.router.add_post("/api/students/{sid}/cert189", api_student_cert189_post)
    app.router.add_post("/api/students/{sid}/parent-link", api_parent_link_post)
    app.router.add_get("/parent", parent_index)
    app.router.add_get("/api/parent/me", api_parent_me)
    return app


async def start_server(db, bot, port: int):
    runner = web.AppRunner(create_app(db, bot))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Veb-server %s portda ishga tushdi", port)
    return runner
