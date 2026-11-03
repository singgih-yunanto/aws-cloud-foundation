#!/usr/bin/env python3
"""Membuat user-data siap tempel dari lab-app.py + user-data.template.sh.

Pemakaian:  python build-userdata.py
Hasil:      user-data.lab4.sh  (library standar saja, TRACING off, tanpa DB)      -> Lab 4 (dan instance tunggal Lab 5)
            user-data.lab6.sh  (extras, TRACING on, DocumentDB)                    -> Lab 6, Lab 8
Tanpa CloudWatch Agent: dipasang peserta (instance tunggal Lab 5, ASG Lab 6; lihat cwagent/).
Batas User Data EC2 adalah 16 KB (sebelum base64); skrip memeriksanya.
"""
import base64, gzip, pathlib

here = pathlib.Path(__file__).parent
app = (here / "lab-app.py").read_bytes()
b64 = base64.b64encode(gzip.compress(app, 9)).decode()
tpl = (here / "user-data.template.sh").read_text(encoding="utf-8")

variants = {
    "user-data.lab4.sh": {"TRACING": "off", "EXTRAS": "no", "DB_MODE": "mock"},
    "user-data.lab6.sh": {"TRACING": "on", "EXTRAS": "yes", "DB_MODE": "docdb"},
}
for name, v in variants.items():
    out = tpl.replace("@@APP_B64@@", b64)
    for k, val in v.items():
        out = out.replace("@@%s@@" % k, val)
    data = out.encode("utf-8")
    (here / name).write_bytes(data)
    flag = "OK" if len(data) < 16384 else "MELEBIHI 16 KB"
    print("%-20s %6d byte  %s" % (name, len(data), flag))
