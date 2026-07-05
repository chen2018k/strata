from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

try:
    from strategyforge import SymbolInfo, load_symbols
except ModuleNotFoundError:
    from .strategyforge import SymbolInfo, load_symbols


BENCHMARK_CATEGORIES = {"Benchmark ETF", "Sector ETF", "Market ETF", "Cross-market ETF"}


@dataclass(frozen=True)
class SymbolUniverse:
    symbols: list[SymbolInfo]
    markets: list[str]
    categories: list[str]
    benchmarks: list[SymbolInfo]


def normalize_market(symbol: SymbolInfo) -> str:
    if symbol.market:
        return symbol.market
    if symbol.code.endswith(".HK"):
        return "HK"
    if symbol.code.endswith(".SI"):
        return "SG"
    return "US"


def is_benchmark(symbol: SymbolInfo) -> bool:
    return symbol.category in BENCHMARK_CATEGORIES or symbol.code in {
        "SPY",
        "QQQ",
        "DIA",
        "IWM",
        "VTI",
        "VOO",
        "IVV",
        "VT",
        "EWH",
        "EWS",
        "2800.HK",
        "ES3.SI",
    }


def load_universe() -> SymbolUniverse:
    symbols = load_symbols()
    markets = sorted({normalize_market(item) for item in symbols})
    categories = sorted({item.category for item in symbols if item.category})
    benchmarks = [item for item in symbols if is_benchmark(item)]
    return SymbolUniverse(symbols=symbols, markets=markets, categories=categories, benchmarks=benchmarks)


def filter_symbols(
    symbols: Iterable[SymbolInfo],
    *,
    market: str = "全部",
    category: str = "全部",
    query: str = "",
    min_rows: int = 252,
    include_benchmarks: bool = False,
) -> list[SymbolInfo]:
    query_lower = query.strip().lower()
    filtered: list[SymbolInfo] = []
    for item in symbols:
        item_market = normalize_market(item)
        if market != "全部" and item_market != market:
            continue
        if category != "全部" and item.category != category:
            continue
        if item.rows < min_rows:
            continue
        if not include_benchmarks and is_benchmark(item):
            continue
        if query_lower:
            haystack = f"{item.code} {item.name} {item.category} {item_market}".lower()
            if query_lower not in haystack:
                continue
        filtered.append(item)
    return sorted(filtered, key=lambda item: (is_benchmark(item), normalize_market(item), item.category, item.code))


def preferred_benchmarks(symbol: SymbolInfo, universe: SymbolUniverse) -> list[SymbolInfo]:
    benchmarks = universe.benchmarks
    market = normalize_market(symbol)
    category = symbol.category
    priority: list[str] = []

    if market == "US":
        sector_map = {
            "Information Technology": "XLK",
            "Financials": "XLF",
            "Energy": "XLE",
            "Health Care": "XLV",
            "Consumer Discretionary": "XLY",
            "Consumer Staples": "XLP",
            "Industrials": "XLI",
            "Materials": "XLB",
            "Utilities": "XLU",
            "Real Estate": "XLRE",
            "Communication Services": "XLC",
        }
        priority.extend([sector_map.get(category, ""), "SPY", "QQQ", "VTI", "IWM"])
    elif market == "HK":
        priority.extend(["2800.HK", "EWH", "3033.HK", "SPY"])
    elif market == "SG":
        priority.extend(["ES3.SI", "EWS", "SPY"])
    else:
        priority.extend(["VT", "SPY"])

    by_code = {item.code: item for item in benchmarks}
    ordered = [by_code[code] for code in priority if code and code in by_code]
    seen = {item.code for item in ordered}
    ordered.extend(item for item in benchmarks if item.code not in seen)
    return ordered


def universe_stats(symbols: Iterable[SymbolInfo]) -> dict[str, int]:
    counter = Counter(normalize_market(item) for item in symbols)
    return dict(counter)
