"""
Lớp bọc DB rất mỏng. Hai phương ngữ:
  - 'mssql'  : SQL Server qua pyodbc (dùng thật)
  - 'sqlite' : file .db cục bộ (chạy thử / kiểm tra logic khi chưa muốn đụng SQL Server)
Mọi câu SQL của pipeline dùng cú pháp chung (tham số `?`, không TOP/MERGE) để chạy được trên cả hai.
"""
import datetime
import re
import sqlite3


def utcnow():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _norm(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, str):
        return v
    return v


class DB:
    def __init__(self, conn, dialect):
        self.conn, self.dialect = conn, dialect
        self._cols = {}

    # ------------------------------------------------------------ kết nối
    @classmethod
    def sqlserver(cls, conn_str):
        import pyodbc  # pip install pyodbc
        return cls(pyodbc.connect(conn_str, autocommit=False), "mssql")

    @classmethod
    def sqlite(cls, path):
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA foreign_keys=ON")
        return cls(conn, "sqlite")

    def t(self, name):
        return f"dbo.{name}" if self.dialect == "mssql" else name

    # ------------------------------------------------------------ truy vấn
    def q(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        if cur.description is None:
            return []
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def x(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur.rowcount

    def insert(self, table, values, id_col):
        cols = list(values)
        ph = ",".join("?" * len(cols))
        cur = self.conn.cursor()
        if self.dialect == "mssql":
            cur.execute(f"INSERT INTO {self.t(table)} ({','.join(cols)}) OUTPUT INSERTED.{id_col} "
                        f"VALUES ({ph})", [_norm(values[c]) for c in cols])
            return int(cur.fetchone()[0])
        cur.execute(f"INSERT INTO {self.t(table)} ({','.join(cols)}) VALUES ({ph})",
                    [_norm(values[c]) for c in cols])
        return int(cur.lastrowid)

    def upsert(self, table, key, values, id_col, insert_only=None):
        """Trả về (id, 'inserted'|'updated'|'unchanged'). `key` xác định dòng; NULL trong key được xử lý."""
        where, params = [], []
        for k, v in key.items():
            if v is None:
                where.append(f"{k} IS NULL")
            else:
                where.append(f"{k} = ?")
                params.append(_norm(v))
        sel_cols = [id_col] + [c for c in values if c != id_col]
        rows = self.q(f"SELECT {','.join(sel_cols)} FROM {self.t(table)} WHERE {' AND '.join(where)}", params)
        if not rows:
            allv = dict(key)
            allv.update(values)
            allv.update(insert_only or {})
            return self.insert(table, allv, id_col), "inserted"
        row = rows[0]
        changed = {c: values[c] for c in values
                   if _norm(row[c]) != _norm(values[c])
                   and not (row[c] in (None, "") and values[c] in (None, ""))}
        if not changed:
            return int(row[id_col]), "unchanged"
        sets = ",".join(f"{c} = ?" for c in changed)
        self.x(f"UPDATE {self.t(table)} SET {sets} WHERE {id_col} = ?",
               [_norm(v) for v in changed.values()] + [row[id_col]])
        return int(row[id_col]), "updated"

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    # ------------------------------------------------------------ siêu dữ liệu
    def table_exists(self, table):
        return bool(self.columns(table))

    def columns(self, table):
        if table in self._cols:
            return self._cols[table]
        try:
            if self.dialect == "mssql":
                rows = self.q("SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?)", [f"dbo.{table}"])
                cols = {r["name"] for r in rows}
            else:
                cols = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
        except Exception:
            cols = set()
        self._cols[table] = cols
        return cols

    # ------------------------------------------------------------ khởi tạo schema
    def run_script(self, text):
        batches = [b.strip() for b in re.split(r"^\s*GO\s*$", text, flags=re.M | re.I) if b.strip()]
        for b in batches:
            self.x(b)
        self.commit()
        self._cols.clear()
        return len(batches)

    def init_sqlite(self):
        self.conn.executescript(SQLITE_SCHEMA)
        self.commit()
        self._cols.clear()


# Tập con schema v2 + patch v3 đủ để pipeline chạy trên SQLite (chỉ dùng cho chạy thử).
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS Books (
  BookId INTEGER PRIMARY KEY AUTOINCREMENT, BookKey TEXT UNIQUE NOT NULL, Title TEXT, Genre TEXT,
  StyleGuide TEXT, CreatedAt TEXT, OriginalLanguage TEXT, TargetLanguage TEXT, AuthorName TEXT,
  BookStatus TEXT, UpdatedAt TEXT);
CREATE TABLE IF NOT EXISTS Chapters (
  ChapterId INTEGER PRIMARY KEY AUTOINCREMENT, BookId INTEGER NOT NULL REFERENCES Books(BookId),
  ChapterNumber INTEGER NOT NULL, Title TEXT, SummaryVI TEXT, CreatedAt TEXT, SourceFileName TEXT,
  ChapterStatus TEXT, TranslatedAt TEXT, UpdatedAt TEXT, UNIQUE (BookId, ChapterNumber));
CREATE TABLE IF NOT EXISTS Characters (
  CharacterId INTEGER PRIMARY KEY AUTOINCREMENT, BookId INTEGER NOT NULL REFERENCES Books(BookId),
  Name TEXT NOT NULL, Notes TEXT, Description TEXT, FirstSeenChapter INTEGER, ReviewStatus TEXT,
  CreatedAt TEXT, Gender TEXT, CharacterKind TEXT NOT NULL DEFAULT 'person', DisplayNameVI TEXT,
  ThirdPersonPronoun TEXT, SpeechStyle TEXT, UNIQUE (BookId, Name));
CREATE TABLE IF NOT EXISTS StoryEvents (
  EventId INTEGER PRIMARY KEY AUTOINCREMENT, BookId INTEGER NOT NULL, ChapterId INTEGER NOT NULL,
  ChunkIndex INTEGER, EventType TEXT, EventTitle TEXT, DescriptionVI TEXT, EvidenceEN TEXT,
  DetectionMethod TEXT, ReviewStatus TEXT, CreatedAt TEXT, ChapterNumber INTEGER, ParaIndex INTEGER,
  AffectsPronouns INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS StoryEventCharacters (
  EventId INTEGER NOT NULL, BookId INTEGER NOT NULL, CharacterId INTEGER NOT NULL, EffectState TEXT,
  Notes TEXT, PRIMARY KEY (EventId, CharacterId));
CREATE TABLE IF NOT EXISTS PronounRules (
  RuleId INTEGER PRIMARY KEY AUTOINCREMENT, BookId INTEGER NOT NULL, SpeakerId INTEGER NOT NULL,
  ListenerId INTEGER, SceneState TEXT, SelfPronoun TEXT, AddressPronoun TEXT, Notes TEXT,
  IsConfirmed INTEGER NOT NULL DEFAULT 0, Priority INTEGER DEFAULT 0, SpeechMode TEXT NOT NULL DEFAULT 'speech',
  ReferPronoun TEXT, StartChapter INTEGER NOT NULL DEFAULT 0, StartPara INTEGER NOT NULL DEFAULT 0,
  EndChapter INTEGER, EndPara INTEGER, EventId INTEGER);
CREATE TABLE IF NOT EXISTS ContextFacts (
  FactId INTEGER PRIMARY KEY AUTOINCREMENT, BookId INTEGER NOT NULL, CharacterId INTEGER, FactType TEXT,
  FactText TEXT, StartChapter INTEGER NOT NULL DEFAULT 0, StartPara INTEGER NOT NULL DEFAULT 0,
  EndChapter INTEGER, EndPara INTEGER, EvidenceEN TEXT, ReviewStatus TEXT, CreatedAt TEXT);
CREATE TABLE IF NOT EXISTS GlossaryTerms (
  TermId INTEGER PRIMARY KEY AUTOINCREMENT, BookId INTEGER NOT NULL, SourceTerm TEXT NOT NULL,
  TargetTerm TEXT NOT NULL, TermType TEXT, Notes TEXT, IsApproved INTEGER DEFAULT 0, IsActive INTEGER DEFAULT 1,
  CreatedAt TEXT, Variants TEXT, DoNotTranslate INTEGER NOT NULL DEFAULT 0, FirstSeenChapter INTEGER,
  UNIQUE (BookId, SourceTerm));
CREATE TABLE IF NOT EXISTS ChapterScenes (
  SceneId INTEGER PRIMARY KEY AUTOINCREMENT, BookId INTEGER NOT NULL, ChapterId INTEGER NOT NULL,
  SceneIndex INTEGER NOT NULL, StartPara INTEGER NOT NULL, EndPara INTEGER, Location TEXT, TimeOfDay TEXT,
  Mood TEXT, SummaryVI TEXT, ReviewStatus TEXT NOT NULL DEFAULT 'suggested', CreatedAt TEXT,
  UNIQUE (ChapterId, SceneIndex));
CREATE TABLE IF NOT EXISTS ModelVersions (
  ModelVersionId INTEGER PRIMARY KEY AUTOINCREMENT, BaseModel TEXT NOT NULL, AdapterPath TEXT,
  TemplateVersion TEXT NOT NULL, TrainSetHash TEXT, TrainExamples INTEGER, Hyperparams TEXT, EvalResult TEXT,
  IsActive INTEGER NOT NULL DEFAULT 0, CreatedAt TEXT);
CREATE TABLE IF NOT EXISTS TranslationJobs (
  JobId INTEGER PRIMARY KEY AUTOINCREMENT, BookId INTEGER NOT NULL, ChapterId INTEGER NOT NULL,
  ModelVersionId INTEGER, TemplateVersion TEXT NOT NULL, JobStatus TEXT NOT NULL DEFAULT 'exported',
  PendingFile TEXT, ResultFile TEXT, ChunkCount INTEGER, FailedCount INTEGER, Notes TEXT,
  ExportedAt TEXT, ImportedAt TEXT);
CREATE TABLE IF NOT EXISTS TranslationContextSnapshots (
  SnapshotId INTEGER PRIMARY KEY AUTOINCREMENT, BookId INTEGER NOT NULL, ChapterNumber INTEGER NOT NULL,
  ParaStart INTEGER NOT NULL, ParaEnd INTEGER NOT NULL, TemplateVersion TEXT NOT NULL, ContextHash TEXT NOT NULL,
  ContextJson TEXT NOT NULL, CreatedAt TEXT, UNIQUE (BookId, ChapterNumber, ParaStart, ParaEnd, ContextHash));
CREATE TABLE IF NOT EXISTS ChapterParagraphs (
  ParagraphId INTEGER PRIMARY KEY AUTOINCREMENT, BookId INTEGER NOT NULL, ChapterId INTEGER NOT NULL,
  ChapterNumber INTEGER NOT NULL, ParaIndex INTEGER NOT NULL, SourceEN TEXT NOT NULL, TargetVI TEXT,
  SourceHash TEXT NOT NULL, Mode TEXT NOT NULL, SpeakerId INTEGER, ListenerId INTEGER, SceneState TEXT,
  SceneBreak INTEGER NOT NULL DEFAULT 0, IsConfirmed INTEGER NOT NULL DEFAULT 0, AlignConf TEXT, Flags TEXT,
  Note TEXT, UpdatedAt TEXT, UNIQUE (BookId, ChapterNumber, ParaIndex));
"""
