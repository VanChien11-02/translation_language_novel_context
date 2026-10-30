"""Nạp ví dụ JSONL (mỗi dòng một object) vào SQL Server.

Hỗ trợ trường en, vi, speaker, listener, scene, approved.
Mặc định không duyệt tự động. Có thể dùng --approve nếu đã kiểm tra kỹ toàn bộ file.
"""
import argparse
import json
from pathlib import Path
from dao import Store

p = argparse.ArgumentParser()
p.add_argument('file')
p.add_argument('--book', default='blue-archive')
p.add_argument('--approve', action='store_true')
a = p.parse_args()

items = []
for number, raw in enumerate(Path(a.file).read_text(encoding='utf-8-sig').splitlines(), 1):
    if not raw.strip():
        continue
    try:
        d = json.loads(raw)
        en, vi = d['en'].strip(), d['vi'].strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f'Lỗi dòng JSONL {number}: {exc}') from exc
    if not en or not vi:
        continue
    items.append(d)

with Store() as db:
    book = db.book(a.book)
    for d in items:
        db.ensure_example(book['id'], d['en'], d['vi'],
                          d.get('speaker'), d.get('listener'),
                          d.get('scene', 'general'), approved=a.approve)
print(f'Đã import {len(items)} ví dụ. Approved={a.approve}.')
