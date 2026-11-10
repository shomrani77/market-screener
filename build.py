import json, datetime, pathlib
import yfinance as yf
from alphasift import screen

TOP = 15
SA = ["2222.SR","1120.SR","1180.SR","2010.SR","7010.SR","1211.SR","2082.SR",
      "1150.SR","1010.SR","1060.SR","1050.SR","1140.SR","2020.SR","2280.SR",
      "4002.SR","4013.SR","4190.SR","5110.SR","2350.SR","2310.SR","1810.SR",
      "4300.SR","2290.SR","4030.SR","4003.SR"]

def to_rows(res):
    for n in ("picks", "results", "rows", "items"):
        v = getattr(res, n, None)
        if v is not None and len(v):
            res = v; break
    if hasattr(res, "to_dict"):
        try: return res.to_dict("records")
        except TypeError: return [res.to_dict()]
    out = []
    for r in res:
        if isinstance(r, dict): out.append(r)
        elif hasattr(r, "model_dump"): out.append(r.model_dump())
        elif hasattr(r, "__dict__"): out.append(vars(r))
        else: out.append({"value": str(r)})
    return out

def clean(rows):
    ok = (str, int, float, bool)
    res = [{k: (round(v, 2) if isinstance(v, float) else v)
            for k, v in r.items() if isinstance(v, ok)} for r in rows]
    return res[:TOP]

def us():
    try:
        res = screen("global_value", use_llm=False, market="us", max_output=15)
    except TypeError:
        res = screen("global_value", use_llm=False, market="us")
    out = []
    for r in to_rows(res):
        mv = r.get("total_mv")
        out.append({
            "الرمز": r.get("code"), "الاسم": r.get("name"),
            "القطاع": r.get("industry"), "السعر": r.get("price"),
            "التغير %": r.get("change_pct"),
            "PE": r.get("pe_ratio"), "PB": r.get("pb_ratio"),
            "القيمة السوقية (مليار $)": round(mv / 1e9, 1) if isinstance(mv, (int, float)) else None,
        })
    return clean(out)

def saudi():
    rows = []
    for t in SA:
        try:
            i = yf.Ticker(t).info
            pe, pb = i.get("trailingPE"), i.get("priceToBook")
            if pe and pb and 0 < pe < 25 and 0 < pb < 4:
                rows.append({"الرمز": t, "الاسم": i.get("shortName", ""),
                             "القطاع": i.get("sector", ""),
                             "PE": round(pe, 2), "PB": round(pb, 2)})
        except Exception:
            continue
    pe_r = {r["الرمز"]: n for n, r in enumerate(sorted(rows, key=lambda x: x["PE"]))}
    pb_r = {r["الرمز"]: n for n, r in enumerate(sorted(rows, key=lambda x: x["PB"]))}
    rows.sort(key=lambda r: pe_r[r["الرمز"]] + pb_r[r["الرمز"]])
    return rows[:TOP]

dj = pathlib.Path("data.json")
old = json.loads(dj.read_text()) if dj.exists() else {}
data = {"updated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
for key, fn in (("sa", saudi), ("us", us)):
    try:
        rows = fn()
        if not rows: raise ValueError("empty")
        data[key] = {"rows": rows, "stale": False}
    except Exception as e:
        print(key, "failed:", e)
        prev = old.get(key, {"rows": []})
        data[key] = {"rows": prev["rows"], "stale": True}
        if "updated_" + key in old: data["updated_" + key] = old["updated_" + key]
    else:
        data["updated_" + key] = data["updated"]

dj.write_text(json.dumps(data, ensure_ascii=False, indent=1))

HTML = """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>فلتر الأسهم</title>
<style>
:root{--bg:#fff;--fg:#1a1a1a;--card:#f3f4f6;--ac:#0f766e}
@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--card:#1e1e1e;--ac:#2dd4bf}}
body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:12px}
button{padding:10px 18px;border:0;border-radius:8px;background:var(--card);color:var(--fg);font-size:16px}
button.on{background:var(--ac);color:#fff}
.w{overflow-x:auto}table{border-collapse:collapse;width:100%;margin-top:10px}
td,th{padding:8px;border-bottom:1px solid var(--card);white-space:nowrap;text-align:right}
.s{color:#dc2626;font-weight:bold}.n{font-size:13px;opacity:.75;line-height:1.7}
</style></head><body>
<h2>نتائج فلترة الأسهم (قيمة: PE وPB منخفضان)</h2>
<div><button id="sa" class="on">🇸🇦 السعودي</button> <button id="us">🇺🇸 الأمريكي</button></div>
<p id="meta" class="n"></p><div class="w"><table id="t"></table></div>
<p class="n">PE = مضاعف الربحية، PB = مضاعف القيمة الدفترية؛ الأقل أرخص نسبياً وليس بالضرورة أفضل.
هذه نتيجة فلترة آلية للبحث والتعلم، وليست توصية شراء أو بيع. البيانات من Yahoo Finance وقد تتأخر أو تنقص.</p>
<script>
const D=__DATA__;let cur="sa";
function show(){
 const s=D[cur]||{rows:[]},rows=s.rows,u=D["updated_"+cur]||"غير معروف";
 const age=u==="غير معروف"?99:(Date.now()-new Date(u.replace(" UTC","").replace(" ","T")+"Z"))/864e5;
 let m="آخر تحديث ناجح: "+u;
 if(s.stale||age>4)m+=' <span class="s">⚠ البيانات قديمة، لا تعتمد عليها</span>';
 document.getElementById("meta").innerHTML=m;
 const t=document.getElementById("t");
 if(!rows.length){t.innerHTML="<tr><td>لا توجد بيانات</td></tr>";return}
 const k=Object.keys(rows[0]);
 t.innerHTML="<tr>"+k.map(x=>"<th>"+x+"</th>").join("")+"</tr>"+
  rows.map(r=>"<tr>"+k.map(x=>"<td>"+(r[x]??"")+"</td>").join("")+"</tr>").join("");
}
for(const id of["sa","us"])document.getElementById(id).onclick=()=>{
 cur=id;document.querySelectorAll("button").forEach(b=>b.classList.toggle("on",b.id==id));show()};
show();
</script></body></html>"""
blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
pathlib.Path("index.html").write_text(HTML.replace("__DATA__", blob), encoding="utf-8")
