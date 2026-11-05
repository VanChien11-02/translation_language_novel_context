#!/usr/bin/env python3
"""
Stage 1 - Align & Clean  (+ tạo bảng gán nhãn cho Stage 1.5)

Chạy:
    python align_clean.py --source bản_gốc_1.txt --target bản_dịch.txt --out out_dir

Đầu ra (trong out_dir):
    aligned_pairs.csv       một dòng / đoạn gốc: source_en, target_vi, kind, conf, flags
    align_report.md         đoạn không ghép được, ghép độ tin cậy thấp, cảnh báo cần sửa tay
    annotation_sheet.xlsx   bảng gán nhãn Stage 1.5 (có dropdown, ô đoán tô vàng)
"""
import argparse, csv, math, os, re, sys, unicodedata
from collections import defaultdict

# ----------------------------------------------------------------- CẤU HÌNH
BOOK_KEY = "blue-archive"
KNOWN_CHARS = ["Sensei", "Arona", "Plana", "Yuuka", "Saori", "Black Suit"]
STATES = ["normal", "worried", "hostile", "sarcastic", "panic", "regret",
          "pleading", "joking", "serious", "sad", "tired", "happy", "suffer", "chill"]
GROUPS = ["Arona, Plana", "Group"]      # nhãn nhóm; cập nhật qua --chars-csv
MODES = ["speech", "thought", "narration", "system", "sfx"]

# Bản dịch: bỏ mọi đoạn trước đoạn bắt đầu bằng chuỗi này (tiêu đề + độc thoại mở đầu + * * *)
TARGET_START_AT = "Bên trong một chiếc taxi"

# Sửa tự động trên bản dịch (đã chốt trong chot_db.md)
AUTO_FIXES = [
    (re.compile(r"Shcale"), "Schale"),
    (re.compile(r"Hội đồng [Hh]ọc [Ss]inh"), "Hội Học Sinh"),
    (re.compile(r"Huff\.\.\.\s*Huff\.\.\."), "Hộc...Hộc..."),
]
# Cảnh báo: không tự sửa vì phụ thuộc ngữ cảnh -> đưa vào báo cáo
FLAG_PATTERNS = [
    (re.compile(r"(?<!\w)hai người(?!\w)"), "hai người -> 'hai em' nếu Sensei nói với Arona/Plana"),
    (re.compile(r"(?<!đàn )(?<!\w)ông(?!\w)"), "'ông' -> 'anh' nếu nói về Sensei"),
    (re.compile(r"(?<!\w)bạn(?!\w)"), "'bạn' -> xem lại (Plana/Arona nói với Sensei dùng 'thầy')"),
]

CH_SRC = re.compile(r"^Chapter\s+(\d+)\s*[:.\-]\s*(.*)$", re.I)
CH_TGT = re.compile(r"^Chương\s+(\d+)\s*[:.\-]\s*(.*)$", re.I)
SEP = re.compile(r"^(\*\s*){3}$|^[-_=]{3,}$")
JUNK = re.compile(r"^[+\-_=~\s]*$")


# ----------------------------------------------------------------- ĐỌC FILE
def read_paras(path):
    t = unicodedata.normalize("NFC", open(path, encoding="utf-8-sig").read()).replace("\r", "")
    out = []
    for p in re.split(r"\n\s*\n", t):
        p = " ".join(x.strip() for x in p.strip().split("\n")).strip()
        if p:
            out.append(p)
    return out


def norm_src(p):
    p = p.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", p).strip()


def curly_quotes(p):
    """Đổi " thẳng thành “ ” theo thứ tự mở/đóng trong từng đoạn."""
    out, open_q = [], True
    for ch in p:
        if ch == '"':
            out.append("“" if open_q else "”")
            open_q = not open_q
        else:
            out.append(ch)
    return "".join(out)


def split_chapters(paras, heading_re, drop_junk=True):
    """-> (chapters: {num: {'title','paras':[(text, scene_break_before)]}}, ignored_before_first)"""
    chapters, cur, ignored, brk = {}, None, [], False
    for p in paras:
        m = heading_re.match(p)
        if m:
            cur = int(m.group(1))
            chapters[cur] = {"title": m.group(2).strip(), "paras": []}
            brk = False
            continue
        if cur is None:
            ignored.append(p)
            continue
        if SEP.match(p):
            brk = True
            continue
        if drop_junk and JUNK.match(p):
            continue
        chapters[cur]["paras"].append((p, brk))
        brk = False
    return chapters, ignored


