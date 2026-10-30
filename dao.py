"""Lớp lưu trữ SQL Server. Truy vấn luôn sử dụng parameter (?) của pyodbc."""
import os

from dotenv import load_dotenv
import pyodbc

from utils import stable_hash

load_dotenv()


def get_connection():
    installed = pyodbc.drivers()
    driver = os.getenv('SQL_DRIVER', 'ODBC Driver 18 for SQL Server')
    if driver not in installed:
        raise RuntimeError(
            f'Chưa cài {driver}. Driver hiện có: {installed}. '
            'Hãy cài Microsoft ODBC Driver 18 for SQL Server.'
        )
    server = os.getenv('SQL_SERVER', 'localhost')
    database = os.getenv('SQL_DATABASE', 'ContextTranslateDB')
    trust = os.getenv('SQL_TRUST_SERVER_CERTIFICATE', 'no').lower()
    conn_str = (
        f'DRIVER={{{driver}}};SERVER={server};DATABASE={database};'
        f'Encrypt=yes;TrustServerCertificate={trust};'
    )
    user, password = os.getenv('SQL_USER'), os.getenv('SQL_PASSWORD')
    if user:
        conn_str += f'UID={user};PWD={password or ""};'
    else:
        conn_str += 'Trusted_Connection=yes;'
    return pyodbc.connect(conn_str, timeout=10)


