import hashlib
import os
import pandas as pd
import pyodbc

# Chuỗi kết nối vào ContextTranslateDB trên SQL Server
CONN_STR = os.getenv(
    "SQL_CONN_STR",
    "Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=ContextTranslateDB;Trusted_Connection=yes;"
)

CSV_FILE_PATH = "novel_pairs_complete.csv"  # Hoặc novel_pairs_draft.csv sau khi bạn duyệt trên Excel

def get_sha256_hash(text: str) -> str:
    """Tạo mã băm 64 ký tự chuẩn CHAR(64) cho cột ExampleKey."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def get_or_create_character(cursor, book_id: int, char_name: str, cache: dict):
    """Tự động lấy CharacterId hoặc tạo mới trong dbo.Characters nếu tên nhân vật chưa tồn tại."""
    if pd.isna(char_name) or not str(char_name).strip():
        return None
    
    clean_name = str(char_name).strip()
    if clean_name in cache:
        return cache[clean_name]

    cursor.execute(
        "SELECT CharacterId FROM dbo.Characters WHERE BookId = ? AND Name = ?",
        (book_id, clean_name)
    )
    row = cursor.fetchone()
    if row:
        cache[clean_name] = row[0]
        return row[0]

    # Nếu nhân vật mới xuất hiện trong CSV, tự động thêm vào bảng dbo.Characters
    cursor.execute("""
        INSERT INTO dbo.Characters (BookId, Name, Notes)
        OUTPUT INSERTED.CharacterId
        VALUES (?, ?, N'Tự động thêm từ file CSV')
    """, (book_id, clean_name))
    new_id = cursor.fetchone()[0]
    cache[clean_name] = new_id
    print(f"  [+] Đã thêm nhân vật mới vào dbo.Characters: {clean_name} (ID={new_id})")
    return new_id

def import_csv_to_context_translate_db(csv_path: str):
    df = pd.read_csv(csv_path)

    with pyodbc.connect(CONN_STR) as conn:
        cursor = conn.cursor()

        # 1. Lấy hoặc tạo bộ truyện trong bảng dbo.Books
        book_key = "blue_archive_hatred_begins"
        cursor.execute("SELECT BookId FROM dbo.Books WHERE BookKey = ?", (book_key,))
        row = cursor.fetchone()
        if row:
            book_id = row[0]
        else:
            cursor.execute("""
                INSERT INTO dbo.Books (BookKey, Title, Genre, StyleGuide)
                OUTPUT INSERTED.BookId
                VALUES (?, ?, ?, ?)
            """, (
                book_key,
                "Blue Archive: Nơi Mọi Thù Hận Bắt Đầu",
                "Dark Fantasy / Action Fanfic",
                "Ngôi kể thứ 3 gọi Sensei là 'anh'. Độc thoại nội tâm dùng dấu '...' và xưng 'mình'. Thông báo dùng dấu 「...」."
            ))
            book_id = cursor.fetchone()[0]

        char_cache = {}
        inserted_examples = 0
        updated_examples = 0

        # 2. Đồng bộ danh sách số chương (chapter) từ CSV vào bảng dbo.Chapters
        for chap_num in sorted(df["chapter"].dropna().unique()):
            chap_int = int(chap_num)
            cursor.execute("""
                IF NOT EXISTS (SELECT 1 FROM dbo.Chapters WHERE BookId = ? AND ChapterNumber = ?)
                INSERT INTO dbo.Chapters (BookId, ChapterNumber, Title)
                VALUES (?, ?, ?)
            """, (book_id, chap_int, book_id, chap_int, f"Chương {chap_int}"))

        # 3. Duyệt từng dòng CSV và đẩy vào bảng dbo.TranslationExamples
        for idx, r in df.iterrows():
            source_en = str(r["source_en"]).strip() if pd.notna(r["source_en"]) else ""
            target_vi = str(r["target_vi"]).strip() if pd.notna(r["target_vi"]) else ""
            if not source_en or not target_vi:
                continue

            speaker_id = get_or_create_character(cursor, book_id, r.get("speaker"), char_cache)
            listener_id = get_or_create_character(cursor, book_id, r.get("listener"), char_cache)
            scene_state = str(r["scene"]).strip() if pd.notna(r.get("scene")) and str(r["scene"]).strip() else "general"
            is_approved = 1 if int(r.get("human_reviewed", 0)) == 1 else 0

            # Băm cặp câu gốc - dịch để làm khóa chống trùng ExampleKey CHAR(64)
            example_key = get_sha256_hash(f"{source_en}||{target_vi}")

            cursor.execute("""
                SELECT ExampleId FROM dbo.TranslationExamples
                WHERE BookId = ? AND ExampleKey = ?
            """, (book_id, example_key))
            existing = cursor.fetchone()

            if existing:
                # Nếu câu đã tồn tại, cập nhật lại SpeakerId, ListenerId, SceneState và cờ IsApproved mới nhất từ Excel
                cursor.execute("""
                    UPDATE dbo.TranslationExamples
                    SET SpeakerId = ?, ListenerId = ?, SceneState = ?, IsApproved = ?
                    WHERE ExampleId = ?
                """, (speaker_id, listener_id, scene_state, is_approved, existing[0]))
                updated_examples += 1
            else:
                cursor.execute("""
                    INSERT INTO dbo.TranslationExamples
                        (BookId, ExampleKey, SpeakerId, ListenerId, SceneState, SourceEN, TargetVI, IsApproved)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (book_id, example_key, speaker_id, listener_id, scene_state, source_en, target_vi, is_approved))
                inserted_examples += 1

        conn.commit()
        print(f"Hoàn tất! Đã thêm mới {inserted_examples} dòng và cập nhật {updated_examples} dòng vào dbo.TranslationExamples.")

if __name__ == "__main__":
    import_csv_to_context_translate_db(CSV_FILE_PATH)