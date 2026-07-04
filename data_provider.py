"""
可插拔数据接口层 — Pluggable Data Provider Layer

支持三种模式，统一接口，一键切换：
  - csv      : 离线 CSV 历史数据（回测用，零网络依赖）
  - eastmoney: 东方财富实时日线行情（纸面验证、策略监控）
  - yfinance : 港美股行情数据（跨市场扩展）

设计目标:
  1. 所有 Provider 实现 MarketDataProvider / LiveDataProvider 协议
  2. DataProviderFactory 根据 mode 字符串创建对应实例
  3. 上层回测/验证逻辑完全不感知底层数据源
  4. 新增数据源只需实现协议 + 注册到 factory

使用示例:
  >>> from data_provider import DataProviderFactory
  >>> market = DataProviderFactory.create_market("csv")
  >>> live   = DataProviderFactory.create_live("csv")
  >>> df = market.history(market.symbols()[0])
  >>> bars = live.latest_bars(market.symbols()[0], lookback=60)

协议兼容:
  - 本模块的 Provider 与 agent_runtime.py 中的 Protocol 完全兼容
  - 上层代码可以直接用 isinstance 做运行时检查
"""

from __future__ import annotations

import csv
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

# ── 复用 strategyforge 的数据类型 ──────────────────────────────
try:
    from strategyforge import (
        DATASET_DIR,
        SymbolInfo,
        load_price_data,
        load_symbols,
    )
except ModuleNotFoundError:
    from .strategyforge import (
        DATASET_DIR,
        SymbolInfo,
        load_price_data,
        load_symbols,
    )

logger = logging.getLogger("data_provider")

# ── 公开数据模式 ──────────────────────────────────────────────
ProviderMode = Literal["csv", "eastmoney", "yfinance"]
VALID_MODES: tuple[ProviderMode, ...] = ("csv", "eastmoney", "yfinance")


# ================================================================
# 统一符号规格
# ================================================================


@dataclass(frozen=True)
class UniversalSymbol:
    """跨市场的统一标的描述，所有 Provider 都输出此结构。"""

    code: str
    name: str
    market: str  # SH / SZ / US / HK
    category: str  # 宽基ETF / 主题ETF / 股票 / ETF / …

    @property
    def label(self) -> str:
        return f"{self.code} {self.name} · {self.category}"

    def to_symbol_info(self) -> SymbolInfo:
        """转换为 strategyforge 的 SymbolInfo（兼容现有代码）。"""
        return SymbolInfo(
            code=self.code,
            name=self.name,
            market=self.market,
            category=self.category,
            file=f"{self.code}_{self.name}.csv",
            rows=0,
            start="",
            end="",
            source="data_provider",
        )


# ================================================================
# CSV 离线数据提供者
# ================================================================


class CsvMarketDataProvider:
    """离线模式：从 DATASET/*.csv 读取历史日线。

    零网络依赖，所有数据预下载到本地。
    黑客松演示最安全的选择 —— 保证不翻车。
    """

    def __init__(self, dataset_dir: Path | None = None) -> None:
        self.dataset_dir = Path(dataset_dir) if dataset_dir else DATASET_DIR
        self._symbols: list[SymbolInfo] | None = None

    # ── MarketDataProvider 协议 ──────────────────────────────

    def symbols(self) -> list[SymbolInfo]:
        if self._symbols is None:
            self._symbols = load_symbols(self.dataset_dir)
        return self._symbols

    def history(self, symbol: SymbolInfo) -> pd.DataFrame:
        return load_price_data(symbol, self.dataset_dir)

    # ── CSV 专属工具 ───────────────────────────────────────

    @property
    def symbol_count(self) -> int:
        return len(self.symbols())

    def find(self, code: str | None = None, name: str | None = None, category: str | None = None) -> SymbolInfo | None:
        """按 code / name / category 查找标的。"""
        for item in self.symbols():
            if code and item.code == code:
                return item
            if name and name.lower() in item.name.lower():
                return item
            if category and category in item.category:
                return item
        return None

    def list_symbols(self) -> pd.DataFrame:
        """以 DataFrame 形式列出所有可用标的。"""
        return pd.DataFrame(
            [
                {"code": item.code, "name": item.name, "market": item.market, "category": item.category,
                 "rows": item.rows, "start": item.start, "end": item.end}
                for item in self.symbols()
            ]
        )


