@st.cache_data(ttl=1800, show_spinner=False)
def run_market_scan(tickers_dict: dict, interval: str = "1d") -> pd.DataFrame:
  period_map = {
      "15m": "60d",
      "1h": "6mo",
      "1d": "18mo",
  }
  period = period_map.get(interval, "18mo")
  symbols = list(tickers_dict.keys())
  raw = yf.download(
      tickers=symbols,
      period=period,
      interval=interval,
      group_by="ticker",
      auto_adjust=False,
      threads=True,
      progress=False,
  )

  if raw is None or raw.empty:
    return pd.DataFrame()

  results = []
  for sym, name in tickers_dict.items():
    try:
      if isinstance(raw.columns, pd.MultiIndex):
        if sym not in raw.columns.get_level_values(0):
          continue
        sub_df = raw[sym]
      else:
        sub_df = raw
      row = evaluate_ticker(sym, name, sub_df)
      if row:
        results.append(row)
    except Exception:
      continue

  if not results:
    return pd.DataFrame()

  df_res = pd.DataFrame(results)
  rank_map = {"A+": 0, "A": 1, "WATCH": 2}
  df_res["_rank"] = df_res["التصنيف"].map(rank_map)
  df_res = df_res.sort_values(by=["_rank", "ADX"], ascending=[True, False]).drop(
      columns=["_rank"]
  )
  return df_res.reset_index(drop=True)



