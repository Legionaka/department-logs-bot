import aiosqlite
from typing import Optional, List, Tuple

DB_PATH = "data.db"

CREATE_TABLES_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS shifts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  username TEXT NOT NULL,
  badge TEXT,
  division TEXT,
  rank TEXT,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS arrests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  username TEXT NOT NULL,
  date_time TEXT NOT NULL,
  location TEXT NOT NULL,
  suspect TEXT NOT NULL,
  charges TEXT NOT NULL,
  assisting TEXT,
  evidence TEXT,
  summary TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discharges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  username TEXT NOT NULL,
  date_time TEXT NOT NULL,
  location TEXT NOT NULL,
  firearm TEXT NOT NULL,
  rounds INTEGER NOT NULL,
  reason TEXT NOT NULL,
  injuries TEXT,
  supervisor TEXT,
  summary TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS loa (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  username TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,
  approved_by TEXT
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_TABLES_SQL)
        await db.commit()

# ---------------- SHIFTS ----------------
async def get_active_shift(user_id: int) -> Optional[Tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT * FROM shifts WHERE user_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        return row

async def start_shift(user_id: int, username: str, badge: str, division: str, rank: str, started_at: str, notes: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO shifts (user_id, username, badge, division, rank, started_at, notes) VALUES (?,?,?,?,?,?,?)",
            (user_id, username, badge, division, rank, started_at, notes),
        )
        await db.commit()

async def end_shift(user_id: int, ended_at: str, notes_append: str):
    async with aiosqlite.connect(DB_PATH) as db:
        if notes_append:
            await db.execute(
                """
                UPDATE shifts
                SET ended_at=?,
                    notes=CASE
                        WHEN notes IS NULL OR notes='' THEN ?
                        ELSE notes || '\n' || ?
                    END
                WHERE user_id=? AND ended_at IS NULL
                """,
                (ended_at, notes_append, notes_append, user_id),
            )
        else:
            await db.execute(
                "UPDATE shifts SET ended_at=? WHERE user_id=? AND ended_at IS NULL",
                (ended_at, user_id),
            )
        await db.commit()

async def list_shifts(limit: int = 10) -> List[Tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, username, badge, division, rank, started_at, ended_at FROM shifts ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        await cur.close()
        return rows

# ---------------- ARRESTS ----------------
async def add_arrest(
    user_id: int, username: str, date_time: str, location: str, suspect: str, charges: str,
    assisting: str, evidence: str, summary: str
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO arrests (user_id, username, date_time, location, suspect, charges, assisting, evidence, summary)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, username, date_time, location, suspect, charges, assisting, evidence, summary),
        )
        await db.commit()

async def list_arrests(limit: int = 10) -> List[Tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, username, date_time, location, suspect, charges FROM arrests ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        await cur.close()
        return rows

# ---------------- DISCHARGES ----------------
async def add_discharge(
    user_id: int, username: str, date_time: str, location: str, firearm: str, rounds: int,
    reason: str, injuries: str, supervisor: str, summary: str
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO discharges (user_id, username, date_time, location, firearm, rounds, reason, injuries, supervisor, summary)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (user_id, username, date_time, location, firearm, rounds, reason, injuries, supervisor, summary),
        )
        await db.commit()

async def list_discharges(limit: int = 10) -> List[Tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, username, date_time, location, firearm, rounds FROM discharges ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        await cur.close()
        return rows

# ---------------- LOA ----------------
async def add_loa(
    user_id: int, username: str, start_date: str, end_date: str, reason: str,
    status: str, approved_by: str
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO loa (user_id, username, start_date, end_date, reason, status, approved_by)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, username, start_date, end_date, reason, status, approved_by),
        )
        await db.commit()

async def update_loa_status(loa_id: int, status: str, approved_by: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE loa SET status=?, approved_by=? WHERE id=?",
            (status, approved_by, loa_id),
        )
        await db.commit()

async def list_loa(limit: int = 10) -> List[Tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, username, start_date, end_date, status FROM loa ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        await cur.close()
        return rows