from datetime import datetime
import inspect
import json
import os
import time
import urllib.error
import urllib.request
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from streamlit_app import DEFAULT_TASI_TICKERS, run_market_scan

RTL = "\u200f"
TIMEFRAMES = [
    ("15m", "ربع ساعة"),
    ("1h", "ساعة"),
    ("1d", "يومي"),
]

# رابط اختياري لملف خطة ثابت على GitHub إذا رغبت في إرفاقه كرابط نصي أيضاً
REPO_EXCEL_RAW_URL = (
    "https://raw.githubusercontent.com/shomrani77/market-screener/main/"
    "tasi_daily_plan.xlsx"
)


def _pf(hex_color: str) -> PatternFill:
  c = hex_color.lstrip("#")
  return PatternFill(start_color=c, end_color=c, fill_type="solid")


def _api_request(
    token: str,
    method: str,
    payload: dict | None = None,
    retries: int = 3,
) -> dict:
  url = f"https://api.telegram.org/bot{token}/{method}"
  data = None
  headers = {}
  if payload is not None:
    data = json.dumps(payload).encode("utf-8")
    headers["Content-Type"] = "application/json"

  last_error: Exception | None = None
  for attempt in range(1, retries + 1):
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
      with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except urllib.error.HTTPError as e:
      body = e.read().decode("utf-8", errors="replace")
      raise RuntimeError(f"Telegram HTTP {e.code} on {method}: {body}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
      last_error = e
      if attempt < retries:
        time.sleep(2 * attempt)

  raise RuntimeError(
      f"Failed {method} after {retries} attempts: {last_error}"
  ) from last_error


def _send_document(
    token: str,
    chat_id: int,
    file_path: str,
    caption: str = "",
    retries: int = 3,
) -> None:
  url = f"https://api.telegram.org/bot{token}/sendDocument"
  boundary = "----TasiScreenerBoundary7MA4YWxkTrZu0gW"
  filename = os.path.basename(file_path)

  with open(file_path, "rb") as f:
    file_bytes = f.read()

  body_parts = []

  def add_field(name: str, value: str) -> None:
    body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
    body_parts.append(
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
    )
    body_parts.append(f"{value}\r\n".encode("utf-8"))

  add_field("chat_id", str(chat_id))
  if caption:
    add_field("caption", caption[:1000])

  body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
  body_parts.append(
      f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
      "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n".encode(
          "utf-8"
      )
  )
  body_parts.append(file_bytes)
  body_parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))

  body = b"".join(body_parts)
  headers = {
      "Content-Type": f"multipart/form-data; boundary={boundary}",
      "Content-Length": str(len(body)),
  }

  last_error: Exception | None = None
  for attempt in range(1, retries + 1):
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
      with urllib.request.urlopen(req, timeout=45) as resp:
        resp.read()
        print(f"Telegram document '{filename}' delivered successfully.")
        return
    except urllib.error.HTTPError as e:
      err_body = e.read().decode("utf-8", errors="replace")
      raise RuntimeError(
          f"Telegram HTTP {e.code} on sendDocument: {err_body}"
      ) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
      last_error = e
      if attempt < retries:
        time.sleep(2 * attempt)

  raise RuntimeError(
      f"Failed sendDocument after {retries} attempts: {last_error}"
  ) from last_error


def verify_credentials(token: str, chat_id_raw: str) -> int:
  if not token or ":" not in token:
    raise ValueError("Invalid TELEGRAM_BOT_TOKEN format.")

  chat_id_str = chat_id_raw.strip()
  try:
    chat_id = int(chat_id_str)
  except ValueError as e:
    raise ValueError(
        f"Invalid TELEGRAM_CHAT_ID ('{chat_id_str}'); must be an integer."
    ) from e

  me = _api_request(token, "getMe")
  bot_info = me.get("result", {})
  print(
      f"Verified bot: @{bot_info.get('username', 'unknown')} | chat_id={chat_id}"
  )
  return chat_id


