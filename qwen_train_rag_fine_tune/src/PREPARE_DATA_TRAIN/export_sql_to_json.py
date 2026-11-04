import json
import os
import pyodbc

CONN_STR = os.getenv(
    "SQL_CONN_STR",
    "Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=NovelTranslateDB;Trusted_Connection=yes;"
)

def export_sql_to_structured_json(book_id=1, output_file=r"G:\My Drive\NovelAI\dataset\train_structured.jsonl"):
    with pyodbc.connect(CONN_STR) as conn:
        cursor = conn.cursor()
        # Tự động JOIN bảng câu mẫu với bảng Nhân vật và bảng Quy tắc xưng hô
        cursor.execute("""
            SELECT 
                c1.Name AS SpeakerName,
                c2.Name AS ListenerName,
                te.SceneState,
                pr.SelfPronoun,
                pr.AddressPronoun,
                te.SourceEN,
                te.TargetVI
            FROM dbo.TranslationExamples te
            LEFT JOIN dbo.Characters c1 
                ON te.BookId = c1.BookId AND te.SpeakerId = c1.CharacterId
            LEFT JOIN dbo.Characters c2 
                ON te.BookId = c2.BookId AND te.ListenerId = c2.CharacterId
            LEFT JOIN dbo.PronounRules pr 
                ON te.BookId = pr.BookId 
                AND te.SpeakerId = pr.SpeakerId 
                AND te.ListenerId = pr.ListenerId 
                AND te.SceneState = pr.SceneState
            WHERE te.BookId = ? AND te.IsApproved = 1
        """, (book_id,))

        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        count = 0
        with open(output_file, "w", encoding="utf-8") as f:
            for row in cursor.fetchall():
                # Tạo khối pronouns động từ bảng PronounRules
                pronouns_dict = {}
                if row.SelfPronoun:
                    pronouns_dict["I"] = row.SelfPronoun
                if row.AddressPronoun:
                    pronouns_dict["you"] = row.AddressPronoun

                # Đóng gói đúng định dạng JSON như trong ảnh của bạn
                record = {
                    "instruction": "Dịch truyện tiếng Anh sang tiếng Việt",
                    "context": {
                        "speaker": row.SpeakerName or "Narrator",
                        "listener": row.ListenerName or "Reader",
                        "scene": row.SceneState,
                        "pronouns": pronouns_dict
                    },
                    "input": row.SourceEN,
                    "output": row.TargetVI
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

        print(f"Đã xuất {count} mẫu JSON từ SQL Server ra: {output_file}")

if __name__ == "__main__":
    export_sql_to_structured_json(book_id=1)