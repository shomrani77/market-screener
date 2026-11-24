import json
import os
import urllib.error
import urllib.request
from streamlit_app import DEFAULT_TASI_TICKERS, run_market_scan


def send_telegram_message(token: str, chat_id: str, text: str) -> None:
  url = f"https://api.telegram.org/bot{token}/sendMessage"
  payload = json.dumps({
      "chat_id": chat_id,
      "text": text[:4000],
  }).encode("utf-8")
  req = urllib.request.Request(
      url,
      data=payload,
      headers={"Content-Type": "application/json"},
  )
  try:
    with urllib.request.urlopen(req, timeout=30) as resp:
      resp.read()
  except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", errors="replace")
    raise RuntimeError(f"Telegram API error {e.code}: {body}") from e


def main() -> None:
  df = run_market_scan(DEFAULT_TASI_TICKERS)
  if df.empty:
    msg = "فاحص السوق السعودي: لا توجد إشارات مطابقة حالياً."
  else:
    lines = ["📈 إشارات فاحص السوق السعودي:"]
    for _, row in df.head(10).iterrows():
      lines.append(
          f"• [{row['التصنيف']}] {row['الرمز']} {row['الشركة']} | دخول:"
          f" {row['الدخول']} | وقف: {row['الوقف']} | هدف 2R: {row['هدف 2R']}"
      )
    msg = "\n".join(lines)

  token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
  chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
  send_telegram_message(token, chat_id, msg)


if __name__ == "__main__":
  main()

