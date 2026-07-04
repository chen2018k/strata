from __future__ import annotations

import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = Path(os.getenv("STRATA_DATASET_DIR", WORKSPACE_ROOT / "local_data" / "DATASET"))


@dataclass(frozen=True)
class SymbolSpec:
    code: str
    name: str
    market: str
    category: str

    @property
    def secid(self) -> str:
        prefix = "1" if self.market == "SH" else "0"
        return f"{prefix}.{self.code}"

    @property
    def filename(self) -> str:
        safe_name = self.name.replace(" ", "_")
        return f"{self.code}_{safe_name}.csv"


SYMBOLS = [
    SymbolSpec("510300", "沪深300ETF", "SH", "宽基ETF"),
    SymbolSpec("510500", "中证500ETF", "SH", "宽基ETF"),
    SymbolSpec("588000", "科创50ETF", "SH", "主题ETF"),
    SymbolSpec("159915", "创业板ETF", "SZ", "宽基ETF"),
    SymbolSpec("512100", "中证1000ETF", "SH", "宽基ETF"),
    SymbolSpec("600519", "贵州茅台", "SH", "股票"),
    SymbolSpec("000001", "平安银行", "SZ", "股票"),
    SymbolSpec("300750", "宁德时代", "SZ", "股票"),
]


FIELDS = [
    "date",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
    "amplitude",
    "pct_change",
    "change",
    "turnover",
]


def fetch_symbol(spec: SymbolSpec, begin: str = "20200101", end: str = "20260702") -> list[dict[str, str]]:
    params = {
        "secid": spec.secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "beg": begin,
        "end": end,
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 StrategyForge data bootstrap",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    data = payload.get("data") or {}
    klines = data.get("klines") or []
    rows: list[dict[str, str]] = []
    for raw in klines:
        parts = raw.split(",")
        if len(parts) < len(FIELDS):
            continue
        row = dict(zip(FIELDS, parts[: len(FIELDS)]))
        row.update(
            {
                "code": spec.code,
                "name": spec.name,
                "market": spec.market,
                "category": spec.category,
            }
        )
        rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    columns = ["code", "name", "market", "category", *FIELDS]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    metadata = []
    failures = []
    for spec in SYMBOLS:
        try:
            rows = fetch_symbol(spec)
            if not rows:
                raise RuntimeError("no rows returned")
            path = DATASET_DIR / spec.filename
            write_csv(path, rows)
            metadata.append(
                {
                    "code": spec.code,
                    "name": spec.name,
                    "market": spec.market,
                    "category": spec.category,
                    "file": path.name,
                    "rows": len(rows),
                    "start": rows[0]["date"],
                    "end": rows[-1]["date"],
                    "source": "Eastmoney push2his daily kline API",
                }
            )
            print(f"saved {path} ({len(rows)} rows)")
        except Exception as exc:  # noqa: BLE001 - bootstrap script should continue across symbols.
            failures.append({"code": spec.code, "name": spec.name, "error": str(exc)})
            print(f"failed {spec.code} {spec.name}: {exc}", file=sys.stderr)

    with (DATASET_DIR / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump({"symbols": metadata, "failures": failures}, handle, ensure_ascii=False, indent=2)

    if failures and not metadata:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