class Store:
    def __enter__(self):
        self.conn = get_connection()
        return self

    def __exit__(self, typ, val, tb):
        try:
            if typ:
                self.conn.rollback()
            else:
                self.conn.commit()
        finally:
            self.conn.close()

    def book(self, key: str):
        row = self.conn.cursor().execute(
            'SELECT BookId, Title, ISNULL(StyleGuide, N\'\') FROM dbo.Books WHERE BookKey = ?',
            key
        ).fetchone()
        if not row:
            raise ValueError(f'Không tìm thấy truyện {key!r}. Chạy python seed_demo.py trước.')
        return {'id': row[0], 'title': row[1], 'style': row[2]}

    def ensure_book(self, key, title, genre, style):
        cur = self.conn.cursor()
        row = cur.execute('SELECT BookId FROM dbo.Books WHERE BookKey = ?', key).fetchone()
        if row:
            cur.execute(
                'UPDATE dbo.Books SET Title=?, Genre=?, StyleGuide=? WHERE BookId=?',
                title, genre, style, row[0]
            )
            return row[0]
        return cur.execute('''INSERT INTO dbo.Books(BookKey,Title,Genre,StyleGuide)
                   OUTPUT INSERTED.BookId VALUES(?,?,?,?)''',
                   key, title, genre, style).fetchone()[0]

    def char_id(self, book_id, name, required=True):
        if not name:
            return None
        row = self.conn.cursor().execute(
            'SELECT CharacterId FROM dbo.Characters WHERE BookId=? AND Name=?', book_id, name
        ).fetchone()
        if not row and required:
            raise ValueError(f'Không có nhân vật {name!r} trong SQL Server.')
        return row[0] if row else None

    def ensure_character(self, book_id, name, notes=''):
        cur = self.conn.cursor()
        existing = self.char_id(book_id, name, required=False)
        if existing:
            cur.execute('UPDATE dbo.Characters SET Notes=? WHERE CharacterId=?', notes, existing)
            return existing
        return cur.execute('''INSERT INTO dbo.Characters(BookId,Name,Notes)
                   OUTPUT INSERTED.CharacterId VALUES(?,?,?)''',
                   book_id, name, notes).fetchone()[0]

    def ensure_rule(self, book_id, speaker, listener, scene, self_word, you_word, notes=''):
        sid = self.char_id(book_id, speaker)
        lid = self.char_id(book_id, listener)
        cur = self.conn.cursor()
        row = cur.execute('''SELECT RuleId FROM dbo.PronounRules
                             WHERE BookId=? AND SpeakerId=? AND ListenerId=? AND SceneState=?''',
                          book_id, sid, lid, scene).fetchone()
        if row:
            cur.execute('''UPDATE dbo.PronounRules
                           SET SelfPronoun=?, AddressPronoun=?, Notes=? WHERE RuleId=?''',
                        self_word, you_word, notes, row[0])
        else:
            cur.execute('''INSERT INTO dbo.PronounRules
                           (BookId,SpeakerId,ListenerId,SceneState,SelfPronoun,AddressPronoun,Notes)
                           VALUES(?,?,?,?,?,?,?)''',
                        book_id, sid, lid, scene, self_word, you_word, notes)

    def ensure_example(self, book_id, en, vi, speaker=None, listener=None,
                       scene='general', approved=False):
        sid = self.char_id(book_id, speaker)
        lid = self.char_id(book_id, listener)
        # Hai ví dụ có cùng câu EN nhưng khác người nói / scene được phép cùng tồn tại.
        ex_key = stable_hash({'en': en, 'speaker': speaker, 'listener': listener, 'scene': scene})
        cur = self.conn.cursor()
        row = cur.execute('''SELECT ExampleId FROM dbo.TranslationExamples
                             WHERE BookId=? AND ExampleKey=?''', book_id, ex_key).fetchone()
        if row:
            cur.execute('''UPDATE dbo.TranslationExamples
                           SET TargetVI=?, IsApproved=CASE WHEN ?=1 THEN 1 ELSE IsApproved END
                           WHERE ExampleId=?''',
                        vi, int(approved), row[0])
        else:
            cur.execute('''INSERT INTO dbo.TranslationExamples
                           (BookId,ExampleKey,SpeakerId,ListenerId,SceneState,SourceEN,TargetVI,IsApproved)
                           VALUES(?,?,?,?,?,?,?,?)''',
                        book_id, ex_key, sid, lid, scene, en, vi, int(approved))

    def get_rules(self, book_id):
        rows = self.conn.cursor().execute('''
            SELECT s.Name, l.Name, r.SceneState, r.SelfPronoun, r.AddressPronoun, ISNULL(r.Notes,N'')
            FROM dbo.PronounRules r
            JOIN dbo.Characters s ON s.CharacterId = r.SpeakerId
            JOIN dbo.Characters l ON l.CharacterId = r.ListenerId
            WHERE r.BookId=? ORDER BY s.Name, l.Name, r.SceneState
        ''', book_id).fetchall()
        return [dict(speaker=x[0], listener=x[1], scene=x[2], self_word=x[3],
                     you_word=x[4], notes=x[5]) for x in rows]

    def get_examples(self, book_id, speaker=None, listener=None, scene='mixed', limit=3):
        sid = self.char_id(book_id, speaker)
        lid = self.char_id(book_id, listener)
        rows = self.conn.cursor().execute('''
            SELECT TOP (100) ExampleId, SpeakerId, ListenerId, SceneState, SourceEN, TargetVI
            FROM dbo.TranslationExamples
            WHERE BookId=? AND IsApproved=1 ORDER BY ExampleId DESC
        ''', book_id).fetchall()
        scored = []
        for x in rows:
            exid, es, el, estate, en, vi = x
            if speaker and listener:
                # Không truyền ví dụ của cặp khác hoặc scene không phù hợp vào prompt.
                if es not in (None, sid) or el not in (None, lid):
                    continue
                if scene != 'mixed' and estate not in (scene, 'general'):
                    continue
                score = (4 if es == sid else 0) + (3 if el == lid else 0)
                score += (2 if estate == scene else 0)
            else:
                # Dịch cả chương có nhiều người nói: chỉ dùng ví dụ văn phong chung.
                if es is not None or el is not None or estate != 'general':
                    continue
                score = 0
            scored.append((score, exid, dict(en=en, vi=vi, scene=estate)))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [x[2] for x in scored[:limit]]

    def ensure_chapter(self, book_id, chapter_number):
        cur = self.conn.cursor()
        row = cur.execute('''SELECT ChapterId FROM dbo.Chapters
                             WHERE BookId=? AND ChapterNumber=?''', book_id, chapter_number).fetchone()
        if row:
            return row[0]
        return cur.execute('''INSERT INTO dbo.Chapters(BookId,ChapterNumber)
                   OUTPUT INSERTED.ChapterId VALUES(?,?)''',
                   book_id, chapter_number).fetchone()[0]

    def find_chapter(self, book_id, chapter_number):
        row = self.conn.cursor().execute('''
            SELECT ChapterId FROM dbo.Chapters WHERE BookId=? AND ChapterNumber=?
        ''', book_id, chapter_number).fetchone()
        return row[0] if row else None

    def previous_summaries(self, book_id, chapter_number, limit=2):
        rows = self.conn.cursor().execute('''
            SELECT TOP (2) ChapterNumber, SummaryVI FROM dbo.Chapters
            WHERE BookId=? AND ChapterNumber<? AND SummaryVI IS NOT NULL
            ORDER BY ChapterNumber DESC
        ''', book_id, chapter_number).fetchall()
        return list(reversed([(x[0], x[1]) for x in rows]))[:limit]

    def save_summary(self, chapter_id, summary):
        self.conn.cursor().execute('''
            UPDATE dbo.Chapters SET SummaryVI=? WHERE ChapterId=?
        ''', summary, chapter_id)

    def previous_chunk(self, chapter_id, chunk_index):
        row = self.conn.cursor().execute('''
            SELECT TOP(1) SourceEN, TargetVI FROM dbo.TranslationChunks
            WHERE ChapterId=? AND ChunkIndex<? ORDER BY ChunkIndex DESC
        ''', chapter_id, chunk_index).fetchone()
        return {'en': row[0], 'vi': row[1]} if row else None

    def cached_chunk(self, chapter_id, index, source_hash, context_hash, model):
        row = self.conn.cursor().execute('''
            SELECT TargetVI FROM dbo.TranslationChunks
            WHERE ChapterId=? AND ChunkIndex=? AND SourceHash=?
                  AND ContextHash=? AND ModelName=?
        ''', chapter_id, index, source_hash, context_hash, model).fetchone()
        return row[0] if row else None

    def save_chunk(self, chapter_id, index, source, translated, source_hash,
                   context_hash, model, input_tokens=None, output_tokens=None):
        cur = self.conn.cursor()
        existing = cur.execute('''SELECT ChunkId FROM dbo.TranslationChunks
                                  WHERE ChapterId=? AND ChunkIndex=?''', chapter_id, index).fetchone()
        if existing:
            cur.execute('''UPDATE dbo.TranslationChunks
                        SET SourceEN=?, TargetVI=?, SourceHash=?, ContextHash=?, ModelName=?,
                            InputTokens=?, OutputTokens=?, UpdatedAt=SYSUTCDATETIME()
                        WHERE ChunkId=?''',
                        source, translated, source_hash, context_hash, model,
                        input_tokens, output_tokens, existing[0])
        else:
            cur.execute('''INSERT INTO dbo.TranslationChunks
                (ChapterId,ChunkIndex,SourceEN,TargetVI,SourceHash,ContextHash,
                 ModelName,InputTokens,OutputTokens)
                VALUES(?,?,?,?,?,?,?,?,?)''',
                chapter_id, index, source, translated, source_hash, context_hash,
                model, input_tokens, output_tokens)
        # Commit sau MỖI chunk để có checkpoint nếu API lỗi giữa chương.
        self.conn.commit()

    def stats(self):
        return self.conn.cursor().execute('''
            SELECT (SELECT COUNT(*) FROM dbo.Books) AS Books,
                   (SELECT COUNT(*) FROM dbo.Characters) AS Characters,
                   (SELECT COUNT(*) FROM dbo.TranslationExamples) AS Examples,
                   (SELECT COUNT(*) FROM dbo.TranslationChunks) AS Chunks
        ''').fetchone()
