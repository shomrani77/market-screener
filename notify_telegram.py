import json
import os
import time
import urllib.error
import urllib.request
from streamlit_app import DEFAULT_TASI_TICKERS, run_market_scan

# علامة ضبط الاتجاه من اليمين لليسار لمنع تداخل الأرقام والرموز
RTL = "\u200f"


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


def _format_row_card(idx: int, row) -> str:
  ticker = str(row.get("الرمز", "")).strip()
  company = str(row.get("الشركة", "")).strip()
  tier = str(row.get("التصنيف", "")).strip()
  entry = str(row.get("الدخول", "")).strip()
  stop = str(row.get("الوقف", "")).strip()
  target_2r = str(row.get("هدف 2R", "")).strip()
  tv_url = f"https://www.tradingview.com/symbols/TADAWUL-{ticker}/"

  card_lines = [
      f"{RTL}{idx}) {company} - {ticker} [{tier}]",
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
  df = run_market_scan(DEFAULT_TASI_TICKERS)
  if df.empty:
    return (
        f"{RTL}📊 فاحص السوق السعودي (تاسي)\n"
        f"{RTL}• 💥 لا توجد إشارات مطابقة حالياً\n"
        f"{RTL}• 💡 مزاد 9:30-9:55 الرياض"
    )

  parts = [
      f"{RTL}🔥 إشارات فاحص السوق السعودي (تاسي)",
      "────────────────────",
  ]
  for i, (_, row) in enumerate(df.head(8).iterrows(), start=1):
    parts.append(_format_row_card(i, row))
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

