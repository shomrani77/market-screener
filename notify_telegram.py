
import os
import urllib.error
import urllib.request
from streamlit_app import DEFAULT_TASI_TICKERS, run_market_scan


def _api_request(token: str, method: str, payload: dict | None = None) -> dict:
  url = f"https://api.telegram.org/bot{token}/{method}"
  data = None
  headers = {}
  if payload is not None:
    data = json.dumps(payload).encode("utf-8")
    headers["Content-Type"] = "application/json"

  req = urllib.request.Request(url, data=data, headers=headers)
  try:
    with urllib.request.urlopen(req, timeout=30) as resp:
      raw = resp.read().decode("utf-8", errors="replace")
      return json.loads(raw)
  except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", errors="replace")
    raise RuntimeError(
        f"Telegram HTTP {e.code} on {method}: {body}"
        " | تحقق من صحة TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID ومن الضغط على"
        " Start في محادثة البوت."
    ) from e


def verify_credentials(token: str, chat_id_raw: str) -> int:
  if not token or ":" not in token:
    raise ValueError(
        "صيغة TELEGRAM_BOT_TOKEN غير صحيحة. يجب إدخال التوكن كاملاً كما يظهر"
        " في @BotFather."
    )

  chat_id_str = chat_id_raw.strip()
  try:
    chat_id = int(chat_id_str)
  except ValueError as e:
    raise ValueError(
        f"قيمة TELEGRAM_CHAT_ID ('{chat_id_str}') ليست رقماً صحيحاً. استخدم رقم"
        " Id من @userinfobot (أو رقم المجموعة/القناة)."
    ) from e

  me = _api_request(token, "getMe")
  bot_info = me.get("result", {})
  bot_username = bot_info.get("username", "unknown")
  bot_id = bot_info.get("id")
  print(f"Verified bot: @{bot_username} (id={bot_id}) | target chat_id={chat_id}")

  if bot_id is not None and chat_id == int(bot_id):
    raise ValueError(
        "خطأ في الإعداد: TELEGRAM_CHAT_ID يطابق معرف البوت نفسه بدلاً من معرف"
        " حسابك أو المحادثة المستهدفة."
    )

  return chat_id


def send_telegram_message(token: str, chat_id: int, text: str) -> None:
  _api_request(
      token,
      "sendMessage",
      {
          "chat_id": chat_id,
          "text": text[:4000],
      },
  )
  print("Telegram message delivered successfully.")


def build_alert_message() -> str:
  df = run_market_scan(DEFAULT_TASI_TICKERS)
  if df.empty:
    return "فاحص السوق السعودي: لا توجد إشارات مطابقة حالياً."

  lines = ["📈 إشارات فاحص السوق السعودي:"]
  for _, row in df.head(10).iterrows():
    lines.append(
        f"• [{row['التصنيف']}] {row['الرمز']} {row['الشركة']} | دخول:"
        f" {row['الدخول']} | وقف: {row['الوقف']} | هدف 2R: {row['هدف 2R']}"
    )
  return "\n".join(lines)


def main() -> None:
  token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
  chat_id_raw = os.environ.get("TELEGRAM_CHAT_ID", "")

  chat_id = verify_credentials(token, chat_id_raw)
  msg = build_alert_message()
  send_telegram_message(token, chat_id, msg)


if __name__ == "__main__":
  main()
main()

