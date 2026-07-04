#!/usr/bin/env python3
"""
独立回测脚本 —— 多引擎策略回测（native + VectorBT 加速）。

功能:
  1. 加载 DATASET 中的 CSV 历史日线数据
  2. 双引擎支持：native（strategyforge）/ vbt（VectorBT 向量化加速）
  3. 三种信号来源：内部策略 / 外部因子注入 / 基准线相对策略
  4. 多候选方案对比，输出权益曲线、绩效摘要、交易点清单
  5. 离线/在线模式一键切换

使用方式:
  # 基础回测（native 引擎）
  python run_backtest.py --symbol 510300 --family 趋势跟踪 --risk 均衡

  # VectorBT 加速回测
  python run_backtest.py --symbol 510300 --family 趋势跟踪 --engine vbt

  # 基准线相对策略
  python run_backtest.py --symbol 510300 --engine vbt --benchmark 510300

  # 外部因子注入（从 CSV 加载因子数据）
  python run_backtest.py --symbol 510300 --engine vbt --factor my_factor.csv --factor-threshold 1.0

  # 完整对比：所有策略族 vs 基准
  python run_backtest.py --symbol 510300 --compare-all

架构说明:
  - native 引擎：纯 strategyforge.py，确定性回测代码，适合策略研究和审计
  - vbt 引擎：VectorBT 向量化加速，适合批量参数对比和基准线策略
  - 外部因子：任何 CSV/JSON → pandas Series → VBT 信号生成
  - 数据源通过 DataProviderFactory 创建，mode 切换 CSV/Eastmoney/yfinance
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

# ── 确保 demo 目录在 sys.path 中 ────────────────────────────
DEMO_DIR = Path(__file__).resolve().parent
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from data_provider import (
    VALID_MODES,
    CsvMarketDataProvider,
    DataProviderFactory,
    ProviderMode,
)
from strategyforge import (
    RiskProfile,
    StrategyFamily,
    SymbolInfo,
    backtest,
    build_strategy_variants,
    compare_variants,
    format_pct,
    load_symbols,
    max_drawdown,
    risk_parameters,
    sharpe_ratio,
    summarize_backtest,
    trade_points,
)

VALID_ENGINES = ("native", "vbt")

# ── CLI 界面 ───────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="智塔 Strata 独立回测工具 — 用 CSV/Eastmoney 数据验证策略",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_backtest.py --list
  python run_backtest.py --symbol 510300 --family 趋势跟踪
  python run_backtest.py --symbol 510300 --family 均值回归 --risk 保守 --window 近1年
  python run_backtest.py --symbol 510300 --family 多策略投票 --mode eastmoney --output results/
        """,
    )
    parser.add_argument("--list", action="store_true", help="列出所有可用标的和数据源状态")
    parser.add_argument("--symbol", type=str, default=None, help="标的代码，如 510300、600519")
    parser.add_argument("--family", type=str, default="趋势跟踪",
                        choices=["趋势跟踪", "均值回归", "布林带反转", "多策略投票", "基础模板"],
                        help="策略族（默认: 趋势跟踪）")
    parser.add_argument("--risk", type=str, default="均衡",
                        choices=["保守", "均衡", "进取"],
                        help="风险档位（默认: 均衡）")
    parser.add_argument("--window", type=str, default="全部",
                        choices=["近6个月", "近1年", "近3年", "近5年", "全部"],
                        help="回测时间窗口（默认: 全部）")
    parser.add_argument("--mode", type=str, default="csv",
                        choices=list(VALID_MODES),
                        help="数据源模式: csv=离线CSV, eastmoney=东方财富实时API（默认: csv）")
    parser.add_argument("--engine", type=str, default="native",
                        choices=list(VALID_ENGINES),
                        help="回测引擎: native=strategyforge, vbt=VectorBT加速（默认: native）")
    parser.add_argument("--benchmark", type=str, default=None,
                        help="基准标的代码，用于 VBT 基准线相对策略")
    parser.add_argument("--factor", type=str, default=None,
                        help="外部因子文件路径（CSV/JSON），注入外部 alpha 因子到 VBT 引擎")
    parser.add_argument("--factor-threshold", type=float, default=0.0,
                        help="外部因子入场阈值（默认: 0.0）")
    parser.add_argument("--compare-all", action="store_true",
                        help="一次性对比所有策略族 + 基准线策略")
    parser.add_argument("--output", type=str, default=None,
                        help="输出目录（默认: 打印到终端）")
    return parser


