"""Lưu tóm tắt ngắn của chương ĐÃ ĐỌC để tránh spoil chương tiếp theo."""
import argparse
from pathlib import Path
from dao import Store

p = argparse.ArgumentParser()
p.add_argument('--book', default='blue-archive')
p.add_argument('--chapter', type=int, required=True)
p.add_argument('--input', required=True, help='File .txt chứa tóm tắt chương đã đọc')
a = p.parse_args()
summary = Path(a.input).read_text(encoding='utf-8-sig').strip()
if not summary:
    raise ValueError('Tóm tắt rỗng')
with Store() as db:
    book = db.book(a.book)
    chapter_id = db.ensure_chapter(book['id'], a.chapter)
    db.save_summary(chapter_id, summary)
print(f'Đã lưu tóm tắt chương {a.chapter}.')
