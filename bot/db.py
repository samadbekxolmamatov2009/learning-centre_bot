import aiosqlite
from datetime import date

from .config import DB_PATH, DIRECTOR_IDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    tg_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('director','admin','teacher')));
CREATE TABLE IF NOT EXISTS teachers(
    tg_id INTEGER PRIMARY KEY REFERENCES users(tg_id),
    pay_type TEXT NOT NULL CHECK(pay_type IN ('percent','per_student')),
    pay_value REAL NOT NULL);
CREATE TABLE IF NOT EXISTS groups(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
    teacher_id INTEGER REFERENCES teachers(tg_id));
CREATE TABLE IF NOT EXISTS students(
    id INTEGER PRIMARY KEY AUTOINCREMENT, first_name TEXT NOT NULL,
    last_name TEXT NOT NULL, grade TEXT NOT NULL,
    group_id INTEGER NOT NULL REFERENCES groups(id));
CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    group_id INTEGER NOT NULL, amount INTEGER NOT NULL,
    month TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS attendance(
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL,
    day TEXT NOT NULL, student_id INTEGER NOT NULL, present INTEGER NOT NULL,
    UNIQUE(group_id, day, student_id));
"""


def current_month() -> str:
    return date.today().strftime("%Y-%m")


async def connect():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA)
    for d in DIRECTOR_IDS:
        await db.execute(
            "INSERT INTO users(tg_id, full_name, role) VALUES(?,?,'director') "
            "ON CONFLICT(tg_id) DO UPDATE SET role='director'", (d, "Direktor"))
    await db.commit()
    return db


async def fetchall(db, sql, args=()):
    async with db.execute(sql, args) as cur:
        return await cur.fetchall()


async def fetchone(db, sql, args=()):
    async with db.execute(sql, args) as cur:
        return await cur.fetchone()


async def get_role(db, tg_id):
    row = await fetchone(db, "SELECT role FROM users WHERE tg_id=?", (tg_id,))
    return row["role"] if row else None


async def group_students(db, group_id, month=None):
    """Guruh o'quvchilari; paid = shu oyda to'lov kiritilganmi (summasi qanday bo'lishidan qat'iy nazar)."""
    month = month or current_month()
    return await fetchall(db, """
        SELECT s.*, COALESCE(SUM(p.amount),0) AS paid_sum,
               COUNT(p.id) > 0 AS paid
        FROM students s LEFT JOIN payments p
             ON p.student_id=s.id AND p.month=?
        WHERE s.group_id=? GROUP BY s.id ORDER BY s.last_name, s.first_name
    """, (month, group_id))


async def group_income(db, group_id, month=None):
    month = month or current_month()
    row = await fetchone(db, "SELECT COALESCE(SUM(amount),0) t FROM payments "
                             "WHERE group_id=? AND month=?", (group_id, month))
    return row["t"]


async def teacher_salary(db, teacher_id, month=None):
    """Return (pay_type, pay_value, [(group, income, paid_count)], salary)."""
    month = month or current_month()
    t = await fetchone(db, "SELECT * FROM teachers WHERE tg_id=?", (teacher_id,))
    if not t:
        return None
    rows, total = [], 0.0
    for g in await fetchall(db, "SELECT * FROM groups WHERE teacher_id=?", (teacher_id,)):
        income = await group_income(db, g["id"], month)
        paid_cnt = sum(1 for s in await group_students(db, g["id"], month) if s["paid"])
        rows.append((g["name"], income, paid_cnt))
        total += income * t["pay_value"] / 100 if t["pay_type"] == "percent" \
            else paid_cnt * t["pay_value"]
    return t["pay_type"], t["pay_value"], rows, total