def list_symbols(mode: ProviderMode = "csv") -> None:
    """列出可用标的。"""
    try:
        market = DataProviderFactory.create_market(mode)
    except Exception as exc:
        print(f"[错误] 无法连接数据源 '{mode}': {exc}")
        print("[提示] 尝试使用离线模式: --mode csv")
        sys.exit(1)

    symbols = market.symbols()
    print(f"\n数据源: {mode} | 可用标的: {len(symbols)} 个\n")
    print(f"{'代码':<10} {'名称':<16} {'市场':<6} {'类别':<10} {'行数':<8} {'起始':<12} {'结束':<12}")
    print("-" * 74)
    for item in symbols:
        rows_str = str(item.rows) if item.rows else "?"
        start_str = item.start or "?"
        end_str = item.end or "?"
        print(f"{item.code:<10} {item.name:<16} {item.market:<6} {item.category:<10} {rows_str:<8} {start_str:<12} {end_str:<12}")


# ── 核心运行逻辑 ────────────────────────────────────────────


def run_single_backtest(
    symbol_code: str,
    family: StrategyFamily,
    risk: RiskProfile,
    window: str = "全部",
    mode: ProviderMode = "csv",
    benchmark_code: str | None = None,
) -> dict[str, Any]:
    """
    运行单次回测并返回完整结果。

    返回 dict:
      - symbol: SymbolInfo
      - family: StrategyFamily
      - risk: RiskProfile
      - window: str
      - variants: list[StrategyVariant]
      - summary: pd.DataFrame
      - curves: pd.DataFrame
      - backtests: dict[str, pd.DataFrame]
      - trade_points: dict[str, pd.DataFrame]
      - data_source: str
      - timestamp: str
    """

    # 1. 加载数据
    market = DataProviderFactory.create_market(mode)
    symbols = market.symbols()
    symbol = next((s for s in symbols if s.code == symbol_code), None)
    if symbol is None:
        raise ValueError(f"标的 {symbol_code} 不在数据源中。可用标的: {[s.code for s in symbols]}")

    df = market.history(symbol)

    # 2. 窗口切片
    from agent_runtime import slice_history_window
    df = slice_history_window(df, window=window)
    if df.empty or len(df) < 60:
        raise ValueError(f"{symbol.label} 在窗口 {window} 内数据不足（需要至少 60 根 bar，实际 {len(df)} 根）")

    # 3. 生成策略候选方案
    idea = f"用户选择了 {family} 策略，风险偏好 {risk}，窗口 {window}"
    variants = build_strategy_variants(idea, risk, base_family=family)

    # 4. 运行回测
    summary_df, curves_df, backtests = compare_variants(df, variants, risk)

    # 5. 交易点
    trades = {name: trade_points(bt) for name, bt in backtests.items()}

    # 6. 基准处理
    benchmark = market.history(symbol)
    benchmark = slice_history_window(benchmark, window=window)
    benchmark_curve = (1 + benchmark["return"]).cumprod()
    curves_df["买入持有基准"] = benchmark_curve.values[:len(curves_df)] if len(benchmark_curve) >= len(curves_df) else benchmark_curve.values

    return {
        "symbol": symbol,
        "family": family,
        "risk": risk,
        "window": window,
        "variants": variants,
        "summary": summary_df,
        "curves": curves_df,
        "backtests": backtests,
        "trade_points": trades,
        "data_source": mode,
        "data_rows": len(df),
        "data_start": str(df["date"].iloc[0].date()),
        "data_end": str(df["date"].iloc[-1].date()),
        "timestamp": datetime.now().isoformat(),
    }


# ── 格式化输出 ──────────────────────────────────────────────


