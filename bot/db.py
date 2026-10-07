import asyncio
import base64
from datetime import date

import aiohttp
import aiosqlite

from .config import DB_PATH, DIRECTOR_IDS, TURSO_URL, TURSO_TOKEN

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
CREATE INDEX IF NOT EXISTS idx_payments_student_month ON payments(student_id, month);
CREATE INDEX IF NOT EXISTS idx_payments_group_month ON payments(group_id, month);
CREATE TABLE IF NOT EXISTS attendance(
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL,
    day TEXT NOT NULL, student_id INTEGER NOT NULL, present INTEGER NOT NULL,
    UNIQUE(group_id, day, student_id));
CREATE TABLE IF NOT EXISTS notices(key TEXT PRIMARY KEY);
"""


class Database:
    """Ikki backend uchun umumiy interfeys: lokal SQLite yoki Turso (libSQL, HTTP)."""

    async def execute(self, sql, args=()):
        await self.batch([(sql, args)])

    async def fetchall(self, sql, args=()) -> list:
        raise NotImplementedError

    async def fetchone(self, sql, args=()):
        rows = await self.fetchall(sql, args)
        return rows[0] if rows else None

    async def batch(self, stmts):
        """Bir nechta so'rovni bitta tranzaksiyada bajaradi (xato bo'lsa hammasi bekor)."""
        raise NotImplementedError

    async def commit(self):  # eski chaqiruvlar bilan moslik; har so'rov o'zi saqlanadi
        pass

    async def init_schema(self):
        stmts = [x.strip() for x in SCHEMA.split(";") if x.strip()]
        await self.batch([(x, ()) for x in stmts])

    async def close(self):
        pass


class SqliteDB(Database):
    def __init__(self, conn):
        self.conn = conn
        self.lock = asyncio.Lock()

    @classmethod
    async def open(cls, path):
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        return cls(conn)

    async def fetchall(self, sql, args=()):
        async with self.conn.execute(sql, tuple(args)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def batch(self, stmts):
        async with self.lock:
            try:
                for sql, args in stmts:
                    await self.conn.execute(sql, tuple(args))
                await self.conn.commit()
            except Exception:
                await self.conn.rollback()
                raise

    async def close(self):
        await self.conn.close()


def _enc(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, bytes):
        return {"type": "blob", "base64": base64.b64encode(v).decode()}
    return {"type": "text", "value": str(v)}


def _dec(c):
    t = c["type"]
    if t == "null":
        return None
    if t == "integer":
        return int(c["value"])
    if t == "float":
        return float(c["value"])
    if t == "blob":
        return base64.b64decode(c["base64"])
    return c["value"]


class TursoDB(Database):
    """Turso HTTP API (/v2/pipeline) - qo'shimcha kutubxona kerak emas."""

    def __init__(self, url, token):
        url = url.strip().rstrip("/")
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        self.endpoint = url + "/v2/pipeline"
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))

    async def _pipeline(self, requests):
        body = {"requests": requests + [{"type": "close"}]}
        last = None
        for attempt in range(3):
            try:
                async with self.session.post(self.endpoint, json=body, headers=self.headers) as r:
                    if r.status >= 500:
                        raise aiohttp.ClientError(f"Turso HTTP {r.status}")
                    data = await r.json(content_type=None)
                    if r.status != 200:
                        raise RuntimeError(f"Turso HTTP {r.status}: {data}")
                break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last = e
                await asyncio.sleep(1 + attempt)
        else:
            raise RuntimeError(f"Turso bilan aloqa yo'q: {last}")
        results = data["results"]
        for res in results:
            if res["type"] == "error":
                raise RuntimeError(f"Turso xatosi: {res['error'].get('message')}")
        return results

    @staticmethod
    def _stmt(sql, args):
        return {"type": "execute", "stmt": {"sql": sql, "args": [_enc(a) for a in args]}}

    async def fetchall(self, sql, args=()):
        res = await self._pipeline([self._stmt(sql, args)])
        result = res[0]["response"]["result"]
        cols = [c["name"] for c in result["cols"]]
        return [dict(zip(cols, (_dec(c) for c in row))) for row in result["rows"]]

    async def batch(self, stmts):
        reqs = [self._stmt("BEGIN", ())] + [self._stmt(s, a) for s, a in stmts] + \
               [self._stmt("COMMIT", ())]
        await self._pipeline(reqs)  # xatoda stream yopiladi -> tranzaksiya bekor

    async def close(self):
        await self.session.close()


def current_month() -> str:
    return date.today().strftime("%Y-%m")


async def connect() -> Database:
    db = TursoDB(TURSO_URL, TURSO_TOKEN) if TURSO_URL else await SqliteDB.open(DB_PATH)
    await db.init_schema()
    for d in DIRECTOR_IDS:
        await db.execute(
            "INSERT INTO users(tg_id, full_name, role) VALUES(?,?,'director') "
            "ON CONFLICT(tg_id) DO UPDATE SET role='director'", (d, "Direktor"))
    return db


async def fetchall(db, sql, args=()):
    return await db.fetchall(sql, args)


async def fetchone(db, sql, args=()):
    return await db.fetchone(sql, args)


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
