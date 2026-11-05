# prompt_template.py  -  MỘT template duy nhất cho TRAIN và INFERENCE
# Đặt file này trên Drive, import ở cả notebook Train lẫn notebook Inference.
import re
from typing import Optional, List, Dict

TEMPLATE_VERSION = "v1"

SYSTEM = (
    "Bạn là dịch giả tiểu thuyết Anh→Việt. Dịch từng đoạn [P#] trong <source>, "
    "tuân thủ tuyệt đối <pronouns>, <glossary>, <scene> và <style_guide>. "
    "Giữ đúng cảm xúc, ngập ngừng, tiếng động. Chỉ xuất bản dịch: mỗi đoạn bắt đầu "
    "bằng đúng nhãn [P#] tương ứng; không giải thích, không thêm hay bỏ đoạn."
)

def _block(tag: str, lines: List[str]) -> str:
    body = "\n".join(lines) if lines else "(không có)"
    return f"<{tag}>\n{body}\n</{tag}>"

def _pronoun_line(r: Dict) -> str:
    who = f"{r['speaker']} → {r.get('listener') or '*'}"
    parts = [who, r.get("mode", "speech"), r.get("state", "normal")]
    if r.get("self"):    parts.append(f"tự xưng: {r['self']}")
    if r.get("address"): parts.append(f"gọi: {r['address']}")
    if r.get("refer"):   parts.append(f"nhắc đến: {r['refer']}")
    return "- " + " | ".join(parts)

def _para_line(p: Dict) -> str:
    # [P3 | speech | Arona>Sensei | worried] <text EN>
    who = p.get("speaker", "?")
    if p.get("listener"):
        who += f">{p['listener']}"
    return f"[{p['id']} | {p.get('mode','narration')} | {who} | {p.get('state','-')}] {p['text']}"

def render_user(ctx: Dict, paras: List[Dict],
                prev: Optional[Dict] = None,
                examples: Optional[List[Dict]] = None) -> str:
    sc = ctx.get("scene", {})
    scene = [f"bối cảnh: {sc.get('location','-')} | thời gian: {sc.get('time','-')} | "
             f"cảm xúc chủ đạo: {sc.get('mood','-')}"]
    if sc.get("summary"):
        scene.append(f"tóm tắt: {sc['summary']}")
    chars = [f"- {c['name']} ({c.get('gender','?')})" + (f": {c['note']}" if c.get("note") else "")
             for c in ctx.get("characters", [])]
    gloss = [f"- {g['src']} = {g['vi']}" + (f" ({g['note']})" if g.get("note") else "")
             for g in ctx.get("glossary", [])]
    out = [
        _block("style_guide", [ctx.get("style_guide", "")]),
        _block("scene", scene),
        _block("characters", chars),
        _block("pronouns", [_pronoun_line(r) for r in ctx.get("pronouns", [])]),
        _block("glossary", gloss),
        _block("facts", [f"- {f}" for f in ctx.get("facts", [])]),
    ]
    if prev:   # chỉ để tham khảo mạch văn, KHÔNG dịch lại
        pl = [f"EN: {s}" for s in prev["source"]] + [f"VI: {t}" for t in prev["target"]]
        out.append(_block("prev", pl))
    if examples:  # tối đa 2 ví dụ đã duyệt, cùng định dạng [P#]
        el = []
        for e in examples:
            el += [f"EN: {e['source']}", f"VI: {e['target']}"]
        out.append(_block("examples", el))
    out.append(_block("source", [_para_line(p) for p in paras]))
    return "\n".join(out)

def render_target(paras: List[Dict], target: List[str]) -> str:
    assert len(paras) == len(target), "số đoạn dịch phải bằng số đoạn nguồn"
    return "\n".join(f"[{p['id']}] {t}" for p, t in zip(paras, target))

def build_messages(ctx, paras, prev=None, examples=None, target=None):
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": render_user(ctx, paras, prev, examples)}]
    if target is not None:
        msgs.append({"role": "assistant", "content": render_target(paras, target)})
    return msgs

# ---- TRAIN: ghép chuỗi thủ công để tiền tố GIỐNG HỆT lúc inference ----
def build_prompt_text(tokenizer, ctx, paras, prev=None, examples=None):
    msgs = build_messages(ctx, paras, prev, examples)
    return tokenizer.apply_chat_template(
        msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)

def build_train_text(tokenizer, ctx, paras, target, prev=None, examples=None):
    prompt = build_prompt_text(tokenizer, ctx, paras, prev, examples)
    full = prompt + render_target(paras, target) + "<|im_end|>\n"
    assert full.startswith(prompt)          # train == inference prefix
    return full

# ---- QA sau khi dịch (chạy trên Colab trước khi ghi translated_chunks.json) ----
def parse_output(text: str, paras: List[Dict]):
    got = dict(re.findall(r"^\[(P\d+)\]\s*(.*?)(?=^\[P\d+\]|\Z)", text, re.S | re.M))
    got = {k: v.strip() for k, v in got.items()}
    flags = []
    want = [p["id"] for p in paras]
    if list(got) != want:            flags.append("para_mismatch")
    if "<think>" in text:            flags.append("think_tag")
    if any(not v for v in got.values()): flags.append("empty_para")
    return got, flags