def send_telegram_message(token: str, chat_id: int, text: str) -> None:
  _api_request(
      token,
      "sendMessage",
      {
          "chat_id": chat_id,
          "text": text[:4000],
          "disable_web_page_preview": True,
      },
  )
  print("Telegram message delivered successfully.")


def _scan_timeframe(tf_code: str):
  sig = inspect.signature(run_market_scan)
  params = sig.parameters
  for name in ("interval", "timeframe", "tf", "period_interval"):
    if name in params:
      return run_market_scan(DEFAULT_TASI_TICKERS, **{name: tf_code})
  return run_market_scan(DEFAULT_TASI_TICKERS) if tf_code == "1d" else None


def _to_float_or_none(val: str) -> float | None:
  cleaned = str(val).replace("—", "").replace("-", "").strip()
  if not cleaned:
    return None
  try:
    return float(cleaned)
  except ValueError:
    return None


def _collect_multi_tf_signals() -> list[dict]:
  merged: dict[str, dict] = {}

  for tf_code, tf_label in TIMEFRAMES:
    df = _scan_timeframe(tf_code)
    if df is None or df.empty:
      continue

    for _, row in df.iterrows():
      ticker = str(row.get("الرمز", "")).strip()
      if not ticker:
        continue

      company = str(row.get("الشركة", "")).strip()
      tier = str(row.get("التصنيف", "")).strip()
      entry = str(row.get("الدخول", "")).strip()
      stop = str(row.get("الوقف", "")).strip()
      target_2r = str(row.get("هدف 2R", "")).strip()

      if ticker not in merged:
        merged[ticker] = {
            "ticker": ticker,
            "company": company,
            "tier": tier,
            "entry": entry,
            "stop": stop,
            "target_2r": target_2r,
            "timeframes": [],
        }

      if tf_label not in merged[ticker]["timeframes"]:
        merged[ticker]["timeframes"].append(tf_label)

      if entry and not merged[ticker]["entry"]:
        merged[ticker]["entry"] = entry
      if stop and not merged[ticker]["stop"]:
        merged[ticker]["stop"] = stop
      if target_2r and not merged[ticker]["target_2r"]:
        merged[ticker]["target_2r"] = target_2r
      if tier:
        merged[ticker]["tier"] = tier

  return sorted(
      merged.values(),
      key=lambda item: len(item["timeframes"]),
      reverse=True,
  )


def _format_multi_tf_card(idx: int, item: dict) -> str:
  ticker = item["ticker"]
  company = item["company"]
  tier = item["tier"]
  entry = item["entry"]
  stop = item["stop"]
  target_2r = item["target_2r"]
  tfs_text = " | ".join(item["timeframes"]) if item["timeframes"] else "يومي"
  tv_url = f"https://www.tradingview.com/symbols/TADAWUL-{ticker}/"

  card_lines = [
      f"{RTL}{idx}) {company} - {ticker} [{tier}]",
      f"{RTL}• ⏱️ الفريمات: {tfs_text}",
      f"{RTL}• 💵 إغلاق أمس: تحقق من TV",
      f"{RTL}• 📊 EMA200 = تحقق من TV",
      f"{RTL}• 📊 RSI = تحقق من TV",
      f"{RTL}• 📈 دخول: {entry} — أكده من TV",
      f"{RTL}• 🛑 وقف: {stop}",
      f"{RTL}• 🎯 هدف 2R: {target_2r}",
      f"{RTL}• 🔗 TV: {tv_url}",
  ]
  return "\n".join(card_lines)