def compute_dmi_adx(df: pd.DataFrame, period: int = 14):
  high = df["High"]
  low = df["Low"]
  close = df["Close"]

  up_move = high.diff()
  down_move = -low.diff()

  plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
  minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

  tr1 = high - low
  tr2 = (high - close.shift(1)).abs()
  tr3 = (low - close.shift(1)).abs()
  tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

  atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
  plus_di = 100 * (
      pd.Series(plus_dm, index=df.index)
      .ewm(alpha=1 / period, min_periods=period, adjust=False)
      .mean()
      / atr.replace(0, np.nan)
  )
  minus_di = 100 * (
      pd.Series(minus_dm, index=df.index)
      .ewm(alpha=1 / period, min_periods=period, adjust=False)
      .mean()
      / atr.replace(0, np.nan)
  )

  dx = 100 * (
      (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
  )
  adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
  return plus_di, minus_di, adx, atr


def evaluate_ticker(symbol: str, name: str, df: pd.DataFrame) -> dict | None:
  if df is None or len(df) < 210:
    return None

  df = df.dropna().copy()
  if len(df) < 210:
    return None

  close = df["Close"]
  high = df["High"]
  low = df["Low"]

  # المؤشرات الفنية المعتمدة في الفاحص
  ema200_high = high.ewm(span=200, adjust=False).mean()
  ema200_close = close.ewm(span=200, adjust=False).mean()

  # MACD Histogram (34 / 144 / 25)
  ema_fast = close.ewm(span=34, adjust=False).mean()
  ema_slow = close.ewm(span=144, adjust=False).mean()
  macd_line = ema_fast - ema_slow
  macd_signal = macd_line.ewm(span=25, adjust=False).mean()
  macd_hist = macd_line - macd_signal

  # RSI(21)
  rsi21 = compute_rsi_wilder(close, period=21)

  # DMI / ADX (14)
  plus_di, minus_di, adx, atr = compute_dmi_adx(df, period=14)

  # Bollinger Bands (20, 2)
  bb_mid = close.rolling(20).mean()
  bb_std = close.rolling(20).std()
  bb_upper = bb_mid + 2 * bb_std

  last_close = float(close.iloc[-1])
  prev_close = float(close.iloc[-2])
  last_ema200_h = float(ema200_high.iloc[-1])
  last_ema200_c = float(ema200_close.iloc[-1])
  last_hist = float(macd_hist.iloc[-1])
  prev_hist = float(macd_hist.iloc[-2])
  last_rsi = float(rsi21.iloc[-1])
  last_pdi = float(plus_di.iloc[-1])
  last_mdi = float(minus_di.iloc[-1])
  last_adx = float(adx.iloc[-1])
  last_atr = float(atr.iloc[-1])
  last_bb_mid = float(bb_mid.iloc[-1])
  last_bb_up = float(bb_upper.iloc[-1])

  # شروط النماذج
  above_ema200_high = last_close > last_ema200_h
  near_ema200_high = (
      (not above_ema200_high)
      and (last_close >= last_ema200_h * 0.975)
      and (last_close >= last_ema200_c * 0.985)
  )

  momentum_ok = (last_hist > 0 or last_hist > prev_hist) and (last_rsi >= 52)
  dmi_ok = (last_pdi > last_mdi) and (last_adx >= 18)
  bb_ok = (last_close > last_bb_mid) and (last_close >= last_bb_up * 0.96)

  signal = None
  if above_ema200_high and momentum_ok and dmi_ok and bb_ok:
    signal = "A+"
  elif above_ema200_high and momentum_ok:
    signal = "A"
  elif near_ema200_high and (last_hist > prev_hist) and (last_rsi >= 48):
    signal = "WATCH"

  if signal is None:
    return None

  # حساب مستويات الدخول والوقف وهدف 2R
  if signal in ("A+", "A"):
    entry = round(last_close, 2)
  else:
    entry = round(max(last_ema200_h * 1.002, float(high.iloc[-3:].max())), 2)

  recent_swing_low = float(low.iloc[-7:].min())
  atr_stop = entry - (1.5 * last_atr)
  stop_loss = round(min(recent_swing_low * 0.995, atr_stop), 2)

  # حماية في حال كان الوقف قريباً جداً أو أعلى من الدخول
  if stop_loss >= entry * 0.99:
    stop_loss = round(entry * 0.97, 2)

  risk = entry - stop_loss
  target_2r = round(entry + (2.0 * risk), 2)
  risk_pct = round((risk / entry) * 100, 2)
  chg_pct = round(((last_close - prev_close) / prev_close) * 100, 2)

  return {
      "التصنيف": signal,
      "الرمز": symbol.replace(".SR", ""),
      "الشركة": name,
      "الإغلاق": round(last_close, 2),
      "التغير %": chg_pct,
      "الدخول": entry,
      "الوقف": stop_loss,
      "هدف 2R": target_2r,
      "المخاطرة %": risk_pct,
      "EMA200 High": round(last_ema200_h, 2),
      "RSI(21)": round(last_rsi, 1),
      "MACD Hist": round(last_hist, 3),
      "+DI / -DI": f"{last_pdi:.1f} / {last_mdi:.1f}",
      "ADX": round(last_adx, 1),
  }


@st.cache_data(ttl=1800, show_spinner=False)
def run_market_scan(tickers_dict: dict) -> pd.DataFrame:
  symbols = list(tickers_dict.keys())
  raw = yf.download(
      tickers=symbols,
      period="18mo",
      interval="1d",
      group_by="ticker",
      auto_adjust=False,
      threads=True,
      progress=False,
  )

  results = []
  for sym, name in tickers_dict.items():
    try:
      if isinstance(raw.columns, pd.MultiIndex):
        if sym not in raw.columns.get_level_values(0):
          continue
        sub_df = raw[sym]
      else:
        sub_df = raw
      row = evaluate_ticker(sym, name, sub_df)
      if row:
        results.append(row)
    except Exception:
      continue

  if not results:
    return pd.DataFrame()

  df_res = pd.DataFrame(results)
  rank_map = {"A+": 0, "A": 1, "WATCH": 2}
  df_res["_rank"] = df_res["التصنيف"].map(rank_map)
  df_res = df_res.sort_values(by=["_rank", "ADX"], ascending=[True, False]).drop(
      columns=["_rank"]
  )
  return df_res.reset_index(drop=True)


# --- واجهة المستخدم ---
st.title("📈 فاحص السوق السعودي (TASI EMA200 Scanner)")
st.caption(
    "فحص يومي للأسهم السعودية السائلة وفق نموذج EMA200 High مع تأكيد الزخم"
    " (MACD 34/144/25 و RSI 21) وقوة الاتجاه (DMI/ADX) والبولنجر."
)

col_btn, col_filter, col_time = st.columns([1.2, 2, 2])
with col_btn:
  if st.button("🔄 تحديث وفحص الآن", use_container_width=True, type="primary"):
    st.cache_data.clear()

with col_filter:
  selected_tiers = st.multiselect(
      "تصفية حسب التصنيف",
      options=["A+", "A", "WATCH"],
      default=["A+", "A", "WATCH"],
  )

with col_time:
  st.info(f"آخر تحديث: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

with st.expander("➕ إضافة رموز أسهم إضافية للفحص (اختياري)"):
  extra_input = st.text_input(
      "أدخل الرموز مفصولة بفاصلة (مثال: 2070, 4164, 4240)",
      value="",
  )

tickers_to_scan = DEFAULT_TASI_TICKERS.copy()
if extra_input.strip():
  for item in extra_input.split(","):
    clean = item.strip().replace(".SR", "")
    if clean.isdigit():
      sym_key = f"{clean}.SR"
      if sym_key not in tickers_to_scan:
        tickers_to_scan[sym_key] = f"سهم {clean}"

with st.spinner("جاري سحب البيانات وفحص الأسهم السعودية..."):
  scan_df = run_market_scan(tickers_to_scan)

if scan_df.empty:
  st.warning("لا توجد أسهم مطابقة للشروط حالياً أو تعذر جلب البيانات مؤقتاً.")
else:
  filtered_df = scan_df[scan_df["التصنيف"].isin(selected_tiers)].copy()

  m1, m2, m3, m4 = st.columns(4)
  m1.metric("إجمالي المرشحين", len(filtered_df))
  m2.metric("إشارات A+", int((filtered_df["التصنيف"] == "A+").sum()))
  m3.metric("إشارات A", int((filtered_df["التصنيف"] == "A").sum()))
  m4.metric("قائمة المراقبة WATCH", int((filtered_df["التصنيف"] == "WATCH").sum()))

  st.dataframe(
      filtered_df,
      use_container_width=True,
      hide_index=True,
  )

  csv_bytes = filtered_df.to_csv(index=False).encode("utf-8-sig")
  st.download_button(
      label="📥 تنزيل المرشحين بصيغة CSV",
      data=csv_bytes,
      file_name=f"tasi_scanner_{datetime.now().strftime('%Y%m%d')}.csv",
      mime="text/csv",
  )

st.divider()
st.caption(
    "⚠️ تنبيه: بيانات Yahoo Finance المستخدمة غير رسمية وقد تتأخر أو تختلف عن"
    " بيانات تداول الرسمية؛ راجع شارت السهم قبل اتخاذ أي قرار."
)
