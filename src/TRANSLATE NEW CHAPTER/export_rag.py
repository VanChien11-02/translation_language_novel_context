import hashlib
import json
import os
import pyodbc
from docx import Document

CONN_STR = os.getenv(
    "SQL_CONN_STR",
    "Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=ContextTranslateDB;Trusted_Connection=yes;"
)
DRIVE_INPUT_JSON = r"G:\My Drive\NovelAI\input\pending_chunks.json"

def sha256_str(text: str) -> str:
    """Tạo mã băm SHA-256 chuẩn 64 ký tự cho cột SourceHash và ContextHash."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def read_source_file(file_path: str) -> str:
    """Hỗ trợ đọc cả file .txt và .docx."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def split_into_chunks(raw_text: str, max_chars: int = 1400) -> list[str]:
    """Gom các dòng thành từng đoạn vừa khít bộ nhớ ngữ cảnh của Qwen3-4B."""
    paragraphs = [p.strip() for p in raw_text.splitlines() if p.strip()]
    chunks, current_chunk, current_len = [], [], 0

    for p in paragraphs:
        # Bỏ qua các dòng rác thống kê web nếu có
        if p.startswith("bởi "):
            continue
        if current_len + len(p) > max_chars and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [p]
            current_len = len(p)
        else:
            current_chunk.append(p)
            current_len += len(p) + 1

    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks

def retrieve_sql_rag_context(cursor, book_id: int, chunk_text: str) -> tuple[dict, str]:
    """Truy xuất động StyleGuide, PronounRules và TranslationExamples cho đoạn văn."""
    chunk_lower = chunk_text.lower()

    # 1. Lấy StyleGuide từ bảng dbo.Books
    cursor.execute("SELECT StyleGuide FROM dbo.Books WHERE BookId = ?", (book_id,))
    row = cursor.fetchone()
    style_guide = row[0] if row and row[0] else ""

    # 2. Lọc các quy tắc xưng hô trong dbo.PronounRules có nhân vật xuất hiện trong đoạn
    cursor.execute("""
        SELECT c1.Name AS Speaker, c2.Name AS Listener, pr.SceneState, pr.SelfPronoun, pr.AddressPronoun
        FROM dbo.PronounRules pr
        JOIN dbo.Characters c1 ON pr.BookId = c1.BookId AND pr.SpeakerId = c1.CharacterId
        JOIN dbo.Characters c2 ON pr.BookId = c2.BookId AND pr.ListenerId = c2.CharacterId
        WHERE pr.BookId = ?
    """, (book_id,))

    pronouns_list = []
    for spk, lst, scene, self_p, addr_p in cursor.fetchall():
        spk_first = spk.split("/")[0].split()[0].lower()
        lst_first = lst.split("/")[0].split()[0].lower()
        # Luôn giữ quy tắc của nhân vật chính (Sensei) hoặc nhân vật có tên trong đoạn văn
        if spk_first in chunk_lower or lst_first in chunk_lower or spk == "Sensei":
            pronouns_list.append({
                "speaker": spk,
                "listener": lst,
                "scene": scene,
                "pronouns": {"I": self_p, "you": addr_p}
            })

    # 3. Tìm 3 câu mẫu đã duyệt (IsApproved = 1) có từ vựng gần giống nhất với đoạn đang dịch
    cursor.execute("""
        SELECT c1.Name, c2.Name, te.SceneState, te.SourceEN, te.TargetVI
        FROM dbo.TranslationExamples te
        LEFT JOIN dbo.Characters c1 ON te.BookId = c1.BookId AND te.SpeakerId = c1.CharacterId
        LEFT JOIN dbo.Characters c2 ON te.BookId = c2.BookId AND te.ListenerId = c2.CharacterId
        WHERE te.BookId = ? AND te.IsApproved = 1
    """, (book_id,))

    chunk_words = set(chunk_lower.split())
    scored_examples = []
    for spk, lst, scene, src_en, tgt_vi in cursor.fetchall():
        overlap = len(chunk_words.intersection(set(src_en.lower().split())))
        if overlap > 0:
            scored_examples.append((overlap, {
                "speaker": spk or "Narrator",
                "listener": lst or "Reader",
                "scene": scene,
                "input": src_en,
                "output": tgt_vi
            }))

    scored_examples.sort(key=lambda x: x[0], reverse=True)
    top_examples = [item[1] for item in scored_examples[:3]]

    rag_context = {
        "style_guide": style_guide,
        "pronoun_rules": pronouns_list,
        "few_shot_examples": top_examples
    }
    # Tính ContextHash để phát hiện nếu sau này bạn sửa quy tắc xưng hô trong SQL
    context_hash = sha256_str(json.dumps(rag_context, ensure_ascii=False, sort_keys=True))
    return rag_context, context_hash

