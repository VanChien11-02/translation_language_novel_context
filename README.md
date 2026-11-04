# ContextTranslate — Hệ thống Dịch Tiểu Thuyết AI (SQL Server RAG + Qwen3-4B QLoRA)

Hệ thống dịch tiểu thuyết Anh – Việt tự động kết hợp cơ sở dữ liệu **SQL Server (ContextTranslateDB)** để quản lý ngữ cảnh động (nhân vật, ma trận xưng hô theo trạng thái cảm xúc, câu mẫu đã duyệt, mã băm chống dịch lặp) cùng mô hình **Qwen3-4B-Instruct** được tinh chỉnh bằng **Unsloth QLoRA 4-bit** trên **Google Colab GPU T4** thông qua cầu nối đồng bộ **Google Drive**.

---

## 1. Kiến trúc tổng thể (4 Giai đoạn khép kín)

```text
[GIAI ĐOẠN 1: PREPARE DATA TRAIN]
Bản gốc (.txt/.docx) + Bản dịch mẫu (.txt/.docx)
   │  (1. Align & Clean bằng Python)
   ▼
File CSV nháp (source_en, target_vi, chapter, speaker, listener, scene, human_reviewed)
   │  (2. Kiểm duyệt trên Excel -> bật human_reviewed = 1)
   ▼
SQL Server (ContextTranslateDB: Books, Characters, PronounRules, TranslationExamples)
   │  (3. JOIN & Export JSONL)
   ▼
data_train.jsonl (Đồng bộ lên Google Drive)

[GIAI ĐOẠN 2: FINE-TUNE MODEL TRÊN GOOGLE COLAB]
data_train.jsonl + Base Model (Qwen3-4B-Instruct 4-bit)
   │  (Huấn luyện bằng Unsloth QLoRA + train_on_responses_only)
   ▼
LoRA Adapter (~100MB lưu cố định trên Google Drive)

[GIAI ĐOẠN 3: TRANSLATE NEW CHAPTER (SQL RAG + QLORA)]
Chương mới tiếng Anh (.txt/.docx)
   │  (1. Chia đoạn thông minh + Tính SourceHash & ContextHash)
   ▼
Nhánh 3A: AI Context Analyzer (Phát hiện nhân vật mới & sự kiện đổi ngôi xưng SceneState)
   │  (2. Truy xuất SQL RAG: StyleGuide + PronounRules + Few-shot Examples đã duyệt)
   ▼
pending_chunks.json ──(Google Colab GPU T4 + LoRA Adapter)──► translated_chunks.json
   │  (3. Cập nhật TargetVI, InputTokens, OutputTokens vào bảng TranslationChunks)
   ▼
Bản dịch hoàn chỉnh (.txt)

[GIAI ĐOẠN 4: VÒNG LẶP HẬU KIỂM & CẢI THIỆN MODEL (ACTIVE LEARNING)]
Người dùng sửa lỗi bản dịch (ReviewedVI <> TargetVI)
   ├──► Ngắn hạn (0 phút): Tự động nạp câu đã sửa vào TranslationExamples (IsApproved = 1) làm RAG mẫu ngay cho chương sau.
   └──► Dài hạn (Định kỳ): Xuất lại data_train.jsonl để Fine-tune nâng cấp LoRA Adapter.
```

---

## 2. Yêu cầu hệ thống

- **Cơ sở dữ liệu:** SQL Server Database Engine đang chạy và SQL Server Management Studio (SSMS).
- **Trình điều khiển kết nối:** Microsoft ODBC Driver 17 hoặc ODBC Driver 18 for SQL Server.
- **Môi trường máy cá nhân:** Windows, Python >= 3.10, ứng dụng **Google Drive for Desktop** (ánh xạ Google Drive thành ổ đĩa cục bộ, ví dụ `G:\My Drive\NovelAI`).
- **Môi trường huấn luyện & suy luận AI:** Tài khoản Google Colab (sử dụng GPU T4 miễn phí).

---

## 3. Cấu trúc thư mục dự án