def print_backtest_report(result: dict[str, Any]) -> None:
    """美观打印回测报告。"""
    summary = result["summary"]
    best = summary.iloc[0]

    # 如果 summary 为空则跳过
    if len(summary) == 0:
        print("[提示] 没有产生有效的回测结果")
        return

    print()
    print("=" * 68)
    print("  智塔 Strata · 策略回测报告")
    print("=" * 68)
    print(f"  标的        : {result['symbol'].label}")
    print(f"  策略族      : {result['family']}")
    print(f"  风险档位    : {result['risk']}")
    print(f"  时间窗口    : {result['window']} ({result['data_start']} ~ {result['data_end']})")
    print(f"  数据源      : {result['data_source']} ({result['data_rows']} 根 bar)")
    print(f"  生成时间    : {result['timestamp'][:19]}")
    print()

    # 绩效摘要表
    print("─" * 68)
    print("  绩效对比")
    print("─" * 68)
    # 根据实际列动态选择
    display_cols = [c for c in ["方案", "策略类型", "累计收益", "超额收益", "最大回撤", "夏普比率", "胜率", "交易次数", "综合评分"] if c in summary.columns]
    display = summary[display_cols].copy()
    for col in display.select_dtypes(include=['float64', 'float32', 'int64']).columns:
        col_lower = str(col)
        if any(kw in col_lower for kw in ["收益", "回撤", "胜率", "占比"]):
            display[col] = display[col].map(lambda v: format_pct(float(v)))
        elif any(kw in col_lower for kw in ["比率", "评分"]):
            display[col] = display[col].map(lambda v: f"{float(v):.2f}")
    print(display.to_string(index=False))
    print()

    # 最佳方案详解
    print("─" * 68)
    print(f"  推荐方案: {best.get('方案', best.index[0] if hasattr(best, 'index') else '—')}")
    print("─" * 68)
    for key, label in [("说明", "说明"), ("策略类型", "策略类型"), ("风险档位", "风险档位"), ("是否增强", "是否增强")]:
        if key in best:
            print(f"  {label:<10}: {best[key]}")
    for key, fmt_pct in [("累计收益", True), ("基准收益", True), ("超额收益", True), ("最大回撤", True), ("胜率", True), ("持仓天数占比", True)]:
        if key in best:
            print(f"  {key:<10}: {format_pct(float(best[key]))}")
    for key in ["夏普比率"]:
        if key in best:
            print(f"  {key:<10}: {float(best[key]):.2f}")
    for key in ["交易次数"]:
        if key in best:
            print(f"  {key:<10}: {int(best[key])}")
    print()

    # 策略假设
    print("─" * 68)
    print("  策略假设与规则")
    print("─" * 68)
    variant = next((v for v in result["variants"] if v.name == best["方案"]), None)
    if variant:
        from strategyforge import build_strategy_card
        card = build_strategy_card("", result["risk"], variant.family)
        print(f"  假设      : {card.hypothesis}")
        print(f"  入场规则  : {card.entry_rule}")
        print(f"  退出规则  : {card.exit_rule}")
        print(f"  风控规则  : {card.risk_rule}")
        print(f"  基准      : {card.benchmark}")
    print()

    # 警告
    print("─" * 68)
    print("  ⚠ 边界声明")
    print("─" * 68)
    print("  本报告仅为策略研究和模拟回测结果，不构成投资建议。")
    print("  历史表现不代表未来收益，回测存在幸存者偏差等局限性。")
    print()


