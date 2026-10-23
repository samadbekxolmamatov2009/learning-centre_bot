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
    g = await db.fetchone("SELECT teacher_id FROM groups WHERE id=?", (gid,))
    return bool(g) and (role in ("admin", "director") or g["teacher_id"] == uid)


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
    return app


async def start_server(db, bot, port: int):
    runner = web.AppRunner(create_app(db, bot))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Veb-server %s portda ishga tushdi", port)
    return runner