def prepare_new_chapter_for_colab(book_id: int, chapter_num: int, title: str, file_path: str):
    raw_text = read_source_file(file_path)
    chunks = split_into_chunks(raw_text, max_chars=1400)
    pending_payload = []

    with pyodbc.connect(CONN_STR) as conn:
        cursor = conn.cursor()

        # 1. Tạo hoặc lấy ChapterId trong bảng dbo.Chapters
        cursor.execute(
            "SELECT ChapterId FROM dbo.Chapters WHERE BookId = ? AND ChapterNumber = ?",
            (book_id, chapter_num)
        )
        row = cursor.fetchone()
        if row:
            chapter_id = row[0]
        else:
            cursor.execute("""
                INSERT INTO dbo.Chapters (BookId, ChapterNumber, Title)
                OUTPUT INSERTED.ChapterId
                VALUES (?, ?, ?)
            """, (book_id, chapter_num, title))
            chapter_id = cursor.fetchone()[0]

        # 2. Lưu từng đoạn vào dbo.TranslationChunks và đóng gói JSON
        for idx, chunk_en in enumerate(chunks, start=1):
            source_hash = sha256_str(chunk_en)
            rag_context, context_hash = retrieve_sql_rag_context(cursor, book_id, chunk_en)

            cursor.execute("""
                SELECT ChunkId, TargetVI, SourceHash, ContextHash
                FROM dbo.TranslationChunks
                WHERE ChapterId = ? AND ChunkIndex = ?
            """, (chapter_id, idx))
            existing = cursor.fetchone()

            if existing:
                chunk_id, target_vi, old_src_hash, old_ctx_hash = existing
                # Nếu cả văn bản gốc lẫn quy tắc xưng hô đều không đổi và đã dịch rồi thì bỏ qua
                if target_vi.strip() and old_src_hash == source_hash and old_ctx_hash == context_hash:
                    print(f"  [Skip] Đoạn {idx} đã có bản dịch và không thay đổi ngữ cảnh.")
                    continue
                cursor.execute("""
                    UPDATE dbo.TranslationChunks
                    SET SourceEN = ?, SourceHash = ?, ContextHash = ?, UpdatedAt = SYSUTCDATETIME()
                    WHERE ChunkId = ?
                """, (chunk_en, source_hash, context_hash, chunk_id))
            else:
                # Truyền TargetVI = N'' và ModelName = N'pending' theo ràng buộc NOT NULL của bảng
                cursor.execute("""
                    INSERT INTO dbo.TranslationChunks
                        (ChapterId, ChunkIndex, SourceEN, TargetVI, SourceHash, ContextHash, ModelName)
                    OUTPUT INSERTED.ChunkId
                    VALUES (?, ?, ?, N'', ?, ?, N'pending')
                """, (chapter_id, idx, chunk_en, source_hash, context_hash))
                chunk_id = cursor.fetchone()[0]

            pending_payload.append({
                "chunk_id": chunk_id,
                "chapter_id": chapter_id,
                "chapter_number": chapter_num,
                "chunk_index": idx,
                "source_hash": source_hash,
                "context_hash": context_hash,
                "instruction": "Dịch truyện tiếng Anh sang tiếng Việt",
                "context": rag_context,
                "input": chunk_en
            })

        conn.commit()

    os.makedirs(os.path.dirname(DRIVE_INPUT_JSON), exist_ok=True)
    with open(DRIVE_INPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(pending_payload, f, ensure_ascii=False, indent=2)

    print(f"Đã xuất {len(pending_payload)} đoạn chờ dịch của Chương {chapter_num} ra: {DRIVE_INPUT_JSON}")

if __name__ == "__main__":
    # Thay đường dẫn bằng file chương mới tiếng Anh của bạn
    prepare_new_chapter_for_colab(
        book_id = 1,
        chapter_num = 3,
        title = "Chapter 3: The First Wound and Collaborator",
        file_path = "bản gốc.docx"
    )