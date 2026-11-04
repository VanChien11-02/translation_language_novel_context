import hashlib
import json
import os
import re
import pandas as pd
import pyodbc

CONN_STR = os.getenv(
    "SQL_CONN_STR",
    "Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=NovelTranslateDB;Trusted_Connection=yes;"
)
CSV_PATH = "novel_pairs_draft.csv"
DRIVE_TRAIN_JSONL = r"G:\My Drive\Colab Notebooks\AI_translation\dataset\train_data.jsonl"

def clean_text(text, is_vi=False):
    if pd.isna(text):
        return ""
    text = str(text).replace("\xa0", " ").strip()
    if is_vi:
        # Xóa ghi chú (TL: ...) ở dòng index 5
        text = re.sub(r"\s*\(TL:.*?\)", "", text)
    # Đồng nhất dấu ngoặc kép
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return text.strip()

def sha256_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def step1_seed_sql_from_csv():
    df = pd.read_csv(CSV_PATH)
    df["source_en"] = df["source_en"].apply(lambda x: clean_text(x, is_vi=False))
    df["target_vi"] = df["target_vi"].apply(lambda x: clean_text(x, is_vi=True))

    with pyodbc.connect(CONN_STR) as conn:
        cursor = conn.cursor()

        # 1. Tạo hoặc lấy BookId trong bảng dbo.Books
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
                "Ngôi kể thứ 3 gọi Sensei là 'anh'. Giữ nguyên dấu '...' cho suy nghĩ nội tâm và 「...」 cho thông báo/tin tức."
            ))
            book_id = cursor.fetchone()[0]

        # 2. Nạp danh sách nhân vật vào dbo.Characters (Bao gồm cả nhóm 'Arona/Plana' trong CSV)
        characters_meta = {
            "Sensei": "Giáo viên cố vấn của Schale, ngôi kể gọi là 'anh', độc thoại tự xưng 'mình'",
            "Yuuka": "Học sinh trường Millennium, đang bị thao túng ký ức thù địch với Sensei",
            "Black Suit": "Thành viên Gematria gọi điện cảnh báo cho Sensei",
            "Arona": "AI trong Shittim Chest, xưng 'em', gọi 'Sensei/thầy'",
            "Plana": "AI trong Shittim Chest, xưng 'em', gọi 'Sensei/thầy'",
            "Arona/Plana": "Khi Sensei trò chuyện chung với cả hai AI Arona và Plana cùng lúc"
        }

        char_id_map = {}
        for name, notes in characters_meta.items():
            cursor.execute("SELECT CharacterId FROM dbo.Characters WHERE BookId = ? AND Name = ?", (book_id, name))
            c_row = cursor.fetchone()
            if c_row:
                char_id_map[name] = c_row[0]
            else:
                cursor.execute("""
                    INSERT INTO dbo.Characters (BookId, Name, Notes)
                    OUTPUT INSERTED.CharacterId
                    VALUES (?, ?, ?)
                """, (book_id, name, notes))
                char_id_map[name] = cursor.fetchone()[0]

        # 3. Nạp bảng dbo.PronounRules khớp với các SceneState trong CSV
        rules_data = [
            ("Sensei", "Yuuka", "worried", "thầy", "em / Yuuka", "Sensei lo lắng hỏi thăm Yuuka qua điện thoại"),
            ("Yuuka", "Sensei", "hostile", "ta / tôi", "ngươi", "Yuuka bị thao túng ký ức, lạnh lùng thù địch"),
            ("Black Suit", "Sensei", "warning", "tôi", "anh / Sensei", "Black Suit nghiêm túc cảnh báo nguy hiểm"),
            ("Sensei", "Black Suit", "warning", "tôi", "ngươi / Black Suit", "Sensei đề phòng nói chuyện với Black Suit"),
            ("Plana", "Sensei", "urgent", "em", "Sensei / thầy", "Plana thúc giục Sensei chạy trốn khẩn cấp"),
            ("Arona", "Sensei", "urgent", "em", "Sensei / thầy", "Arona lo lắng cho sự an toàn của Sensei"),
            ("Sensei", "Arona/Plana", "urgent", "thầy", "hai người / hai em", "Sensei nói với cả Arona và Plana"),
            ("Sensei", "Arona", "normal", "thầy", "em / Arona", "Giao tiếp bình thường")
        ]

        for spk, lst, scene, self_p, addr_p, note in rules_data:
            spk_id, lst_id = char_id_map[spk], char_id_map[lst]
            cursor.execute("""
                IF NOT EXISTS (
                    SELECT 1 FROM dbo.PronounRules
                    WHERE BookId = ? AND SpeakerId = ? AND ListenerId = ? AND SceneState = ?
                )
                INSERT INTO dbo.PronounRules (BookId, SpeakerId, ListenerId, SceneState, SelfPronoun, AddressPronoun, Notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (book_id, spk_id, lst_id, scene, book_id, spk_id, lst_id, scene, self_p, addr_p, note))

        # 4. Nạp 85 dòng từ CSV vào dbo.TranslationExamples (Bật IsApproved = 1 cho các dòng đã làm sạch)
        inserted_count = 0
        for _, r in df.iterrows():
            # Bỏ qua các dòng chỉ có dấu chấm lửng như ".........." khi đưa vào kho RAG
            if len(r["source_en"].strip('." ')) == 0:
                continue

            spk_id = char_id_map.get(r["speaker"]) if pd.notna(r["speaker"]) else None
            lst_id = char_id_map.get(r["listener"]) if pd.notna(r["listener"]) else None
            scene_state = r["scene"] if pd.notna(r["scene"]) else "general"
            ex_key = sha256_hash(f"{r['source_en']}||{r['target_vi']}")

            cursor.execute("""
                IF NOT EXISTS (SELECT 1 FROM dbo.TranslationExamples WHERE BookId = ? AND ExampleKey = ?)
                INSERT INTO dbo.TranslationExamples
                    (BookId, ExampleKey, SpeakerId, ListenerId, SceneState, SourceEN, TargetVI, IsApproved)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """, (book_id, ex_key, book_id, ex_key, spk_id, lst_id, scene_state, r["source_en"], r["target_vi"]))
            inserted_count += 1

        conn.commit()
        print(f"Đã nạp thành công {inserted_count} câu mẫu vào dbo.TranslationExamples (BookId={book_id})!")
        return book_id, df

def step2_export_grouped_jsonl_for_colab(df, group_size=10):
    # Gom mỗi 10 dòng liên tiếp trong cùng 1 chương thành 1 đoạn văn hoàn chỉnh để Fine-tune Qwen3-4B
    os.makedirs(os.path.dirname(DRIVE_TRAIN_JSONL), exist_ok=True)
    system_prompt = (
        "Bạn là dịch giả tiểu thuyết chuyên nghiệp. Hãy dịch đoạn văn tiếng Anh sang tiếng Việt mượt mà, "
        "giữ nguyên dấu '...' cho độc thoại nội tâm, dấu 「...」 cho thông báo và tuân thủ đúng quy tắc xưng hô."
    )
    glossary_block = (
        "- Sensei: ngôi kể gọi là 'anh', độc thoại xưng 'mình', nói với học sinh xưng 'thầy' - gọi 'em'\n"
        "- Yuuka (SceneState=hostile): gọi Sensei là 'ngươi'\n"
        "- Black Suit (SceneState=warning): xưng 'tôi' - gọi Sensei là 'anh'\n"
        "- Arona, Plana: xưng 'em' - gọi Sensei là 'Sensei / thầy'"
    )

    sample_count = 0
    with open(DRIVE_TRAIN_JSONL, "w", encoding="utf-8") as f:
        for chap_num, group_df in df.groupby("chapter"):
            rows = group_df.to_dict("records")
            for i in range(0, len(rows), group_size):
                batch = rows[i : i + group_size]
                en_paragraph = "\n".join([item["source_en"] for item in batch])
                vi_paragraph = "\n".join([item["target_vi"] for item in batch])

                record = {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"### Bảng thuật ngữ & Xưng hô (SQL RAG):\n{glossary_block}\n\n### Đoạn văn cần dịch:\n{en_paragraph}"},
                        {"role": "assistant", "content": vi_paragraph}
                    ]
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                sample_count += 1

    print(f"Done")

if __name__ == "__main__":
    book_id, cleaned_df = step1_seed_sql_from_csv()
    step2_export_grouped_jsonl_for_colab(cleaned_df, group_size=10)