# ----------------------------------------------------------------- ĐẶC TRƯNG
def kind(p):
    s = p.strip()
    if s[:1] in ('"', "“", "”"):
        return "speech"
    if s[:1] in ("'", "‘") and s[-1:] in ("'", "’"):
        return "thought"
    if s[:1] == "「":
        return "system"
    if len(s) <= 25:
        return "short"
    return "narr"


def kind_compat(a, b):
    if a == b:
        return 2.0 if a != "short" else 1.5
    if {a, b} == {"short", "narr"}:
        return 0.3
    return -1.2


def known_set(p):
    return {c for c in KNOWN_CHARS if c.lower() in p.lower()}


def name_tokens(p):
    return {t.lower() for t in re.findall(r"\b[A-ZĐ][\w]{2,}\b", p)}


def digits(p):
    return set(re.findall(r"\d+(?:[.,]\d+)?", p.replace(",", ".")))


def pair_score(s, t):
    sk, tk = kind(s), kind(t)
    sc = kind_compat(sk, tk)
    a, b = known_set(s), known_set(t)
    if a or b:
        sc += 1.5 if a == b else (0.6 if a & b else -1.0)
    shared = name_tokens(s) & name_tokens(t)
    sc += min(1.5, 0.5 * len(shared))
    ds, dt = digits(s), digits(t)
    if ds or dt:
        sc += 1.0 if ds == dt else -0.6
    qs, qt = s.count("?") > 0, t.count("?") > 0
    sc += 0.5 if qs == qt else -0.4
    if len(s) > 60 or len(t) > 60:
        lr = len(t) / max(len(s), 1)
        if not (0.8 <= lr <= 2.0):
            sc -= min(2.0, abs(math.log(lr / 1.25)) * 1.5)
    return sc


GAP = -2.0
MERGE_PEN = -0.5


def align(src, tgt):
    """DP: 1:1, 1:2, 2:1, bỏ nguồn, bỏ đích. Trả về list (src_idx[], tgt_idx[], score)."""
    n, m = len(src), len(tgt)
    NEG = -1e9
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    bp = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0
    for i in range(n + 1):
        for j in range(m + 1):
            cur = dp[i][j]
            if cur == NEG:
                continue
            def upd(ni, nj, val, move):
                if val > dp[ni][nj]:
                    dp[ni][nj], bp[ni][nj] = val, move
            if i < n and j < m:
                upd(i + 1, j + 1, cur + pair_score(src[i], tgt[j]), (1, 1))
            if i < n and j + 1 < m:
                upd(i + 1, j + 2, cur + pair_score(src[i], tgt[j] + " " + tgt[j + 1]) + MERGE_PEN, (1, 2))
            if i + 1 < n and j < m:
                upd(i + 2, j + 1, cur + pair_score(src[i] + " " + src[i + 1], tgt[j]) + MERGE_PEN, (2, 1))
            if i < n:
                upd(i + 1, j, cur + GAP, (1, 0))
            if j < m:
                upd(i, j + 1, cur + GAP, (0, 1))
    out, i, j = [], n, m
    while i > 0 or j > 0:
        di, dj = bp[i][j]
        pi, pj = i - di, j - dj
        sc = None
        if di and dj:
            s = " ".join(src[pi:i]); t = " ".join(tgt[pj:j])
            sc = pair_score(s, t)
        out.append((list(range(pi, i)), list(range(pj, j)), sc))
        i, j = pi, pj
    return out[::-1]


def conf_of(score):
    if score is None:
        return "none"
    return "high" if score >= 3.0 else ("mid" if score >= 1.5 else "low")


# ----------------------------------------------------------------- CHUẨN HÓA BẢN DỊCH
def clean_target(p):
    flags = []
    for rx, rep in AUTO_FIXES:
        if rx.search(p):
            p = rx.sub(rep, p)
            flags.append("auto_fix")
    if '"' in p:
        p = curly_quotes(p)
        flags.append("quotes_normalized")
    if p.count("“") != p.count("”"):
        flags.append("unbalanced_quotes")
    for rx, msg in FLAG_PATTERNS:
        if rx.search(p):
            flags.append("check:" + msg)
    return p, sorted(set(flags))