def save_report(result: dict[str, Any], output_dir: str | Path) -> None:
    """保存回测结果到文件。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    symbol_code = result["symbol"].code
    family = result["family"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{symbol_code}_{family}_{timestamp}"

    # 权益曲线
    curves_path = out / f"{prefix}_curves.csv"
    result["curves"].to_csv(curves_path, index=False)
    print(f"[已保存] 权益曲线 → {curves_path}")

    # 绩效摘要
    summary_path = out / f"{prefix}_summary.csv"
    result["summary"].to_csv(summary_path, index=False)
    print(f"[已保存] 绩效摘要 → {summary_path}")

    # 交易点
    for name, trades_df in result["trade_points"].items():
        if trades_df.empty:
            continue
        safe_name = name.replace(" ", "_")
        trades_path = out / f"{prefix}_{safe_name}_trades.csv"
        trades_df.to_csv(trades_path, index=False)
        print(f"[已保存] 交易点 → {trades_path}")

    # 完整报告 JSON
    report = {
        "symbol": result["symbol"].code,
        "name": result["symbol"].name,
        "family": result["family"],
        "risk": result["risk"],
        "window": result["window"],
        "data_source": result["data_source"],
        "data_rows": result["data_rows"],
        "data_start": result["data_start"],
        "data_end": result["data_end"],
        "timestamp": result["timestamp"],
        "variants": [
            {"name": v.name, "family": v.family, "risk": v.risk_profile, "enhanced": v.enhanced, "description": v.description}
            for v in result["variants"]
        ],
        "summary": result["summary"].to_dict(orient="records"),
    }
    report_path = out / f"{prefix}_report.json"
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, default=str)
    print(f"[已保存] 完整报告 → {report_path}")


# ── VBT 引擎回测 ────────────────────────────────────────────


def run_single_backtest_vbt(
    symbol_code: str,
    family: StrategyFamily = "趋势跟踪",
    risk: RiskProfile = "均衡",
    window: str = "全部",
    mode: ProviderMode = "csv",
    benchmark_code: str | None = None,
    factor_path: str | None = None,
    factor_threshold: float = 0.0,
) -> dict[str, Any]:
    """使用 VectorBT 加速引擎运行回测。"""
    from vbt_adapter import VbtAdapter, quick_vbt_backtest

    market = DataProviderFactory.create_market(mode)
    symbol = next((s for s in market.symbols() if s.code == symbol_code), None)
    if symbol is None:
        raise ValueError(f"标的 {symbol_code} 不在数据源中")

    # 外部因子加载
    external_factor = None
    if factor_path:
        external_factor = _load_external_factor(factor_path, mode)

    # 基准对标
    actual_benchmark = benchmark_code or symbol_code

    return quick_vbt_backtest(
        symbol_code=symbol_code,
        family=family,
        risk=risk,
        window=window,
        mode=mode,
        benchmark_code=actual_benchmark,
        external_factor=external_factor,
        factor_threshold=factor_threshold,
    )


def run_compare_all(
    symbol_code: str,
    risk: RiskProfile = "均衡",
    window: str = "全部",
    mode: ProviderMode = "csv",
    benchmark_code: str | None = None,
) -> dict[str, Any]:
    """一次性对比所有策略族，使用 VBT 加速。"""
    from vbt_adapter import VbtAdapter
    from agent_runtime import slice_history_window

    market = DataProviderFactory.create_market(mode)
    symbol = next((s for s in market.symbols() if s.code == symbol_code), None)
    if symbol is None:
        raise ValueError(f"标的 {symbol_code} 不在数据源中")

    data = market.history(symbol)
    data = slice_history_window(data, window=window)
    close = data.set_index("date")["close"]
    all_variants = []
    for family in ["趋势跟踪", "均值回归", "布林带反转", "多策略投票"]:
        idea = f"compare-all: {family} {risk}"
        all_variants.extend(build_strategy_variants(idea, risk, base_family=family))

    # 基准数据
    bench_close = None
    if benchmark_code:
        bench_symbol = next((s for s in market.symbols() if s.code == benchmark_code), None)
        if bench_symbol:
            bench_data = market.history(bench_symbol)
            bench_data = slice_history_window(bench_data, window=window)
            bench_close = bench_data.set_index("date")["close"]

    adapter = VbtAdapter()
    summary_df = adapter.compare_strategy_variants(close, all_variants, benchmark=bench_close)

    # 构建权益曲线
    curves = pd.DataFrame({"date": close.index, "买入持有基准": close / close.iloc[0]})
    for variant in all_variants:
        result = adapter.run_strategyforge(close, variant.family, risk=variant.risk_profile,
                                            enhanced=variant.enhanced, name=variant.name)
        if result.equity_curve is not None:
            curves[variant.name] = result.equity_curve.values

    return {
        "symbol": symbol,
        "family": "全部对比",
        "risk": risk,
        "window": window,
        "variants": all_variants,
        "summary": summary_df,
        "curves": curves,
        "backtests": {},
        "trade_points": {},
        "data_source": f"{mode}+vbt",
        "data_rows": len(data),
        "data_start": str(data["date"].iloc[0].date()),
        "data_end": str(data["date"].iloc[-1].date()),
        "timestamp": datetime.now().isoformat(),
    }


def _load_external_factor(factor_path: str, mode: ProviderMode = "csv") -> pd.Series:
    """从 CSV 或 JSON 文件加载外部因子。"""
    path = Path(factor_path)
    if not path.exists():
        raise FileNotFoundError(f"因子文件不存在: {factor_path}")

    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        # 期望格式: {"dates": [...], "values": [...]} 或 {"factor": {"date": value, ...}}
        if "dates" in payload and "values" in payload:
            series = pd.Series(payload["values"], index=pd.to_datetime(payload["dates"]))
        elif "factor" in payload:
            series = pd.Series(payload["factor"])
            series.index = pd.to_datetime(series.index)
        else:
            series = pd.Series(payload)
            series.index = pd.to_datetime(series.index)
        series.name = path.stem
        return series

    # CSV 格式: date,factor_value
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    factor_col = df.columns[0]
    series = df[factor_col]
    series.name = factor_col
    return series


# ── 主入口 ──────────────────────────────────────────────────


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        list_symbols(args.mode)
        return

    if not args.symbol:
        parser.print_help()
        print("\n[提示] 使用 --list 查看可用标的，或指定 --symbol 运行回测")
        sys.exit(1)

    # 全量对比模式
    if args.compare_all:
        try:
            result = run_compare_all(
                symbol_code=args.symbol,
                risk=args.risk,
                window=args.window,
                mode=args.mode,
                benchmark_code=args.benchmark,
            )
        except Exception as exc:
            print(f"[异常] {exc}")
            print("[提示] 请确认 vectorbt 已安装: pip install vectorbt")
            sys.exit(1)
        print_backtest_report(result)
        if args.output:
            save_report(result, args.output)
        print("全量对比完成。")
        return

    # VBT 引擎模式
    if args.engine == "vbt":
        try:
            result = run_single_backtest_vbt(
                symbol_code=args.symbol,
                family=args.family,
                risk=args.risk,
                window=args.window,
                mode=args.mode,
                benchmark_code=args.benchmark,
                factor_path=args.factor,
                factor_threshold=args.factor_threshold,
            )
        except Exception as exc:
            print(f"[异常] {exc}")
            print("[提示] 请确认 vectorbt 已安装: pip install vectorbt")
            sys.exit(1)

        # 格式化 VBT 结果
        vbt_result = result["vbt_result"]
        summary_df = result["summary"]
        curves_df = result["curves"]
        print()
        print("=" * 68)
        print("  智塔 Strata · VectorBT 加速回测报告")
        print("=" * 68)
        print(f"  标的        : {args.symbol} ({args.family})")
        print(f"  引擎        : VectorBT 1.0 (向量化)")
        print(f"  数据源      : {args.mode}")
        print(f"  因子        : {'外部注入' if args.factor else '内部信号'}")
        if args.benchmark:
            print(f"  基准        : {args.benchmark}")
        print()
        print("─" * 68)
        print("  绩效指标")
        print("─" * 68)
        for col in summary_df.columns:
            val = summary_df[col].iloc[0]
            if isinstance(val, float) and ("收益" in col or "回撤" in col or "率" in col or "占比" in col):
                print(f"  {col:<12}: {val:>.2%}")
            elif isinstance(val, float):
                print(f"  {col:<12}: {val:.2f}")
            else:
                print(f"  {col:<12}: {val}")
        print()

        if args.output:
            out = Path(args.output)
            out.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            curves_df.to_csv(out / f"{args.symbol}_vbt_{ts}_curves.csv", index=False)
            summary_df.to_csv(out / f"{args.symbol}_vbt_{ts}_summary.csv", index=False)
            print(f"[已保存] 结果 → {out}")
        print("回测完成。")
        return

    # Native 引擎模式（默认）
    try:
        result = run_single_backtest(
            symbol_code=args.symbol,
            family=args.family,
            risk=args.risk,
            window=args.window,
            mode=args.mode,
            benchmark_code=args.benchmark,
        )
    except ValueError as exc:
        print(f"[错误] {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"[异常] {exc}")
        print("[提示] 请确认数据源可用。离线模式: --mode csv")
        sys.exit(1)

    print_backtest_report(result)

    if args.output:
        save_report(result, args.output)

    print("回测完成。")


if __name__ == "__main__":
    main()
