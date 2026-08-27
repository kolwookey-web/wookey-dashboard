#!/usr/bin/env python3
"""Update otomatis: baca HANYA sheet+tab yang ditentukan dari master data,
lalu tulis JSON per-sumber ke folder data/. Dipanggil GitHub Actions tiap 12:00 WIB."""
import os, json, datetime
import gspread
from google.oauth2.service_account import Credentials

# Fokus HANYA ke sheet + tab ini (dari master data)
SOURCES = [
    {"id": "1ka3uaYdQp694XCohtWfVOwE5BCdPvoPQneA1CIFc7KA",   # Data Affiliate Wookey Wight 1 Juni 2026
     "tabs": ["Data Omset VT", "Data Jumlah VT"], "out": "affiliate_juni2026"},
    {"id": "17zqWC_OAsinyUzhVQmcnaLQiQJv6I8DRo4i9dVNKtC8",   # Data Omset VT 2024-2026
     "tabs": ["Data Omset VT 1 Juni 2026"], "out": "omset_vt"},
    {"id": "1ETAp3hX_zJgoWzZBEq3kss3XdDs5Rl-d_65FClRYtRs",   # KOL Wookey Wight 2026
     "tabs": ["Result KOL", "Deal KOL", "Result Mega"], "out": "kol"},
    {"id": "1aw9DNP-qIAOYIqD7RTJR4Cx4awYVAcH5s9dtMqZRqF0",   # Affiliate Wookey Wight 2026
     "tabs": ["Deal Affiliate"], "out": "deal_affiliate"},
]

def pick_ws(sh, want):
    """Cari worksheet: cocok persis dulu, lalu 'contains' (abaikan huруф besar/kecil)."""
    wl = sh.worksheets()
    for w in wl:
        if w.title.strip().lower() == want.strip().lower():
            return w
    for w in wl:
        if want.strip().lower() in w.title.strip().lower():
            return w
    return None

def header_index(rows):
    """Baris header = baris pertama dengan >= 3 sel tidak kosong."""
    for i, r in enumerate(rows[:15]):
        if sum(1 for c in r if str(c).strip()) >= 3:
            return i
    return 0

def tab_to_records(ws):
    vals = ws.get_all_values()
    if not vals:
        return {"headers": [], "rows": []}
    hi = header_index(vals)
    headers = [str(c).strip() for c in vals[hi]]
    recs = []
    for r in vals[hi + 1:]:
        if not any(str(c).strip() for c in r):
            continue
        rec = {}
        for j, h in enumerate(headers):
            if not h:
                continue
            rec[h] = (str(r[j]).strip() if j < len(r) else "")
        recs.append(rec)
    return {"headers": [h for h in headers if h], "rows": recs}

def main():
    sa = json.loads(os.environ["GOOGLE_SA_KEY"])
    creds = Credentials.from_service_account_info(
        sa, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    gc = gspread.authorize(creds)
    os.makedirs("data", exist_ok=True)
    stamp = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    for src in SOURCES:
        sh = gc.open_by_key(src["id"])
        out = {"updated": stamp, "sheetId": src["id"], "tabs": {}}
        for want in src["tabs"]:
            ws = pick_ws(sh, want)
            if not ws:
                out["tabs"][want] = {"error": "tab tidak ditemukan", "headers": [], "rows": []}
                print(f"[WARN] {src['out']}: tab '{want}' tidak ada")
                continue
            data = tab_to_records(ws)
            out["tabs"][ws.title] = data
            print(f"[OK] {src['out']} / {ws.title}: {len(data['rows'])} baris, {len(data['headers'])} kolom")
        path = f"data/{src['out']}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        print(f"  -> {path}")

if __name__ == "__main__":
    main()
