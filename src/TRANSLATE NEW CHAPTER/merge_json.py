import hashlib
import json
import os
import pyodbc

CONN_STR = os.getenv(
    "SQL_CONN_STR",
    "Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=ContextTranslateDB;Trusted_Connection=yes;"
)
DRIVE_DIR = r"G:\My Drive\NovelAI"

def sha256_str(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def split_text_into_chunks(raw_text: str, max_chars: int = 1500):
    paragraphs = [p.strip() for p in raw_text.splitlines() if p.strip()]
    chunks, current, length = [], [], 0
    for p in paragraphs:
        if length + len(p) > max_chars and current:
            chunks.append("\n".join(current))
            current, length = [p], len(p)
        else:
            current.append(p)
            length += len(p) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks

def build_rag_for_chunk(cursor, book_id: int, chunk_text: str):
    """Truy xuất động PronounRules và TranslationExamples đã duyệt (IsApproved = 1) theo nhân vật."""
    cursor.execute("SELECT StyleGuide FROM dbo.Books WHERE BookId = ?", (book_id,))
    book_row = cursor.fetchone()
    style_guide = book_row[0] if book_row and book_row[0] else ""

    # 1. Tìm các nhân vật xuất hiện trong đoạn văn
    cursor.execute("SELECT CharacterId, Name FROM dbo.Characters WHERE BookId = ?", (book_id,))
    matched_ids = []
    chunk_lower = chunk_text.lower()
    for cid, cname in cursor.fetchall():
        first_word = cname.split("/")[0].split()[0].lower()
        if cname.lower() in chunk_lower or first_word in chunk_lower:
            matched_ids.append(cid)

    # 2. Lấy quy tắc xưng hô của các nhân vật xuất hiện
    cursor.execute("""
        SELECT c1.Name, c2.Name, pr.SceneState, pr.SelfPronoun, pr.AddressPronoun
        FROM dbo.PronounRules pr
        JOIN dbo.Characters c1 ON pr.BookId = c1.BookId AND pr.SpeakerId = c1.CharacterId
        JOIN dbo.Characters c2 ON pr.BookId = c2.BookId AND pr.ListenerId = c2.CharacterId
        WHERE pr.BookId = ?
    """, (book_id,))
    
    active_pronouns = []
    for spk_name, lst_name, scene, self_p, addr_p in cursor.fetchall():
        if spk_name.lower() in chunk_lower or lst_name.lower() in chunk_lower or "sensei" in spk_name.lower():
            active_pronouns.append({
                "speaker": spk_name,
                "listener": lst_name,
                "scene": scene,
                "I": self_p,
                "you": addr_p
            })

    # 3. Lấy tối đa 3 câu mẫu đã duyệt (IsApproved = 1) có từ vựng gần nhất
    cursor.execute("""
        SELECT TOP 3 SourceEN, TargetVI, SceneState
        FROM dbo.TranslationExamples
        WHERE BookId = ? AND IsApproved = 1
        ORDER BY ExampleId DESC
    """, (book_id,))
    approved_examples = [
        {"source_en": r[0], "target_vi": r[1], "scene": r[2]}
        for r in cursor.fetchall()
    ]

    rag_context = {
        "style_guide": style_guide,
        "active_pronouns": active_pronouns,
        "approved_examples": approved_examples
    }
    context_hash = sha256_str(json.dumps(rag_context, ensure_ascii=False, sort_keys=True))
    return rag_context, context_hash

def ingest_new_chapter_and_export_rag(book_id: int, chapter_num: int, title: str, txt_path: str):
    """Đọc chương tiếng Anh mới, lưu vào Chapters & TranslationChunks và xuất file JSON cho Colab."""
    with open(txt_path, "r", encoding="utf-8") as f:
        raw_en = f.read()

    chunks = split_text_into_chunks(raw_en, max_chars=1500)
    pending_payload = []

    with pyodbc.connect(CONN_STR) as conn:
        cursor = conn.cursor()

        # 1. Tạo hoặc lấy ChapterId trong dbo.Chapters
        cursor.execute("""
            SELECT ChapterId FROM dbo.Chapters WHERE BookId = ? AND ChapterNumber = ?
        """, (book_id, chapter_num))
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

        # 2. Xử lý từng đoạn trong dbo.TranslationChunks
        for idx, chunk_en in enumerate(chunks, start=1):
            source_hash = sha256_str(chunk_en)
            rag_context, context_hash = build_rag_for_chunk(cursor, book_id, chunk_en)

            cursor.execute("""
                SELECT ChunkId, TargetVI, SourceHash, ContextHash
                FROM dbo.TranslationChunks
                WHERE ChapterId = ? AND ChunkIndex = ?
            """, (chapter_id, idx))
            c_row = cursor.fetchone()

            if c_row:
                chunk_id, target_vi, old_s_hash, old_c_hash = c_row
                # Nếu đoạn văn và ngữ cảnh không đổi và đã có bản dịch thì bỏ qua không dịch lại
                if target_vi and old_s_hash == source_hash and old_c_hash == context_hash:
                    continue
                cursor.execute("""
                    UPDATE dbo.TranslationChunks
                    SET SourceEN = ?, SourceHash = ?, ContextHash = ?, UpdatedAt = SYSUTCDATETIME()
                    WHERE ChunkId = ?
                """, (chunk_en, source_hash, context_hash, chunk_id))
            else:
                # Khởi tạo TargetVI = N'' và ModelName = N'pending' để thỏa mãn ràng buộc NOT NULL
                cursor.execute("""
                    INSERT INTO dbo.TranslationChunks
                        (ChapterId, ChunkIndex, SourceEN, TargetVI, SourceHash, ContextHash, ModelName)
                    OUTPUT INSERTED.ChunkId
                    VALUES (?, ?, ?, N'', ?, ?, N'pending')
                """, (chapter_id, idx, chunk_en, source_hash, context_hash))
                chunk_id = cursor.fetchone()[0]

            pending_payload.append({
                "chunk_id": chunk_id,
                "chapter": chapter_num,
                "chunk_index": idx,
                "source_hash": source_hash,
                "context_hash": context_hash,
                "rag_context": rag_context,
                "input": chunk_en
            })

        conn.commit()

    out_json = os.path.join(DRIVE_DIR, "input", "pending_chunks.json")
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(pending_payload, f, ensure_ascii=False, indent=2)
    print(f"Đã lưu {len(pending_payload)} đoạn vào dbo.TranslationChunks và xuất RAG JSON tại: {out_json}")

def update_translated_chunks_and_export_txt(chapter_num: int, book_id: int, out_txt_path: str):
    """Đọc kết quả từ Colab, cập nhật vào dbo.TranslationChunks và xuất file .txt hoàn chỉnh."""
    in_json = os.path.join(DRIVE_DIR, "output", "translated_chunks.json")
    with open(in_json, "r", encoding="utf-8") as f:
        results = json.load(f)

    with pyodbc.connect(CONN_STR) as conn:
        cursor = conn.cursor()
        for item in results:
            cursor.execute("""
                UPDATE dbo.TranslationChunks
                SET TargetVI = ?,
                    ModelName = ?,
                    InputTokens = ?,
                    OutputTokens = ?,
                    UpdatedAt = SYSUTCDATETIME()
                WHERE ChunkId = ?
            """, (
                item["output"],
                item.get("model_name", "Qwen3-4B-QLoRA"),
                item.get("input_tokens"),
                item.get("output_tokens"),
                item["chunk_id"]
            ))
        conn.commit()

        # Ghép toàn bộ các đoạn theo đúng thứ tự ChunkIndex để xuất ra file .txt
        cursor.execute("""
            SELECT tc.TargetVI
            FROM dbo.TranslationChunks tc
            JOIN dbo.Chapters ch ON tc.ChapterId = ch.ChapterId
            WHERE ch.BookId = ? AND ch.ChapterNumber = ?
            ORDER BY tc.ChunkIndex ASC
        """, (book_id, chapter_num))
        full_chapter_vi = "\n\n".join([r[0] for r in cursor.fetchall() if r[0]])

    with open(out_txt_path, "w", encoding="utf-8") as f:
        f.write(full_chapter_vi)
    print(f"Đã cập nhật SQL Server và xuất bản dịch chương {chapter_num} ra file: {out_txt_path}")