### Trên máy tính cá nhân (Local Repo)
- `sql/01_schema.sql`: Kịch bản khởi tạo cơ sở dữ liệu `ContextTranslateDB` và 6 bảng cốt lõi.
- `generate_draft_csv.py`: Tách câu từ file gốc và bản dịch, tự động gợi ý nhãn nhân vật và xuất file CSV nháp.
- `import_csv_to_sql.py`: Đồng bộ file CSV đã kiểm duyệt trên Excel vào các bảng trong SQL Server.
- `stage2_step1_export_train_json.py`: Kết xuất các câu mẫu `IsApproved = 1` kèm ngữ cảnh xưng hô ra file `data_train.jsonl`.
- `stage3_step1_export_rag.py`: Băm chương tiếng Anh mới thành các đoạn nhỏ, truy xuất ngữ cảnh RAG và xuất `pending_chunks.json`.
- `stage3_step3_sync_and_merge.py`: Đọc kết quả từ Colab, cập nhật `TargetVI` và thống kê Token vào SQL Server, ghép thành file `.txt` hoàn chỉnh.
- `stage4_feedback_loop.py`: Thu hoạch các câu do người dùng sửa lỗi (`ReviewedVI`) đưa ngược về bảng `TranslationExamples`.
- `Qwen3_4B_Novel_Translation_RAG_QLoRA.ipynb`: Notebook chạy trên Google Colab cho Giai đoạn 2 và Giai đoạn 3.

### Trên Google Drive (`/MyDrive/NovelAI/`)
- `dataset/data_train.jsonl`: Dữ liệu huấn luyện xuất từ SQL Server.
- `lora_adapter/`: Nơi lưu trữ bộ trọng số QLoRA sau khi Fine-tune.
- `input/pending_chunks.json`: Gói dữ liệu các đoạn văn chờ dịch kèm ngữ cảnh SQL RAG.
- `output/translated_chunks.json`: Kết quả dịch và số lượng token tiêu thụ do Colab trả về.

---

## 4. Hướng dẫn cài đặt & Khởi tạo Database

### Bước 1: Tạo cơ sở dữ liệu trong SSMS
1. Mở **SSMS**, đăng nhập vào SQL Server.
2. Mở file `sql/01_schema.sql` và nhấn **Execute (F5)**.
3. Kiểm tra trong `Databases -> ContextTranslateDB -> Tables` đảm bảo đã có đủ 6 bảng:
   - `dbo.Books`: Lưu thông tin truyện (`BookKey`, `Title`, `Genre`, `StyleGuide`).
   - `dbo.Characters`: Danh sách nhân vật theo từng bộ truyện.
   - `dbo.PronounRules`: Ma trận xưng hô 2 chiều (`SpeakerId`, `ListenerId`, `SceneState`, `SelfPronoun`, `AddressPronoun`).
   - `dbo.TranslationExamples`: Kho câu dịch mẫu Anh – Việt có cờ kiểm duyệt `IsApproved`.
   - `dbo.Chapters`: Quản lý danh sách chương và bản tóm tắt diễn biến (`SummaryVI`).
   - `dbo.TranslationChunks`: Lưu từng đoạn dịch, mã băm `SourceHash`, `ContextHash`, tên mô hình `ModelName` và số lượng `InputTokens`, `OutputTokens`.

*(Lưu ý: File SQL chứa lệnh `GO`, bắt buộc chạy trực tiếp trong SSMS hoặc `sqlcmd`, không chạy nguyên file qua `cursor.execute()` của `pyodbc`).*

