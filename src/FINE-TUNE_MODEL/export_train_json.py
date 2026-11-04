import json
import os
import pyodbc

CONN_STR = os.getenv(
    "SQL_CONN_STR",
    "Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=ContextTranslateDB;Trusted_Connection=yes;"
)
DRIVE_TRAIN_JSON = r"G:\My Drive\NovelAI\dataset\data_train.jsonl"

def export_sql_to_train_jsonl(book_id: int = 1, group_size: int = 8):
    with pyodbc.connect(CONN_STR) as conn:
        cursor = conn.cursor()

        # Truy vấn kết hợp TranslationExamples với Characters và PronounRules
        cursor.execute("""
            SELECT 
                te.ExampleId,
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
            ORDER BY te.ExampleId ASC
        """, (book_id,))

        rows = cursor.fetchall()
        if not rows:
            print("Không tìm thấy dữ liệu đã duyệt trong bảng dbo.TranslationExamples.")
            return

        records = []

        # 1. Tạo các mẫu JSON từng câu đơn (Khớp với sơ đồ JSON của bạn)
        for r in rows:
            pronouns_dict = {}
            if r.SelfPronoun:
                pronouns_dict["I"] = r.SelfPronoun
            if r.AddressPronoun:
                pronouns_dict["you"] = r.AddressPronoun

            single_item = {
                "instruction": "Dịch truyện tiếng Anh sang tiếng Việt",
                "context": {
                    "speaker": r.SpeakerName or "Narrator",
                    "listener": r.ListenerName or "Reader",
                    "scene": r.SceneState or "general",
                    "pronouns": pronouns_dict
                },
                "input": r.SourceEN,
                "output": r.TargetVI
            }
            records.append(single_item)

        # 2. Tạo thêm các mẫu JSON gộp đoạn (8 câu liên tiếp) để dạy AI giữ mạch văn dài
        for i in range(0, len(rows), group_size):
            batch = rows[i : i + group_size]
            if len(batch) < 2:
                continue

            active_rules = []
            seen_pairs = set()
            for b in batch:
                if b.SpeakerName and (b.SelfPronoun or b.AddressPronoun):
                    pair_key = (b.SpeakerName, b.ListenerName, b.SceneState)
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        active_rules.append({
                            "speaker": b.SpeakerName,
                            "listener": b.ListenerName or "Reader",
                            "scene": b.SceneState,
                            "pronouns": {
                                k: v for k, v in [("I", b.SelfPronoun), ("you", b.AddressPronoun)] if v
                            }
                        })

            grouped_item = {
                "instruction": "Dịch truyện tiếng Anh sang tiếng Việt",
                "context": {
                    "scene": "multi_line_paragraph",
                    "pronoun_rules": active_rules
                },
                "input": "\n".join([b.SourceEN for b in batch]),
                "output": "\n".join([b.TargetVI for b in batch])
            }
            records.append(grouped_item)

    os.makedirs(os.path.dirname(DRIVE_TRAIN_JSON), exist_ok=True)
    with open(DRIVE_TRAIN_JSON, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"Đã xuất {len(records)} mẫu huấn luyện (câu đơn + đoạn gộp) ra: {DRIVE_TRAIN_JSON}")

if __name__ == "__main__":
    export_sql_to_train_jsonl(book_id=1, group_size=8)