#!/usr/bin/env python3
"""
ctx.py - pipeline Stage 1.5 -> DB -> file train / pending_chunks

  python ctx.py init-db [--full]                DB trống: --full (sql/020). DB v2 sẵn có: patch (sql/001). SQLite: tạo schema chạy thử
  python ctx.py check-db                        kiểm tra bảng/cột cần thiết
  python ctx.py import-annotations FILE.xlsx    Excel đã gán nhãn -> ChapterParagraphs (+ Chapters, Characters)
  python ctx.py sync-seeds                      seed/*.csv|txt -> Characters, PronounRules, GlossaryTerms, ChapterScenes, StyleGuide
  python ctx.py build-context                   sinh ChapterScenes (khung), StoryEvents từ nhãn
  python ctx.py qa-rules                        đối chiếu bản dịch với PronounRules, liệt kê rule còn thiếu
  python ctx.py export-train --out DIR          xuất train.jsonl / val.jsonl (mức chunk, đúng template v1)
  python ctx.py export-pending --chapter N      xuất pending_chunks.json cho chương mới (đã gán nhãn, chưa dịch)
  python ctx.py all --xlsx FILE.xlsx            chạy tuần tự: import -> sync-seeds -> build-context -> qa-rules -> export-train

Thêm `--sqlite file.db` TRƯỚC tên lệnh để chạy thử trên SQLite thay vì SQL Server.
"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

import config as C
import prompt_template as PT
from db import DB, utcnow

# --------------------------------------------------------------------------- tiện ích
def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def pos(ch, para):
    return int(ch) * 100000 + int(para)


def blank(v):
    return v is None or str(v).strip() == ""


def nz(v):
    return None if blank(v) else str(v).strip()


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    return [r for r in rows if any(r.values())]


def write_csv(path, rows, fields):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def parse_names(label):
    return [x.strip() for x in str(label).split(",") if x.strip()]


def word_rx(term, flags=re.I):
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", flags)


REQUIRED = {
    "Books": ["BookId", "BookKey", "Title", "StyleGuide"],
    "Chapters": ["ChapterId", "BookId", "ChapterNumber", "Title"],
    "Characters": ["CharacterId", "BookId", "Name", "Gender", "CharacterKind", "DisplayNameVI",
                   "ThirdPersonPronoun", "SpeechStyle"],
    "PronounRules": ["RuleId", "BookId", "SpeakerId", "ListenerId", "SceneState", "SelfPronoun", "AddressPronoun",
                     "IsConfirmed", "SpeechMode", "ReferPronoun", "StartChapter", "StartPara", "EndChapter", "EndPara"],
    "StoryEvents": ["EventId", "BookId", "ChapterId", "EventType", "ChapterNumber", "ParaIndex", "AffectsPronouns"],
    "StoryEventCharacters": ["EventId", "BookId", "CharacterId", "EffectState"],
    "GlossaryTerms": ["TermId", "BookId", "SourceTerm", "TargetTerm", "DoNotTranslate", "Variants"],
    "ChapterScenes": ["SceneId", "ChapterId", "SceneIndex", "StartPara", "EndPara", "Location", "Mood"],
    "ChapterParagraphs": ["ParagraphId", "BookId", "ChapterNumber", "ParaIndex", "SourceEN", "TargetVI", "Mode",
                          "SpeakerId", "ListenerId", "SceneState", "SceneBreak", "IsConfirmed"],
}


# --------------------------------------------------------------------------- kiểm tra DB
def cmd_check_db(db, quiet=False):
    bad = 0
    for t, cols in REQUIRED.items():
        have = db.columns(t)
        if not have:
            print(f"THIẾU BẢNG  {t}")
            bad += 1
            continue
        miss = [c for c in cols if c not in have]
        if miss:
            print(f"THIẾU CỘT   {t}: {', '.join(miss)}")
            bad += 1
    if bad:
        print("\n=> Chạy:  python ctx.py init-db   (SQL Server: sql/001_patch_v3.sql, nhớ backup trước)")
    elif not quiet:
        print("Schema đủ cho pipeline.")
    return bad


def cmd_init_db(db, full=False):
    if db.dialect == "sqlite":
        db.init_sqlite()
        print("Đã tạo schema SQLite (chạy thử).")
        return
    name = "020_schema_full_v3.sql" if full else "001_patch_v3.sql"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sql", name)
    n = db.run_script(open(path, encoding="utf-8-sig").read())
    print(f"Đã chạy {n} batch từ sql/{name}")


# --------------------------------------------------------------------------- phiên làm việc
class Session:
    def __init__(self, db):
        self.db = db
        self.book_id = self._ensure_book()
        self._chars, self._chaps = {}, {}
        for r in db.q(f"SELECT CharacterId, Name FROM {db.t('Characters')} WHERE BookId = ?", [self.book_id]):
            self._chars[r["Name"]] = r["CharacterId"]
        for r in db.q(f"SELECT ChapterId, ChapterNumber FROM {db.t('Chapters')} WHERE BookId = ?", [self.book_id]):
            self._chaps[r["ChapterNumber"]] = r["ChapterId"]

    def _ensure_book(self):
        db = self.db
        r = db.q(f"SELECT BookId FROM {db.t('Books')} WHERE BookKey = ?", [C.BOOK_KEY])
        if r:
            return r[0]["BookId"]
        now = utcnow()
        return db.insert("Books", {"BookKey": C.BOOK_KEY, "Title": C.BOOK_TITLE, "StyleGuide": "",
                                   "CreatedAt": now, "OriginalLanguage": "en", "TargetLanguage": "vi",
                                   "BookStatus": "reading", "UpdatedAt": now}, "BookId")

    def chapter(self, n):
        if n not in self._chaps:
            now = utcnow()
            self._chaps[n] = self.db.insert("Chapters", {
                "BookId": self.book_id, "ChapterNumber": n, "Title": f"Chapter {n}", "ChapterStatus": "new",
                "CreatedAt": now, "UpdatedAt": now}, "ChapterId")
        return self._chaps[n]

    def character(self, label, chapter=None):
        """Trả về CharacterId cho nhãn (tự tạo nếu chưa có). 'Arona, Plana' => nhân vật nhóm."""
        if blank(label):
            return None
        names = parse_names(label)
        key = ", ".join(names)
        if len(names) > 1 or key in C.GROUP_NAMES:
            kind = "group"
            for n in names:
                if n not in C.GROUP_NAMES:
                    self.character(n, chapter)
        elif key == C.NARRATOR:
            kind = "narrator"
        else:
            kind = "person"
        if key not in self._chars:
            self._chars[key] = self.db.insert("Characters", {
                "BookId": self.book_id, "Name": key, "ReviewStatus": "suggested", "FirstSeenChapter": chapter,
                "CreatedAt": utcnow(), "CharacterKind": kind}, "CharacterId")
        return self._chars[key]


# --------------------------------------------------------------------------- 1. import Excel
def read_annotation_xlsx(path, sheet="Annotate"):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    ws = wb[sheet] if sheet in wb.sheetnames else wb.worksheets[0]
    hdr = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
    need = ["chapter", "para", "mode", "speaker", "listener", "state", "confirmed", "scene_break", "source_en",
            "target_vi"]
    miss = [c for c in need if c not in hdr]
    if miss:
        raise SystemExit(f"Excel thiếu cột: {miss}")
    out = []
    for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        d = dict(zip(hdr, r))
        if all(v in (None, "") for v in d.values()):
            continue
        d["_row"] = i
        out.append(d)
    return out


def cmd_import_annotations(db, xlsx, sheet="Annotate", include_unconfirmed=False, force=False):
    rows = read_annotation_xlsx(xlsx, sheet)
    errors, warns, seen = [], [], set()
    clean = []
    skipped_unconf = 0
    for d in rows:
        loc = f"dòng Excel {d['_row']}"
        try:
            ch, pa = int(d["chapter"]), int(d["para"])
        except (TypeError, ValueError):
            errors.append(f"{loc}: chapter/para không phải số")
            continue
        mode = (nz(d["mode"]) or "").lower()
        if mode not in C.MODES:
            errors.append(f"{loc} (ch.{ch} đoạn {pa}): mode '{d['mode']}' không hợp lệ")
            continue
        if (ch, pa) in seen:
            errors.append(f"{loc}: trùng (chapter={ch}, para={pa})")
            continue
        seen.add((ch, pa))
        confirmed = str(d.get("confirmed") or "").strip().upper() == "Y"
        if not confirmed and not include_unconfirmed:
            skipped_unconf += 1
            continue
        speaker, listener, state = nz(d["speaker"]), nz(d["listener"]), nz(d["state"])
        if mode in ("speech", "thought") and not speaker:
            errors.append(f"{loc} (ch.{ch} đoạn {pa}): {mode} nhưng thiếu speaker")
            continue
        if state and state not in C.STATES:
            warns.append(f"ch.{ch} đoạn {pa}: state lạ '{state}' (thêm vào config.STATES nếu hợp lệ)")
        src = nz(d["source_en"])
        if not src:
            errors.append(f"{loc} (ch.{ch} đoạn {pa}): thiếu source_en")
            continue
        tgt = nz(d["target_vi"])
        if tgt and tgt.startswith("(gộp"):
            warns.append(f"ch.{ch} đoạn {pa}: target là '(gộp ...)': đoạn dịch bị gộp, cần xử lý tay")
        clean.append(dict(ch=ch, pa=pa, mode=mode, speaker=speaker, listener=listener, state=state, src=src, tgt=tgt,
                          brk=str(d.get("scene_break") or "").strip().upper() == "Y", conf=confirmed,
                          align=nz(d.get("align")), flags=nz(d.get("flags")), note=nz(d.get("note"))))
    by_ch = defaultdict(list)
    for r in clean:
        by_ch[r["ch"]].append(r["pa"])
    for ch, ps in by_ch.items():
        ps = sorted(ps)
        if ps != list(range(1, len(ps) + 1)):
            warns.append(f"ch.{ch}: chỉ số đoạn không liên tục 1..{len(ps)} (có thể do dòng chưa confirmed)")
    if errors and not force:
        print("LỖI (chưa ghi gì vào DB):")
        for e in errors[:50]:
            print("  -", e)
        raise SystemExit(f"{len(errors)} lỗi. Sửa Excel rồi chạy lại (hoặc --force để bỏ qua các dòng lỗi).")

    s = Session(db)
    stat = Counter()
    changed_src = []
    now = utcnow()
    for r in sorted(clean, key=lambda x: (x["ch"], x["pa"])):
        chap_id = s.chapter(r["ch"])
        spk = s.character(r["speaker"], r["ch"])
        lst = s.character(r["listener"], r["ch"])
        h = sha(r["src"])
        old = db.q(f"SELECT SourceHash FROM {db.t('ChapterParagraphs')} WHERE BookId = ? AND ChapterNumber = ? "
                   f"AND ParaIndex = ?", [s.book_id, r["ch"], r["pa"]])
        if old and old[0]["SourceHash"] != h:
            changed_src.append((r["ch"], r["pa"]))
        _, how = db.upsert("ChapterParagraphs",
                           {"BookId": s.book_id, "ChapterNumber": r["ch"], "ParaIndex": r["pa"]},
                           {"ChapterId": chap_id, "SourceEN": r["src"], "TargetVI": r["tgt"], "SourceHash": h,
                            "Mode": r["mode"], "SpeakerId": spk, "ListenerId": lst, "SceneState": r["state"],
                            "SceneBreak": int(r["brk"]), "IsConfirmed": int(r["conf"]), "AlignConf": r["align"],
                            "Flags": r["flags"], "Note": r["note"]}, "ParagraphId",
                           insert_only={"UpdatedAt": now})
        stat[how] += 1
    # đoạn có trong DB nhưng không còn trong Excel
    for ch in by_ch:
        have = {r["ParaIndex"] for r in db.q(f"SELECT ParaIndex FROM {db.t('ChapterParagraphs')} "
                                              f"WHERE BookId = ? AND ChapterNumber = ?", [s.book_id, ch])}
        gone = sorted(have - set(by_ch[ch]))
        if gone:
            warns.append(f"ch.{ch}: DB còn các đoạn {gone[:10]}{'...' if len(gone) > 10 else ''} không có trong Excel (không xóa)")
    db.commit()
    print(f"Import xong: thêm {stat['inserted']}, cập nhật {stat['updated']}, không đổi {stat['unchanged']}; "
          f"bỏ qua chưa confirmed: {skipped_unconf}; dòng lỗi bị bỏ: {len(errors)}")
    if changed_src:
        print(f"CẢNH BÁO: nội dung gốc đổi ở {len(changed_src)} đoạn {changed_src[:8]}: "
              f"nhãn/sự kiện/rule neo theo đoạn có thể đã lệch, hãy kiểm tra.")
    for w in warns[:30]:
        print("  !", w)
    if len(warns) > 30:
        print(f"  ... và {len(warns) - 30} cảnh báo khác")


# --------------------------------------------------------------------------- 2. seeds
def check_overlap(rows):
    """Không cho hai rule ĐÃ DUYỆT cùng (speaker, listener, mode, state) chồng khoảng hiệu lực."""
    groups = defaultdict(list)
    for r in rows:
        if r["confirmed"].upper() != "Y":
            continue
        st = pos(r["start_chapter"] or 0, r["start_para"] or 0)
        en = pos(r["end_chapter"], r["end_para"] or 0) if r["end_chapter"] else None
        groups[(r["speaker"], r["listener"], r["mode"] or "speech", r["state"] or "*")].append((st, en))
    errs = []
    for k, iv in groups.items():
        iv.sort()
        for (s1, e1), (s2, e2) in zip(iv, iv[1:]):
            if e1 is None or s2 < e1:
                errs.append(f"rule chồng khoảng hiệu lực: {k}")
                break
    return errs


def cmd_sync_seeds(db, seed_dir=None):
    seed_dir = seed_dir or C.SEED_DIR
    s = Session(db)
    now = utcnow()
    stat = defaultdict(Counter)

    p = os.path.join(seed_dir, "style_guide.txt")
    if os.path.exists(p):
        text = open(p, encoding="utf-8").read().strip()
        db.x(f"UPDATE {db.t('Books')} SET StyleGuide = ?, UpdatedAt = ? WHERE BookId = ?", [text, now, s.book_id])
        if len(text) > 600:
            print(f"  ! style_guide dài {len(text)} ký tự (>600): nó nằm trong MỌI prompt, nên rút gọn")

    for r in read_csv(os.path.join(seed_dir, "characters.csv")):
        cid = s.character(r["name"])
        _, how = db.upsert("Characters", {"BookId": s.book_id, "Name": r["name"]},
                           {"CharacterKind": r.get("kind") or "person", "Gender": nz(r.get("gender")),
                            "DisplayNameVI": nz(r.get("display_vi")), "ThirdPersonPronoun": nz(r.get("third_person")),
                            "SpeechStyle": nz(r.get("speech_style")), "Description": nz(r.get("description")),
                            "ReviewStatus": "confirmed"}, "CharacterId")
        stat["characters"][how] += 1

    for r in read_csv(os.path.join(seed_dir, "glossary.csv")):
        dnt = r.get("do_not_translate", "").strip() in ("1", "Y", "y", "true", "True")
        _, how = db.upsert("GlossaryTerms", {"BookId": s.book_id, "SourceTerm": r["source"]},
                           {"TargetTerm": r.get("target") or r["source"], "TermType": nz(r.get("type")),
                            "Notes": nz(r.get("note")), "DoNotTranslate": int(dnt), "Variants": nz(r.get("variants")),
                            "IsApproved": 1, "IsActive": 1}, "TermId", insert_only={"CreatedAt": now})
        stat["glossary"][how] += 1

    rules = read_csv(os.path.join(seed_dir, "pronoun_rules.csv"))
    errs = check_overlap(rules)
    if errs:
        raise SystemExit("LỖI pronoun_rules.csv:\n  - " + "\n  - ".join(errs))
    for r in rules:
        spk, lst = s.character(r["speaker"]), s.character(r.get("listener"))
        state = r.get("state") or "*"
        sc = int(r["start_chapter"]) if r.get("start_chapter") else 0
        sp = int(r["start_para"]) if r.get("start_para") else 0
        ec = int(r["end_chapter"]) if r.get("end_chapter") else None
        ep = int(r["end_para"]) if r.get("end_para") else None
        _, how = db.upsert("PronounRules",
                           {"BookId": s.book_id, "SpeakerId": spk, "ListenerId": lst,
                            "SpeechMode": r.get("mode") or "speech", "SceneState": state,
                            "StartChapter": sc, "StartPara": sp},
                           {"SelfPronoun": nz(r.get("self")), "AddressPronoun": nz(r.get("address")),
                            "ReferPronoun": nz(r.get("refer")), "EndChapter": ec, "EndPara": ep,
                            "Notes": nz(r.get("note")), "IsConfirmed": int(r.get("confirmed", "").upper() == "Y"),
                            "Priority": 0 if state == "*" else 10}, "RuleId")
        stat["pronoun_rules"][how] += 1

    for r in read_csv(os.path.join(seed_dir, "scenes.csv")):
        ch = int(r["chapter"])
        end = int(r["end_para"]) if r.get("end_para") else None
        filled = r.get("confirmed", "").upper() == "Y"
        _, how = db.upsert("ChapterScenes", {"ChapterId": s.chapter(ch), "SceneIndex": int(r["scene_index"])},
                           {"BookId": s.book_id, "StartPara": int(r["start_para"]), "EndPara": end,
                            "Location": nz(r.get("location")), "TimeOfDay": nz(r.get("time")), "Mood": nz(r.get("mood")),
                            "SummaryVI": nz(r.get("summary")),
                            "ReviewStatus": "confirmed" if filled else "suggested"}, "SceneId",
                           insert_only={"CreatedAt": now})
        stat["scenes"][how] += 1
    db.commit()
    for k, v in stat.items():
        print(f"  {k:15s} thêm {v['inserted']}, cập nhật {v['updated']}, không đổi {v['unchanged']}")


# --------------------------------------------------------------------------- 3. thế giới (đọc DB vào bộ nhớ)
class World:
    def __init__(self, db):
        self.db = db
        s = Session(db)
        self.book_id = s.book_id
        t = db.t
        b = db.q(f"SELECT StyleGuide FROM {t('Books')} WHERE BookId = ?", [self.book_id])
        self.style_guide = (b[0]["StyleGuide"] or "").strip() if b else ""
        self.chars = {}
        self.char_by_name = {}
        for r in db.q(f"SELECT CharacterId, Name, Gender, CharacterKind, DisplayNameVI, ThirdPersonPronoun, "
                      f"SpeechStyle FROM {t('Characters')} WHERE BookId = ?", [self.book_id]):
            self.chars[r["CharacterId"]] = r
            self.char_by_name[r["Name"]] = r
        # quy tắc xưng hô đã duyệt
        self.rule_idx = defaultdict(list)
        self.rules = {}
        for r in db.q(f"SELECT RuleId, SpeakerId, ListenerId, SpeechMode, SceneState, SelfPronoun, AddressPronoun, "
                      f"ReferPronoun, StartChapter, StartPara, EndChapter, EndPara, Priority FROM "
                      f"{t('PronounRules')} WHERE BookId = ? AND IsConfirmed = 1", [self.book_id]):
            r["start"] = pos(r["StartChapter"] or 0, r["StartPara"] or 0)
            r["end"] = None if r["EndChapter"] is None else pos(r["EndChapter"], r["EndPara"] or 0)
            r["prio"] = r["Priority"] or 0
            self.rule_idx[(r["SpeakerId"], r["SpeechMode"])].append(r)
            self.rules[r["RuleId"]] = r
        # thuật ngữ
        self.glossary = []
        for r in db.q(f"SELECT SourceTerm, TargetTerm, TermType, Notes, DoNotTranslate, Variants FROM "
                      f"{t('GlossaryTerms')} WHERE BookId = ? AND IsActive = 1 AND IsApproved = 1", [self.book_id]):
            forms = [r["SourceTerm"]] + [v.strip() for v in re.split(r"[|;]", r["Variants"] or "") if v.strip()]
            cs = (r["TermType"] == "sfx")
            r["rx"] = [word_rx(f, 0 if cs else re.I) for f in forms]
            self.glossary.append(r)
        # cảnh
        self.scenes = defaultdict(list)
        for r in db.q(f"SELECT c.ChapterNumber, s.SceneIndex, s.StartPara, s.EndPara, s.Location, s.TimeOfDay, "
                      f"s.Mood, s.SummaryVI FROM {t('ChapterScenes')} s JOIN {t('Chapters')} c "
                      f"ON c.ChapterId = s.ChapterId WHERE s.BookId = ? ORDER BY c.ChapterNumber, s.SceneIndex",
                      [self.book_id]):
            self.scenes[r["ChapterNumber"]].append(r)
        # sự thật theo thời gian (không bắt buộc)
        self.facts = []
        if db.table_exists("ContextFacts") and "StartChapter" in db.columns("ContextFacts"):
            for r in db.q(f"SELECT CharacterId, FactText, StartChapter, StartPara, EndChapter, EndPara FROM "
                          f"{t('ContextFacts')} WHERE BookId = ? AND ReviewStatus = 'confirmed'", [self.book_id]):
                r["start"] = pos(r["StartChapter"] or 0, r["StartPara"] or 0)
                r["end"] = None if r["EndChapter"] is None else pos(r["EndChapter"], r["EndPara"] or 0)
                self.facts.append(r)
        # đoạn văn
        self.paras = defaultdict(list)
        for r in db.q(f"SELECT ChapterNumber, ParaIndex, SourceEN, TargetVI, Mode, SpeakerId, ListenerId, SceneState, "
                      f"SceneBreak, IsConfirmed FROM {t('ChapterParagraphs')} WHERE BookId = ? "
                      f"ORDER BY ChapterNumber, ParaIndex", [self.book_id]):
            nm = lambda i: self.chars[i]["Name"] if i in self.chars else None
            self.paras[r["ChapterNumber"]].append(dict(
                chapter=r["ChapterNumber"], para=r["ParaIndex"], source=r["SourceEN"], target=r["TargetVI"],
                mode=r["Mode"], spk_id=r["SpeakerId"], lst_id=r["ListenerId"], spk=nm(r["SpeakerId"]),
                lst=nm(r["ListenerId"]), state=r["SceneState"], brk=bool(r["SceneBreak"]),
                conf=bool(r["IsConfirmed"]), pos=pos(r["ChapterNumber"], r["ParaIndex"])))
        # sự kiện đổi xưng hô (không bị từ chối)
        self.cuts = defaultdict(set)
        for r in db.q(f"SELECT ChapterNumber, ParaIndex FROM {t('StoryEvents')} WHERE BookId = ? "
                      f"AND AffectsPronouns = 1 AND ReviewStatus <> 'rejected' AND ParaIndex IS NOT NULL",
                      [self.book_id]):
            self.cuts[r["ChapterNumber"]].add(r["ParaIndex"])
        self.missing = Counter()

    # ---- xưng hô
    def resolve_rule(self, spk_id, lst_id, mode, state, p):
        if spk_id is None:
            return None
        cands = [r for r in self.rule_idx.get((spk_id, mode), [])
                 if r["start"] <= p and (r["end"] is None or p < r["end"])]
        state = state or "normal"
        for want in (state, "*"):
            hit = [r for r in cands if r["ListenerId"] == lst_id and r["SceneState"] == want]
            if hit:
                return max(hit, key=lambda r: (r["prio"], r["start"]))
        return None

    def scene_for(self, ch, para):
        for sc in self.scenes.get(ch, []):
            if sc["StartPara"] <= para and (sc["EndPara"] is None or para < sc["EndPara"]):
                return sc
        return None


# --------------------------------------------------------------------------- 4. build-context (sinh dữ liệu dẫn xuất)
def cmd_build_context(db, out_dir="out"):
    os.makedirs(out_dir, exist_ok=True)
    w = World(db)
    s = Session(db)
    now = utcnow()
    # --- khung ChapterScenes từ scene_break
    created, todo = 0, []
    for ch, ps in w.paras.items():
        starts = [p["para"] for p in ps if p["brk"] or p["para"] == ps[0]["para"]]
        starts = sorted(set(starts))
        for i, st in enumerate(starts):
            en = starts[i + 1] if i + 1 < len(starts) else None
            ex = db.q(f"SELECT SceneId, StartPara, EndPara, Location, Mood, ReviewStatus FROM {db.t('ChapterScenes')} "
                      f"WHERE ChapterId = ? AND SceneIndex = ?", [s.chapter(ch), i + 1])
            if not ex:
                db.insert("ChapterScenes", {"BookId": s.book_id, "ChapterId": s.chapter(ch), "SceneIndex": i + 1,
                                            "StartPara": st, "EndPara": en, "ReviewStatus": "suggested",
                                            "CreatedAt": now}, "SceneId")
                created += 1
                ex = [{"Location": None, "Mood": None}]
            else:
                e = ex[0]
                if (e["StartPara"], e["EndPara"]) != (st, en):
                    if e["ReviewStatus"] == "confirmed":
                        print(f"  ! ch.{ch} cảnh {i+1}: biên trong DB ({e['StartPara']}-{e['EndPara']}) khác nhãn "
                              f"scene_break ({st}-{en}); cảnh đã confirmed nên KHÔNG tự sửa")
                    else:
                        db.x(f"UPDATE {db.t('ChapterScenes')} SET StartPara = ?, EndPara = ? WHERE SceneId = ?",
                             [st, en, e["SceneId"]])
            if not ex[0].get("Location") or not ex[0].get("Mood"):
                todo.append({"chapter": ch, "scene_index": i + 1, "start_para": st, "end_para": en or "",
                             "location": ex[0].get("Location") or "", "time": "", "mood": ex[0].get("Mood") or "",
                             "summary": "", "confirmed": ""})
    # --- sự kiện đổi xưng hô từ nhãn
    ev_new = ev_total = 0
    last_state, last_rule = {}, {}      # theo (speaker, listener, mode), giữ qua các chương
    for ch, ps in sorted(w.paras.items()):
        chap_id = s.chapter(ch)
        for p in ps:
            if p["mode"] not in ("speech", "thought") or not p["conf"] or p["spk_id"] is None:
                continue
            key = (p["spk_id"], p["lst_id"], p["mode"])
            rule = w.resolve_rule(p["spk_id"], p["lst_id"], p["mode"], p["state"], p["pos"])
            old_state, old_rule = last_state.get(key), last_rule.get(key)
            last_state[key] = p["state"]
            if rule is not None:
                last_rule[key] = rule
            if old_state is None or old_state == p["state"] or rule is None:
                continue
            if old_rule is None:
                shifted = rule["SceneState"] != "*"          # vào một trạng thái có rule riêng
            else:
                shifted = (old_rule["SelfPronoun"], old_rule["AddressPronoun"]) != \
                          (rule["SelfPronoun"], rule["AddressPronoun"])
            if not shifted:
                continue
            ev_total += 1
            a = old_rule
            before = f"{a['SelfPronoun'] or '?'}/{a['AddressPronoun'] or '?'}" if a else "(mặc định/không rõ)"
            title = f"{p['spk']} → {p['lst'] or '(không rõ)'}: {old_state} → {p['state']}"
            desc = f"Xưng hô đổi: {before} → {rule['SelfPronoun'] or '?'}/{rule['AddressPronoun'] or '?'}"
            eid, how = db.upsert("StoryEvents",
                                 {"BookId": s.book_id, "ChapterId": chap_id, "ParaIndex": p["para"],
                                  "EventType": "pronoun_shift"},
                                 {"ChapterNumber": ch, "EventTitle": title, "DescriptionVI": desc,
                                  "EvidenceEN": p["source"][:500], "DetectionMethod": "label_diff",
                                  "AffectsPronouns": 1}, "EventId",
                                 insert_only={"ReviewStatus": "suggested", "CreatedAt": now})
            if how == "inserted":
                ev_new += 1
                db.x(f"INSERT INTO {db.t('StoryEventCharacters')} (EventId, BookId, CharacterId, EffectState) "
                     f"VALUES (?, ?, ?, ?)", [eid, s.book_id, p["spk_id"], p["state"]])
    db.commit()
    print(f"ChapterScenes: tạo mới {created}. StoryEvents (pronoun_shift): {ev_total} điểm đổi xưng hô, mới {ev_new}.")
    if todo:
        path = os.path.join(out_dir, "scenes_to_fill.csv")
        write_csv(path, todo, ["chapter", "scene_index", "start_para", "end_para", "location", "time", "mood",
                               "summary", "confirmed"])
        print(f"  {len(todo)} cảnh còn thiếu địa điểm/cảm xúc -> điền vào seed/scenes.csv (mẫu: {path}), "
              f"đặt confirmed=Y rồi chạy lại sync-seeds")


# --------------------------------------------------------------------------- 5. dựng chunk + context
def chunk_paras(paras, cuts, max_paras, max_chars, offset=0):
    """Chia các đoạn của MỘT chương. Luôn cắt tại: đầu cảnh (scene_break) và điểm đổi xưng hô (cuts)."""
    segs, cur = [], []
    for p in paras:
        if cur and (p["brk"] or p["para"] in cuts):
            segs.append(cur)
            cur = []
        cur.append(p)
    if cur:
        segs.append(cur)
    out = []
    for seg in segs:
        i = 0
        if offset and len(seg) > offset + 1:
            out.append(seg[:offset])
            i = offset
        cur, n = [], 0
        for p in seg[i:]:
            if cur and (len(cur) >= max_paras or n + len(p["source"]) > max_chars):
                out.append(cur)
                cur, n = [], 0
            cur.append(p)
            n += len(p["source"])
        if cur:
            out.append(cur)
    return out


def hard_windows(paras, cuts):
    by = {p["para"]: i for i, p in enumerate(paras)}
    out = []
    for e in sorted(cuts):
        if e not in by:
            continue
        a = max(by[e] - 1, 0)
        b = min(by[e] + 2, len(paras))
        win = paras[a:b]
        trimmed = [win[0]]
        for p in win[1:]:
            if p["brk"]:
                break
            trimmed.append(p)
        out.append(trimmed)
    return out


GENDER_VI = {"male": "nam", "female": "nữ"}


def build_context(w, chunk):
    """Dựng khối context cho một chunk; trả (ctx, missing_keys)."""
    ch, p0, p1 = chunk[0]["chapter"], chunk[0]["para"], chunk[-1]["para"]
    text = "\n".join(p["source"] for p in chunk)
    pstart = chunk[0]["pos"]
    pend = chunk[-1]["pos"] + 1
    # nhân vật xuất hiện
    ids = []

    def add(i):
        if i is not None and i not in ids:
            ids.append(i)
    for p in chunk:
        for i in (p["spk_id"], p["lst_id"]):
            add(i)
            if i in w.chars and w.chars[i]["CharacterKind"] == "group":
                for n in parse_names(w.chars[i]["Name"]):
                    if n in w.char_by_name:
                        add(w.char_by_name[n]["CharacterId"])
    for r in w.chars.values():
        if r["CharacterKind"] == "person" and word_rx(r["Name"]).search(text):
            add(r["CharacterId"])
    persons, groups = [], []
    for i in ids:
        r = w.chars[i]
        if r["CharacterKind"] == "narrator":
            continue
        if r["CharacterKind"] == "group":
            members = [n for n in parse_names(r["Name"]) if n not in C.GROUP_NAMES]
            groups.append({"name": r["Name"], "gender": GENDER_VI.get(r["Gender"] or "", "?"),
                           "note": ("gồm " + " + ".join(members)) if members else "nhóm người"})
        else:
            persons.append({"name": r["Name"], "gender": GENDER_VI.get(r["Gender"] or "", "?"),
                            "note": r["SpeechStyle"] or None})
    # xưng hô
    pron, seen = [], set()
    for i in ids:  # người dẫn truyện nhắc tới nhân vật
        r = w.chars[i]
        if r["CharacterKind"] == "person" and r["ThirdPersonPronoun"]:
            pron.append({"speaker": C.NARRATOR, "listener": r["Name"], "mode": "narration", "state": "-",
                         "refer": r["ThirdPersonPronoun"]})
    missing = []
    for p in chunk:
        if p["mode"] not in ("speech", "thought") or p["spk_id"] is None:
            continue
        rule = w.resolve_rule(p["spk_id"], p["lst_id"], p["mode"], p["state"], p["pos"])
        if rule is None:
            missing.append((p["spk"], p["lst"], p["mode"], p["state"] or "normal"))
            continue
        if rule["RuleId"] in seen:
            continue
        seen.add(rule["RuleId"])
        pron.append({"speaker": p["spk"], "listener": p["lst"], "mode": p["mode"], "state": rule["SceneState"],
                     "self": rule["SelfPronoun"], "address": rule["AddressPronoun"], "refer": rule["ReferPronoun"]})
    # thuật ngữ
    gloss = []
    for g in w.glossary:
        if any(rx.search(text) for rx in g["rx"]):
            if g["DoNotTranslate"]:
                gloss.append({"src": g["SourceTerm"], "vi": g["SourceTerm"], "note": "giữ nguyên"})
            else:
                gloss.append({"src": g["SourceTerm"], "vi": g["TargetTerm"], "note": g["Notes"] or None})
    # cảnh
    sc = w.scene_for(ch, p0)
    scene = {}
    if sc:
        scene = {"location": sc["Location"] or "-", "time": sc["TimeOfDay"] or "-", "mood": sc["Mood"] or "-"}
        if sc["SummaryVI"]:
            scene["summary"] = sc["SummaryVI"]
    facts = [f["FactText"] for f in w.facts
             if f["start"] < pend and (f["end"] is None or f["end"] > pstart)
             and (f["CharacterId"] is None or f["CharacterId"] in ids)]
    ctx = {"style_guide": w.style_guide, "scene": scene, "characters": persons + groups, "pronouns": pron,
           "glossary": gloss, "facts": facts}
    return ctx, missing


def para_records(chunk):
    out = []
    for i, p in enumerate(chunk, start=1):
        out.append({"id": f"P{i}", "para": p["para"], "mode": p["mode"], "speaker": p["spk"], "listener": p["lst"],
                    "state": p["state"] or "-", "text": p["source"]})
    return out


def build_prev(w, chunk, need_target):
    ch, p0 = chunk[0]["chapter"], chunk[0]["para"]
    if chunk[0]["brk"] or p0 <= 1:
        return None
    by = {p["para"]: p for p in w.paras[ch]}
    got, j = [], p0 - 1
    while j >= 1 and len(got) < 2 and j in by:
        got.append(by[j])
        if by[j]["brk"]:
            break
        j -= 1
    got.reverse()
    if not got:
        return None
    if need_target and any(blank(p["target"]) for p in got):
        return None
    return {"source": [p["source"] for p in got], "target": [p["target"] for p in got] if need_target else None}


def pick_examples(w, chunk, k=2):
    start = chunk[0]["pos"]
    keys = [(p["spk_id"], p["lst_id"], p["state"]) for p in chunk if p["mode"] == "speech" and p["spk_id"]]
    if not keys:
        return None
    chosen = []
    for level in (3, 2):  # khớp (speaker, listener, state) rồi (speaker, listener)
        for ch in sorted(w.paras, reverse=True):
            for p in reversed(w.paras[ch]):
                if len(chosen) >= k:
                    break
                if (p["pos"] >= start - 2 or p["mode"] != "speech" or not p["conf"] or blank(p["target"])
                        or len(p["source"]) > 300 or p in chosen):
                    continue
                for ks, kl, kt in keys:
                    if p["spk_id"] == ks and p["lst_id"] == kl and (level == 2 or p["state"] == kt):
                        chosen.append(p)
                        break
        if len(chosen) >= k:
            break
    if not chosen:
        return None
    chosen.sort(key=lambda p: p["pos"])
    return [{"source": p["source"], "target": p["target"]} for p in chosen]


def make_record(w, chunk, gran, split, with_target, rng, prev_prob=1.0, ex_prob=1.0):
    ctx, missing = build_context(w, chunk)
    prev = build_prev(w, chunk, need_target=with_target) if rng.random() < prev_prob else None
    ex = pick_examples(w, chunk) if rng.random() < ex_prob else None
    paras = para_records(chunk)
    rec = {"template_version": PT.TEMPLATE_VERSION, "book": C.BOOK_KEY, "chapter": chunk[0]["chapter"],
           "para_start": chunk[0]["para"], "para_end": chunk[-1]["para"] + 1, "granularity": gran, "split": split,
           "source_hash": sha("\n".join(p["source"] for p in chunk)), "context": ctx, "paras": paras,
           "prev": prev, "examples": ex}
    rec["context_hash"] = sha(json.dumps({"c": ctx, "p": paras, "pv": prev, "ex": ex, "v": PT.TEMPLATE_VERSION},
                                         sort_keys=True, ensure_ascii=False))
    if with_target:
        rec["target"] = [p["target"] for p in chunk]
    return rec, missing


def record_snapshot(db, book_id, rec):
    sid, _ = db.upsert("TranslationContextSnapshots",
                       {"BookId": book_id, "ChapterNumber": rec["chapter"], "ParaStart": rec["para_start"],
                        "ParaEnd": rec["para_end"], "ContextHash": rec["context_hash"]},
                       {"TemplateVersion": rec["template_version"],
                        "ContextJson": json.dumps({k: rec[k] for k in ("context", "paras", "prev", "examples")},
                                                  ensure_ascii=False)},
                       "SnapshotId", insert_only={"CreatedAt": utcnow()})
    rec["snapshot_id"] = sid


def usable_for_train(chunk):
    if not all(p["conf"] for p in chunk):
        return "chưa confirmed"
    if any(blank(p["target"]) for p in chunk):
        return "thiếu bản dịch"
    if any(p["target"].startswith("(gộp") for p in chunk):
        return "đoạn dịch bị gộp"
    return None


def cmd_export_train(db, out_dir, val_chapters=(), chapters=None, record_snapshots=False, strict=False):
    os.makedirs(out_dir, exist_ok=True)
    w = World(db)
    rng = random.Random(C.RNG_SEED)
    chs = sorted(chapters or w.paras)
    seen, records, skipped = set(), [], Counter()
    missing_all = Counter()
    for ch in chs:
        ps = w.paras.get(ch, [])
        if not ps:
            print(f"  ! chương {ch} chưa có trong DB")
            continue
        cuts = w.cuts.get(ch, set())
        is_val = ch in val_chapters
        plan = []
        if is_val:
            plan += [("chunk", c) for c in chunk_paras(ps, cuts, C.CHUNK_MAX_PARAS, C.CHUNK_MAX_CHARS, 0)]
        else:
            for off in C.SLIDING_OFFSETS:
                plan += [("chunk", c) for c in chunk_paras(ps, cuts, C.CHUNK_MAX_PARAS, C.CHUNK_MAX_CHARS, off)]
        full = [x for x in plan if x[0] == "chunk"]
        if not is_val:
            mids = chunk_paras(ps, cuts, C.MID_MAX_PARAS, C.MID_MAX_CHARS, 0)
            rng.shuffle(mids)
            plan += [("mid", c) for c in mids[:round(len(full) * 25 / 60)]]
            hards = hard_windows(ps, cuts)
            rng.shuffle(hards)
            plan += [("hard", c) for c in hards[:max(round(len(full) * 15 / 60), min(len(hards), 3))]]
        for gran, chunk in plan:
            key = (ch, chunk[0]["para"], chunk[-1]["para"])
            if key in seen:
                skipped["trùng đoạn"] += 1
                continue
            why = usable_for_train(chunk)
            if why:
                skipped[why] += 1
                continue
            seen.add(key)
            rec, miss = make_record(w, chunk, gran, "val" if is_val else "train", True, rng,
                                    prev_prob=1.0 if is_val else C.PREV_PROB,
                                    ex_prob=1.0 if is_val else C.EXAMPLES_PROB)
            for m in miss:
                missing_all[m] += 1
            if record_snapshots:
                record_snapshot(db, w.book_id, rec)
            records.append(rec)
    if strict and missing_all:
        raise SystemExit(f"--strict: còn {len(missing_all)} khoá xưng hô chưa có rule (xem qa-rules). Chưa xuất file.")
    tr = [r for r in records if r["split"] == "train"]
    va = [r for r in records if r["split"] == "val"]
    for name, rs in (("train.jsonl", tr), ("val.jsonl", va)):
        if rs:
            with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
                for r in rs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if record_snapshots:
        db.commit()
    lens = [len(PT.render_user(r["context"], r["paras"], r["prev"], r["examples"])) + sum(map(len, r["target"]))
            for r in records]
    rep = [f"# Báo cáo export-train\n", f"- Template: {PT.TEMPLATE_VERSION}",
           f"- Mẫu train: {len(tr)}, val: {len(va)}",
           "- Theo mức: " + ", ".join(f"{k}={v}" for k, v in Counter(r["granularity"] for r in records).items()),
           f"- Có <prev>: {sum(1 for r in records if r['prev'])}; có <examples>: {sum(1 for r in records if r['examples'])}"]
    if lens:
        rep.append(f"- Độ dài prompt+đáp án (ký tự): min {min(lens)}, TB {sum(lens)//len(lens)}, max {max(lens)} "
                   f"(≈ {max(lens)//3} token ở mức cao nhất; đặt max_seq_length cho phù hợp)")
    if skipped:
        rep.append("- Bỏ qua: " + ", ".join(f"{k}={v}" for k, v in skipped.items()))
    rep.append("\n## Khoá xưng hô chưa có rule (speaker → listener | mode | state): số đoạn")
    for (a, b, m, s), n in missing_all.most_common():
        rep.append(f"- {a} → {b or '(không rõ)'} | {m} | {s}: {n}")
    if not missing_all:
        rep.append("(không có)")
    open(os.path.join(out_dir, "export_report.md"), "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print("\n".join(rep))


def cmd_export_pending(db, out_dir, chapter, retranslate=False):
    os.makedirs(out_dir, exist_ok=True)
    w = World(db)
    rng = random.Random(C.RNG_SEED)
    ps = w.paras.get(chapter, [])
    if not ps:
        raise SystemExit(f"Chương {chapter} chưa có trong DB (hãy import-annotations trước).")
    chunks = chunk_paras(ps, w.cuts.get(chapter, set()), C.CHUNK_MAX_PARAS, C.CHUNK_MAX_CHARS, 0)
    recs, skipped, missing_all = [], Counter(), Counter()
    for chunk in chunks:
        if not all(p["conf"] for p in chunk):
            skipped["chưa confirmed nhãn"] += 1
            continue
        if not retranslate and any(not blank(p["target"]) for p in chunk):
            skipped["đã có bản dịch"] += 1
            continue
        rec, miss = make_record(w, chunk, "chunk", "pending", False, rng)
        for m in miss:
            missing_all[m] += 1
        rec["chunk_key"] = f"{chapter}:{rec['para_start']}-{rec['para_end']}"
        recs.append(rec)
    s = Session(db)
    job_id = None
    if recs and db.table_exists("TranslationJobs"):
        path_name = f"pending_chunks_ch{chapter}.json"
        job_id = db.insert("TranslationJobs", {"BookId": s.book_id, "ChapterId": s.chapter(chapter),
                                               "TemplateVersion": PT.TEMPLATE_VERSION, "JobStatus": "exported",
                                               "PendingFile": path_name, "ChunkCount": len(recs),
                                               "ExportedAt": utcnow()}, "JobId")
        db.commit()
    for r in recs:
        r["job_id"] = job_id
    path = os.path.join(out_dir, f"pending_chunks_ch{chapter}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=1)
    print(f"Đã xuất {len(recs)} chunk -> {path} (job_id={job_id}); bỏ qua: {dict(skipped)}")
    if missing_all:
        print("  ! Còn khoá xưng hô chưa có rule:", ", ".join(f"{a}→{b or '-'}|{m}|{s}" for (a, b, m, s) in missing_all))


# --------------------------------------------------------------------------- 6. QA xưng hô
PRON_RX = re.compile(r"(?<!\w)(chúng tôi|chúng em|chúng ta|hai em|các em|anh ta|hắn ta|cô ấy|em ấy|tôi|ta|em|thầy|anh|"
                     r"ngươi|cô(?! đơn)|ông|bạn|cậu|mày|tao)(?!\w)", re.I)
IGNORE = {"chúng ta", "anh ta", "hắn ta", "cô ấy", "em ấy"}
FIRST = {"tôi", "ta", "em", "chúng tôi", "chúng em"}
SECOND = {"ngươi", "anh", "thầy", "bạn", "cậu", "mày", "ông", "cô", "hai em", "các em", "em"}


def allowed_tokens(rule):
    toks = set()
    for fld in (rule["SelfPronoun"], rule["AddressPronoun"], rule["ReferPronoun"]):
        for t in re.split(r"[/,]", fld or ""):
            t = t.strip().lower()
            if t:
                toks.add(t)
                parts = t.split()
                if len(parts) > 1 and parts[0] in ("chúng", "hai", "các"):
                    toks.add(parts[-1])
    if any("em" in t.split() for t in toks):          # số nhiều của "em"
        toks |= {"em", "hai em", "các em", "chúng em"}
    if toks & {"ta", "tôi"}:
        toks.add("chúng tôi")                           # nói về nhóm của mình
    return toks


def cmd_qa_rules(db, out_dir="out", chapters=None):
    os.makedirs(out_dir, exist_ok=True)
    w = World(db)
    miss, flags = Counter(), []
    miss_ex = defaultdict(list)
    checked = 0
    for ch in sorted(chapters or w.paras):
        for p in w.paras.get(ch, []):
            if p["mode"] not in ("speech", "thought") or p["spk_id"] is None or not p["conf"]:
                continue
            rule = w.resolve_rule(p["spk_id"], p["lst_id"], p["mode"], p["state"], p["pos"])
            if rule is None:
                k = (p["spk"], p["lst"], p["mode"], p["state"] or "normal")
                miss[k] += 1
                miss_ex[k].append(f"{ch}:{p['para']}")
                continue
            if blank(p["target"]):
                continue
            checked += 1
            allowed = allowed_tokens(rule)
            found = {m.group(1).lower() for m in PRON_RX.finditer(p["target"])} - IGNORE
            bad = {t for t in found if t not in allowed}
            if not rule["SelfPronoun"]:
                bad -= FIRST
            if not rule["AddressPronoun"]:
                bad -= SECOND
            if bad:
                flags.append((ch, p["para"], p["spk"], p["lst"], p["state"], sorted(bad), p["target"]))
    rep = ["# Báo cáo qa-rules", f"- Đã đối chiếu {checked} đoạn thoại/suy nghĩ có rule; "
           f"{len(flags)} đoạn có đại từ ngoài rule; {sum(miss.values())} đoạn chưa có rule.", "",
           "## Khoá chưa có rule (thêm vào seed/pronoun_rules.csv)", ""]
    for k, n in miss.most_common():
        rep.append(f"- {k[0]} → {k[1] or '(không rõ)'} | {k[2]} | {k[3]}: {n} đoạn (vd {', '.join(miss_ex[k][:3])})")
    if not miss:
        rep.append("(không có)")
    rep += ["", "## Đoạn có đại từ ngoài rule (cảnh báo: có thể là lời nhắc tới người khác hoặc trích dẫn)", ""]
    for ch, pa, a, b, st, bad, tx in flags:
        rep.append(f"- ch.{ch} đoạn {pa} ({a} → {b or '-'}, {st}): lạ {bad}\n  - {tx[:150]}")
    if not flags:
        rep.append("(không có)")
    path = os.path.join(out_dir, "qa_rules_report.md")
    open(path, "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print("\n".join(rep[:2]) + f"\n  chi tiết: {path}")


# --------------------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sqlite", help="dùng file SQLite thay vì SQL Server (chạy thử)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init-db")
    p.add_argument("--full", action="store_true", help="DB TRỐNG: tạo toàn bộ schema v3 (sql/020). Mặc định: patch DB v2 (sql/001)")
    sub.add_parser("check-db")
    p = sub.add_parser("import-annotations")
    p.add_argument("xlsx")
    p.add_argument("--sheet", default="Annotate")
    p.add_argument("--include-unconfirmed", action="store_true")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("sync-seeds")
    p.add_argument("--seed-dir")
    p = sub.add_parser("build-context")
    p.add_argument("--out", default="out")
    p = sub.add_parser("qa-rules")
    p.add_argument("--out", default="out")
    p.add_argument("--chapters")
    p = sub.add_parser("export-train")
    p.add_argument("--out", default="out")
    p.add_argument("--chapters")
    p.add_argument("--val-chapters", default="")
    p.add_argument("--record-snapshots", action="store_true")
    p.add_argument("--strict", action="store_true")
    p = sub.add_parser("export-pending")
    p.add_argument("--chapter", type=int, required=True)
    p.add_argument("--out", default="out")
    p.add_argument("--retranslate", action="store_true")
    p = sub.add_parser("all")
    p.add_argument("--xlsx", required=True)
    p.add_argument("--out", default="out")
    p.add_argument("--val-chapters", default="")
    a = ap.parse_args()

    ints = lambda s: [int(x) for x in s.split(",") if x.strip()] if s else []
    db = DB.sqlite(a.sqlite) if a.sqlite else DB.sqlserver(C.SQLSERVER_CONN)
    try:
        if a.cmd == "init-db":
            cmd_init_db(db, a.full)
        elif a.cmd == "check-db":
            sys.exit(1 if cmd_check_db(db) else 0)
        else:
            if cmd_check_db(db, quiet=True):
                raise SystemExit("Schema chưa đủ; chạy init-db trước.")
            if a.cmd == "import-annotations":
                cmd_import_annotations(db, a.xlsx, a.sheet, a.include_unconfirmed, a.force)
            elif a.cmd == "sync-seeds":
                cmd_sync_seeds(db, a.seed_dir)
            elif a.cmd == "build-context":
                cmd_build_context(db, a.out)
            elif a.cmd == "qa-rules":
                cmd_qa_rules(db, a.out, ints(a.chapters) or None)
            elif a.cmd == "export-train":
                cmd_export_train(db, a.out, ints(a.val_chapters), ints(a.chapters) or None, a.record_snapshots,
                                 a.strict)
            elif a.cmd == "export-pending":
                cmd_export_pending(db, a.out, a.chapter, a.retranslate)
            elif a.cmd == "all":
                cmd_import_annotations(db, a.xlsx)
                cmd_sync_seeds(db)
                cmd_build_context(db, a.out)
                cmd_qa_rules(db, a.out)
                cmd_export_train(db, a.out, ints(a.val_chapters))
    except BaseException:
        db.rollback()
        raise
    finally:
        db.conn.close()


if __name__ == "__main__":
    main()
