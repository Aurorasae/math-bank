# db.py
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "bank.db"
IMG_DIR = DATA_DIR / "images"

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    publisher TEXT,
    grade TEXT,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    parent_id INTEGER,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES chapters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER,
    chapter_id INTEGER,
    qtype TEXT NOT NULL,
    difficulty INTEGER DEFAULT 3,
    content TEXT NOT NULL,
    options TEXT,
    answer TEXT,
    analysis TEXT,
    tags TEXT,
    source TEXT,
    score REAL DEFAULT 5,
    use_count INTEGER DEFAULT 0,
    created_at TEXT,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE SET NULL,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    class_name TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS wrong_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    wrong_count INTEGER DEFAULT 1,
    last_wrong_at TEXT,
    note TEXT,
    UNIQUE(student_id, question_id),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER,
    filename TEXT,
    path TEXT,
    created_at TEXT,
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_q_chapter ON questions(chapter_id);
CREATE INDEX IF NOT EXISTS idx_q_type ON questions(qtype);
CREATE INDEX IF NOT EXISTS idx_q_diff ON questions(difficulty);
"""


@contextmanager
def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------------- 教材 ----------------
def list_books():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM books ORDER BY sort_order, id").fetchall()]


def add_book(name, publisher="", grade=""):
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO books(name,publisher,grade) VALUES(?,?,?)",
                     (name, publisher, grade))


def delete_book(book_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM books WHERE id=?", (book_id,))


# ---------------- 章节 ----------------
def list_chapters(book_id=None):
    with get_conn() as conn:
        if book_id:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE book_id=? ORDER BY sort_order, id",
                (book_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chapters ORDER BY book_id, sort_order, id").fetchall()
        return [dict(r) for r in rows]


def chapter_paths(book_id=None):
    """返回 [(chapter_id, '父 / 子 / 孙')]"""
    chapters = list_chapters(book_id)
    by_parent = {}
    for c in chapters:
        by_parent.setdefault(c["parent_id"], []).append(c)
    result = []

    def walk(pid, prefix):
        for c in by_parent.get(pid, []):
            path = f"{prefix} / {c['name']}" if prefix else c["name"]
            result.append((c["id"], path))
            walk(c["id"], path)

    walk(None, "")
    return result


def descendant_chapter_ids(chapter_id):
    """递归获取某章节及其所有子章节 id"""
    with get_conn() as conn:
        rows = conn.execute("SELECT id, parent_id FROM chapters").fetchall()
    children = {}
    for r in rows:
        children.setdefault(r["parent_id"], []).append(r["id"])
    out, stack = [], [chapter_id]
    while stack:
        cid = stack.pop()
        out.append(cid)
        stack.extend(children.get(cid, []))
    return out


def add_chapter(book_id, name, parent_id=None, sort_order=0):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chapters(book_id,parent_id,name,sort_order) VALUES(?,?,?,?)",
            (book_id, parent_id, name, sort_order))


def delete_chapter(chapter_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM chapters WHERE id=?", (chapter_id,))


# ---------------- 题目 ----------------
def add_question(data: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO questions
               (book_id,chapter_id,qtype,difficulty,content,options,answer,
                analysis,tags,source,score,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data.get("book_id"), data.get("chapter_id"), data["qtype"],
             data.get("difficulty", 3), data["content"],
             json.dumps(data.get("options", []), ensure_ascii=False),
             data.get("answer", ""), data.get("analysis", ""),
             data.get("tags", ""), data.get("source", ""),
             data.get("score", 5), datetime.now().isoformat(timespec="seconds"))
        )
        return cur.lastrowid


def get_question(qid):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
        return dict(r) if r else None


def search_questions(book_id=None, chapter_ids=None, qtype=None,
                     difficulty=None, keyword=None, limit=500):
    sql = """SELECT q.*, b.name AS book_name, c.name AS chapter_name
             FROM questions q
             LEFT JOIN books b ON q.book_id=b.id
             LEFT JOIN chapters c ON q.chapter_id=c.id
             WHERE 1=1"""
    args = []
    if book_id:
        sql += " AND q.book_id=?"; args.append(book_id)
    if chapter_ids:
        sql += f" AND q.chapter_id IN ({','.join('?' * len(chapter_ids))})"
        args += list(chapter_ids)
    if qtype:
        sql += " AND q.qtype=?"; args.append(qtype)
    if difficulty:
        sql += " AND q.difficulty=?"; args.append(difficulty)
    if keyword:
        sql += " AND (q.content LIKE ? OR q.tags LIKE ? OR q.source LIKE ?)"
        kw = f"%{keyword}%"
        args += [kw, kw, kw]
    sql += " ORDER BY q.id DESC LIMIT ?"
    args.append(limit)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def update_question(qid, data: dict):
    fields = ["book_id", "chapter_id", "qtype", "difficulty", "content",
              "options", "answer", "analysis", "tags", "source", "score"]
    sets, args = [], []
    for f in fields:
        if f in data:
            v = data[f]
            if f == "options" and isinstance(v, list):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"{f}=?")
            args.append(v)
    if not sets:
        return
    args.append(qid)
    with get_conn() as conn:
        conn.execute(f"UPDATE questions SET {','.join(sets)} WHERE id=?", args)


def delete_question(qid):
    with get_conn() as conn:
        conn.execute("DELETE FROM questions WHERE id=?", (qid,))


def inc_use_count(qids):
    with get_conn() as conn:
        conn.executemany(
            "UPDATE questions SET use_count=use_count+1 WHERE id=?",
            [(i,) for i in qids])


def count_questions():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]


# ---------------- 学生 ----------------
def list_students():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM students ORDER BY class_name, name").fetchall()]


def add_student(name, class_name=""):
    with get_conn() as conn:
        conn.execute("INSERT INTO students(name,class_name,created_at) VALUES(?,?,?)",
                     (name, class_name, datetime.now().isoformat(timespec="seconds")))


def delete_student(sid):
    with get_conn() as conn:
        conn.execute("DELETE FROM students WHERE id=?", (sid,))


# ---------------- 错题 ----------------
def add_wrong(student_id, question_id, note=""):
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO wrong_questions(student_id,question_id,wrong_count,last_wrong_at,note)
               VALUES(?,?,1,?,?)
               ON CONFLICT(student_id,question_id) DO UPDATE SET
                 wrong_count = wrong_count + 1,
                 last_wrong_at = excluded.last_wrong_at,
                 note = CASE WHEN excluded.note<>'' THEN excluded.note ELSE note END""",
            (student_id, question_id, now, note))


def list_wrong(student_id):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT w.*, q.content, q.qtype, q.difficulty, q.answer, q.analysis,
                      q.options, c.name AS chapter_name
               FROM wrong_questions w
               JOIN questions q ON w.question_id=q.id
               LEFT JOIN chapters c ON q.chapter_id=c.id
               WHERE w.student_id=?
               ORDER BY w.last_wrong_at DESC""", (student_id,)).fetchall()
        return [dict(r) for r in rows]


def remove_wrong(wid):
    with get_conn() as conn:
        conn.execute("DELETE FROM wrong_questions WHERE id=?", (wid,))


# ---------------- 图片 ----------------
def add_image(question_id, filename, path):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO images(question_id,filename,path,created_at) VALUES(?,?,?,?)",
            (question_id, filename, path,
             datetime.now().isoformat(timespec="seconds")))


# ---------------- 备份 ----------------
def export_db_bytes() -> bytes:
    with open(DB_PATH, "rb") as f:
        return f.read()