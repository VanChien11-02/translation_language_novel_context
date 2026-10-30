# ContextTranslate + SQL Server (MVP)

Bộ demo **Python + SQL Server + Gemini API** để lưu hồ sơ truyện, nhân vật, quy tắc xưng hô, ví dụ dịch Anh–Việt và bản dịch từng đoạn. Thiết kế ưu tiên **dịch chương nào, lưu chương đó**, không cần gửi tất cả chương trước lên API.

> Đã kiểm tra cú pháp Python và unit test thuần Python. Chưa kết nối trực tiếp SQL Server hoặc Gemini API của bạn; cần cài SQL Server, ODBC Driver 18 và API key trên máy Windows.

## 0. Yêu cầu

- SQL Server Database Engine đang chạy và SQL Server Management Studio (SSMS).
- Python >= 3.10 (Windows).
- [Microsoft ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server).
- Chỉ khi muốn dịch thật: Gemini API key từ [Google AI Studio](https://aistudio.google.com/api-keys).

## 1. Tạo database

1. Mở **SSMS**, đăng nhập SQL Server theo cách vẫn dùng.
2. Mở `sql/01_schema.sql`, nhấn **Execute** (F5).
3. Kiểm tra trong SSMS: Databases -> ContextTranslateDB -> Tables. Có 6 bảng: Books, Characters, PronounRules, TranslationExamples, Chapters, TranslationChunks.

File chứa lệnh `GO`, **chạy bằng SSMS hoặc sqlcmd**, không gửi nguyên file qua `cursor.execute()` của pyodbc.

## 2. Cài thư viện

Trong thư mục project, PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Nếu đã kích hoạt venv, có thể dùng lệnh `python` thay đường dẫn `.venv\Scripts\python.exe`.

## 3. Cấu hình `.env`

Mở file `.env` và sửa:

```dotenv
SQL_SERVER=.\SQLEXPRESS
SQL_DATABASE=ContextTranslateDB
SQL_DRIVER=ODBC Driver 18 for SQL Server
SQL_TRUST_SERVER_CERTIFICATE=yes
SQL_USER=
SQL_PASSWORD=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash-lite
```

- `SQL_SERVER`: thay bằng **Server name y hệt như trong SSMS**. Nếu SQL Server mặc định, thường là `localhost`, `.` hoặc tên máy; nếu SQL Express, thường là `.\SQLEXPRESS`.
- `SQL_USER`, `SQL_PASSWORD`: bỏ trống nếu SSMS đang dùng **Windows Authentication** (không cần lưu mật khẩu).
- Nếu SSMS dùng **SQL Server Authentication**, điền cả hai biến cho tài khoản SQL đã có quyền trên `ContextTranslateDB`. Đừng commit `.env`.
- `SQL_TRUST_SERVER_CERTIFICATE=yes` chỉ để thử với **SQL Server local** dùng chứng chỉ tự ký. Sản phẩm deploy ra ngoài cần chứng chỉ tin cậy và `no`.
- Chưa cần điền `GEMINI_API_KEY` để test phần database.

**Kiểm tra kết nối:**

```powershell
.\.venv\Scripts\python.exe check_db.py
```

Nếu kết nối thành công, sẽ thấy thống kê số bản ghi của các bảng.

## 4. Thêm dữ liệu Blue Archive mẫu

```powershell
.\.venv\Scripts\python.exe seed_demo.py
```

Script này thêm 1 truyện, 6 nhân vật, các quy tắc xưng hô (gồm Yuuka `normal` và `hostile`) và 3 cặp ví dụ dịch đã ghép thử từ hai file Word. Chạy lại không tạo bản ghi trùng. Đây là **demo**, nên tự đọc và sửa bản dịch trước khi dùng làm chuẩn dài hạn.

Trong SSMS:

```sql
USE ContextTranslateDB;
SELECT * FROM dbo.Books;
SELECT * FROM dbo.Characters;
SELECT * FROM dbo.PronounRules;
SELECT * FROM dbo.TranslationExamples;
```

## 5. Few-shot/Retrieval từ SQL Server

Demo tìm các ví dụ `IsApproved=1` theo `BookId`, người nói, người nghe, trạng thái cảnh. Với đoạn hội thoại Yuuka -> Sensei và `scene=hostile`, nó ưu tiên đúng cặp tương ứng. Đây là **retrieval theo metadata**, chưa dùng embedding/vectordb.

Xem prompt mà **không gọi API**:

```powershell
.\.venv\Scripts\python.exe translate.py --text "Why are you alive?" --chapter 0 --speaker Yuuka --listener Sensei --scene hostile --dry-run
```

Khi dịch nhiều nhân vật lẫn trong cả chương, **bỏ `--speaker` và `--listener`** và dùng `--scene mixed`. Không đánh dấu cả chương là hội thoại của Yuuka.

## 6. Gọi Gemini và lưu vào SQL Server

Điền `GEMINI_API_KEY` vào `.env`, rồi dịch thử:

```powershell
.\.venv\Scripts\python.exe translate.py --text "Why are you alive?" --chapter 0 --speaker Yuuka --listener Sensei --scene hostile
```

Câu gốc/bản dịch được lưu vào `dbo.TranslationChunks`, cùng hash nội dung, hash context, model, input/output token nếu API trả về. Lặp lại đúng lệnh thì đọc cache từ SQL Server, không gọi Gemini lần nữa.

Dịch file truyện dài:

```powershell
.\.venv\Scripts\python.exe translate.py --input input\chapter_3.txt --chapter 3 --scene mixed --dry-run
.\.venv\Scripts\python.exe translate.py --input input\chapter_3.txt --chapter 3 --scene mixed
```

Dùng file `.txt` UTF-8 của **đúng chương đang đọc**. Công cụ sẽ chia thành khúc khoảng 2.400 ký tự, lưu từng phần. Bản `.txt` đọc được cũng xuất ra `output/blue-archive_chapter_1.txt`. Khi chạy lại và ngữ cảnh/nguồn/model không đổi, từng khúc được đọc cache.

> Chia tự động theo đoạn văn là chiến lược MVP. Với truyện nhiều hội thoại, nên kiểm tra chỗ chia có cắt ngang cảnh hoặc lời thoại không; bản cao cấp có thể dùng scene parser. Khi file chương thay đổi lớn hoặc thay đổi thứ tự đoạn, cần rà soát cache theo `ChunkIndex`.

**Ghi nhớ nội dung chương đã đọc:** viết tóm tắt ngắn vào `summary_1.txt`, rồi chạy:

```powershell
.\.venv\Scripts\python.exe set_chapter_summary.py --chapter 1 --input summary_1.txt
```

Khi dịch chương 2, hệ thống chỉ đọc tóm tắt những chương trước đó (tối đa hai chương có tóm tắt), tránh spoil chương tương lai.

## 7. Import nhiều ví dụ

File `data/examples.jsonl` minh họa các dòng JSON có `en`, `vi`, `speaker`, `listener`, `scene`. Chỉ import vào **dạng chưa duyệt**:

```powershell
.\.venv\Scripts\python.exe import_examples.py data\examples.jsonl
```

Sau khi đã xem và sửa kỹ tất cả dòng trong file, có thể dùng:

```powershell
.\.venv\Scripts\python.exe import_examples.py data\examples.jsonl --approve
```

Các bản `IsApproved=0` không tham gia Few-shot. Không cần train model để AI áp dụng những ví dụ này: retrieval đưa tối đa 3 ví dụ được duyệt vào prompt.

## 8. Các truy vấn hữu ích trong SSMS

```sql
USE ContextTranslateDB;

-- Xem cách xưng hô theo trạng thái:
SELECT s.Name AS Speaker, l.Name AS Listener, r.SceneState,
       r.SelfPronoun, r.AddressPronoun
FROM dbo.PronounRules r
JOIN dbo.Characters s ON s.CharacterId = r.SpeakerId
JOIN dbo.Characters l ON l.CharacterId = r.ListenerId
WHERE r.BookId = 1;

-- Kiểm tra bản dịch đã được lưu, theo chương:
SELECT c.ChapterNumber, t.ChunkIndex, t.SourceEN, t.TargetVI,
       t.ModelName, t.InputTokens, t.OutputTokens
FROM dbo.TranslationChunks t
JOIN dbo.Chapters c ON c.ChapterId = t.ChapterId
ORDER BY c.ChapterNumber, t.ChunkIndex;
```

## 9. Lỗi thường gặp

- `IM002 / Data source name not found`: chưa cài ODBC Driver 18 đúng kiến trúc, hoặc `SQL_DRIVER` không trùng tên trong `pyodbc.drivers()`.
- `08001 / timeout`: sai `SQL_SERVER`, SQL Server Database Engine chưa chạy, hoặc named instance/TCP/IP chưa được cấu hình.
- `18456 / Login failed`: sai kiểu xác thực hoặc tài khoản chưa có quyền.
- `Cannot open database ... requested by login`: chạy `01_schema.sql` hoặc cấp quyền truy cập database.
- `certificate chain was issued by an authority that is not trusted`: ODBC Driver 18 mã hóa kết nối mặc định; với local dev có thể dùng `TrustServerCertificate=yes`, production thì phải dùng certificate hợp lệ.
- `429 / rate limit` của Gemini: các chunk đã lưu không mất; có thể chạy lại sau khi giới hạn được phục hồi.

## 10. Cách tổ chức database khi đọc dài hạn

- Không bắt buộc đưa toàn bộ 100 chương cũ vào API. Chỉ gửi vài ví dụ đã duyệt + quy tắc nhân vật + ngữ cảnh gần nhất.
- Khi xưng hô thay đổi, thêm/sửa `PronounRules` theo `SceneState` và kiểm tra lại cách dịch ở phần cần thiết.
- Hãy tạo tóm tắt thủ công sau mỗi chương đã đọc để giảm token và hạn chế spoil.
- `TranslationChunks` là bản dịch theo `ChapterId + ChunkIndex`; cách này phù hợp MVP một người dùng. Khi có nhiều bản dịch/version hoặc chỉnh lại chương, hãy bổ sung `TranslationVersions` và quản lý revision.

## 11. Test nguồn Python (không cần database)

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

---

Tài liệu tham khảo:
- [ODBC connection string examples — Microsoft Learn](https://learn.microsoft.com/sql/odbc/reference/odbc-programmer-s-reference)
- [ODBC Driver 18 encryption changes — Microsoft Learn](https://learn.microsoft.com/sql/connect/odbc/major-version-differences)
- [Gemini model list](https://ai.google.dev/gemini-api/docs/models)