def build_alert_message(
    signals: list[dict], excel_filename: str = "tasi_daily_plan.xlsx"
) -> str:
  if not signals:
    return (
        f"{RTL}📊 فاحص السوق السعودي (تاسي)\n"
        f"{RTL}• 💥 لا توجد إشارات مطابقة حالياً (ربع ساعة / ساعة / يومي)\n"
        f"{RTL}• 📎 ملف الإكسل المرفق: {excel_filename}\n"
        f"{RTL}• 💡 مزاد 9:30-9:55 الرياض"
    )

  parts = [
      f"{RTL}🔥 إشارات فاحص السوق السعودي (15m | 1h | 1d)",
      "────────────────────",
  ]
  for i, item in enumerate(signals[:6], start=1):
    parts.append(_format_multi_tf_card(i, item))
    parts.append("────────────────────")

  parts.append(f"{RTL}📎 ملف خطة اليوم المرفق: {excel_filename}")
  parts.append(f"{RTL}🔗 رابط ملف المستودع: {REPO_EXCEL_RAW_URL}")
  parts.append(f"{RTL}💡 مزاد 9:30-9:55 الرياض")
  return "\n".join(parts)


def generate_daily_excel(signals: list[dict], output_path: str) -> str:
  wb = Workbook()
  navy = "1B2A4A"
  sub_bg = "2D4263"
  sec_bg = "E8EEF5"
  zebra = "F7F9FC"
  white = "FFFFFF"
  border_c = "CBD5E1"

  thin = Side(style="thin", color=border_c)
  med = Side(style="medium", color=navy)
  grid_b = Border(left=thin, right=thin, top=thin, bottom=thin)
  hdr_b = Border(left=thin, right=thin, top=med, bottom=med)

  f_title = Font(name="Calibri", size=14, bold=True, color=white)
  f_sub = Font(name="Calibri", size=10, italic=True, color="E2E8F0")
  f_hdr = Font(name="Calibri", size=10, bold=True, color=white)
  f_body = Font(name="Calibri", size=10, color="0F172A")
  f_bold = Font(name="Calibri", size=10, bold=True, color="0F172A")

  al_c = Alignment(horizontal="center", vertical="center", wrap_text=True)
  al_r = Alignment(horizontal="right", vertical="center", wrap_text=True)

  ws1 = wb.active
  ws1.title = "المرشحون والخطة"
  ws1.views.sheetView[0].rightToLeft = True

  ws1.merge_cells("A1:K1")
  ws1["A1"] = (
      "خطة التداول اليومية والأسهم المرشحة (رأس المال المرجعي: 100,000 ريال)"
  )
  ws1["A1"].font = f_title
  ws1["A1"].fill = _pf(navy)
  ws1["A1"].alignment = al_r
  ws1.row_dimensions[1].height = 28

  ws1.merge_cells("A2:K2")
  ws1["A2"] = (
      "الفريم اليومي (1D) للاتجاه والاحتفاظ حتى أسبوع • فريم الساعة (1H)"
      " للتوقيت • فريم الربع ساعة (15m) للاستئناس"
  )
  ws1["A2"].font = f_sub
  ws1["A2"].fill = _pf(sub_bg)
  ws1["A2"].alignment = al_r
  ws1.row_dimensions[2].height = 20

  ws1["A4"] = "رأس المال (ريال):"
  ws1["A4"].font = f_bold
  ws1["A4"].alignment = al_r
  ws1["B4"] = 100000
  ws1["B4"].number_format = "#,##0"
  ws1["B4"].font = f_bold
  ws1["B4"].fill = _pf("ECFDF5")
  ws1["B4"].alignment = al_c

  ws1["C4"] = "مخاطرة الصفقة (%):"
  ws1["C4"].font = f_bold
  ws1["C4"].alignment = al_r
  ws1["D4"] = 0.015
  ws1["D4"].number_format = "0.0%"
  ws1["D4"].font = f_bold
  ws1["D4"].fill = _pf("ECFDF5")
  ws1["D4"].alignment = al_c

  ws1["E4"] = "الحد الأقصى للمركز (%):"
  ws1["E4"].font = f_bold
  ws1["E4"].alignment = al_r
  ws1["F4"] = 0.35
  ws1["F4"].number_format = "0.0%"
  ws1["F4"].font = f_bold
  ws1["F4"].fill = _pf("ECFDF5")
  ws1["F4"].alignment = al_c

  for col in range(1, 12):
    ws1.cell(row=4, column=col).border = grid_b
    if col > 6:
      ws1.cell(row=4, column=col).fill = _pf(sec_bg)

  headers = [
      "الرمز",
      "الشركة",
      "التصنيف",
      "الفريمات",
      "الدخول",
      "الوقف",
      "هدف 2R",
      "الأسهم المقترحة",
      "قيمة المركز",
      "حالة الفحص",
      "قراري / ملاحظات",
  ]
  ws1.row_dimensions[6].height = 25
  for idx, h in enumerate(headers, start=1):
    c = ws1.cell(row=6, column=idx, value=h)
    c.font = f_hdr
    c.fill = _pf(navy)
    c.alignment = al_c
    c.border = hdr_b

  dv_chk = DataValidation(
      type="list", formula1='"معتمد للدخول,مراقبة فقط,مستبعد"', allow_blank=True
  )
  ws1.add_data_validation(dv_chk)

  total_rows = max(15, len(signals) + 5)
  for i in range(total_rows):
    r = 7 + i
    ws1.row_dimensions[r].height = 22
    r_fill = _pf(zebra) if r % 2 == 1 else _pf(white)

    if i < len(signals):
      item = signals[i]
      sym = item.get("ticker", "")
      comp = item.get("company", "")
      tier = item.get("tier", "")
      tfs = " | ".join(item.get("timeframes", [])) or "يومي"
      ent = _to_float_or_none(item.get("entry", ""))
      stp = _to_float_or_none(item.get("stop", ""))
      tgt = _to_float_or_none(item.get("target_2r", ""))
    else:
      sym, comp, tier, tfs, ent, stp, tgt = ("", "", "", "", None, None, None)

    f_sh = (
        f"=IF(AND(ISNUMBER(E{r}),ISNUMBER(F{r}),E{r}>F{r}),"
        f"MIN(INT(($B$4*$D$4)/(E{r}-F{r})),INT(($B$4*$F$4)/E{r})),0)"
    )
    f_val = f"=IF(AND(ISNUMBER(E{r}),ISNUMBER(H{r})),E{r}*H{r},0)"

    vals = [sym, comp, tier, tfs, ent, stp, tgt, f_sh, f_val, "مراقبة فقط", ""]
    for c_idx, val in enumerate(vals, start=1):
      cell = ws1.cell(row=r, column=c_idx, value=val)
      cell.fill = r_fill
      cell.border = grid_b
      if c_idx in (1, 3, 10):
        cell.alignment = al_c
        cell.font = f_bold if c_idx in (1, 3) else f_body
      elif c_idx in (5, 6, 7, 9):
        cell.alignment = al_r
        cell.font = f_body
        cell.number_format = "#,##0.00"
      elif c_idx == 8:
        cell.alignment = al_r
        cell.font = f_bold
        cell.number_format = "#,##0"
      else:
        cell.alignment = al_r
        cell.font = f_body

    dv_chk.add(ws1.cell(row=r, column=10))

  ws2 = wb.create_sheet(title="الشروط والنفسية")
  ws2.views.sheetView[0].rightToLeft = True

  ws2.merge_cells("A1:E1")
  ws2["A1"] = "شروط الدخول وأسئلة العامل النفسي (قبل الدخول وأثناء الاحتفاظ)"
  ws2["A1"].font = f_title
  ws2["A1"].fill = _pf(navy)
  ws2["A1"].alignment = al_r
  ws2.row_dimensions[1].height = 28

  q_headers = [
      "#",
      "المحور",
      "الشرط أو السؤال النفسي",
      "التقييم (نعم/لا)",
      "ملاحظتي",
  ]
  ws2.row_dimensions[3].height = 24
  for idx, h in enumerate(q_headers, start=1):
    c = ws2.cell(row=3, column=idx, value=h)
    c.font = f_hdr
    c.fill = _pf(navy)
    c.alignment = al_c
    c.border = hdr_b

  items = [
      (
          1,
          "شرط فني",
          (
              "توافق الاتجاه اليومي (1D) وتأكيد فريم الساعة (1H) مع وضوح السعر"
              " في TradingView؟"
          ),
          "نعم",
          "",
      ),
      (
          2,
          "إدارة مخاطر",
          (
              "وضوح الوقف والهدف (2R) وحساب حجم المركز بحيث لا يتجاوز المخاطرة"
              " المحددة؟"
          ),
          "نعم",
          "",
      ),
      (
          3,
          "نفسية الدخول",
          (
              "هل أدخل بدافع جودة الفرصة والالتزام بالخطة وليس بدافع الملل أو"
              " تعويض خسارة؟"
          ),
          "نعم",
          "",
      ),
      (
          4,
          "نفسية الصبر",
          (
              "هل أستطيع الانتظار من عدة أيام إلى أسبوع كامل ما دام السهم يحترم"
              " مساره ووقفه؟"
          ),
          "نعم",
          "",
      ),
      (
          5,
          "نفسية الاستمرار",
          (
              "هل أفرّق بين تذبذب 15m/1H اللحظي وكسر الهيكل الفعلي دون خروج"
              " مبكر بدافع القلق؟"
          ),
          "نعم",
          "",
      ),
      (
          6,
          "نفسية الهدف",
          "هل ألتزم بخطة إدارة الربح والهدف دون جشع أو خوف غير مبرر؟",
          "نعم",
          "",
      ),
  ]

  dv_yn = DataValidation(type="list", formula1='"نعم,لا"', allow_blank=True)
  ws2.add_data_validation(dv_yn)

  for idx, (num, cat, q, ans, note) in enumerate(items, start=4):
    ws2.row_dimensions[idx].height = 26
    r_fill = _pf(zebra) if idx % 2 == 1 else _pf(white)
    for c_idx, val in enumerate([num, cat, q, ans, note], start=1):
      cell = ws2.cell(row=idx, column=c_idx, value=val)
      cell.fill = r_fill
      cell.border = grid_b
      cell.alignment = al_c if c_idx in (1, 2, 4) else al_r
      cell.font = f_bold if c_idx in (1, 4) else f_body
    dv_yn.add(ws2.cell(row=idx, column=4))

  w1 = {
      1: 10,
      2: 20,
      3: 11,
      4: 20,
      5: 11,
      6: 11,
      7: 11,
      8: 15,
      9: 15,
      10: 15,
      11: 28,
  }
  for c_i, w in w1.items():
    ws1.column_dimensions[get_column_letter(c_i)].width = w

  w2 = {1: 6, 2: 16, 3: 62, 4: 15, 5: 28}
  for c_i, w in w2.items():
    ws2.column_dimensions[get_column_letter(c_i)].width = w

  wb.save(output_path)
  return output_path


def main() -> None:
  token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
  chat_id_raw = os.environ.get("TELEGRAM_CHAT_ID", "")

  chat_id = verify_credentials(token, chat_id_raw)
  signals = _collect_multi_tf_signals()

  date_str = datetime.now().strftime("%Y-%m-%d")
  excel_filename = f"tasi_daily_plan_{date_str}.xlsx"

  msg = build_alert_message(signals, excel_filename=excel_filename)
  send_telegram_message(token, chat_id, msg)

  excel_path = generate_daily_excel(signals, excel_filename)
  _send_document(
      token=token,
      chat_id=chat_id,
      file_path=excel_path,
      caption=f"{RTL}📊 ملف خطة التداول والمرشحين ({date_str}) — 100,000 ريال",
  )


if __name__ == "__main__":
  main()
