import os
import pandas as pd
import yfinance as yf

tickers = ["SPY", "QQQ", "IWM", "TLT", "GLD"]
dest = r"C:\Users\vici3\investment-lab\data\real_prices"
os.makedirs(dest, exist_ok=True)

for t in tickers:
    print(f"Descargando y normalizando {t}...")
    df = yf.download(
        t,
        start="2015-01-01",
        end="2026-01-01",
        auto_adjust=False,
        progress=False,
        group_by="column"
    )

    if df is None or df.empty:
        print(f"  ERROR: sin datos para {t}")
        continue

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()

    wanted = ["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"]
    existing = [c for c in wanted if c in df.columns]
    df = df[existing]

    out = os.path.join(dest, f"{t}.csv")
    df.to_csv(out, index=False)
    print(f"  OK: {out} ({len(df)} filas)")