class CsvLiveDataProvider:
    """离线实时模拟：读取 CSV 文件的最后 N 行，模拟"最新行情"。

    用途：
      - 在离线环境中测试实时验证流程
      - 验证 live_validator.py 的纸面信号逻辑
      - 不需要网络连接的演示场景
    """

    def __init__(self, market: CsvMarketDataProvider | None = None) -> None:
        self._market = market or CsvMarketDataProvider()

    def symbols(self) -> list[SymbolInfo]:
        return self._market.symbols()

    def history(self, symbol: SymbolInfo) -> pd.DataFrame:
        return self._market.history(symbol)

    def latest_bars(self, symbol: SymbolInfo, lookback: int = 260) -> pd.DataFrame:
        """返回最近 lookback 根日线 bar，模拟实时行情。"""
        df = self._market.history(symbol)
        df = df.sort_values("date").tail(lookback).reset_index(drop=True)
        if df.empty:
            raise ValueError(f"no data for {symbol.label}")
        return df

    def latest_quote(self, symbol: SymbolInfo) -> dict[str, Any]:
        """返回最新一根 bar 的快照。"""
        df = self.latest_bars(symbol, lookback=1)
        if df.empty:
            return {}
        row = df.iloc[-1]
        return {
            "code": symbol.code,
            "name": symbol.name,
            "date": str(row["date"].date()),
            "open": float(row["open"]),
            "close": float(row["close"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "volume": float(row["volume"]),
            "pct_change": float(row["pct_change"]),
            "turnover": float(row["turnover"]),
        }


# ================================================================
# 东方财富（Eastmoney / Invenio）实时/历史数据提供者
# ================================================================


EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


@dataclass(frozen=True)
class EastmoneySymbolSpec:
    """东方财富 API 的标的规格。"""
    code: str
    name: str
    market: str  # SH / SZ
    category: str

    @property
    def secid(self) -> str:
        prefix = "1" if self.market == "SH" else "0"
        return f"{prefix}.{self.code}"


# 默认标的列表（与 fetch_a_share_data.py 保持一致）
DEFAULT_EASTMONEY_SYMBOLS = [
    EastmoneySymbolSpec("510300", "沪深300ETF", "SH", "宽基ETF"),
    EastmoneySymbolSpec("510500", "中证500ETF", "SH", "宽基ETF"),
    EastmoneySymbolSpec("588000", "科创50ETF", "SH", "主题ETF"),
    EastmoneySymbolSpec("159915", "创业板ETF", "SZ", "宽基ETF"),
    EastmoneySymbolSpec("512100", "中证1000ETF", "SH", "宽基ETF"),
    EastmoneySymbolSpec("600519", "贵州茅台", "SH", "股票"),
    EastmoneySymbolSpec("000001", "平安银行", "SZ", "股票"),
    EastmoneySymbolSpec("300750", "宁德时代", "SZ", "股票"),
]


class EastmoneyDataProvider:
    """东方财富数据提供者。

    直接从东财 push2his API 拉取日线数据。
    支持历史回测（全量拉取）和实时校验（仅拉最近 N 日）。

    注意：
      - API 是公开的，但需要 User-Agent 和 Referer
      - 免费额度较宽松（通常无日限额），但不要高频并发
      - 港股支持需额外确认 API 端点
    """

    KLINE_FIELDS = [
        "date", "open", "close", "high", "low",
        "volume", "amount", "amplitude", "pct_change", "change", "turnover",
    ]

    def __init__(
        self,
        symbols: list[EastmoneySymbolSpec] | None = None,
        timeout: int = 20,
        retries: int = 2,
    ) -> None:
        self._specs = symbols or DEFAULT_EASTMONEY_SYMBOLS
        self.timeout = timeout
        self.retries = retries
        self._symbol_infos: list[SymbolInfo] | None = None
        self._cache: dict[str, pd.DataFrame] = {}

    # ── MarketDataProvider 协议 ──────────────────────────────

    def symbols(self) -> list[SymbolInfo]:
        if self._symbol_infos is None:
            self._symbol_infos = [
                SymbolInfo(
                    code=spec.code,
                    name=spec.name,
                    market=spec.market,
                    category=spec.category,
                    file="", rows=0, start="", end="",
                    source="eastmoney",
                )
                for spec in self._specs
            ]
        return self._symbol_infos

    def history(self, symbol: SymbolInfo, begin: str = "20200101", end: str | None = None) -> pd.DataFrame:
        cache_key = f"{symbol.code}:{begin}:{end or 'latest'}"
        if cache_key in self._cache:
            return self._cache[cache_key].copy()

        secid = _secid_for(symbol)
        end = end or datetime.now().strftime("%Y%m%d")
        rows = self._fetch_klines(secid, begin, end)
        df = _klines_to_dataframe(rows)
        self._cache[cache_key] = df
        return df.copy()

    # ── LiveDataProvider 协议 ──────────────────────────────

    def latest_bars(self, symbol: SymbolInfo, lookback: int = 260) -> pd.DataFrame:
        """拉取最近 lookback 根日线 bar（含今天）。"""
        secid = _secid_for(symbol)
        today = datetime.now().strftime("%Y%m%d")
        # 拉足够多的数据，再截尾
        begin = _shift_date(today, -(lookback + 30))
        rows = self._fetch_klines(secid, begin, today)
        df = _klines_to_dataframe(rows)
        df = df.sort_values("date").tail(lookback).reset_index(drop=True)
        return df

    def latest_quote(self, symbol: SymbolInfo) -> dict[str, Any]:
        """返回最新一根日线 bar 的快照。"""
        df = self.latest_bars(symbol, lookback=1)
        if df.empty:
            return {}
        row = df.iloc[-1]
        return {
            "code": symbol.code,
            "name": symbol.name,
            "date": str(row["date"].date()),
            "open": float(row["open"]),
            "close": float(row["close"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "volume": float(row["volume"]),
            "pct_change": float(row["pct_change"]),
            "turnover": float(row["turnover"]),
        }

    # ── 底层网络调用 ────────────────────────────────────────

    def _fetch_klines(self, secid: str, begin: str, end: str) -> list[dict[str, str]]:
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",   # 日线
            "fqt": "1",     # 前复权
            "beg": begin,
            "end": end,
        }
        url = EASTMONEY_KLINE_URL + "?" + urllib.parse.urlencode(params)

        for attempt in range(self.retries + 1):
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 StrategyForge data bootstrap",
                        "Referer": "https://quote.eastmoney.com/",
                    },
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                data = payload.get("data") or {}
                klines = data.get("klines") or []
                rows: list[dict[str, str]] = []
                for raw in klines:
                    parts = raw.split(",")
                    if len(parts) < len(self.KLINE_FIELDS):
                        continue
                    rows.append(dict(zip(self.KLINE_FIELDS, parts[:len(self.KLINE_FIELDS)])))
                return rows
            except (urllib.error.URLError, OSError) as exc:
                logger.warning("eastmoney fetch attempt %d/%d: %s", attempt + 1, self.retries + 1, exc)
                if attempt >= self.retries:
                    raise RuntimeError(f"eastmoney fetch failed after {self.retries + 1} attempts: {exc}") from exc

        return []

    def clear_cache(self) -> None:
        self._cache.clear()


# ================================================================
# yfinance 港美股数据提供者（未来扩展）
# ================================================================


class YfinanceDataProvider:
    """港美股数据提供者（通过 yfinance）。

    pip install yfinance

    支持的标的格式：
      - 美股：AAPL, TSLA, SPY, QQQ
      - 港股：0700.HK, 9988.HK
      - ETF：SPY, QQQ, IWM

    适合：
      - 跨市场策略验证
      - 美股基本面因子（财报、分红等）
      - 与智塔港美股数据源文档联动
    """

    _IMPORT_ERROR_MSG = "yfinance is not installed. Run: pip install yfinance"

    def __init__(self, tickers: list[str] | None = None, timeout: int = 30) -> None:
        self._tickers = tickers or ["SPY", "QQQ", "AAPL", "TSLA", "0700.HK", "9988.HK"]
        self.timeout = timeout
        self._symbol_infos: list[SymbolInfo] | None = None

    def symbols(self) -> list[SymbolInfo]:
        if self._symbol_infos is not None:
            return self._symbol_infos
        result: list[SymbolInfo] = []
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ImportError(self._IMPORT_ERROR_MSG) from exc

        for ticker in self._tickers:
            try:
                info = yf.Ticker(ticker).info
                market = "HK" if ".HK" in ticker.upper() else "US"
                result.append(SymbolInfo(
                    code=ticker,
                    name=info.get("shortName") or info.get("longName") or ticker,
                    market=market,
                    category="ETF" if "ETF" in (info.get("quoteType") or "") else "股票",
                    file="", rows=0, start="", end="",
                    source="yfinance",
                ))
            except Exception:
                result.append(SymbolInfo(
                    code=ticker, name=ticker, market="US", category="股票",
                    file="", rows=0, start="", end="", source="yfinance",
                ))
        self._symbol_infos = result
        return result

    def history(self, symbol: SymbolInfo, period: str = "5y") -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ImportError(self._IMPORT_ERROR_MSG) from exc

        ticker = yf.Ticker(symbol.code)
        df = ticker.history(period=period, auto_adjust=True)
        if df.empty:
            raise ValueError(f"no data for {symbol.code}")
        # 标准化为 strategyforge 兼容格式
        df = df.reset_index()
        df.columns = [col.lower() for col in df.columns]
        rename_map = {"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        if "date" not in df.columns and "Date" in [str(c) for c in df.columns]:
            date_col = [c for c in df.columns if str(c).lower() == "date"][0]
            df["date"] = pd.to_datetime(df[date_col])
        else:
            df["date"] = pd.to_datetime(df["date"])
        df["return"] = df["close"].pct_change().fillna(0.0)
        return df.sort_values("date").reset_index(drop=True)

    def latest_bars(self, symbol: SymbolInfo, lookback: int = 260) -> pd.DataFrame:
        df = self.history(symbol, period="1y")
        return df.tail(lookback).reset_index(drop=True)


# ================================================================
# 工厂函数 —— 一键切换数据源
# ================================================================


class DataProviderFactory:
    """数据提供者工厂。

    上层代码只需要关心 mode 字符串，不需要知道具体实现类。

    示例:
        market = DataProviderFactory.create_market("csv")
        live   = DataProviderFactory.create_live("eastmoney")
        manager = DataProviderFactory.create_manager("csv", "csv")
    """

    @staticmethod
    def create_market(mode: ProviderMode, **kwargs: Any) -> CsvMarketDataProvider | EastmoneyDataProvider | YfinanceDataProvider:
        """创建历史数据（市场数据）提供者。"""
        if mode == "csv":
            return CsvMarketDataProvider(dataset_dir=kwargs.get("dataset_dir"))
        if mode == "eastmoney":
            return EastmoneyDataProvider(
                symbols=kwargs.get("symbols"),
                timeout=kwargs.get("timeout", 20),
                retries=kwargs.get("retries", 2),
            )
        if mode == "yfinance":
            return YfinanceDataProvider(
                tickers=kwargs.get("tickers"),
                timeout=kwargs.get("timeout", 30),
            )
        raise ValueError(f"unknown market mode: {mode}, valid: {VALID_MODES}")

    @staticmethod
    def create_live(mode: ProviderMode, **kwargs: Any) -> CsvLiveDataProvider | EastmoneyDataProvider | YfinanceDataProvider:
        """创建实时数据提供者。

        注意：eastmoney / yfinance 同时支持 history 和 latest_bars，
        因此同一个实例既可以用作 MarketDataProvider 也可以用作 LiveDataProvider。
        """
        if mode == "csv":
            market = kwargs.get("market") or CsvMarketDataProvider(
                dataset_dir=kwargs.get("dataset_dir")
            )
            return CsvLiveDataProvider(market=market)
        if mode == "eastmoney":
            return EastmoneyDataProvider(
                symbols=kwargs.get("symbols"),
                timeout=kwargs.get("timeout", 20),
                retries=kwargs.get("retries", 2),
            )
        if mode == "yfinance":
            return YfinanceDataProvider(
                tickers=kwargs.get("tickers"),
                timeout=kwargs.get("timeout", 30),
            )
        raise ValueError(f"unknown live mode: {mode}, valid: {VALID_MODES}")

    @staticmethod
    def create_manager(
        market_mode: ProviderMode = "csv",
        live_mode: ProviderMode = "csv",
        **kwargs: Any,
    ) -> "DataManager":
        """创建统一的数据管理器，同时持有 market 和 live 两个 provider。"""
        return DataManager(
            market=DataProviderFactory.create_market(market_mode, **kwargs),
            live=DataProviderFactory.create_live(live_mode, **kwargs),
        )


# ================================================================
# 统一数据管理器
# ================================================================


@dataclass
class DataManager:
    """同时管理历史数据和实时数据。

    回测链路用 market.history()，实时验证链路用 live.latest_bars()。
    两者可以在不同模式下独立运行（比如回测用 CSV，实时用 Eastmoney）。
    """

    market: CsvMarketDataProvider | EastmoneyDataProvider | YfinanceDataProvider
    live: CsvLiveDataProvider | EastmoneyDataProvider | YfinanceDataProvider

    # ── 便利方法 ──────────────────────────────────────────

    def symbols(self) -> list[SymbolInfo]:
        return self.market.symbols()

    def backtest_data(self, symbol: SymbolInfo, window: str = "全部") -> pd.DataFrame:
        """获取用于回测的历史数据（可按窗口切片）。"""
        from agent_runtime import slice_history_window
        df = self.market.history(symbol)
        return slice_history_window(df, window=window)

    def live_bars(self, symbol: SymbolInfo, lookback: int = 260) -> pd.DataFrame:
        """获取用于实时验证的最新 bar 数据。"""
        return self.live.latest_bars(symbol, lookback=lookback)

    def status(self) -> dict[str, str]:
        """返回当前数据源状态，用于 UI 展示。"""
        return {
            "market_provider": type(self.market).__name__,
            "live_provider": type(self.live).__name__,
            "symbol_count": str(len(self.market.symbols())),
        }


# ================================================================
# 工具函数
# ================================================================


def _secid_for(symbol: SymbolInfo) -> str:
    """计算东方财富 secid。"""
    prefix = "1" if symbol.market == "SH" else "0"
    return f"{prefix}.{symbol.code}"


def _klines_to_dataframe(rows: list[dict[str, str]]) -> pd.DataFrame:
    """把东财 K 线原始行转成 strategyforge 兼容的 DataFrame。"""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pct_change", "change", "turnover"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
    df["return"] = df["close"].pct_change().fillna(0.0)
    return df


def _shift_date(date_str: str, delta_days: int) -> str:
    """日期字符串偏移 N 天。"""
    from datetime import timedelta
    dt = datetime.strptime(date_str, "%Y%m%d")
    return (dt + timedelta(days=delta_days)).strftime("%Y%m%d")


# ================================================================
# 模块自检
# ================================================================


def smoke_test() -> dict[str, object]:
    """验证所有 Provider 可以在离线模式下正常工作。"""

    results: dict[str, object] = {}

    # 1. CSV 离线模式
    csv_market = CsvMarketDataProvider()
    symbols = csv_market.symbols()
    results["csv_symbol_count"] = len(symbols)
    first = symbols[0]
    df = csv_market.history(first)
    results["csv_first_rows"] = len(df)
    results["csv_first_symbol"] = first.label

    # 2. CSV 实时模拟
    csv_live = CsvLiveDataProvider(csv_market)
    bars = csv_live.latest_bars(first, lookback=60)
    results["csv_live_bars"] = len(bars)
    quote = csv_live.latest_quote(first)
    results["csv_latest_date"] = quote.get("date", "")

    # 3. 工厂模式
    factory_market = DataProviderFactory.create_market("csv")
    factory_live = DataProviderFactory.create_live("csv")
    results["factory_market_type"] = type(factory_market).__name__
    results["factory_live_type"] = type(factory_live).__name__

    # 4. 统一管理器
    manager = DataProviderFactory.create_manager("csv", "csv")
    results["manager_status"] = manager.status()

    return results


if __name__ == "__main__":
    print(json.dumps(smoke_test(), ensure_ascii=False, indent=2, default=str))