### Bước 2: Cài đặt thư viện Python dưới máy cá nhân
Mở PowerShell tại thư mục dự án:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install pandas pyodbc python-docx
Copy-Item .env.example .env
```

### Bước 3: Cấu hình kết nối trong file `.env`
```dotenv
SQL_SERVER=localhost
SQL_DATABASE=ContextTranslateDB
SQL_DRIVER=ODBC Driver 18 for SQL Server
SQL_TRUST_SERVER_CERTIFICATE=yes
SQL_USER=
SQL_PASSWORD=
DRIVE_BASE_DIR=G:\My Drive\NovelAI
```
- Nếu dùng **Windows Authentication**, để trống `SQL_USER` và `SQL_PASSWORD`.
- Nếu dùng **SQL Express**, đổi `SQL_SERVER=localhost` thành `SQL_SERVER=.\SQLEXPRESS`.

---

## 5. Quy trình vận hành từng giai đoạn

### Giai đoạn 1: Chuẩn bị dữ liệu huấn luyện (Prepare Data Train)
1. **Tạo file CSV nháp từ bản gốc và bản dịch mẫu:**
   ```powershell
   python generate_draft_csv.py
   ```
2. **Kiểm duyệt trên Excel:** Mở file CSV sinh ra, lọc các dòng có `human_reviewed = 0`, kiểm tra cột `speaker`, `listener`, `scene` (`worried`, `hostile`, `urgent`, `warning`, `monologue`, `normal`) rồi đổi `human_reviewed` thành `1`.
3. **Nạp CSV vào SQL Server và xuất JSONL lên Google Drive:**
   ```powershell
   python import_csv_to_sql.py
   python stage2_step1_export_train_json.py
   ```

### Giai đoạn 2: Tinh chỉnh mô hình trên Google Colab (Fine-tune QLoRA)
1. Tải file `Qwen3_4B_Novel_Translation_RAG_QLoRA.ipynb` lên Google Colab và chọn **Runtime -> Change runtime type -> T4 GPU**.
2. Chạy ô **Bước 1** để kết nối Google Drive và ô **Giai đoạn 2** để huấn luyện `Qwen3-4B-Instruct` với dữ liệu từ `data_train.jsonl`.
3. Sau khi hoàn tất, bộ trọng số LoRA (~100MB) được lưu tự động vào `/MyDrive/NovelAI/lora_adapter/`.

### Giai đoạn 3: Dịch chương mới kết hợp SQL RAG + QLoRA
1. **Dưới máy cá nhân — Băm chương mới và đóng gói ngữ cảnh RAG:**
   ```powershell
   python stage3_step1_export_rag.py
   ```
   *(Hệ thống chỉ xuất những đoạn có mã băm `SourceHash` hoặc `ContextHash` mới, tự động bỏ qua các đoạn đã dịch không thay đổi ngữ cảnh).*
2. **Trên Google Colab — Chạy suy luận hàng loạt (Batch Inference):**
   Chạy ô **Giai đoạn 3** trong Notebook để dịch từng đoạn kèm cơ chế lưu Checkpoint chống ngắt kết nối.
3. **Dưới máy cá nhân — Đồng bộ kết quả về SQL Server và ghép file `.txt`:**
   ```powershell
   python stage3_step3_sync_and_merge.py
   ```

### Giai đoạn 4: Hiệu đính bản dịch & Học liên tục (Feedback Loop)
Khi phát hiện câu dịch chưa mượt, cập nhật bản sửa vào cột `ReviewedVI` trong bảng `dbo.TranslationChunks` rồi chạy:
```powershell
python stage4_feedback_loop.py
```
Các câu đã sửa sẽ tự động được tách và thêm vào bảng `dbo.TranslationExamples` với `IsApproved = 1` để phục vụ ngay cho lượt truy xuất RAG ở chương kế tiếp.

---

## 6. Các câu truy vấn kiểm tra nhanh trong SSMS

```sql
USE ContextTranslateDB;

-- 1. Xem ma trận xưng hô giữa các nhân vật theo từng trạng thái cảm xúc (SceneState):
SELECT s.Name AS Speaker, l.Name AS Listener, r.SceneState,
       r.SelfPronoun, r.AddressPronoun, r.Notes
FROM dbo.PronounRules r
JOIN dbo.Characters s ON s.BookId = r.BookId AND s.CharacterId = r.SpeakerId
JOIN dbo.Characters l ON l.BookId = r.BookId AND l.CharacterId = r.ListenerId
WHERE r.BookId = 1;

-- 2. Kiểm tra tiến độ dịch và số lượng Token tiêu thụ theo từng chương:
SELECT c.ChapterNumber, t.ChunkIndex, t.SourceEN, t.TargetVI,
       t.ModelName, t.InputTokens, t.OutputTokens, t.UpdatedAt
FROM dbo.TranslationChunks t
JOIN dbo.Chapters c ON c.ChapterId = t.ChapterId
ORDER BY c.ChapterNumber, t.ChunkIndex;
```

---

## 7. Xử lý lỗi thường gặp (Troubleshooting)

- **`IM002 / Data source name not found`**: Máy chưa cài Microsoft ODBC Driver 17/18 hoặc tên driver khai báo trong chuỗi kết nối không khớp với `pyodbc.drivers()`.
- **`08001 / Timeout expired`**: Sai tên `SQL_SERVER`, dịch vụ SQL Server chưa khởi động hoặc chưa bật giao thức TCP/IP trong SQL Server Configuration Manager.
- **`18456 / Login failed for user`**: Sai chế độ xác thực (Windows Authentication so với SQL Server Authentication) hoặc tài khoản chưa được cấp quyền trên `ContextTranslateDB`.
- **`SSL Provider: The certificate chain was issued by an authority that is not trusted`**: ODBC Driver 18 bật mã hóa mặc định; cần thêm `TrustServerCertificate=yes;` vào chuỗi kết nối khi chạy SQL Server cục bộ.
- **Colab ngắt kết nối giữa chừng khi đang dịch**: Không cần chạy lại từ đầu; chỉ cần bấm chạy lại ô **Giai đoạn 3** trên Colab, code sẽ tự động đọc file `translated_chunks.json` trên Google Drive để bỏ qua các `chunk_id` đã dịch xong.
