from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf


APP_DIR = Path(__file__).resolve().parent
DATASET_DIR = APP_DIR / "DATASET"
WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
DEFAULT_START = "2000-01-01"


@dataclass(frozen=True)
class YahooSymbol:
    code: str
    name: str
    sector: str

    @property
    def filename(self) -> str:
        safe_code = self.code.replace("^", "").replace("/", "-")
        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in self.name)[:80]
        return f"{safe_code}_{safe_name}.csv"


def yahoo_code(symbol: str) -> str:
    return symbol.replace(".", "-").strip()


def load_sp500_symbols(limit: int | None = None) -> list[YahooSymbol]:
    response = requests.get(
        WIKI_SP500_URL,
        headers={"User-Agent": "Mozilla/5.0 StrataDatasetDownloader/1.0"},
        timeout=30,
    )
    response.raise_for_status()
    table = pd.read_html(StringIO(response.text))[0]
    rows = []
    for _, row in table.iterrows():
        rows.append(
            YahooSymbol(
                code=yahoo_code(str(row["Symbol"])),
                name=str(row["Security"]),
                sector=str(row["GICS Sector"]),
            )
        )
    return rows[:limit] if limit else rows


def normalize_history(raw: pd.DataFrame, symbol: YahooSymbol) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.copy()
        raw.columns = [col[0] if isinstance(col, tuple) else col for col in raw.columns]
    df = raw.reset_index().rename(
        columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    keep = ["date", "open", "high", "low", "close", "volume"]
    df = df[[col for col in keep if col in df.columns]].copy()
    if len(df.columns) < len(keep):
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date")
    df["code"] = symbol.code
    df["name"] = symbol.name
    df["market"] = "US"
    df["category"] = symbol.sector
    df["amount"] = df["close"] * df["volume"]
    df["change"] = df["close"].diff().fillna(0.0)
    df["pct_change"] = df["close"].pct_change().fillna(0.0) * 100.0
    df["turnover"] = 0.0
    columns = [
        "code",
        "name",
        "market",
        "category",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "pct_change",
        "change",
        "turnover",
    ]
    return df[columns]


def download_symbol(symbol: YahooSymbol, start: str, end: str | None) -> pd.DataFrame:
    return yf.download(
        symbol.code,
        start=start,
        end=end,
        progress=False,
        auto_adjust=False,
        actions=False,
        threads=False,
    )


def write_dataset(symbols: list[YahooSymbol], start: str, end: str | None, pause: float) -> dict:
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    metadata = []
    failures = []
    for index, symbol in enumerate(symbols, start=1):
        try:
            path = DATASET_DIR / symbol.filename
            if path.exists():
                df = pd.read_csv(path, encoding="utf-8-sig")
                if df.empty:
                    path.unlink(missing_ok=True)
                    raw = download_symbol(symbol, start=start, end=end)
                    df = normalize_history(raw, symbol)
            else:
                raw = download_symbol(symbol, start=start, end=end)
                df = normalize_history(raw, symbol)
            if df.empty:
                raise RuntimeError("no usable rows returned")
            if not path.exists():
                df.to_csv(path, index=False, encoding="utf-8-sig")
            metadata.append(
                {
                    "code": symbol.code,
                    "name": symbol.name,
                    "market": "US",
                    "category": symbol.sector,
                    "file": symbol.filename,
                    "rows": int(len(df)),
                    "start": str(df["date"].iloc[0]),
                    "end": str(df["date"].iloc[-1]),
                    "source": "Yahoo Finance via yfinance",
                }
            )
            print(f"[{index}/{len(symbols)}] ok {symbol.code} rows={len(df)}")
        except Exception as exc:
            failures.append({"code": symbol.code, "name": symbol.name, "error": str(exc)})
            print(f"[{index}/{len(symbols)}] failed {symbol.code}: {exc}")
        if pause:
            time.sleep(pause)

    payload = {
        "source": "Yahoo Finance via yfinance",
        "universe": "Current S&P 500 constituents from Wikipedia",
        "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "symbols": metadata,
        "failures": failures,
    }
    (DATASET_DIR / "metadata.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Download US stock daily OHLCV data from Yahoo Finance.")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--pause", type=float, default=0.05)
    args = parser.parse_args()
    symbols = load_sp500_symbols(limit=args.limit)
    payload = write_dataset(symbols, start=args.start, end=args.end, pause=args.pause)
    print(
        json.dumps(
            {
                "dataset_dir": str(DATASET_DIR),
                "symbols": len(payload["symbols"]),
                "failures": len(payload["failures"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload["symbols"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
