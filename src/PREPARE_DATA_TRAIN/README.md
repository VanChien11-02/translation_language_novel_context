# ctx_pipeline: Excel đã gán nhãn → SQL Server → file train / pending_chunks

## Cài đặt
```
pip install -r requirements.txt
```
Sửa `config.py`: `BOOK_KEY`, `BOOK_TITLE`, chuỗi kết nối `SQLSERVER_CONN` (hoặc đặt biến môi trường `CTX_CONN`).

## Lần đầu (chương 1–2)
```
python ctx.py init-db                                   # patch schema v3 (BACKUP DB trước; chạy trên bản sao trước)
python ctx.py import-annotations annotation_sheet_annotated.xlsx
python ctx.py sync-seeds                                # seed/*.csv|txt -> DB
python ctx.py build-context --out out                   # khung ChapterScenes + StoryEvents từ nhãn
python ctx.py qa-rules --out out                        # xưng hô trong bản dịch có khớp rule không? rule nào còn thiếu?
python ctx.py export-train --out out --val-chapters 2   # train.jsonl + val.jsonl + export_report.md
```
Hoặc một lệnh: `python ctx.py all --xlsx annotation_sheet_annotated.xlsx --val-chapters 2`.

Chạy thử không cần SQL Server: thêm `--sqlite file.db` TRƯỚC tên lệnh, hoặc `python selftest_sqlite.py <file.xlsx>`.

## Mỗi chương mới (tái sử dụng)
1. Tách và gán nhãn khung: `python align_clean.py --source chuong3.txt --chars-csv seed/characters.csv --out s3`
   (có thêm `--target ban_dich.txt` nếu đã có bản dịch). Mở `s3/annotation_sheet.xlsx`, sửa ô vàng, gõ `Y` ở cột `confirmed`.
2. `python ctx.py import-annotations s3/annotation_sheet.xlsx`
3. Nhân vật/rule/thuật ngữ mới: thêm dòng vào `seed/*.csv`, rồi `python ctx.py sync-seeds`.
4. `python ctx.py build-context` rồi `python ctx.py qa-rules`: điền các "khoá chưa có rule" còn thiếu.
5. Đã có bản dịch gold → `export-train` (thêm vào tập train). Chưa có bản dịch → `export-pending --chapter 3` sinh `pending_chunks_ch3.json`
   cho Notebook Inference (tạo luôn một dòng `TranslationJobs`).

Mọi lệnh **idempotent**: chạy lại không nhân đôi dữ liệu; sửa Excel/CSV rồi chạy lại để cập nhật.

## Ai là nguồn sự thật cho cái gì
| Dữ liệu | Nơi bạn sửa | Vào DB bằng |
|---|---|---|
| Nhãn từng đoạn (mode, speaker, listener, state, scene_break) + bản dịch | `annotation_sheet.xlsx` | `import-annotations` → `ChapterParagraphs` |
| Nhân vật (giới tính, ngôi 3 của người dẫn truyện) | `seed/characters.csv` | `sync-seeds` → `Characters` |
| Quy tắc xưng hô | `seed/pronoun_rules.csv` | `sync-seeds` → `PronounRules` |
| Thuật ngữ, tiếng động | `seed/glossary.csv` | `sync-seeds` → `GlossaryTerms` |
| Bối cảnh / thời gian / cảm xúc từng cảnh | `seed/scenes.csv` | `sync-seeds` → `ChapterScenes` |
| Văn phong chung | `seed/style_guide.txt` | `sync-seeds` → `Books.StyleGuide` |
| Điểm đổi xưng hô (sự kiện) | tự sinh | `build-context` → `StoryEvents` (+ `StoryEventCharacters`) |

### `pronoun_rules.csv`
Khoá = (speaker, listener, mode, state). `state` để `*` là mặc định cho mọi trạng thái; một dòng có state cụ thể (ví dụ `hostile`) là
**ngoại lệ** ghi đè mặc định. `listener` để trống = độc thoại / không rõ người nghe. Nhóm viết đúng như trong Excel (`Arona, Plana`).
Dòng `confirmed` khác `Y` được lưu nhưng KHÔNG dùng. Rule đổi theo thời gian: điền `start_chapter,start_para,end_chapter,end_para`
(End không bao gồm); hai rule đã duyệt cùng khoá không được chồng khoảng.

Vì nhãn trong Excel không nói đại từ nào được dùng, rule xưng hô **không thể tự suy ra**; tool chỉ tự sinh *điểm đổi xưng hô* (StoryEvents)
bằng cách so rule trước/sau khi `state` của một cặp đổi, và dùng các điểm đó để cắt chunk đúng chỗ.

## Đã kiểm chứng và chưa kiểm chứng
- Đã chạy thử đầu-cuối trên SQLite với `annotation_sheet_annotated.xlsx` (277 đoạn): import lần 2 "không đổi", sinh sự kiện, xuất train/val/pending.
- **CHƯA chạy trên SQL Server thật**: `sql/001_patch_v3.sql`, kết nối pyodbc, `OUTPUT INSERTED`. Hãy chạy `init-db` trên bản sao DB trước.
  Nếu schema v2 của bạn có UNIQUE trên PronounRules(BookId, SpeakerId, ListenerId, SceneState), nó sẽ chặn rule theo mode/khoảng thời gian:
  xem câu truy vấn chẩn đoán trong file SQL và DROP index cũ.
- `Books` chỉ được tạo khi chưa có `BookKey`; nếu bảng của bạn có cột NOT NULL khác (ví dụ `Genre`), `Session._ensure_book` cần thêm giá trị.

## Dùng file train trong Colab
Mỗi dòng `train.jsonl` có `context`, `paras`, `prev`, `examples`, `target`. Dựng chuỗi huấn luyện bằng đúng hàm của template:
```python
import json, prompt_template as PT
rows = [json.loads(l) for l in open("train.jsonl", encoding="utf-8")]
texts = [PT.build_train_text(tokenizer, r["context"], r["paras"], r["target"], r["prev"], r["examples"]) for r in rows]
```
`template_version` trong từng dòng phải bằng `PT.TEMPLATE_VERSION`. Inference dùng `PT.build_prompt_text(...)` với `pending_chunks.json`.
