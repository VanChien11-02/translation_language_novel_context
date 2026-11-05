#!/usr/bin/env python3
"""Chạy thử toàn bộ pipeline trên SQLite (không cần SQL Server):
    python selftest_sqlite.py annotation_sheet_annotated.xlsx
Kiểm tra: import idempotent, seed, sự kiện đổi xưng hô, export train/val, export pending."""
import json, os, subprocess, sys, tempfile

xlsx = sys.argv[1]
tmp = tempfile.mkdtemp()
dbf, out = os.path.join(tmp, "t.db"), os.path.join(tmp, "out")
run = lambda *a: subprocess.run([sys.executable, "ctx.py", "--sqlite", dbf, *a], check=True,
                                capture_output=True, text=True).stdout
run("init-db")
print(run("import-annotations", xlsx).strip())
print(run("import-annotations", xlsx).strip(), " <- chạy lần 2 phải 'không đổi'")
run("sync-seeds")
print(run("build-context", "--out", out).strip().splitlines()[0])
run("qa-rules", "--out", out)
print(run("export-train", "--out", out, "--val-chapters", "2").strip().splitlines()[2])
tr = [json.loads(l) for l in open(os.path.join(out, "train.jsonl"), encoding="utf-8")]
va = [json.loads(l) for l in open(os.path.join(out, "val.jsonl"), encoding="utf-8")]
assert tr and va and all(r["template_version"] == "v1" for r in tr + va)
assert all(len(r["paras"]) == len(r["target"]) for r in tr + va)
assert not any(r["chapter"] == 2 for r in tr), "val chapter không được lẫn vào train"
print(run("export-pending", "--chapter", "2", "--retranslate", "--out", out).strip())
print("OK")
