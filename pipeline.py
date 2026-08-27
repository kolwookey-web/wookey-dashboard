#!/usr/bin/env python3
"""Update otomatis: baca HANYA sheet+tab tertentu dari master data, RAMPINGKAN kolom,
lalu tulis JSON kecil ke data/. Juga tulis data/performa_video.json (siap-dashboard).
Dipanggil GitHub Actions tiap 12:00 WIB."""
import os, json, re, datetime, traceback, time
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

def _retry(fn, tries=6, base=2):
    """Coba ulang saat Google API error sementara (503/500/429/timeout) dgn jeda bertambah."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            m=str(e).lower()
            transient=any(t in m for t in ('503','500','429','unavailable','rate limit','ratelimit','timed out','timeout','deadline','internal error'))
            if i==tries-1 or not transient:
                raise
            wait=base*(2**i)
            print(f"[retry] error sementara ({str(e)[:60]}), tunggu {wait}s lalu ulang ({i+1}/{tries})")
            time.sleep(wait)
def gav(ws):
    return _retry(lambda: ws.get_all_values())

def iso(s):
    s=str(s).strip()
    m=re.match(r'^(\d{4})-(\d{2})-(\d{2})',s)
    if m: return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m=re.match(r'^(\d{4})/(\d{1,2})/(\d{1,2})',s)   # 2026/06/01 16:58:26
    if m:
        y,mo,d=m.groups(); return f"{y}-{int(mo):02d}-{int(d):02d}"
    m=re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})',s)   # 01/06/2026 (d/m/y)
    if m:
        d,mo,y=m.groups(); return f"{y}-{int(mo):02d}-{int(d):02d}"
    m=re.match(r'^(\d{1,2})\s+([A-Za-z]{3,4})\s+(\d{4})$',s)
    if m:
        d,mon,y=m.groups(); mo=MB.get(mon[:3].title()); return f"{y}-{mo:02d}-{int(d):02d}" if mo else None
    return None
def toi(v):
    s=str(v).strip()
    # angka valid: hanya digit + pemisah ribuan/desimal (tanpa huruf). Cegah ID produk/teks nyasar.
    if not re.match(r'^\d[\d.,\s]*$', s): return 0
    m=re.match(r'^\d[\d.,]*', s)
    if not m: return 0
    digits=re.sub(r'[.,]','',m.group())
    if not digits or len(digits)>12: return 0   # >12 digit = kemungkinan ID, bukan angka metrik
    return int(digits)

def pick(sh,want):
    wl=_retry(lambda: sh.worksheets())
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
    vals=gav(ws)
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
    vals=gav(ws)
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


BULANL = {'januari':1,'februari':2,'maret':3,'april':4,'mei':5,'juni':6,'juli':7,
          'agustus':8,'september':9,'oktober':10,'november':11,'desember':12}
def iso_long(s):
    s=str(s).strip()
    v=iso(s)
    if v: return v
    m=re.match(r'^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$', s)
    if m:
        d,mon,y=m.groups(); mo=BULANL.get(mon.lower())
        if mo: return f"{y}-{mo:02d}-{int(d):02d}"
    return None

def hmap(vals):
    hi=hidx(vals); headers=[str(c).strip() for c in vals[hi]]
    idxs={}
    for j,h in enumerate(headers):
        idxs.setdefault(h,[]).append(j)
    return hi, headers, idxs

def build_kol_result(sh):
    # peta username -> PIC dari Deal KOL
    picmap={}
    dws=pick(sh,"Deal KOL")
    if dws:
        v=gav(dws); hi,H,I=hmap(v)
        ui=(I.get("Username KOL") or I.get("UsernameKOL") or [None])[0]
        pi=(I.get("PIC") or [None])[0]
        if ui is not None and pi is not None:
            for r in v[hi+1:]:
                u=(r[ui].strip() if ui<len(r) else "")
                p=(r[pi].strip() if pi<len(r) else "")
                if u and p and u not in picmap: picmap[u]=p
    rows=[]
    def add(ws, src, pic_from_col):
        if not ws: return
        v=gav(ws); hi,H,I=hmap(v)
        def gi(*names):
            for n in names:
                if n in I: return I[n][0]
            return None
        u_i=gi("UsernameKOL","Username KOL"); cb_i=gi("Jenis KOL"); ct_i=gi("Ket KOL","Type KOL")
        pd_i=gi("Tanggal Posting"); lk_i=gi("Link Posting"); cd_i=gi("SPARK ADS")
        vw_i=gi("View"); li_i=gi("Like"); ko_i=gi("Komen"); sh_i=gi("Share"); kp_i=gi("Klik Produk")
        pic_i=gi("PIC")
        gmv_list=I.get("GMV",[])
        gmv_i=None
        if gmv_list:
            after=[g for g in gmv_list if kp_i is not None and g>kp_i]
            gmv_i=(after[0] if after else gmv_list[-1])
        for r in v[hi+1:]:
            def c(i): return (r[i].strip() if (i is not None and i<len(r)) else "")
            u=c(u_i)
            if not u: continue
            view=toi(c(vw_i)); klik=toi(c(kp_i))
            rows.append({
                "src":src,"u":u,"cb":c(cb_i),"ct":c(ct_i),
                "pic":(c(pic_i) if pic_from_col else picmap.get(u,"")),
                "pd":iso_long(c(pd_i)),
                "view":view,"like":toi(c(li_i)),"komen":toi(c(ko_i)),"share":toi(c(sh_i)),
                "gmv":toi(c(gmv_i)),"klik":klik,
                "ctr":(klik/view*100 if view>0 else None),
                "link":c(lk_i),"code":c(cd_i)
            })
    add(pick(sh,"Result KOL"), "KOL", False)
    add(pick(sh,"Result Mega"), "Mega", True)
    return rows

def build_kol_deal(sh):
    """DEAL siap-dashboard dari Deal KOL. Kategori dijoin dari Jenis KOL (Result KOL/Mega)."""
    # peta username -> kategori (Jenis KOL): Pareto/KOL/Clipper/dll
    catmap={}
    for tabn in ("Result KOL","Result Mega"):
        ws=pick(sh,tabn)
        if not ws: continue
        v=gav(ws); hi,H,I=hmap(v)
        ui=(I.get("UsernameKOL") or I.get("Username KOL") or [None])[0]
        ji=(I.get("Jenis KOL") or [None])[0]
        if ui is None or ji is None: continue
        for r in v[hi+1:]:
            u=(r[ui].strip() if ui<len(r) else ""); k=(r[ji].strip() if ji<len(r) else "")
            if u and k and u not in catmap: catmap[u]=k
    ws=pick(sh,"Deal KOL")
    if not ws: return []
    v=gav(ws); hi,H,I=hmap(v)
    def gi(*names):
        for n in names:
            if n in I: return I[n][0]
        return None
    d_i=gi("Tanggal Deal"); p_i=gi("PIC"); t_i=gi("Type KOL","Jenis KOL")
    u_i=gi("Username KOL","UsernameKOL"); st_i=gi("STATUS","Status")
    rc_i=None
    for h in I:
        if "total ratecard" in h.lower(): rc_i=I[h][0]; break
    if rc_i is None: rc_i=gi("Rate Card Tawar","Rate Card")
    vt_i=gi("Jumlah VT Deal")
    rows=[]
    for r in v[hi+1:]:
        def c(i): return (r[i].strip() if (i is not None and i<len(r)) else "")
        u=c(u_i)
        if not u: continue
        vtraw=c(vt_i); vtnum=re.sub(r'[.,]','',vtraw)
        is_num=bool(re.fullmatch(r'\d+', vtnum)) and vtnum!=""
        cat=catmap.get(u,"KOL")
        rows.append({
            "date":iso_long(c(d_i)),"pic":c(p_i),"category":cat,"type":c(t_i),
            "username":u,"ratecardDeal":toi(c(rc_i)),
            "vtDeal":(int(vtnum) if is_num else None),
            "vtRaw":vtraw,"vtExclusive":(not is_num and vtraw!=""),
            "status":c(st_i)
        })
    return rows

def _colmap(ws):
    v=gav(ws); hi,H,I=hmap(v)
    def gi(*names):
        for n in names:
            if n in I: return I[n][0]
        # partial match
        for n in names:
            nl=n.lower()
            for h in I:
                if nl in h.lower(): return I[h][0]
        return None
    return v,hi,gi

# Semua spreadsheet Master Data yang menyusun tab Eksternal & Affiliate.
# has_meta=True bila tab Omset punya kolom Kategori & PIC (dipakai untuk mewarnai kreator).
RADAR_OMSET = [
    ("17zqWC_OAsinyUzhVQmcnaLQiQJv6I8DRo4i9dVNKtC8", "Data Omset VT", True),   # #10 2024-2026 (ada Kategori/PIC)
    ("1ka3uaYdQp694XCohtWfVOwE5BCdPvoPQneA1CIFc7KA", "Data Omset VT", False),  # #6  Jun 2026
    ("12oqomN_Gp1O5QWNEdrfywp_Bs582DOGQ6ZviXuHYNP8", "Data Omset VT", False),  # #7  Feb-Mei 2026
    ("1V-3YQu5mlLlqzcf7fXldDfFr8lyAgDzvJzX_JkCD1zA", "Data Omset VT", False),  # #8  Agu2025-Jan2026
    ("1srEe2soNggNqNy_YDyMC9ZWPpX8rMJXL7CL_OTql9Hw", "Data Omset VT", False),  # #9  Okt2024-Jul2025
]
RADAR_JVT = [
    ("1g1536iL_73eGtXwTJ_6x2AlHcprzlfp6NnoiPmXtseQ", "Data Jumlah VT"),  # #11 Okt2024-Jul2026
    ("1ka3uaYdQp694XCohtWfVOwE5BCdPvoPQneA1CIFc7KA", "Data Jumlah VT"),  # #6
    ("12oqomN_Gp1O5QWNEdrfywp_Bs582DOGQ6ZviXuHYNP8", "Data Jumlah VT"),  # #7
    ("1V-3YQu5mlLlqzcf7fXldDfFr8lyAgDzvJzX_JkCD1zA", "Data Jumlah VT"),  # #8
    ("1srEe2soNggNqNy_YDyMC9ZWPpX8rMJXL7CL_OTql9Hw", "Data Jumlah VT"),  # #9
]
RADAR_DEAL = [
    ("1aw9DNP-qIAOYIqD7RTJR4Cx4awYVAcH5s9dtMqZRqF0", "Deal Affiliate"),  # #4  2026
    ("1pPR0iEjTRrcyyAxLe-ctpW375fBjIG3xq2n2Y0fmnck", "Deal Affiliate"),  # #5  2024-2025
]

def build_radar(opener):
    """Kompilasi struktur D untuk tab Eksternal & Affiliate dari SEMUA sheet Master Data.
    opener(id) -> spreadsheet (atau None bila tak bisa diakses)."""
    _cache={}
    def getsheet(sid):
        if sid not in _cache:
            try: _cache[sid]=opener(sid)
            except Exception as e: print(f"[WARN] tak bisa buka {sid}: {e}"); _cache[sid]=None
        return _cache[sid]
    # ---------- 1) OMSET: dedup per ID Video (utamakan yg punya kategori/PIC) ----------
    omvid={}
    def read_om(ws, has_meta):
        if not ws: return
        v,hi,gi=_colmap(ws)
        u_i=gi("Nama Kreator"); vid_i=gi("ID Video"); wk_i=gi("Waktu")
        vv_i=gi("VV","View"); kp_i=gi("Klik Produk"); gm_i=gi("GMV video (Rp)","GMV video","GMV dari video")
        kt_i=gi("Kategori") if has_meta else None; pc_i=gi("PIC") if has_meta else None
        for r in v[hi+1:]:
            def c(i): return (r[i].strip() if (i is not None and i<len(r)) else "")
            vid=c(vid_i); u=c(u_i)
            if not vid or not u: continue
            day=iso(c(wk_i))
            rec={"u":u,"day":day,"vv":toi(c(vv_i)),"kl":toi(c(kp_i)),"gm":toi(c(gm_i)),
                 "kat":(c(kt_i) if kt_i is not None else ""),"pic":(c(pc_i) if pc_i is not None else "")}
            old=omvid.get(vid)
            if old is None: omvid[vid]=rec
            else:
                # lengkapi kategori/pic bila kosong; pertahankan angka terbesar (snapshot terbaru)
                if not old["kat"] and rec["kat"]: old["kat"]=rec["kat"]
                if not old["pic"] and rec["pic"]: old["pic"]=rec["pic"]
                if rec["vv"]>old["vv"]: old["vv"]=rec["vv"]
                if rec["kl"]>old["kl"]: old["kl"]=rec["kl"]
                if rec["gm"]>old["gm"]: old["gm"]=rec["gm"]
                if not old["day"] and rec["day"]: old["day"]=rec["day"]
    for sid,tab,has_meta in RADAR_OMSET:
        try:
            sh=getsheet(sid)
            if sh:
                ws=pick(sh,tab)
                if ws: read_om(ws,has_meta); print(f"[radar] Omset {sid[:6]}/{ws.title}: {len(omvid)} vid kumulatif")
        except Exception as e:
            print(f"[WARN] radar Omset {sid[:6]} dilewati: {e}")
    # ---------- 2) JVT: dedup per ID Video ----------
    jvid={}
    for sid,tab in RADAR_JVT:
        try:
            sh=getsheet(sid)
            if not sh: continue
            ws=pick(sh,tab)
            if not ws: continue
            v,hi,gi=_colmap(ws)
            u_i=gi("Nama Kreator"); vid_i=gi("ID Video"); wk_i=gi("Waktu")
            for r in v[hi+1:]:
                def c(i): return (r[i].strip() if (i is not None and i<len(r)) else "")
                vid=c(vid_i); u=c(u_i)
                if not vid or not u: continue
                if vid not in jvid: jvid[vid]={"u":u,"day":iso(c(wk_i))}
            print(f"[radar] JVT {sid[:6]}/{ws.title}: {len(jvid)} vid kumulatif")
        except Exception as e:
            print(f"[WARN] radar JVT {sid[:6]} dilewati: {e}")
    # ---------- 3) tanggal kontigu ----------
    alldays=set()
    for r in omvid.values():
        if r["day"]: alldays.add(r["day"])
    for r in jvid.values():
        if r["day"]: alldays.add(r["day"])
    deal_rows=[]
    for sid,tab in RADAR_DEAL:
      try:
        sh=getsheet(sid)
        if not sh: continue
        ws=pick(sh,tab)
        if not ws: continue
        v,hi,gi=_colmap(ws)
        u_i=gi("Username"); t_i=gi("Tanggal"); p_i=gi("PIC")
        for r in v[hi+1:]:
            def c(i): return (r[i].strip() if (i is not None and i<len(r)) else "")
            u=c(u_i); day=iso_long(c(t_i))
            if not u or not day: continue
            deal_rows.append({"u":u,"day":day,"pic":c(p_i)})
            alldays.add(day)
        print(f"[radar] Deal {sid[:6]}/{ws.title}: {len(deal_rows)} baris kumulatif")
      except Exception as e:
        print(f"[WARN] radar Deal {sid[:6]} dilewati: {e}")
    if not alldays:
        return None
    import datetime as _dt
    d0=min(alldays); d1=max(alldays)
    y0,m0,dd0=map(int,d0.split("-")); y1,m1,dd1=map(int,d1.split("-"))
    cur=_dt.date(y0,m0,dd0); end=_dt.date(y1,m1,dd1)
    dates=[];
    while cur<=end:
        dates.append(cur.isoformat()); cur+=_dt.timedelta(days=1)
    didx={d:i for i,d in enumerate(dates)}; NDAY=len(dates)
    # ---------- 4) creators (Omset) + agregasi creator-day ----------
    creators=[]; cidx={}
    def cget(u):
        if u not in cidx: cidx[u]=len(creators); creators.append(u)
        return cidx[u]
    ckat=[]; cpic=[]
    agg={}  # (c,d)->[vv,kl,gm,vid]
    dvv=[0]*NDAY; dkl=[0]*NDAY; dgm=[0]*NDAY; dvid=[0]*NDAY
    catcount={}  # c-> {kat:count}
    piccount={}
    for r in omvid.values():
        if not r["day"] or r["day"] not in didx: continue
        c=cget(r["u"]); d=didx[r["day"]]
        a=agg.get((c,d))
        if not a: a=agg[(c,d)]=[0,0,0,0]
        a[0]+=r["vv"]; a[1]+=r["kl"]; a[2]+=r["gm"]; a[3]+=1
        dvv[d]+=r["vv"]; dkl[d]+=r["kl"]; dgm[d]+=r["gm"]; dvid[d]+=1
        if r["kat"]: catcount.setdefault(c,{})[r["kat"]]=catcount.setdefault(c,{}).get(r["kat"],0)+1
        if r["pic"]: piccount.setdefault(c,{})[r["pic"]]=piccount.setdefault(c,{}).get(r["pic"],0)+1
    NC=len(creators)
    ckat=[""]*NC; cpic=[""]*NC; cfirst=[0]*NC
    firstday=[NDAY]*NC
    rows=[]
    for (c,d),a in agg.items():
        rows.append([c,d,a[0],a[1],a[2],a[3]])
        if d<firstday[c]: firstday[c]=d
    for c in range(NC):
        if catcount.get(c): ckat[c]=max(catcount[c].items(),key=lambda x:x[1])[0]
        if piccount.get(c): cpic[c]=max(piccount[c].items(),key=lambda x:x[1])[0]
        cfirst[c]=firstday[c] if firstday[c]<NDAY else 0
    # ---------- 5) JVT: jvtrows, jcfirst, jvtByCi, dvtvid ----------
    jcreators=[]; jidx={}
    def jget(u):
        if u not in jidx: jidx[u]=len(jcreators); jcreators.append(u)
        return jidx[u]
    jvtrows=[]; dvtvid=[0]*NDAY; jvtByCi=[]
    for r in jvid.values():
        if not r["day"] or r["day"] not in didx: continue
        d=didx[r["day"]]; j=jget(r["u"])
        jvtrows.append([j,d]); dvtvid[d]+=1
        if r["u"] in cidx: jvtByCi.append([cidx[r["u"]],d])
    NJ=len(jcreators); jcfirst=[NDAY]*NJ
    for j,d in jvtrows:
        if d<jcfirst[j]: jcfirst[j]=d
    jcfirst=[x if x<NDAY else 0 for x in jcfirst]
    # ---------- 6) Deal Affiliate: dealDeals, cdeal, dealPosts ----------
    dealu=[]; duidx={}
    def duget(u):
        if u not in duidx: duidx[u]=len(dealu); dealu.append(u)
        return duidx[u]
    dealDeals=[]
    for r in deal_rows:
        u=duget(r["u"]); dealDeals.append([u,didx[r["day"]]])
    cdeal=[-1]*NC
    for u,ui in duidx.items():
        if u in cidx: cdeal[cidx[u]]=ui
    # dealPosts: postingan (dari Omset creator-day) utk akun yg ada di Deal Affiliate
    dealPosts=[]
    for (c,d),a in agg.items():
        u=creators[c]
        if u in duidx: dealPosts.append([duidx[u],d,a[3]])
    # ---------- 7) daftar kategori & PIC ----------
    katList=sorted({k for k in ckat if k})
    picList=sorted({p for p in cpic if p}|{r["pic"] for r in deal_rows if r["pic"]})
    D={"dates":dates,"creators":creators,"cfirst":cfirst,"rows":rows,
       "dvv":dvv,"dkl":dkl,"dgm":dgm,"dvid":dvid,"dvtvid":dvtvid,
       "creatorsJ":jcreators,"jvtrows":jvtrows,"jcfirst":jcfirst,"jvtByCi":jvtByCi,
       "dealDeals":dealDeals,"dealPosts":dealPosts,"dealu":dealu,"cdeal":cdeal,
       "ckat":ckat,"cpic":cpic,"katList":katList,"picList":picList}
    return D

def main():
    sa=json.loads(os.environ["GOOGLE_SA_KEY"])
    creds=Credentials.from_service_account_info(sa,scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    gc=gspread.authorize(creds)
    os.makedirs("data",exist_ok=True)
    stamp=datetime.datetime.utcnow().replace(microsecond=0).isoformat()+"Z"
    sheets={}
    for src in SOURCES:
        try:
            sh=_retry(lambda: gc.open_by_key(src["id"])); sheets[src["id"]]=sh
            out={"updated":stamp,"tabs":{}}
            for want in src["tabs"]:
                ws=pick(sh,want)
                if not ws:
                    out["tabs"][want]={"error":"tab tidak ditemukan","headers":[],"rows":[]}; continue
                d=slim_tab(ws); out["tabs"][ws.title]=d
                print(f"[OK] {src['out']}/{ws.title}: {len(d['rows'])} baris, {len(d['headers'])} kol")
            json.dump(out,open(f"data/{src['out']}.json","w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
        except Exception as e:
            traceback.print_exc(); print(f"[WARN] sumber {src['out']} dilewati: {e}")
    rows=[]
    # file siap-dashboard
    try:
        rows=build_performa(sheets["17zqWC_OAsinyUzhVQmcnaLQiQJv6I8DRo4i9dVNKtC8"])
        pv={"updated":stamp,"count":len(rows),"rows":rows}
        json.dump(pv,open("data/performa_video.json","w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
        print(f"[OK] performa_video.json: {len(rows)} video unik")
    except Exception as e:
        traceback.print_exc(); print(f"[WARN] performa_video.json dilewati: {e}")
    # KOL result (siap-dashboard: tab KOL)
    try:
        krows=build_kol_result(sheets["1ETAp3hX_zJgoWzZBEq3kss3XdDs5Rl-d_65FClRYtRs"])
        kr={"updated":stamp,"count":len(krows),"rows":krows}
        json.dump(kr,open("data/kol_result.json","w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
        print(f"[OK] kol_result.json: {len(krows)} baris")
    except Exception as e:
        traceback.print_exc(); print(f"[WARN] kol_result.json dilewati: {e}")
    # KOL deal (kartu Deal)
    try:
        drows=build_kol_deal(sheets["1ETAp3hX_zJgoWzZBEq3kss3XdDs5Rl-d_65FClRYtRs"])
        dd={"updated":stamp,"count":len(drows),"rows":drows}
        json.dump(dd,open("data/kol_deal.json","w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
        print(f"[OK] kol_deal.json: {len(drows)} baris")
    except Exception as e:
        traceback.print_exc(); print(f"[WARN] kol_deal.json dilewati: {e}")
    # KOL performa (kartu Omset/Views) — subset kategori KOL dari performa video
    try:
        KOLCAT={"KOL","Pareto","Spesial","Clipper","Berita"}
        prows=[{"pd":r["pd"],"pic":r.get("pic",""),"cat":r.get("kat",""),
                "view":r.get("view",0),"gmv":r.get("gmv",0),"vid":r.get("vid","")}
               for r in rows if r.get("kat") in KOLCAT]
        pp={"updated":stamp,"count":len(prows),"rows":prows}
        json.dump(pp,open("data/kol_perf.json","w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
        print(f"[OK] kol_perf.json: {len(prows)} baris")
    except Exception as e:
        traceback.print_exc(); print(f"[WARN] kol_perf.json dilewati: {e}")
    # RADAR (tab Eksternal & Affiliate) — kompilasi struktur D dari SEMUA sheet Master Data
    def _open(sid):
        if sid in sheets: return sheets[sid]
        return _retry(lambda: gc.open_by_key(sid))
    try:
        D=build_radar(_open)
        if D:
            D["updated"]=stamp
            json.dump(D,open("data/radar.json","w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
            print(f"[OK] radar.json: {len(D['creators'])} kreator, {len(D['dates'])} hari, {len(D['rows'])} baris")
    except Exception as e:
        traceback.print_exc(); print(f"[WARN] radar.json GAGAL (tab KOL & lainnya tetap tersimpan): {e}")

if __name__=="__main__":
    try:
        main()
    except Exception as e:
        traceback.print_exc()
        print(f"[FATAL] {e} — tapi selesai supaya data yg sudah tertulis tetap tersimpan.")
        # exit 0 supaya workflow tetap commit data yg sudah jadi
