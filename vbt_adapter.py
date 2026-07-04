"""
VectorBT 适配层 —— 将 VectorBT 的向量化加速能力注入智塔 Strata。

设计原则:
  1. 薄适配 —— 不替换 strategyforge.py，只做加速和增强
  2. 三模信号 —— 内部信号 / 外部因子 / 基准线策略
  3. 双向兼容 —— 输出同时支持 VBT Portfolio 和智塔 summary 格式
  4. 零侵入 —— 上层 run_backtest.py 通过 --engine vbt 切换

信号来源:
  - from_strategyforge  : 利用现有 build_signals() 生成 entry/exit
  - from_external_factor: 接收外部 pandas Series 作为 alpha 因子
  - from_benchmark      : 生成相对于基准的超额信号（基准线策略）

使用示例:
  >>> from vbt_adapter import VbtAdapter
  >>> adapter = VbtAdapter(close_prices)
  >>> result = adapter.run_strategyforge(symbol, family, risk)
  >>> result = adapter.run_external_factor(my_factor_series)
  >>> result = adapter.run_benchmark_relative(benchmark_prices)
  >>> comparison = adapter.compare_all_strategies(close, strategies_dict)

参考:
  - VectorBT GitHub: https://github.com/polakowo/vectorbt
  - awesome-quant: https://github.com/wilsonfreitas/awesome-quant
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

try:
    import vectorbt as vbt
except ImportError:
    vbt = None
    import warnings
    warnings.warn("vectorbt not installed. Run: pip install vectorbt")

from data_provider import DataProviderFactory, ProviderMode
from strategyforge import (
    RiskProfile,
    StrategyFamily,
    StrategyVariant,
    SymbolInfo,
    backtest,
    build_signals,
    build_strategy_variants,
    compare_variants,
    format_pct,
    load_price_data,
    load_symbols,
    max_drawdown,
    risk_parameters,
    sharpe_ratio,
    summarize_backtest,
)


# ================================================================
# 统一结果类型
# ================================================================


@dataclass
class VbtResult:
    """VectorBT 回测结果（同时包含 VBT 原生和智塔格式）。"""
    name: str
    strategy_type: str  # "内部信号" | "外部因子" | "基准线策略"
    family: str = ""
    risk: str = ""

    # VBT 原生指标
    total_return: float = 0.0
    benchmark_return: float = 0.0
    excess_return: float = 0.0
    sharpe: float = 0.0
    max_dd: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0
    holding_ratio: float = 0.0

    # 智塔兼容
    summary: dict[str, float] = field(default_factory=dict)
    equity_curve: pd.Series | None = None
    benchmark_curve: pd.Series | None = None
    trades: pd.DataFrame | None = None
    raw_portfolio: Any = None  # vbt.Portfolio

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "方案": self.name,
            "策略类型": self.strategy_type,
            "累计收益": self.total_return,
            "基准收益": self.benchmark_return,
            "超额收益": self.excess_return,
            "最大回撤": self.max_dd,
            "夏普比率": self.sharpe,
            "胜率": self.win_rate,
            "交易次数": self.trade_count,
            "持仓天数占比": self.holding_ratio,
        }


# ================================================================
# VectorBT 适配器
# ================================================================


class VbtAdapter:
    """VectorBT 适配器 —— 薄封装层。

    核心能力:
      - 从 strategyforge 信号驱动 VectorBT 回测
      - 从任意 pandas Series 作为外部 alpha 因子
      - 生成基准线相对策略信号
      - 批量对比多种策略

    VBT 版本兼容: v1.0+（以 from_signals 为核心 API）
    """

    def __init__(self, freq: str = "D", init_cash: float = 1.0, fees: float = 0.0006):
        if vbt is None:
            raise ImportError("vectorbt is required. Run: pip install vectorbt")
        self.freq = freq
        self.init_cash = init_cash
        self.fees = fees

    # ── 模式一：从 strategyforge 信号 ──────────────────────────

    def run_strategyforge(
        self,
        close: pd.Series,
        family: StrategyFamily,
        risk: RiskProfile = "均衡",
        enhanced: bool = True,
        name: str | None = None,
    ) -> VbtResult:
        """将 strategyforge.build_signals() 的输出转为 VBT 回测。

        Args:
            close: 收盘价 Series（带 DatetimeIndex）
            family: 策略族
            risk: 风险档位
            enhanced: 风控增强
            name: 结果命名

        Returns:
            VbtResult
        """
        # 构建 DataFrame（strategyforge 需要）
        df = pd.DataFrame({"close": close, "date": close.index})
        df["return"] = df["close"].pct_change().fillna(0.0)

        # 用 strategyforge 生成信号
        signal_series = build_signals(df, family, enhanced=enhanced, risk_profile=risk)
        signal_series.index = close.index

        # 信号 → entry/exit
        entries = (signal_series > 0) & (signal_series.shift(1).fillna(0) == 0)
        exits = (signal_series == 0) & (signal_series.shift(1).fillna(0) > 0)

        # VectorBT 回测
        pf = vbt.Portfolio.from_signals(
            close, entries, exits,
            freq=self.freq,
            init_cash=self.init_cash,
            fees=self.fees,
        )

        return self._build_result(
            pf=pf,
            close=close,
            name=name or f"{family}·{'增强' if enhanced else '基础'}",
            strategy_type="内部信号",
            family=family,
            risk=risk,
        )

    # ── 模式二：外部因子注入 ──────────────────────────────────

    def run_external_factor(
        self,
        close: pd.Series,
        factor: pd.Series,
        entry_threshold: float = 0.0,
        exit_threshold: float | None = None,
        long_only: bool = True,
        name: str = "外部因子策略",
    ) -> VbtResult:
        """从外部 alpha 因子生成交易信号并回测。

        这是智塔的核心扩展能力：任何外部数据源（基本面、情绪、另类数据）
        只要能转成 pandas Series，就能直接注入策略回测。

        Args:
            close: 收盘价 Series
            factor: 外部 alpha 因子 Series（必须与 close 对齐索引）
            entry_threshold: 因子超过此阈值时入场
            exit_threshold: 因子低于此阈值时出场（默认 = -entry_threshold）
            long_only: 是否只做多
            name: 结果命名

        Returns:
            VbtResult

        示例:
            # 用 RSI 偏离度作为外部因子
            rsi_factor = -(rsi(close) - 50) / 50  # 负偏差越大越超卖
            result = adapter.run_external_factor(close, rsi_factor, entry_threshold=0.3)

            # 用基本面数据作为因子
            pe_factor = -pe_series.zscore()  # PE 越低越好
            result = adapter.run_external_factor(close, pe_factor, entry_threshold=1.0)
        """
        # 对齐索引
        factor = factor.reindex(close.index).fillna(0.0)
        exit_threshold = exit_threshold if exit_threshold is not None else -entry_threshold

        if long_only:
            entries = factor > entry_threshold
            exits = factor < exit_threshold
        else:
            entries = factor > entry_threshold
            exits = factor < -entry_threshold

        pf = vbt.Portfolio.from_signals(
            close, entries, exits,
            freq=self.freq,
            init_cash=self.init_cash,
            fees=self.fees,
        )

        return self._build_result(
            pf=pf,
            close=close,
            name=name,
            strategy_type="外部因子",
        )

    # ── 模式三：基准线相对策略 ────────────────────────────────

    def run_benchmark_relative(
        self,
        close: pd.Series,
        benchmark: pd.Series,
        entry_zscore: float = 1.5,
        exit_zscore: float = 0.5,
        lookback: int = 60,
        name: str = "基准线相对策略",
    ) -> VbtResult:
        """生成基于基准线偏离度的交易信号。

        策略逻辑:
          1. 计算相对强度 = close / benchmark
          2. 对相对强度做 Z-score 标准化
          3. Z-score > entry_zscore → 入场（跑赢基准，趋势延续）
          4. Z-score < exit_zscore  → 出场（跑输基准，趋势结束）

        这是文档里提到的"基准线策略"的核心实现。

        Args:
            close: 策略标的收盘价
            benchmark: 基准标的价格
            entry_zscore: 入场 Z-score 阈值
            exit_zscore: 出场 Z-score 阈值
            lookback: Z-score 计算回看窗口
            name: 结果命名

        Returns:
            VbtResult
        """
        # 对齐索引
        benchmark = benchmark.reindex(close.index).ffill().bfill()

        # 相对强度
        relative_strength = close / benchmark

        # Z-score
        rolling_mean = relative_strength.rolling(lookback).mean()
        rolling_std = relative_strength.rolling(lookback).std().replace(0, np.nan)
        zscore = (relative_strength - rolling_mean) / rolling_std

        # 信号
        entries = zscore > entry_zscore
        exits = zscore < exit_zscore

        pf = vbt.Portfolio.from_signals(
            close, entries, exits,
            freq=self.freq,
            init_cash=self.init_cash,
            fees=self.fees,
        )

        result = self._build_result(
            pf=pf,
            close=close,
            benchmark=benchmark,
            name=name,
            strategy_type="基准线策略",
        )

        # 附加相对强度指标
        result.summary["相对强度均值"] = float(relative_strength.mean())
        result.summary["Z-score 阈值"] = entry_zscore
        result.summary["回看窗口"] = lookback

        return result

    # ── 批量对比 ─────────────────────────────────────────────

    def compare_all(
        self,
        close: pd.Series,
        strategies: dict[str, tuple[pd.Series, pd.Series]],  # name → (entries, exits)
        benchmark: pd.Series | None = None,
    ) -> pd.DataFrame:
        """批量运行多种策略并返回对比 DataFrame。

        Args:
            close: 收盘价
            strategies: {name: (entries_series, exits_series)} 的字典
            benchmark: 可选基准价格

        Returns:
            对比 DataFrame（按超额收益排序）
        """
        results: list[VbtResult] = []
        benchmark = benchmark.reindex(close.index).ffill().bfill() if benchmark is not None else None

        for name, (entries, exits) in strategies.items():
            entries = entries.reindex(close.index).fillna(False)
            exits = exits.reindex(close.index).fillna(False)
            pf = vbt.Portfolio.from_signals(
                close, entries, exits,
                freq=self.freq, init_cash=self.init_cash, fees=self.fees,
            )
            result = self._build_result(
                pf=pf, close=close, benchmark=benchmark, name=name, strategy_type="批量对比",
            )
            results.append(result)

        return self._compare_dataframe(results)

    def compare_strategy_variants(
        self,
        close: pd.Series,
        variants: list[StrategyVariant],
        benchmark: pd.Series | None = None,
    ) -> pd.DataFrame:
        """对比智塔 StrategyVariant 列表的性能。

        Args:
            close: 收盘价
            variants: 策略方案列表
            benchmark: 基准价格

        Returns:
            对比 DataFrame
        """
        results: list[VbtResult] = []
        df = pd.DataFrame({"close": close, "date": close.index})
        df["return"] = df["close"].pct_change().fillna(0.0)

        for variant in variants:
            signal = build_signals(df, variant.family, enhanced=variant.enhanced, risk_profile=variant.risk_profile)
            signal.index = close.index
            entries = (signal > 0) & (signal.shift(1).fillna(0) == 0)
            exits = (signal == 0) & (signal.shift(1).fillna(0) > 0)

            pf = vbt.Portfolio.from_signals(
                close, entries, exits,
                freq=self.freq, init_cash=self.init_cash, fees=self.fees,
            )
            result = self._build_result(
                pf=pf, close=close, benchmark=benchmark,
                name=variant.name, strategy_type=variant.family, family=variant.family, risk=variant.risk_profile,
            )
            results.append(result)

        return self._compare_dataframe(results)

    # ── 工具方法 ────────────────────────────────────────────

    def factor_from_series(self, series: pd.Series, name: str = "external") -> pd.Series:
        """将外部数据标准化为可用于策略的因子 Series。

        输入可以是任意频率/格式的 Series，输出是标准化（Z-score）后的日频因子。

        Args:
            series: 原始外部数据
            name: 因子名称

        Returns:
            标准化因子 Series
        """
        # 重采样到日频并前向填充
        daily = series.resample("D").last().ffill()
        # Z-score 标准化
        mean = daily.rolling(252).mean()
        std = daily.rolling(252).std().replace(0, np.nan)
        zscore = (daily - mean) / std
        zscore.name = name
        return zscore.fillna(0.0)

    @staticmethod
    def list_strategies() -> list[dict[str, str]]:
        """列出所有可用的策略生成方式。"""
        return [
            {"name": "趋势跟踪", "type": "内部信号", "description": "20/60 日均线金叉入场，死叉出场"},
            {"name": "均值回归", "type": "内部信号", "description": "RSI < 30 入场，RSI > 55 或最大持有期出场"},
            {"name": "布林带反转", "type": "内部信号", "description": "价格跌破下轨入场，回到中轨/上轨出场"},
            {"name": "多策略投票", "type": "内部信号", "description": "趋势/RSI/布林带 ≥2 支持时入场"},
            {"name": "外部因子", "type": "外部因子", "description": "从任意 pandas Series 生成交易信号"},
            {"name": "基准线相对", "type": "基准线策略", "description": "相对基准指数的 Z-score 偏离策略"},
        ]

    # ── 内部方法 ────────────────────────────────────────────

    def _build_result(
        self,
        pf: Any,
        close: pd.Series,
        benchmark: pd.Series | None = None,
        name: str = "",
        strategy_type: str = "",
        family: str = "",
        risk: str = "",
    ) -> VbtResult:
        """从 VBT Portfolio 提取所有指标。"""
        # 收益
        total_ret = float(pf.total_return())
        bench_ret = float(pf.benchmark_returns().iloc[-1] - 1) if benchmark is None else float(benchmark.iloc[-1] / benchmark.iloc[0] - 1)
        excess_ret = total_ret - bench_ret

        # 风险
        sharpe = float(pf.sharpe_ratio()) if not np.isinf(float(pf.sharpe_ratio())) else 0.0
        max_dd_val = float(pf.max_drawdown())

        # 交易统计
        trades_df = pf.trades.records_readable if hasattr(pf.trades, 'records_readable') else pd.DataFrame()
        trade_count = len(trades_df)
        if trade_count > 0 and 'Status' in trades_df.columns:
            closed = trades_df[trades_df['Status'] == 'Closed']
            win_rate = float((closed['PnL'] > 0).mean()) if len(closed) > 0 else 0.0
        else:
            win_rate = 0.0

        # 持仓占比
        positions = pf.positions.records_readable if hasattr(pf.positions, 'records_readable') else pd.DataFrame()
        total_bars = len(close)
        if len(positions) > 0 and 'Size' in positions.columns:
            held_bars = int(positions['Size'].abs().sum() if 'Size' in positions.columns else 0)
            holding_ratio = min(1.0, held_bars / total_bars) if total_bars > 0 else 0.0
        else:
            holding_ratio = 0.0

        # 权益曲线
        equity = pf.value()

        return VbtResult(
            name=name,
            strategy_type=strategy_type,
            family=family,
            risk=risk,
            total_return=total_ret,
            benchmark_return=bench_ret,
            excess_return=excess_ret,
            sharpe=sharpe,
            max_dd=max_dd_val,
            win_rate=win_rate,
            trade_count=trade_count,
            holding_ratio=holding_ratio,
            summary={
                "累计收益": total_ret,
                "基准收益": bench_ret,
                "超额收益": excess_ret,
                "最大回撤": max_dd_val,
                "夏普比率": sharpe,
                "胜率": win_rate,
                "交易次数": trade_count,
                "持仓天数占比": holding_ratio,
            },
            equity_curve=equity,
            trades=trades_df,
            raw_portfolio=pf,
        )

    def _compare_dataframe(self, results: list[VbtResult]) -> pd.DataFrame:
        """构建对比 DataFrame。"""
        rows = [r.to_summary_dict() for r in results]
        df = pd.DataFrame(rows)
        if "超额收益" in df.columns:
            df = df.sort_values("超额收益", ascending=False).reset_index(drop=True)
        return df


# ================================================================
# 便捷函数 —— 一步式回测
# ================================================================


def quick_vbt_backtest(
    symbol_code: str,
    family: StrategyFamily = "趋势跟踪",
    risk: RiskProfile = "均衡",
    window: str = "全部",
    mode: ProviderMode = "csv",
    benchmark_code: str | None = None,
    external_factor: pd.Series | None = None,
    factor_threshold: float = 0.0,
) -> dict[str, Any]:
    """一步式 VectorBT 回测。

    自动处理: 数据加载 → 窗口切片 → VBT 回测 → 结果汇总

    Args:
        symbol_code: 标的代码
        family: 策略族
        risk: 风险档位
        window: 时间窗口
        mode: 数据源模式
        benchmark_code: 基准标的代码
        external_factor: 外部因子 Series（可选）

    Returns:
        {"vbt_result": VbtResult, "native_summary": pd.DataFrame, "curves": pd.DataFrame}
    """
    from agent_runtime import slice_history_window

    market = DataProviderFactory.create_market(mode)
    symbol = next((s for s in market.symbols() if s.code == symbol_code), None)
    if symbol is None:
        raise ValueError(f"Symbol {symbol_code} not found")

    data = market.history(symbol)
    data = slice_history_window(data, window=window)
    close = data.set_index("date")["close"]

    adapter = VbtAdapter()

    if external_factor is not None:
        # 外部因子模式
        vbt_result = adapter.run_external_factor(
            close, external_factor, entry_threshold=factor_threshold, name=f"外部因子·{symbol_code}",
        )
    else:
        # 内部信号模式
        vbt_result = adapter.run_strategyforge(close, family=family, risk=risk)

    # 构建基准对比
    benchmark_close = None
    if benchmark_code:
        bench_symbol = next((s for s in market.symbols() if s.code == benchmark_code), None)
        if bench_symbol:
            bench_data = market.history(bench_symbol)
            bench_data = slice_history_window(bench_data, window=window)
            benchmark_close = bench_data.set_index("date")["close"]

    if benchmark_close is not None:
        vbt_result.benchmark_return = float(benchmark_close.iloc[-1] / benchmark_close.iloc[0] - 1)
    else:
        vbt_result.benchmark_return = float(close.iloc[-1] / close.iloc[0] - 1)

    vbt_result.excess_return = vbt_result.total_return - vbt_result.benchmark_return

    # 构建权益曲线 DataFrame
    curves = pd.DataFrame({"date": close.index, "策略权益": vbt_result.equity_curve.values})
    curves["买入持有基准"] = close.values / close.values[0]

    return {
        "vbt_result": vbt_result,
        "summary": pd.DataFrame([vbt_result.to_summary_dict()]),
        "curves": curves,
        "trades": vbt_result.trades,
    }


# ================================================================
# 模块自检
# ================================================================


def smoke_test() -> dict[str, Any]:
    """验证 VectorBT 适配层所有功能。"""
    results: dict[str, Any] = {}

    # 准备测试数据
    dates = pd.date_range("2023-01-01", "2025-12-31", freq="D")
    np.random.seed(42)
    close_arr = 100 * (1 + np.random.randn(len(dates)).cumsum() * 0.008)
    close = pd.Series(close_arr, index=dates)
    # 基准：略微不同的随机游走
    bench_arr = 100 * (1 + np.random.randn(len(dates)).cumsum() * 0.007)
    benchmark = pd.Series(bench_arr, index=dates)

    adapter = VbtAdapter()

    # Test 1: 内部信号
    r1 = adapter.run_strategyforge(close, family="趋势跟踪", name="Test趋势")
    results["internal_signal_ok"] = r1.total_return != 0.0
    results["internal_return"] = f"{r1.total_return:.2%}"

    # Test 2: 外部因子
    rsi_factor = -(close.pct_change(14).fillna(0.0))
    r2 = adapter.run_external_factor(close, rsi_factor, entry_threshold=0.02, name="Test因子")
    results["external_factor_ok"] = True
    results["external_return"] = f"{r2.total_return:.2%}"

    # Test 3: 基准线策略
    r3 = adapter.run_benchmark_relative(close, benchmark, name="Test基准")
    results["benchmark_ok"] = True
    results["benchmark_return"] = f"{r3.total_return:.2%}"

    # Test 4: 批量对比
    entries1 = close > close.rolling(20).mean()
    exits1 = close < close.rolling(60).mean()
    entries2 = close < close.rolling(20).mean() * 0.95
    exits2 = close > close.rolling(20).mean() * 1.05
    df_compare = adapter.compare_all(close, {
        "趋势策略": (entries1, exits1),
        "反转策略": (entries2, exits2),
    })
    results["compare_count"] = len(df_compare)
    results["compare_ok"] = len(df_compare) >= 2

    return results


if __name__ == "__main__":
    print(json.dumps(smoke_test(), ensure_ascii=False, indent=2, default=str))