# ----------------------------------------------------------------- ĐOÁN NHÃN (chỉ để điền sẵn)
def _name_rx():
    names = sorted(KNOWN_CHARS, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b(?!'s)")


NAME_RX = _name_rx()
PROTAGONIST = "Sensei"


def subject_name(txt):
    """Tên nhân vật cuối cùng KHÔNG ở dạng sở hữu ('s): thường là chủ ngữ của câu dẫn."""
    best = None
    for m in _name_rx().finditer(txt):
        best = m.group(1)
    return best


def guess_mode(s):
    kd = kind(s)
    if kd == "speech":
        return "speech"
    if kd == "thought":
        return "thought"
    if kd == "system":
        return "system"
    if kd == "short" and len(s.split()) <= 3 and not known_set(s):
        return "sfx"
    return "narration"


def guess_labels(rows):
    """Điền sẵn mode/speaker/listener/state bằng luật đơn giản (chỉ là ĐOÁN, bạn duyệt lại)."""
    hist = []  # người nói đã xác định của các đoạn speech gần nhất
    for k, r in enumerate(rows):
        s = r["source_en"]
        mode = guess_mode(s)
        r["mode"], r["speaker"], r["listener"], r["state"] = mode, "", "", "normal"
        if mode == "narration":
            r["speaker"] = "Narrator"
        elif mode == "thought":
            r["speaker"] = PROTAGONIST
        elif mode == "speech":
            spk = ""
            prev = rows[k - 1] if k > 0 else None
            if prev is not None and prev["mode"] == "narration":
                spk = subject_name(prev["source_en"]) or ""
            elif prev is not None and prev["mode"] == "speech" and hist:
                # đối thoại xen kẽ: lấy người nói khác gần nhất
                for sp in reversed(hist[-6:]):
                    if sp != hist[-1]:
                        spk = sp
                        break
            vocative = re.search(r"\bSensei\b", s) is not None and not spk == "Sensei"
            if spk:
                hist.append(spk)
            r["speaker"] = spk
            if spk and spk != PROTAGONIST:
                r["listener"] = PROTAGONIST
            elif spk == PROTAGONIST:
                r["listener"] = next((x for x in reversed(hist[:-1]) if x != PROTAGONIST), "")
            elif vocative:
                r["listener"] = PROTAGONIST
        r["guess"] = "Y"
    return rows


# ----------------------------------------------------------------- XUẤT
def write_xlsx(rows, path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.utils import get_column_letter

    F = "Arial"
    wb = Workbook()
    ws = wb.active
    ws.title = "Annotate"
    lst = wb.create_sheet("Lists")
    guide = wb.create_sheet("Hướng dẫn", 0)

    cols = ["chapter", "para", "mode", "speaker", "listener", "state", "confirmed",
            "scene_break", "source_en", "target_vi", "align", "flags", "note"]
    ws.append(cols)
    for c in range(1, len(cols) + 1):
        cell = ws.cell(1, c)
        cell.font = Font(name=F, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="3C3489")
        cell.alignment = Alignment(vertical="center")
    yellow = PatternFill("solid", fgColor="FFF2CC")
    for r in rows:
        ws.append([r["chapter"], r["para"], r["mode"], r["speaker"], r["listener"], r["state"], "",
                   "Y" if r["scene_break"] else "", r["source_en"], r["target_vi"],
                   r["conf"], "; ".join(r["flags"]), ""])
    widths = {"A": 8, "B": 6, "C": 11, "D": 14, "E": 14, "F": 12, "G": 10, "H": 11,
              "I": 60, "J": 60, "K": 8, "L": 34, "M": 24}
    for k, w in widths.items():
        ws.column_dimensions[k].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name=F, size=10)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        for idx in (2, 3, 4, 5):  # mode, speaker, listener, state: ô đoán
            row[idx].fill = yellow
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{ws.max_row}"

    # Lists
    lists = {"A": ("mode", MODES), "B": ("speaker", ["Narrator"] + KNOWN_CHARS + GROUPS),
             "C": ("listener", KNOWN_CHARS + GROUPS), "D": ("state", STATES),
             "E": ("confirmed", ["Y"])}
    for col, (name, vals) in lists.items():
        lst[f"{col}1"] = name
        lst[f"{col}1"].font = Font(name=F, bold=True)
        for i, v in enumerate(vals, start=2):
            lst[f"{col}{i}"] = v
            lst[f"{col}{i}"].font = Font(name=F)
    last = ws.max_row
    def dv(col, lcol, n):
        d = DataValidation(type="list", formula1=f"=Lists!${lcol}$2:${lcol}${n + 1}", allow_blank=True,
                           showErrorMessage=False)
        ws.add_data_validation(d)
        d.add(f"{col}2:{col}{last}")
    dv("C", "A", len(MODES)); dv("D", "B", len(lists["B"][1])); dv("E", "C", len(lists["C"][1]))
    dv("F", "D", len(STATES)); dv("G", "E", 1)

    # Hướng dẫn
    g = [
        ["Bảng gán nhãn Stage 1.5"],
        [""],
        ["Cột cần sửa/điền (ô tô vàng là ĐOÁN tự động, hãy kiểm tra):"],
        ["mode", "speech = lời nói; thought = suy nghĩ; narration = lời dẫn; system = tin nhắn hệ thống; sfx = tiếng động"],
        ["speaker", "Ai nói / ai nghĩ. Lời dẫn truyện = Narrator. Nếu chưa chắc để trống hoặc chọn 'Arona|Plana'."],
        ["listener", "Nói với ai (để trống nếu độc thoại hoặc lời dẫn)."],
        ["state", "Trạng thái cảm xúc/quan hệ của đoạn: " + ", ".join(STATES)],
        ["confirmed", "Gõ Y khi bạn đã kiểm tra dòng đó."],
        ["note", "Ghi chú tự do (ví dụ: 'đổi sang hostile từ đoạn này')."],
        [""],
        ["Không sửa: chapter, para (chỉ số đoạn trong bản gốc đã làm sạch), source_en."],
        ["Cột align = độ tin cậy ghép gốc-dịch (low/none cần xem lại target_vi); flags = cảnh báo từ script."],
        [""],
        ["Ví dụ một dòng đã điền:"],
        ["chapter", "para", "mode", "speaker", "listener", "state", "confirmed"],
        [2, 138, "speech", "Arona", "Sensei", "worried", "Y"],
    ]
    for row in g:
        guide.append(row)
    guide.column_dimensions["A"].width = 14
    guide.column_dimensions["B"].width = 100
    for row in guide.iter_rows():
        for c in row:
            c.font = Font(name=F, size=10)
    guide["A1"].font = Font(name=F, size=13, bold=True)
    guide["A3"].font = Font(name=F, size=10, bold=True)
    guide["A14"].font = Font(name=F, size=10, bold=True)
    wb.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--target", help="bỏ trống nếu là chương mới chưa có bản dịch")
    ap.add_argument("--chars-csv", help="seed/characters.csv: nạp danh sách nhân vật cho dropdown + đoán nhãn")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    if a.chars_csv:
        with open(a.chars_csv, encoding="utf-8-sig", newline="") as f:
            rows_c = list(csv.DictReader(f))
        KNOWN_CHARS[:] = [r["name"] for r in rows_c if r.get("kind", "person") == "person"]
        GROUPS[:] = [r["name"] for r in rows_c if r.get("kind") == "group"]
    src_ch, src_ign = split_chapters([norm_src(p) for p in read_paras(a.source)], CH_SRC)
    tgt_ch, tgt_ign = (split_chapters(read_paras(a.target), CH_TGT) if a.target else (None, []))

    # bỏ phần mở đầu của bản dịch (chương đầu)
    dropped = []
    if tgt_ch:
        first = min(tgt_ch)
        items = tgt_ch[first]["paras"]
        idx = next((k for k, (t, _) in enumerate(items) if t.startswith(TARGET_START_AT)), None)
        if idx is None:
            print(f"CẢNH BÁO: không thấy đoạn bắt đầu '{TARGET_START_AT}' trong chương {first}", file=sys.stderr)
        else:
            dropped = [t for t, _ in items[:idx]]
            tgt_ch[first]["paras"] = [(items[idx][0], False)] + items[idx + 1:]

    rows, report = [], []
    stats = defaultdict(int)
    for ch in sorted(src_ch):
        sp = src_ch[ch]["paras"]
        if tgt_ch is None:           # chương mới: chỉ có bản gốc
            for i, (txt, brk) in enumerate(sp, start=1):
                rows.append(dict(chapter=ch, para=i, source_en=txt, target_vi="", conf="none",
                                 flags=["no_target"], scene_break=brk, score=None))
                stats["no_target"] += 1
            continue
        if ch not in tgt_ch:
            report.append(f"- Chương {ch}: không có trong bản dịch.")
            continue
        tp_raw = tgt_ch[ch]["paras"]
        tgt_clean, tgt_flags, tgt_brk = [], [], []
        for t, brk in tp_raw:
            c, f = clean_target(t)
            tgt_clean.append(c); tgt_flags.append(f); tgt_brk.append(brk)
        src_txt = [p for p, _ in sp]
        pairs = align(src_txt, tgt_clean)
        ch_rows = []
        for si, ti, sc in pairs:
            conf = conf_of(sc)
            if si and not ti:
                for i in si:
                    ch_rows.append(dict(chapter=ch, para=i + 1, source_en=src_txt[i], target_vi="",
                                        conf="none", flags=["target_missing"], scene_break=sp[i][1], score=None))
                    stats["target_missing"] += 1
                continue
            if ti and not si:
                for j in ti:
                    report.append(f"- Ch.{ch}: đoạn dịch #{j+1} không có nguồn: “{tgt_clean[j][:90]}”")
                    stats["source_missing"] += 1
                continue
            tvi = " ".join(tgt_clean[j] for j in ti)
            fl = sorted({x for j in ti for x in tgt_flags[j]})
            if len(si) == 2:
                fl.append("merge_2src_1tgt"); stats["merge_2_1"] += 1
            if len(ti) == 2:
                fl.append("merge_1src_2tgt"); stats["merge_1_2"] += 1
            brk = any(tgt_brk[j] for j in ti) or any(sp[i][1] for i in si)
            for n_, i in enumerate(si):
                ch_rows.append(dict(chapter=ch, para=i + 1, source_en=src_txt[i],
                                    target_vi=tvi if n_ == 0 else "(gộp với đoạn trên)",
                                    conf=conf, flags=list(fl), scene_break=(brk if n_ == 0 else False), score=sc))
            stats[conf] += 1
        rows.extend(ch_rows)

    rows = [r for r in rows]
    # đoán nhãn theo từng chương
    for ch in sorted({r["chapter"] for r in rows}):
        guess_labels([r for r in rows if r["chapter"] == ch])

    # CSV
    csv_path = os.path.join(a.out, "aligned_pairs.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["book_key", "chapter", "para", "source_en", "target_vi", "conf", "flags", "scene_break"])
        for r in rows:
            w.writerow([BOOK_KEY, r["chapter"], r["para"], r["source_en"], r["target_vi"], r["conf"],
                        "; ".join(r["flags"]), "Y" if r["scene_break"] else ""])
    write_xlsx(rows, os.path.join(a.out, "annotation_sheet.xlsx"))

    # Báo cáo
    with open(os.path.join(a.out, "align_report.md"), "w", encoding="utf-8") as f:
        f.write("# Báo cáo Align & Clean\n\n")
        f.write(f"- Đoạn nguồn: {sum(len(c['paras']) for c in src_ch.values())} "
                f"({', '.join(f'ch.{k}: {len(v['paras'])}' for k, v in sorted(src_ch.items()))})\n")
        if tgt_ch:
            f.write(f"- Đoạn dịch sau khi bỏ phần mở đầu: {sum(len(c['paras']) for c in tgt_ch.values())}\n")
            f.write(f"- Bỏ khỏi bản dịch: {len(tgt_ign)} đoạn trước 'Chương 1' + {len(dropped)} đoạn đầu chương 1\n")
        else:
            f.write(f"- Chế độ chỉ có bản gốc: {stats['no_target']} đoạn, chưa có bản dịch\n")
        f.write(f"- Độ tin cậy ghép: high={stats['high']}, mid={stats['mid']}, low={stats['low']}, "
                f"gộp 2 nguồn→1 dịch={stats['merge_2_1']}, 1 nguồn→2 dịch={stats['merge_1_2']}\n")
        f.write(f"- Nguồn không có bản dịch: {stats['target_missing']}; bản dịch không có nguồn: {stats['source_missing']}\n\n")
        if report:
            f.write("## Chương/đoạn không ghép được\n\n" + "\n".join(report) + "\n\n")
        f.write("## Đoạn gốc không có bản dịch\n\n")
        miss = [r for r in rows if "target_missing" in r["flags"]]
        f.write("\n".join(f"- Ch.{r['chapter']} đoạn {r['para']}: “{r['source_en'][:90]}”" for r in miss) or "(không có)")
        f.write("\n\n## Ghép độ tin cậy thấp (cần xem lại)\n\n")
        low = [r for r in rows if r["conf"] == "low"]
        for r in low:
            f.write(f"- Ch.{r['chapter']} đoạn {r['para']}\n  - EN: {r['source_en'][:110]}\n  - VI: {r['target_vi'][:110]}\n")
        if not low:
            f.write("(không có)\n")
        f.write("\n## Cảnh báo cần sửa tay trong bản dịch\n\n")
        warn = [r for r in rows if any(x.startswith("check:") or x == "unbalanced_quotes" for x in r["flags"])]
        for r in warn:
            fl = [x for x in r["flags"] if x.startswith("check:") or x == "unbalanced_quotes"]
            f.write(f"- Ch.{r['chapter']} đoạn {r['para']}: {'; '.join(fl)}\n  - VI: {r['target_vi'][:140]}\n")
        if not warn:
            f.write("(không có)\n")
    print(open(os.path.join(a.out, "align_report.md"), encoding="utf-8").read()[:3000])


if __name__ == "__main__":
    main()
