import json
import os
import pyodbc

CONN_STR = os.getenv(
    "SQL_CONN_STR",
    "Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=ContextTranslateDB;Trusted_Connection=yes;"
)
DRIVE_OUTPUT_JSON = r"G:\My Drive\NovelAI\output\translated_chunks.json"

def sync_json_to_sql_and_export_txt(book_id: int, chapter_num: int, output_txt_path: str):
    if not os.path.exists(DRIVE_OUTPUT_JSON):
        print(f"Không tìm thấy file kết quả tại: {DRIVE_OUTPUT_JSON}")
        return

    with open(DRIVE_OUTPUT_JSON, "r", encoding="utf-8") as f:
        translated_list = json.load(f)

    with pyodbc.connect(CONN_STR) as conn:
        cursor = conn.cursor()
        updated_count = 0

        # 1. Cập nhật từng bản dịch và thống kê Token vào bảng dbo.TranslationChunks
        for item in translated_list:
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
                item.get("input_tokens", 0),
                item.get("output_tokens", 0),
                item["chunk_id"]
            ))
            updated_count += 1

        conn.commit()
        print(f"Đã cập nhật {updated_count} đoạn dịch vào bảng dbo.TranslationChunks.")

        # 2. Lấy toàn bộ các đoạn của chương theo thứ tự ChunkIndex để ghép thành file .txt hoàn chỉnh
        cursor.execute("""
            SELECT ch.Title, tc.ChunkIndex, tc.TargetVI, tc.InputTokens, tc.OutputTokens
            FROM dbo.TranslationChunks tc
            JOIN dbo.Chapters ch ON tc.ChapterId = ch.ChapterId
            WHERE ch.BookId = ? AND ch.ChapterNumber = ?
            ORDER BY tc.ChunkIndex ASC
        """, (book_id, chapter_num))

        rows = cursor.fetchall()
        if not rows:
            print(f"Không tìm thấy dữ liệu của Chương {chapter_num} trong SQL Server.")
            return

        chapter_title = rows[0][0] or f"Chương {chapter_num}"
        paragraphs = [r[2] for r in rows if r[2] and r[2].strip()]
        total_in = sum(r[3] or 0 for r in rows)
        total_out = sum(r[4] or 0 for r in rows)

        full_vietnamese_text = f"{chapter_title}\n\n" + "\n\n".join(paragraphs)

        with open(output_txt_path, "w", encoding="utf-8") as out_f:
            out_f.write(full_vietnamese_text)

        print(f"Đã xuất bản dịch hoàn chỉnh ({len(paragraphs)} đoạn) ra file: {output_txt_path}")
        print(f"Tổng Token tiêu thụ của Chương {chapter_num}: Input = {total_in:,} | Output = {total_out:,}")

if __name__ == "__main__":
    sync_json_to_sql_and_export_txt(
        book_id = 1,
        chapter_num = 3,
        output_txt_path = "chap_03_vi.txt"
    )