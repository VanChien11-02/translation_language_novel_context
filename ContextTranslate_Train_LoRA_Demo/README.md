# ContextTranslate — Thử Fine-tune dịch Anh → Việt bằng LoRA

## Chọn model và phần cứng

- Model: `Helsinki-NLP/opus-mt-en-vi` (MarianMT), trọng số PyTorch khoảng 289MB.
- Train: Google Colab GPU free (có hạn mức, không bảo đảm cấp GPU).
- Sau train: tải **adapter LoRA** về máy. Để chạy offline vẫn cần tải model gốc **một lần**.
- Máy 16 GB RAM, i5-6300U, không có GPU NVIDIA: ưu tiên chỉ chạy inference local bằng CPU, có thể rất chậm.
- Không cần API Gemini, nhưng Colab GPU có thể bị giới hạn hoặc tốn tiền nếu chọn gói trả phí.

## Cách dùng (5 bước)

1. Vào https://colab.research.google.com/ → `Upload notebook` → chọn `ContextTranslate_Train_LoRA_Colab.ipynb`.
2. Runtime → Change runtime type → GPU; chạy từng cell lần lượt.
3. Khi notebook mở hộp tải CSV, chọn `novel_pairs_draft.csv`. **Hai file docx đã được ghép sơ bộ thành các cặp.** Chưa được người dùng kiểm duyệt kỹ, có lỗi văn phong và ghép câu cần chỉnh.
4. Sau 2 epoch, xem bản dịch trước và sau; tải `novel_lora_adapter.zip` từ Colab.
5. Giải nén adapter vào cùng thư mục `translate_local.py` và chạy với Python Windows sau khi cài `torch transformers peft sentencepiece sacremoses`.

## Dữ liệu

Các cột CSV: `source_en`, `target_vi`, `chapter`, `speaker`, `listener`, `scene`, `human_reviewed`.

Tất cả dòng `human_reviewed=0` nghĩa là **chưa được kiểm duyệt cuối cùng**. Đây là dữ liệu demo kiểm tra quy trình huấn luyện, chưa thích hợp để đánh giá chất lượng thật. Các cặp được căn theo thứ tự đoạn tương ứng, nhưng cần rà soát thủ công trước khi sử dụng lâu dài.

Với vài chục cặp, model rất dễ học vẹt và dịch kém ở câu chưa gặp. Nên giữ riêng 20% ví dụ chưa dùng train để so sánh và, nếu nghiêm túc, bổ sung nhiều cặp thật đã hiệu đính.

## Đưa vào SQL Server

Dùng file `export_approved_sql_examples.py` để xuất những ví dụ đã đánh dấu `IsApproved=1` từ schema SQL Server của project trước. Cần `pip install pyodbc python-dotenv`, file `.env` theo cấu hình kết nối của project SQL Server. Notebook đang mặc định đọc file mẫu `novel_pairs_draft.csv`, có thể đổi tên CSV ở cell upload và `read_csv` nếu dùng file xuất SQL.

**Không** tự fine-tune mỗi khi xuất hiện một câu mới. Tiếp tục dùng SQL Server để lưu bản dịch, nhân vật, quan hệ và các ví dụ tốt; train lại định kỳ khi có đủ dữ liệu chuẩn, sau khi kiểm thử.

## Hạn chế

Mẫu này train một model dịch máy chỉ với văn bản Anh-Việt, không phải AI hội thoại biết dùng context phức tạp. Metadata `speaker/listener/scene` được giữ trong dataset phục vụ giai đoạn sau, **chưa dùng làm đầu vào huấn luyện**. Để dạy các tình huống xưng hô cần dữ liệu có ngữ cảnh và nhiều cặp ví dụ đối chiếu, rồi fine-tune model hỗ trợ instruction (chẳng hạn LLM nhỏ) hoặc kết hợp RAG/Context Manager. 

Không đưa truyện/bản dịch có bản quyền lên kho công khai nếu không có quyền phù hợp; lưu private khi upload thử vào Colab.
