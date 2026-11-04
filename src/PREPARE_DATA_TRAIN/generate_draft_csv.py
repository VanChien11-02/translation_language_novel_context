import os
import re
import pandas as pd
from docx import Document

KNOWN_CHARACTERS = ["Yuuka", "Black Suit", "Arona", "Plana", "Saori", "Azusa"]

def read_raw_lines(file_path: str):
    """Đọc danh sách các đoạn văn từ file .docx hoặc .txt."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        doc = Document(file_path)
        return [p.text for p in doc.paragraphs]
    elif ext == ".txt":
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    else:
        raise ValueError(f"Định dạng không hỗ trợ: {ext}")

def extract_paragraphs_with_chapter(file_path: str, is_vietnamese: bool = False):
    """Làm sạch văn bản và tự động gắn số chương (chapter) cho từng dòng."""
    raw_lines = read_raw_lines(file_path)
    items = []
    current_chapter = 1

    for line in raw_lines:
        text = line.replace("\xa0", " ").strip()
        if not text:
            continue

        # Tự động nhận diện tiêu đề Chapter 1, Chapter 2 hoặc Chương 1, Chương 2
        chap_match = re.match(r"^(?:Chapter|Chương)\s+(\d+)", text, re.IGNORECASE)
        if chap_match:
            current_chapter = int(chap_match.group(1))
            continue

        # Bỏ qua tên truyện ở dòng đầu, rác thống kê web hoặc dấu ngắt cảnh * * *
        if text.startswith("Blue Archive:") or re.match(r"^\d+\s+\d+\s+\d+$", text) or text.startswith("bởi "):
            continue
        if set(text).issubset({"*", " "}):
            continue

        # Nếu là bản tiếng Việt thì xóa ghi chú dịch giả (TL: ...)
        if is_vietnamese:
            text = re.sub(r"\s*\(TL:.*?\)", "", text).strip()

        # Chuẩn hóa dấu ngoặc kép và ngoặc đơn
        text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        items.append((current_chapter, text))

    return items

def auto_guess_metadata(en_text: str, vi_text: str, prev_en_narration: str):
    """Kết hợp dấu câu bản gốc (EN) và đại từ bản dịch (VI) để gán nhãn tự động."""
    en_clean = en_text.strip()
    vi_lower = vi_text.lower()

    # 1. Dấu 「...」 trong bản gốc -> Thông báo của Hội đồng Học Sinh
    if en_clean.startswith("「"):
        return "General Student Council", "Sensei", "hostile", 1

    # 2. Dấu nháy đơn '...' trong bản gốc -> Độc thoại nội tâm của Sensei
    if en_clean.startswith("'") and not en_clean.startswith('"'):
        return "Sensei", "Sensei", "monologue", 1

    # 3. Dấu ngoặc kép "..." trong bản gốc -> Câu hội thoại giữa các nhân vật
    if en_clean.startswith('"'):
        if "thầy" in vi_lower or "thầy" in vi_lower:
            # Học sinh đang nói với Sensei
            if re.search(r"\b(em|chúng em)\b", vi_lower) and ("sensei" in vi_lower or "thầy phải" in vi_lower or "thầy phải" in vi_lower):
                for char in ["Plana", "Arona", "Saori", "Yuuka"]:
                    if char.lower() in prev_en_narration.lower():
                        return char, "Sensei", "urgent", 0
                return "Arona", "Sensei", "worried", 0
            else:
                # Sensei đang nói với học sinh
                if "arona" in vi_lower and "plana" in vi_lower:
                    return "Sensei", "Arona/Plana", "urgent", 0
                for char in KNOWN_CHARACTERS:
                    if char.lower() in vi_lower or char.lower() in prev_en_narration.lower():
                        return "Sensei", char, "worried", 0
                return "Sensei", "Arona/Plana", "worried", 0

        # Học sinh xưng "ngươi" khi bị thao túng ký ức
        if "ngươi" in vi_lower:
            for char in ["Yuuka", "Saori"]:
                if char.lower() in prev_en_narration.lower():
                    return char, "Sensei", "hostile", 0
            return "Yuuka", "Sensei", "hostile", 0

        # Black Suit cảnh báo Sensei
        if "black suit" in prev_en_narration.lower() or "không được tin tưởng bất kỳ học sinh nào" in vi_lower:
            return "Black Suit", "Sensei", "warning", 0

        # Hội thoại chưa rõ người nói -> Đánh dấu "?" và human_reviewed = 0 để kiểm tra trên Excel
        return "?", "?", "general", 0

    # 4. Câu dẫn truyện bình thường -> Để trống speaker/listener và đặt human_reviewed = 1
    return "", "", "general", 1

def slice_matching_segment(items, start_phrase, end_phrase):
    """Hàm phụ trợ: Cắt đúng đoạn văn bản khớp nhau khi 2 file gốc và dịch dài ngắn khác nhau."""
    start_idx, end_idx = None, None
    for i, (_, text) in enumerate(items):
        if start_idx is None and start_phrase in text:
            start_idx = i
        if start_idx is not None and end_phrase in text:
            end_idx = i
            break
    if start_idx is not None and end_idx is not None:
        return items[start_idx : end_idx + 1]
    return items

def create_draft_csv_from_pairs(en_list, vi_list, output_csv="novel_pairs_auto_draft.csv"):
    """Ghép danh sách câu tiếng Anh và tiếng Việt thành bảng 7 cột CSV."""
    rows = []
    prev_en_narration = ""
    min_len = min(len(en_list), len(vi_list))

    for i in range(min_len):
        chap_en, en_txt = en_list[i]
        _, vi_txt = vi_list[i]

        spk, lst, scn, reviewed = auto_guess_metadata(en_txt, vi_txt, prev_en_narration)

        # Lưu lại câu dẫn truyện tiếng Anh gần nhất để đoán tên nhân vật cho câu thoại kế tiếp
        if not en_txt.startswith(('"', "'", "「")):
            prev_en_narration = en_txt

        rows.append({
            "source_en": en_txt,
            "target_vi": vi_txt,
            "chapter": chap_en,
            "speaker": spk,
            "listener": lst,
            "scene": scn,
            "human_reviewed": reviewed
        })

    df = pd.DataFrame(rows)
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"Đã xử lý {len(df)} cặp câu Anh - Việt và xuất ra file: {output_csv}")
    print(f"Số dòng đã tự duyệt (human_reviewed = 1): {(df['human_reviewed'] == 1).sum()}")
    print(f"Số dòng cần bạn kiểm tra lại trên Excel (human_reviewed = 0): {(df['human_reviewed'] == 0).sum()}")

if __name__ == "__main__":
    # BƯỚC 1: Khai báo đường dẫn cả 2 file (Hỗ trợ cả .docx lẫn .txt)
    EN_FILE = "bản gốc.docx"         # File tiếng Anh
    VI_FILE = "đoạn dịch ngắn.docx"  # File tiếng Việt

    # BƯỚC 2: Đọc và tách dòng từ cả 2 file
    en_all = extract_paragraphs_with_chapter(EN_FILE, is_vietnamese=False)
    vi_all = extract_paragraphs_with_chapter(VI_FILE, is_vietnamese=True)

    # BƯỚC 3: Vì 2 file mẫu của bạn chỉ trùng nhau một phần ở Chương 1 và Chương 2,
    # ta cắt đúng 2 đoạn khớp nhau (Nếu sau này 2 file của bạn khớp từ đầu đến cuối thì bỏ qua bước cắt này)
    en_ch1 = slice_matching_segment(en_all, '"Wh-what?!"', "most cruel story for Sensei begins.")
    vi_ch1 = slice_matching_segment(vi_all, '"C-cái quái gì thế?!"', "câu chuyện tàn khốc nhất của Sensei bắt đầu.")

    en_ch2 = slice_matching_segment(en_all, "In the taxi going back", "You know how much I cherish you two.")
    vi_ch2 = slice_matching_segment(vi_all, "Trên chiếc taxi quay về", "Em biết thầy trân trọng hai em đến mức nào mà.")

    # Gộp các đoạn đã khớp và xuất ra file CSV
    create_draft_csv_from_pairs(
        en_list = en_ch1 + en_ch2,
        vi_list = vi_ch1 + vi_ch2,
        output_csv = "novel_pairs_auto_draft.csv"
    )