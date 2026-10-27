"""Telegram Mini App uchun veb-server: davomat sahifasi va direktor paneli.

Autentifikatsiya: Telegram WebApp initData imzosi (BOT_TOKEN bilan HMAC) tekshiriladi,
rol bazadan olinadi. Hech qanday parol yoki alohida login yo'q.
"""
import asyncio
import hashlib
import hmac
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


async def can_access(db, uid, role, gid) -> bool:
    return await can_access_group(db, uid, gid)


def bad(msg, status=400):
    return web.json_response({"error": msg}, status=status)


# ---------------- sahifa ----------------
async def index(request):
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


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
    days, hist = await A.history(db, gid, before=day.isoformat(), n=10)
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
        groups = await db.fetchall("SELECT id, name FROM groups WHERE teacher_id=? ORDER BY name", (uid,))
    else:
        groups = await db.fetchall("SELECT g.id, g.name, u.full_name AS teacher FROM groups g "
                                   "LEFT JOIN users u ON u.tg_id=g.teacher_id ORDER BY g.name")
    counts = {r["group_id"]: r["n"] for r in await db.fetchall(
        "SELECT group_id, COUNT(*) n FROM students WHERE hidden=0 GROUP BY group_id")}
    out = {"groups": [{**dict(g), "students": counts.get(g["id"], 0)} for g in groups]}
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
    await db.execute("DELETE FROM students WHERE id=?", (sid,))
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
    await db.execute("INSERT INTO payments(student_id,group_id,amount,month) VALUES(?,?,?,?)",
                     (sid, s["group_id"], amount, D.current_month()))
    return web.json_response({"ok": True})


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
    return app


async def start_server(db, bot, port: int):
    runner = web.AppRunner(create_app(db, bot))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Veb-server %s portda ishga tushdi", port)
    return runner
