#!/usr/bin/env python3
"""Update otomatis: baca HANYA sheet+tab tertentu dari master data, RAMPINGKAN kolom,
lalu tulis JSON kecil ke data/. Juga tulis data/performa_video.json (siap-dashboard).
Dipanggil GitHub Actions tiap 12:00 WIB."""
import os, json, re, datetime
import gspread
from google.oauth2.service_account import Credentials

SOURCES = [
    {"id": "1ka3uaYdQp694XCohtWfVOwE5BCdPvoPQneA1CIFc7KA",
     "tabs": ["Data Omset VT", "Data Jumlah VT"], "out": "affiliate_juni2026"},
    {"id": "17zqWC_OAsinyUzhVQmcnaLQiQJv6I8DRo4i9dVNKtC8",
     "tabs": ["Data Omset VT 1 Juni 2026"], "out": "omset_vt"},
    {"id": "1ETAp3hX_zJgoWzZBEq3kss3XdDs5Rl-d_65FClRYtRs",
     "tabs": ["Result KOL", "Deal KOL", "Result Mega"], "out": "kol"},
    {"id": "1aw9DNP-qIAOYIqD7RTJR4Cx4awYVAcH5s9dtMqZRqF0",
     "tabs": ["Deal Affiliate"], "out": "deal_affiliate"},
]
# Kolom yang disimpan (cocok jika header mengandung salah satu kata ini) — untuk merampingkan.
KEEP = ["pic","kategori","nama kreator","id kreator","id video","informasi video",
        "waktu","tanggal","vv","view","like","komentar","komen","dibagikan","share",
        "klik produk","klik","gmv video","gmv","username","followers","ratecard","rate card",
        "jenis","type","status","deal","code"]
MB = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'Mei':5,'Jun':6,'Jul':7,'Agu':8,'Agt':8,'Sep':9,'Okt':10,'Nov':11,'Des':12}

def iso(s):
    s=str(s).strip()
    m=re.match(r'^(\d{4})-(\d{2})-(\d{2})',s)
    if m: return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m=re.match(r'^(\d{1,2})\s+([A-Za-z]{3,4})\s+(\d{4})$',s)
    if m:
        d,mon,y=m.groups(); mo=MB.get(mon[:3].title()); return f"{y}-{mo:02d}-{int(d):02d}" if mo else None
    return None
def toi(v):
    m=re.search(r'\d+',re.sub(r'[.,]','',str(v))); return int(m.group()) if m else 0

def pick(sh,want):
    wl=sh.worksheets()
    for w in wl:
        if w.title.strip().lower()==want.strip().lower(): return w
    for w in wl:
        if want.strip().lower() in w.title.strip().lower(): return w
    return None
def hidx(rows):
    for i,r in enumerate(rows[:15]):
        if sum(1 for c in r if str(c).strip())>=3: return i
    return 0
def keep_col(h):
    hl=h.lower()
    return any(k in hl for k in KEEP)

def slim_tab(ws):
    vals=ws.get_all_values()
    if not vals: return {"headers":[],"rows":[]}
    hi=hidx(vals); headers=[str(c).strip() for c in vals[hi]]
    cols=[j for j,h in enumerate(headers) if h and keep_col(h)]
    kh=[headers[j] for j in cols]
    out=[]
    for r in vals[hi+1:]:
        if not any(str(c).strip() for c in r): continue
        out.append({headers[j]:(str(r[j]).strip() if j<len(r) else "") for j in cols})
    return {"headers":kh,"rows":out}

def build_performa(sh):
    """Dedupe per ID Video (snapshot Tanggal Data terbaru) -> baris siap dashboard."""
    ws=pick(sh,"Data Omset VT 1 Juni 2026") or pick(sh,"Data Omset VT")
    if not ws: return []
    vals=ws.get_all_values()
    if not vals: return []
    hi=hidx(vals); H={h.strip():i for i,h in enumerate(vals[hi])}
    def g(r,c):
        i=H.get(c); return r[i] if (i is not None and i<len(r)) else ""
    best={}
    for r in vals[hi+1:]:
        vid=str(g(r,"ID Video")).strip()
        if not vid: continue
        td=iso(g(r,"Tanggal Data")) or "0000-00-00"
        rec={"u":str(g(r,"Nama Kreator")).strip(),"vid":vid,"pd":iso(g(r,"Waktu")),
             "pic":str(g(r,"PIC")).strip(),"kat":str(g(r,"Kategori")).strip(),
             "view":toi(g(r,"VV")),"klik":toi(g(r,"Klik Produk")),"gmv":toi(g(r,"GMV video (Rp)"))}
        if vid not in best or td>best[vid][0]: best[vid]=(td,rec)
    return [v[1] for v in best.values()]

def main():
    sa=json.loads(os.environ["GOOGLE_SA_KEY"])
    creds=Credentials.from_service_account_info(sa,scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    gc=gspread.authorize(creds)
    os.makedirs("data",exist_ok=True)
    stamp=datetime.datetime.utcnow().replace(microsecond=0).isoformat()+"Z"
    sheets={}
    for src in SOURCES:
        sh=gc.open_by_key(src["id"]); sheets[src["id"]]=sh
        out={"updated":stamp,"tabs":{}}
        for want in src["tabs"]:
            ws=pick(sh,want)
            if not ws:
                out["tabs"][want]={"error":"tab tidak ditemukan","headers":[],"rows":[]}; continue
            d=slim_tab(ws); out["tabs"][ws.title]=d
            print(f"[OK] {src['out']}/{ws.title}: {len(d['rows'])} baris, {len(d['headers'])} kol")
        json.dump(out,open(f"data/{src['out']}.json","w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
    # file siap-dashboard
    rows=build_performa(sheets["17zqWC_OAsinyUzhVQmcnaLQiQJv6I8DRo4i9dVNKtC8"])
    pv={"updated":stamp,"count":len(rows),"rows":rows}
    json.dump(pv,open("data/performa_video.json","w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
    print(f"[OK] performa_video.json: {len(rows)} video unik")

if __name__=="__main__":
    main()
