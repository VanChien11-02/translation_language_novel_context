import json
import os
import pyodbc

CONN_STR = os.getenv(
    "SQL_CONN_STR",
    "Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=NovelTranslationDB;Trusted_Connection=yes;"
)
DRIVE_DIR = r"G:\My Drive\NovelAI"

SYSTEM_PROMPT = (
    "Bạn là dịch giả tiểu thuyết chuyên nghiệp. Hãy dịch đoạn văn tiếng Anh sang tiếng Việt mượt mà, "
    "giữ nguyên định dạng dấu ngoặc ('...' cho độc thoại nội tâm, 「...」 cho thông báo/tin tức) "
    "và tuân thủ tuyệt đối Bảng thuật ngữ & Xưng hô cũng như Văn phong mẫu được cung cấp."
)

def load_sql_metadata(cursor, book_id):
    # 1. Tải danh sách nhân vật
    cursor.execute("SELECT * FROM [Character] WHERE BookId = ?", (book_id,))
    c_cols = [col[0] for col in cursor.description]
    characters = [dict(zip(c_cols, row)) for row in cursor.fetchall()]

    # 2. Tải quy tắc xưng hô 2 chiều
    cursor.execute("""
        SELECT pr.*, c1.TranslatedName AS SpeakerName, c2.TranslatedName AS ListenerName
        FROM PronounRules pr
        JOIN [Character] c1 ON pr.SpeakerId = c1.CharacterId
        JOIN [Character] c2 ON pr.ListenerId = c2.CharacterId
        WHERE pr.BookId = ?
    """, (book_id,))
    r_cols = [col[0] for col in cursor.description]
    pronoun_rules = [dict(zip(r_cols, row)) for row in cursor.fetchall()]

    # 3. Tải kho đoạn văn mẫu phục vụ RAG
    cursor.execute("""
        SELECT ExampleId, GlossarySnippet, EnglishText, VietnameseText
        FROM TranslationExamples WHERE BookId = ?
    """, (book_id,))
    e_cols = [col[0] for col in cursor.description]
    examples = [dict(zip(e_cols, row)) for row in cursor.fetchall()]

    return characters, pronoun_rules, examples

def build_dynamic_rag_context(source_text, characters, pronoun_rules, examples, exclude_example_id=None):
    # Lọc nhân vật xuất hiện trong đoạn văn
    matched_ids = set()
    glossary_lines = []
    source_lower = source_text.lower()

    for char in characters:
        first_token = char["OriginalName"].split()[0].lower()
        if char["OriginalName"].lower() in source_lower or first_token in source_lower:
            matched_ids.add(char["CharacterId"])
            glossary_lines.append(
                f"- {char['OriginalName']} -> {char['TranslatedName']} "
                f"(Ngôi kể gọi là: '{char['DefaultAddressPronoun']}', tự xưng: '{char['DefaultSelfPronoun']}')"
            )

    # Lọc quy tắc xưng hô giữa các nhân vật có mặt trong đoạn
    for rule in pronoun_rules:
        if rule["SpeakerId"] in matched_ids and rule["ListenerId"] in matched_ids:
            glossary_lines.append(
                f"  + {rule['SpeakerName']} nói với {rule['ListenerName']}: "
                f"xưng '{rule['SelfPronoun']}' - gọi '{rule['TargetPronoun']}' ({rule['ContextNote'] or ''})"
            )

    glossary_block = "\n".join(glossary_lines) if glossary_lines else "Dịch tự nhiên theo ngữ cảnh tiểu thuyết."

    # Truy xuất RAG: Tìm 1 đoạn văn mẫu trong TranslationExamples có từ vựng/nhân vật gần giống nhất
    source_words = set(source_lower.split())
    best_score, best_ex = 0, None
    for ex in examples:
        if exclude_example_id and ex["ExampleId"] == exclude_example_id:
            continue
        overlap = len(source_words.intersection(set(ex["EnglishText"].lower().split())))
        if overlap > best_score:
            best_score, best_ex = overlap, ex

    rag_example_block = ""
    if best_ex:
        rag_example_block = (
            f"Bản gốc mẫu:\n{best_ex['EnglishText'][:400]}\n"
            f"Bản dịch chuẩn:\n{best_ex['VietnameseText'][:400]}"
        )

    return glossary_block, rag_example_block

def export_all_for_colab(book_id=1):
    with pyodbc.connect(CONN_STR) as conn:
        cursor = conn.cursor()
        characters, pronoun_rules, examples = load_sql_metadata(cursor, book_id)

        # A. Xuất file train_data.jsonl (Huấn luyện QLoRA học cách đọc ngữ cảnh RAG)
        train_path = os.path.join(DRIVE_DIR, "dataset", "train_data.jsonl")
        os.makedirs(os.path.dirname(train_path), exist_ok=True)
        with open(train_path, "w", encoding="utf-8") as f:
            for ex in examples:
                glossary_str, rag_sample = build_dynamic_rag_context(
                    ex["EnglishText"], characters, pronoun_rules, examples, exclude_example_id=ex["ExampleId"]
                )
                user_content = f"### 1. Bảng thuật ngữ & Xưng hô (SQL RAG):\n{glossary_str}\n\n"
                if rag_sample:
                    user_content += f"### 2. Văn phong mẫu tham khảo:\n{rag_sample}\n\n"
                user_content += f"### 3. Đoạn văn cần dịch:\n{ex['EnglishText']}"

                record = {
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                        {"role": "assistant", "content": ex["VietnameseText"]}
                    ]
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"Đã xuất {len(examples)} mẫu huấn luyện RAFT (RAG + QLoRA) ra: {train_path}")

        # B. Xuất file pending_chunks.json để dịch các chương mới
        cursor.execute("""
            SELECT tc.ChunkId, tc.ChapterId, tc.ChunkOrder, tc.SourceText
            FROM TranslationChunks tc
            JOIN Chapters ch ON tc.ChapterId = ch.ChapterId
            WHERE ch.BookId = ? AND tc.Status = 'Pending'
            ORDER BY ch.ChapterNumber ASC, tc.ChunkOrder ASC
        """, (book_id,))

        pending_payload = []
        for row in cursor.fetchall():
            glossary_str, rag_sample = build_dynamic_rag_context(
                row.SourceText, characters, pronoun_rules, examples
            )
            pending_payload.append({
                "ChunkId": row.ChunkId,
                "ChapterId": row.ChapterId,
                "ChunkOrder": row.ChunkOrder,
                "Glossary": glossary_str,
                "RagExample": rag_sample,
                "SourceText": row.SourceText
            })

        pending_path = os.path.join(DRIVE_DIR, "input", "pending_chunks.json")
        os.makedirs(os.path.dirname(pending_path), exist_ok=True)
        with open(pending_path, "w", encoding="utf-8") as f:
            json.dump(pending_payload, f, ensure_ascii=False, indent=2)
        print(f"Đã xuất {len(pending_payload)} chunks chờ dịch kèm ngữ cảnh RAG ra: {pending_path}")

if __name__ == "__main__":
    export_all_for_colab(book_id=1)