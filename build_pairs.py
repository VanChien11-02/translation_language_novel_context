"""Create a small, manually aligned bilingual example set from the two DOCX files.
Only run this if you have both source documents and have permission to use them.
Indices are based on the documents uploaded for this tutorial.
"""
import json
from pathlib import Path
from docx import Document

ROOT = Path(__file__).resolve().parent
PAIRS = [
    # English paragraph, Vietnamese paragraph, speaker, listener, scene, review_status
    (13, 75, "Sensei", "Yuuka", "normal"),
    (16, 78, "Sensei", "Yuuka", "normal"),
    (19, 81, "Sensei", "Yuuka", "normal"),
    (22, 84, "Sensei", "Yuuka", "normal"),
    (24, 86, "Yuuka", "Sensei", "hostile"),
    (27, 89, "Black Suit", "Sensei", "urgent"),
    (42, 104, "Plana", "Sensei", "urgent"),
    (44, 106, "Sensei", "Arona and Plana", "urgent"),
    (66, 127, "Sensei", "self", "sarcastic"),
    (90, 150, "Sensei", "Arona and Plana", "urgent"),
]

def create_examples(original, translated, destination):
    eng = Document(original).paragraphs
    vie = Document(translated).paragraphs
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('w', encoding='utf-8') as f:
        for k, (i, j, speaker, listener, scene) in enumerate(PAIRS, 1):
            source = eng[i].text.strip()
            target = vie[j].text.strip()
            if not source or not target:
                raise ValueError(f'Empty pair {i}:{j}')
            record = {
                'id': f'blue_archive_{k:02d}',
                'en': source,
                'vi': target,
                'speaker': speaker,
                'listener': listener,
                'scene': scene,
                'chapter': 1 if i < 47 else 2,
                'reviewed': False,
                'note': 'Ghép theo vị trí đã kiểm tra thủ công; cần biên tập lỗi trong bản Việt trước khi coi là đáp án chuẩn'
            }
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    print('Đã tạo', len(PAIRS), 'cặp ví dụ ở', destination)

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--original', required=True)
    p.add_argument('--translated', required=True)
    p.add_argument('--output', default=str(ROOT/'data/examples.jsonl'))
    args = p.parse_args()
    create_examples(args.original, args.translated, Path(args.output))
