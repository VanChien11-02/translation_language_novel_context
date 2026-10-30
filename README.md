# ContextTranslate – Few-shot + Retrieval (Blue Archive)

Bản thực hành Python cho Windows. **Đọc chương nào, dịch chương đó**. Không có giao diện popup; phiên bản này tập trung vào thuật toán context/RAG và an toàn chi phí.

## 1) Cài đặt

```powershell
cd contexttranslate_fewshot_rag
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Mở `.env`, điền `GEMINI_API_KEY`. Tạo key: https://aistudio.google.com/api-keys. Đừng commit `.env` lên GitHub.

## 2) Tìm hiểu ví dụ từ 2 tài liệu đã tải lên

File `data/examples.jsonl` đã gồm 10 cặp câu Anh-Việt được **ghép thủ công theo đúng vị trí** giữa `bản gốc.docx` và `đoạn dịch ngắn.docx`. Các ví dụ giữ bản dịch gốc, **chưa kiểm duyệt lỗi biên tập**. Những phần không có bản tiếng Anh gốc không được tự tạo cặp.

Nếu bạn có 2 file gốc tại cùng một chỗ, có thể tạo lại bằng:

```powershell
python build_pairs.py --original "bản gốc.docx" --translated "đoạn dịch ngắn.docx"
```

Bạn nên tự sửa các ví dụ trong `data/examples.jsonl` trước khi dùng cho truyện dài. Mỗi dòng là một JSON độc lập, có `en`, `vi`, `speaker`, `listener`, `scene` và `reviewed`.

## 3) Few-shot + Context Retrieval

- `data/book_profile.json`: tên truyện, glossary và quy tắc xưng hô theo từng cảnh.
- `data/examples.jsonl`: kho ví dụ song ngữ.
- `retrieve_examples()`: chấm điểm theo người nói, người nghe, trạng thái cảnh và các từ tiếng Anh trùng nhau. Lấy 3 ví dụ gần nhất. Đây là một dạng *retrieval-augmented generation* cơ bản, **chưa có embedding hoặc vector DB**.
- `prompt_for()`: trộn profile + 3 ví dụ + đoạn trước + đoạn cần dịch rồi gửi model.

Test *không tốn API*:

```powershell
python translate.py --text "Why did you want me dead?" --speaker Yuuka --listener Sensei --scene hostile --dry-run
python -m unittest discover -s tests -v
```

Dịch thật (một đoạn):

```powershell
python translate.py --text "Why did you want me dead?" --speaker Yuuka --listener Sensei --scene hostile --chapter demo
```

**Lưu ý:** khi dịch đoạn hội thoại có NHIỀU nhân vật, KHÔNG đặt một `--speaker`/`--listener` áp dụng cả đoạn. Hãy để trống và đưa đủ lời dẫn để AI tự nhận diện hoặc chia đoạn theo từng người nói.

## 4) Dịch cả một chương khi đang đọc

Tạo file UTF-8 `chapter_01.txt`, chỉ chứa **chương đang đọc**. Không đưa toàn bộ sách chưa đọc vào prompt.

```powershell
python translate.py --input chapter_01.txt --chapter 1 --dry-run
python translate.py --input chapter_01.txt --chapter 1
```

Hoặc dùng file Word của **một chương**:

```powershell
python translate.py --input chapter_01.docx --chapter 1
```

Bản dịch được ghi vào `output/chapter_1.txt` ngay sau mỗi đoạn. Checkpoint `output/chapter_1.progress.json` giúp tiếp tục khi ngắt hoặc gặp quota. Nếu nội dung file đổi, phải đổi `--chapter` hoặc xử lý checkpoint cũ để tránh trộn bản dịch.

**Rất quan trọng:** file `bản gốc.docx` đã tải lên chứa cả cuối chương 1 và chương 2; đừng chỉ định nó là `chapter_01.docx` rồi mặc nhiên coi đó là một chương. Hãy tách chương trước.

## 5) Theo dõi và giới hạn chi phí

Biến `.env`:

- `GEMINI_MODEL`: model API đang dùng.
- `PRICE_INPUT_PER_M`, `PRICE_OUTPUT_PER_M`: giá 1 triệu token, thay đổi theo bảng giá mới nhất.
- `MAX_RUN_USD`: **chỉ là mức chặn ước lượng cục bộ trong lần chạy**, không phải hạn mức chi tiêu chính thức của Google; không bảo đảm tuyệt đối chi phí.

Sau mỗi request, console hiển thị token thật do API báo và chi phí ước tính. Lưu ý token tính phí đầu ra có thể bao gồm thinking tokens; SDK có thể báo usage khác nhau tùy API/model. Cache trong `data/cache.json` tránh trả tiền hai lần cho cùng ngữ cảnh, model và đoạn nguồn. Thay đổi ngữ cảnh -> key khác.

API có giới hạn RPM, TPM, RPD theo project. Lỗi 429 sẽ thử lại tối đa 4 lần; nếu quota theo ngày đã hết, tool dừng và bạn chạy lại sau. Không có bảo đảm có thể sử dụng API miễn phí vô hạn.

## 6) Nâng cấp sau khi chạy ổn

1. Kiểm tra và sửa 20–50 cặp mẫu chất lượng cao.
2. Lưu thêm `scene_summary` + `character_state` khi đọc xong từng cảnh, **không đọc trước chương tương lai**.
3. Dùng SQLite thay JSON để lưu lịch sử, kiểm soát revision.
4. Khi tập ví dụ tăng lên hàng nghìn, nâng retrieval từ chấm điểm metadata/keyword sang multilingual embeddings + vector search (FAISS / SQLite extension).
5. Viết extension chỉ dùng để lấy DOM xung quanh đoạn bôi đen; Python backend xử lý profile, prompt, API, cache.

Đây là bản demo học tập, chưa có tự động phân tích thay đổi quan hệ ở từng cảnh và không bảo đảm phát hiện mọi câu thoại sai xưng hô. Hãy kiểm tra kết quả trước khi lưu làm ví dụ chuẩn.
