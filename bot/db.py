import asyncio
import base64
import re
from datetime import date, datetime, timedelta, timezone

import aiohttp
import aiosqlite

from .config import DB_PATH, DIRECTOR_IDS, TURSO_URL, TURSO_TOKEN, TZ_OFFSET

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    tg_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('director','admin','teacher')),
    branch_id INTEGER REFERENCES branches(id));
CREATE TABLE IF NOT EXISTS teachers(
    tg_id INTEGER PRIMARY KEY REFERENCES users(tg_id),
    pay_type TEXT NOT NULL CHECK(pay_type IN ('percent','per_student')),
    pay_value REAL NOT NULL,
    registry_rate INTEGER NOT NULL DEFAULT 0,
    low_pay_percent INTEGER NOT NULL DEFAULT 40);
CREATE TABLE IF NOT EXISTS branches(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS groups(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
    teacher_id INTEGER REFERENCES teachers(tg_id), branch_id INTEGER REFERENCES branches(id),
    lesson_days TEXT NOT NULL DEFAULT '', lesson_time TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS students(
    id INTEGER PRIMARY KEY AUTOINCREMENT, first_name TEXT NOT NULL,
    last_name TEXT NOT NULL, grade TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
    is_registry INTEGER NOT NULL DEFAULT 0, reg_rate INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
    has_189 INTEGER NOT NULL DEFAULT 0,
    group_id INTEGER NOT NULL REFERENCES groups(id));
CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL, amount INTEGER NOT NULL,
    month TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_payments_student_month ON payments(student_id, month);
CREATE INDEX IF NOT EXISTS idx_payments_group_month ON payments(group_id, month);
CREATE TABLE IF NOT EXISTS attendance(
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL,
    day TEXT NOT NULL, student_id INTEGER NOT NULL, present INTEGER NOT NULL,
    rate INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT '',
    UNIQUE(group_id, day, student_id));
CREATE TABLE IF NOT EXISTS notices(key TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS parent_links(
    id INTEGER PRIMARY KEY AUTOINCREMENT, parent_tg_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(parent_tg_id, student_id));
CREATE TABLE IF NOT EXISTS parent_blocks(
    parent_tg_id INTEGER NOT NULL, student_id INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(parent_tg_id, student_id));
CREATE TABLE IF NOT EXISTS exams(
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL,
    title TEXT NOT NULL, max_score INTEGER NOT NULL, day TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS exam_scores(
    id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL, score REAL NOT NULL, grade TEXT NOT NULL DEFAULT '',
    UNIQUE(exam_id, student_id));
CREATE INDEX IF NOT EXISTS idx_exams_group ON exams(group_id);
CREATE INDEX IF NOT EXISTS idx_exam_scores_student ON exam_scores(student_id);
CREATE TABLE IF NOT EXISTS certificates(
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
    subject TEXT NOT NULL, grade TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, subject));
CREATE INDEX IF NOT EXISTS idx_certificates_student ON certificates(student_id);
CREATE TABLE IF NOT EXISTS leads(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL, last_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '', grade TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '', branch_id INTEGER REFERENCES branches(id),
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','contacted','trial','won','lost')),
    lost_reason TEXT NOT NULL DEFAULT '', trial_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, decided_at TEXT);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE TABLE IF NOT EXISTS advances(
    id INTEGER PRIMARY KEY AUTOINCREMENT, teacher_id INTEGER NOT NULL,
    amount INTEGER NOT NULL, month TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_advances_teacher_month ON advances(teacher_id, month);
"""

LEAD_STATUS_LABELS = {"new": "🆕 Yangi", "contacted": "📞 Bog'lanildi", "trial": "🎓 Sinov darsida",
                      "won": "🎉 O'quvchi bo'ldi", "lost": "❌ Voz kechdi"}
LEAD_OPEN_STATUSES = ("new", "contacted", "trial")
LEAD_NEXT_STATUS = {"new": "contacted", "contacted": "trial"}
LEAD_STALE_DAYS = 5

CERT_SUBJECTS = ["Matematika", "Fizika", "Kimyo", "Biologiya", "Ona tili va adabiyot",
                 "Ingliz tili", "Rus tili", "Tarix", "Geografiya", "Informatika"]
CERT_GRADES = ["A+", "A", "B+", "B", "C+", "C"]


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
        cols = [r["name"] for r in await self.fetchall("PRAGMA table_info(students)")]
        # To'lovlar o'quvchi o'chirilgandan keyin ham saqlanadi (tushum/oylik hisobi uchun),
        # shuning uchun payments.student_id da FOREIGN KEY bo'lmasligi kerak.
        if await self.fetchall("PRAGMA foreign_key_list(payments)"):
            await self.batch([
                ("DROP TABLE IF EXISTS payments_new", ()),
                ("CREATE TABLE payments_new(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "student_id INTEGER NOT NULL, group_id INTEGER NOT NULL, amount INTEGER NOT NULL, "
                 "month TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)", ()),
                ("INSERT INTO payments_new(id,student_id,group_id,amount,month,created_at) "
                 "SELECT id,student_id,group_id,amount,month,created_at FROM payments", ()),
                ("DROP TABLE payments", ()),
                ("ALTER TABLE payments_new RENAME TO payments", ()),
                ("CREATE INDEX IF NOT EXISTS idx_payments_student_month ON payments(student_id, month)", ()),
                ("CREATE INDEX IF NOT EXISTS idx_payments_group_month ON payments(group_id, month)", ())])
        for col, ddl in (("is_registry", "INTEGER NOT NULL DEFAULT 0"), ("reg_rate", "INTEGER NOT NULL DEFAULT 0"),
                         ("hidden", "INTEGER NOT NULL DEFAULT 0")):
            if col not in cols:
                await self.execute(f"ALTER TABLE students ADD COLUMN {col} {ddl}")
        tcols = [r["name"] for r in await self.fetchall("PRAGMA table_info(teachers)")]
        if "registry_rate" not in tcols:
            await self.execute("ALTER TABLE teachers ADD COLUMN registry_rate INTEGER NOT NULL DEFAULT 0")
        if "low_pay_percent" not in tcols:
            await self.execute(f"ALTER TABLE teachers ADD COLUMN low_pay_percent INTEGER NOT NULL DEFAULT {LOW_PAY_PERCENT}")
        ucols = [r["name"] for r in await self.fetchall("PRAGMA table_info(users)")]
        if "branch_id" not in ucols:
            await self.execute("ALTER TABLE users ADD COLUMN branch_id INTEGER")
        acols = [r["name"] for r in await self.fetchall("PRAGMA table_info(attendance)")]
        if "status" not in acols:
            await self.execute("ALTER TABLE attendance ADD COLUMN status TEXT NOT NULL DEFAULT ''")
        gcols = [r["name"] for r in await self.fetchall("PRAGMA table_info(groups)")]
        for col in ("lesson_days", "lesson_time"):
            if col not in gcols:
                await self.execute(f"ALTER TABLE groups ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        if "branch_id" not in gcols:
            await self.execute("ALTER TABLE groups ADD COLUMN branch_id INTEGER")
        if "archived" not in gcols:
            await self.execute("ALTER TABLE groups ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        lcols = [r["name"] for r in await self.fetchall("PRAGMA table_info(leads)")]
        if "trial_at" not in lcols:
            await self.execute("ALTER TABLE leads ADD COLUMN trial_at TEXT")
        if "rate" not in acols:
            await self.execute("ALTER TABLE attendance ADD COLUMN rate INTEGER NOT NULL DEFAULT 0")
        if "phone" not in cols:  # eski bazani yangilash
            await self.execute("ALTER TABLE students ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
        for col in ("archived", "has_189"):
            if col not in cols:
                await self.execute(f"ALTER TABLE students ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
        escols = [r["name"] for r in await self.fetchall("PRAGMA table_info(exam_scores)")]
        if "grade" not in escols:
            await self.execute("ALTER TABLE exam_scores ADD COLUMN grade TEXT NOT NULL DEFAULT ''")

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
        await conn.execute("PRAGMA foreign_keys=ON")  # Turso kabi
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


def now_local() -> datetime:
    """Toshkent vaqti (server UTC da bo'lsa ham)."""
    return datetime.now(timezone(timedelta(hours=TZ_OFFSET)))


def today_local() -> date:
    return now_local().date()


def current_month() -> str:
    return today_local().strftime("%Y-%m")


GRADE_SUGGESTED_PAY = {
    "11": 600000, "10": 550000, "9": 500000, "8": 450000,
    "7": 450000, "6": 400000, "5": 400000,
}


def suggested_payment(grade):
    """O'quvchi sinfiga qarab tavsiya etilgan to'lov summasi (5-11 sinflar uchun). Boshqa
    sinflar (yoki noma'lum format) uchun None qaytaradi - tavsiya ko'rsatilmaydi."""
    m = re.match(r"\s*(\d+)", str(grade or ""))
    return GRADE_SUGGESTED_PAY.get(m.group(1)) if m else None


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


async def admin_branch_scope(db, uid, role):
    """Agar 'admin' roli bitta filialga biriktirilgan bo'lsa, shu filial ID'sini qaytaradi -
    o'sha admin faqat shu filial ma'lumotlarini ko'rishi/boshqarishi kerak. Direktor va
    filialga biriktirilmagan (ixtiyoriy) admin uchun None (cheklovsiz, hammasini ko'radi)."""
    if role != "admin":
        return None
    row = await fetchone(db, "SELECT branch_id FROM users WHERE tg_id=?", (uid,))
    return row["branch_id"] if row else None


async def group_students(db, group_id, month=None):
    """Guruh o'quvchilari; paid = shu oyda to'lov kiritilganmi (summasi qanday bo'lishidan qat'iy nazar).
    Reyestr o'quvchilari (davlat to'laydi) hech qachon qarzdor emas, shuning uchun paid=1."""
    month = month or current_month()
    return await fetchall(db, """
        SELECT s.*, COALESCE(SUM(p.amount),0) AS paid_sum,
               (COUNT(p.id) > 0 OR s.is_registry = 1) AS paid,
               (SELECT COUNT(*) FROM parent_links pl WHERE pl.student_id = s.id) AS parent_count
        FROM students s LEFT JOIN payments p
             ON p.student_id=s.id AND p.month=?
        WHERE s.group_id=? AND s.hidden=0 GROUP BY s.id ORDER BY s.last_name, s.first_name
    """, (month, group_id))


async def archive_or_delete_student(db, sid):
    """O'quvchini o'chiradi - lekin agar unda sertifikat yoki 189 ball belgisi bo'lsa,
    butunlay o'chirilmaydi, balki yashirin/arxivlangan holatda saqlanadi
    (yil oxirida sertifikatlar bo'yicha hisob-kitob uchun)."""
    s = await fetchone(db, "SELECT has_189 FROM students WHERE id=?", (sid,))
    if not s:
        return
    has_cert = await fetchone(db, "SELECT 1 FROM certificates WHERE student_id=?", (sid,))
    if s["has_189"] or has_cert:
        await db.execute("UPDATE students SET archived=1, hidden=1 WHERE id=?", (sid,))
    else:
        await db.execute("DELETE FROM students WHERE id=?", (sid,))


async def archive_or_delete_group_students(db, group_id):
    for r in await fetchall(db, "SELECT id FROM students WHERE group_id=?", (group_id,)):
        await archive_or_delete_student(db, r["id"])


def parse_lead_date(text):
    """Lid uchun sinov darsi sanasini tekshiradi (YYYY-MM-DD). Bo'sh/'-' -> "" (tozalash),
    noto'g'ri format -> None (xato)."""
    t = (text or "").strip()
    if not t or t == "-":
        return ""
    try:
        date.fromisoformat(t)
    except ValueError:
        return None
    return t


async def leads_trial_today(db):
    """Bugun sinov darsi rejalashtirilgan, hali ochiq (status='trial') lidlar."""
    today = today_local().isoformat()
    return await fetchall(db, "SELECT * FROM leads WHERE status='trial' AND trial_at=? ORDER BY id", (today,))


async def lead_stats(db, branch_id=None):
    """Manba bo'yicha konversiya (jami/o'quvchi bo'lgan) va voz kechish sabablari bo'yicha hisob.
    branch_id berilsa, faqat shu filialga tegishli (yoki filialsiz) lidlar hisobga olinadi."""
    bcond = " AND (branch_id=? OR branch_id IS NULL)" if branch_id else ""
    bargs = (branch_id,) if branch_id else ()
    sources = await fetchall(db, f"""
        SELECT COALESCE(NULLIF(source,''),'(manba kiritilmagan)') AS source, COUNT(*) AS total,
               SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) AS won
        FROM leads WHERE 1=1{bcond} GROUP BY source ORDER BY total DESC""", bargs)
    reasons = await fetchall(db, f"""
        SELECT COALESCE(NULLIF(lost_reason,''),'(sabab yozilmagan)') AS reason, COUNT(*) AS n
        FROM leads WHERE status='lost'{bcond} GROUP BY reason ORDER BY n DESC""", bargs)
    return sources, reasons


async def stale_leads(db):
    """Hali qaror qilinmagan (yangi/bog'lanildi/sinov darsida) lidlardan qaysilari eslatmaga tushishi kerak:
    - sinov darsi sanasi (trial_at) belgilangan bo'lsa - LEAD_STALE_DAYS kutilmaydi, sinov darsi kuni
      check_trial_today orqali alohida eslatiladi, shu sana o'tib ketgandan keyin (natija bo'lmasa)
      bu yerda har kuni qaytadan eslatiladi;
    - sinov darsi sanasi belgilanmagan bo'lsa - qo'shilganidan LEAD_STALE_DAYS kun o'tgach eslatiladi."""
    cutoff = (now_local() - timedelta(days=LEAD_STALE_DAYS)).isoformat()
    today = today_local().isoformat()
    return await fetchall(db, "SELECT * FROM leads WHERE status IN ('new','contacted','trial') AND ("
                             "(trial_at IS NOT NULL AND trial_at<>'' AND trial_at<?) OR "
                             "((trial_at IS NULL OR trial_at='') AND created_at<=?)) ORDER BY created_at",
                          (today, cutoff))


async def archive_or_delete_group(db, group_id):
    """Guruhni o'chiradi - lekin agar unda to'lov yoki davomat tarixi bo'lsa, butunlay
    o'chirilmaydi, balki arxivlangan holatda saqlanadi (nomi o'zgartiriladi, chunki nom
    UNIQUE - shunda xuddi shu nomda yangi guruh ochish mumkin bo'ladi). Shunday qilinmasa,
    o'tgan oylardagi o'qituvchi oyligi va hisobotlardagi shu guruhga tegishli summalar
    guruh o'chirilgandan keyin butunlay yo'qolib qoladi."""
    g = await fetchone(db, "SELECT name FROM groups WHERE id=?", (group_id,))
    if not g:
        return
    has_history = (await fetchone(db, "SELECT 1 FROM payments WHERE group_id=?", (group_id,)) or
                   await fetchone(db, "SELECT 1 FROM attendance WHERE group_id=?", (group_id,)) or
                   await fetchone(db, "SELECT 1 FROM students WHERE group_id=?", (group_id,)))
    if has_history:
        new_name = f"{g['name']} (arxiv, {today_local().isoformat()})"
        await db.execute("UPDATE groups SET archived=1, name=? WHERE id=?", (new_name, group_id))
    else:
        await db.execute("DELETE FROM groups WHERE id=?", (group_id,))


async def get_setting(db, key, default=""):
    row = await fetchone(db, "SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


async def set_setting(db, key, value):
    await db.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


async def group_income(db, group_id, month=None):
    month = month or current_month()
    row = await fetchone(db, "SELECT COALESCE(SUM(amount),0) t FROM payments "
                             "WHERE group_id=? AND month=?", (group_id, month))
    return row["t"]


async def group_payment_rows(db, group_id, month=None):
    """Guruhda shu oyda har bir o'quvchi qancha to'lagani - to'g'ridan-to'g'ri to'lovlar
    jadvalidan (hozirgi o'quvchilar ro'yxatidan emas). Shuning uchun o'quvchi keyinroq
    guruhdan chiqarilsa/o'chirilsa ham, o'tgan oylardagi to'lovi oylik hisobidan tushib
    qolmaydi (masalan dekabr boshida oylik hisoblanganda, noyabr to'lovi saqlanadi)."""
    month = month or current_month()
    return await fetchall(db, "SELECT student_id, SUM(amount) AS paid_sum FROM payments "
                             "WHERE group_id=? AND month=? GROUP BY student_id", (group_id, month))


# "O'quvchi boshiga" oylik qoidasi: o'quvchi to'lovi stavkaning LOW_PAY_MULT baravaridan
# oshmasa (masalan stavka 200 000 bo'lsa 400 000 gacha) o'qituvchi shu to'lovning
# LOW_PAY_PERCENT foizini oladi, undan ko'p to'lasa - stavkaning o'zini.
LOW_PAY_MULT = 2
LOW_PAY_PERCENT = 40


def per_student_pay(rate: float, paid_sum: float, low_pay_percent=None) -> float:
    if paid_sum <= 0:
        return 0.0
    pct = LOW_PAY_PERCENT if low_pay_percent is None else low_pay_percent
    if paid_sum <= rate * LOW_PAY_MULT:
        return paid_sum * pct / 100
    return float(rate)


async def registry_rows(db, teacher_id, month=None, branch_id=None):
    """Reyestr o'quvchilari: [(guruh, kelgan darslar soni, summa)]. Summa har bir dars paytidagi
    stavka bo'yicha (attendance.rate) hisoblanadi, o'qituvchiga 100% beriladi."""
    month = month or current_month()
    sql = """
        SELECT g.name AS name, COUNT(*) AS lessons, COALESCE(SUM(a.rate),0) AS total
        FROM attendance a JOIN groups g ON g.id=a.group_id
        WHERE g.teacher_id=? AND a.present=1 AND a.rate>0 AND a.day LIKE ?"""
    args = [teacher_id, month + "-%"]
    if branch_id:
        sql += " AND g.branch_id=?"
        args.append(branch_id)
    sql += " GROUP BY g.id ORDER BY g.name"
    rows = await fetchall(db, sql, tuple(args))
    return [(r["name"], r["lessons"], r["total"]) for r in rows]


async def registry_total(db, month=None):
    month = month or current_month()
    row = await fetchone(db, "SELECT COALESCE(SUM(rate),0) t FROM attendance "
                             "WHERE present=1 AND day LIKE ?", (month + "-%",))
    return row["t"]


async def teacher_advance_total(db, teacher_id, month=None):
    """O'qituvchi shu oy uchun oldindan olgan avanslari yig'indisi - oylikdan ayrilishi kerak."""
    month = month or current_month()
    row = await fetchone(db, "SELECT COALESCE(SUM(amount),0) t FROM advances WHERE teacher_id=? AND month=?",
                         (teacher_id, month))
    return row["t"]


async def teacher_salary(db, teacher_id, month=None, branch_id=None):
    """Return (pay_type, pay_value, [(group, income, paid_count)], salary).
    branch_id berilsa, faqat shu filialdagi guruhlar bo'yicha hisoblanadi."""
    month = month or current_month()
    t = await fetchone(db, "SELECT * FROM teachers WHERE tg_id=?", (teacher_id,))
    if not t:
        return None
    rows, total = [], 0.0
    sql = "SELECT * FROM groups WHERE teacher_id=?"
    args = [teacher_id]
    if branch_id:
        sql += " AND branch_id=?"
        args.append(branch_id)
    for g in await fetchall(db, sql, tuple(args)):
        income = await group_income(db, g["id"], month)
        pay_rows = await group_payment_rows(db, g["id"], month)
        rows.append((g["name"], income, len(pay_rows)))
        if t["pay_type"] == "percent":
            total += income * t["pay_value"] / 100
        else:
            total += sum(per_student_pay(t["pay_value"], r["paid_sum"], t["low_pay_percent"]) for r in pay_rows)
    total += sum(r[2] for r in await registry_rows(db, teacher_id, month, branch_id))  # reyestr: 100%
    return t["pay_type"], t["pay_value"], rows, total
