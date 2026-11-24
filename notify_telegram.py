import inspect
import json
import os
import time
import urllib.error
import urllib.request
from streamlit_app import DEFAULT_TASI_TICKERS, run_market_scan

RTL = "\u200f"
TIMEFRAMES = [
    ("15m", "ربع ساعة"),
    ("1h", "ساعة"),
    ("1d", "يومي"),
]


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

  # إذا لم تكن الدالة تقبل معامل فريم بعد، نعيد الفحص الافتراضي فقط للفريم اليومي
  return run_market_scan(DEFAULT_TASI_TICKERS) if tf_code == "1d" else None


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

      # نفضّل تحديث الأسعار بأحدث فريم متوفر إذا كانت فارغة
      if entry and not merged[ticker]["entry"]:
        merged[ticker]["entry"] = entry
      if stop and not merged[ticker]["stop"]:
        merged[ticker]["stop"] = stop
      if target_2r and not merged[ticker]["target_2r"]:
        merged[ticker]["target_2r"] = target_2r
      if tier:
        merged[ticker]["tier"] = tier

  # ترتيب الأسهم: الأكثر توافقاً على الفريمات الثلاثة أولاً
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


def build_alert_message() -> str:
  signals = _collect_multi_tf_signals()
  if not signals:
    return (
        f"{RTL}📊 فاحص السوق السعودي (تاسي)\n"
        f"{RTL}• 💥 لا توجد إشارات مطابقة حالياً (ربع ساعة / ساعة / يومي)\n"
        f"{RTL}• 💡 مزاد 9:30-9:55 الرياض"
    )

  parts = [
      f"{RTL}🔥 إشارات فاحص السوق السعودي (15m | 1h | 1d)",
      "────────────────────",
  ]
  for i, item in enumerate(signals[:6], start=1):
    parts.append(_format_multi_tf_card(i, item))
    parts.append("────────────────────")

  parts.append(f"{RTL}💡 مزاد 9:30-9:55 الرياض")
  return "\n".join(parts)


def main() -> None:
  token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
  chat_id_raw = os.environ.get("TELEGRAM_CHAT_ID", "")

  chat_id = verify_credentials(token, chat_id_raw)
  msg = build_alert_message()
  send_telegram_message(token, chat_id, msg)


if __name__ == "__main__":
  main()

