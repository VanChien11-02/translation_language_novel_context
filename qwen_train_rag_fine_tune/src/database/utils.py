"""Các hàm thuần Python; không cần DB / Gemini để kiểm thử."""
import hashlib
import json
import re as regex

# mã hóa SHA256 của một chuỗi
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def stable_hash(data) -> str:
    # sort key --> sắp xếp các key trong dict để đảm bảo tính ổn định của hash
    json_str = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    return sha256_text(json_str)

def split_into_chunks(text: str, max_chars: int = 2400) -> list[str]:
    """Cố giữ nguyên đoạn văn; nếu quá dài mới cắt tại khoảng trắng.
    Đây là chiến lược đơn giản cho MVP, không phải scene-aware segmentation.
    """
    text = text.strip()
    if not text:
        return []
    
    paragraphs = regex.split(r'\n\s*\n', text) # tách các đoạn văn bằng 2 dòng trống
    parts = []
    
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_chars:
            parts.append(p)
        else:
            words = p.split() # list = ['word1', 'word2', ...]
            buffer = '' # tạm giữ các từ cho đến khi đạt max_chars
            for word in words:
                if len(word) > max_chars: # hiếm có từ siêu dài, ví dụ URL, cần xử lý thủ công
                    raise ValueError('Có một từ dài hơn max_chars, cần xử lý thủ công.')
                if (len(buffer) > 0) and (len(buffer) + 1 + len(word) > max_chars): # +1 cho khoảng trắng, buffer không rỗng
                    parts.append(buffer)
                    buffer = word
                else: # buffer rỗng hoặc vẫn còn chỗ cho từ mới
                    buffer = (buffer + ' ' + word).strip()
            
            if len(buffer) > 0: # còn từ trong buffer sau khi xử lý tất cả từ
                parts.append(buffer)

    chunks = []
    cur = ''
    for part in parts:
        # new_val = (cur + '\n\n' + part) if cur else part
        if len(cur) > 0:
            new_val = cur + '\n\n' + part
        else:
            new_val = part
        
        if len(new_val) > max_chars and len(cur) > 0:
            chunks.append(cur)
            cur = part
        else:
            cur = new_val

    if len(cur) > 0:
        chunks.append(cur)
    return chunks
