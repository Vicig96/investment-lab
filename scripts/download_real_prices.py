import os
import yfinance as yf

tickers = ["SPY", "QQQ", "IWM", "TLT", "GLD"]
dest = r"C:\Users\vici3\investment-lab\data\real_prices"
os.makedirs(dest, exist_ok=True)

for t in tickers:
    print(f"Descargando {t}...")
    df = yf.download(
        t,
        start="2015-01-01",
        end="2026-01-01",
        auto_adjust=False,
        progress=False
    )

    if df is None or df.empty:
        print(f"  ERROR: sin datos para {t}")
        continue

    out = os.path.join(dest, f"{t}.csv")
    df.to_csv(out)
    print(f"  OK: {out} ({len(df)} filas)")
