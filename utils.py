"""Các hàm thuần Python; không cần DB / Gemini để kiểm thử."""
import hashlib
import json
import re


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def stable_hash(data) -> str:
    return sha256_text(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str))


def split_into_chunks(text: str, max_chars: int = 2400) -> list[str]:
    """Cố giữ nguyên đoạn văn; nếu quá dài mới cắt tại khoảng trắng.

    Đây là chiến lược đơn giản cho MVP, không phải scene-aware segmentation.
    """
    text = text.strip()
    if not text:
        return []
    paragraphs = re.split(r'\n\s*\n', text)
    parts = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_chars:
            parts.append(p)
        else:
            words = p.split()
            buf = ''
            for word in words:
                if len(word) > max_chars:
                    raise ValueError('Có một từ dài hơn max_chars, cần xử lý thủ công.')
                if buf and len(buf) + 1 + len(word) > max_chars:
                    parts.append(buf)
                    buf = word
                else:
                    buf = (buf + ' ' + word).strip()
            if buf:
                parts.append(buf)

    chunks = []
    cur = ''
    for part in parts:
        new_val = (cur + '\n\n' + part) if cur else part
        if len(new_val) > max_chars and cur:
            chunks.append(cur)
            cur = part
        else:
            cur = new_val
    if cur:
        chunks.append(cur)
    return chunks
