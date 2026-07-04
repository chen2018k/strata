#!/usr/bin/env python3
"""
实盘/纸面校验脚本 —— 在最新行情上运行策略，输出目标仓位信号。

支持两种运行模式:
  1. 离线模式（csv）：读取 CSV 最后 N 根 bar 模拟"最新行情"
     适合无网络环境、演示、开发调试
  2. 在线模式（eastmoney）：从东方财富 API 拉取最新日线
     适合策略日常监控、纸面验证

使用方式:
  # 离线模式 —— 模拟实盘信号
  python live_validator.py --symbol 510300 --family 趋势跟踪 --risk 均衡

  # 在线模式 —— 拉取最新行情
  python live_validator.py --symbol 510300 --family 趋势跟踪 --mode eastmoney

  # 批量扫描所有标的
  python live_validator.py --scan --family 趋势跟踪

  # 指定当前持仓（用于计算调仓信号）
  python live_validator.py --symbol 510300 --family 趋势跟踪 --position 0.75

架构:
  该脚本调用 data_provider.py 的 LiveDataProvider 接口。
  策略信号由 strategyforge.py 的 build_signals() 生成。
  上层完全不依赖具体数据源实现。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ── 确保 demo 目录在 sys.path 中 ────────────────────────────
DEMO_DIR = Path(__file__).resolve().parent
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from data_provider import (
    VALID_MODES,
    DataProviderFactory,
    ProviderMode,
)
from strategyforge import (
    RiskProfile,
    StrategyFamily,
    SymbolInfo,
    build_signals,
    risk_parameters,
)


# ── 实盘信号生成 ────────────────────────────────────────────


@dataclass
class LiveSignal:
    """实盘信号对象。"""
    date: str
    code: str
    name: str
    strategy_family: str
    risk_profile: str
    enhanced: bool
    close: float
    target_position: float
    current_position: float
    action: str
    signal_raw: float
    source: str
    bars_used: int
    data_start: str
    data_end: str
    timestamp: str


def generate_live_signal(
    symbol: SymbolInfo,
    family: StrategyFamily,
    risk: RiskProfile,
    enhanced: bool = True,
    current_position: float = 0.0,
    mode: ProviderMode = "csv",
    lookback: int = 260,
) -> LiveSignal:
    """
    在最新行情上生成目标仓位信号。

    Args:
        symbol: 标的
        family: 策略族
        risk: 风险档位
        enhanced: 是否启用风控增强
        current_position: 当前持仓（0.0~1.0），用于计算调仓方向
        mode: 数据源模式（csv / eastmoney）
        lookback: 用于信号计算的历史 bar 数

    Returns:
        LiveSignal 对象
    """
    live_provider = DataProviderFactory.create_live(mode)
    bars = live_provider.latest_bars(symbol, lookback=lookback)

    if len(bars) < 60:
        raise ValueError(f"数据不足：{symbol.label} 只有 {len(bars)} 根 bar，至少需要 60 根才能生成可靠信号")

    # 生成信号
    signal_series = build_signals(bars, family, enhanced=enhanced, risk_profile=risk)
    target = float(signal_series.iloc[-1])

    latest = bars.iloc[-1]
    latest_date = str(pd.to_datetime(latest["date"]).date())
    close = float(latest["close"])

    # 确定动作
    delta = target - current_position
    if abs(delta) < 0.02:
        action = "保持"
    elif target <= 0.01:
        action = "空仓"
    elif delta > 0:
        action = "加仓"
    else:
        action = "减仓"

    return LiveSignal(
        date=latest_date,
        code=symbol.code,
        name=symbol.name,
        strategy_family=family,
        risk_profile=risk,
        enhanced=enhanced,
        close=close,
        target_position=round(target, 4),
        current_position=round(current_position, 4),
        action=action,
        signal_raw=round(float(signal_series.iloc[-1]), 4),
        source=mode,
        bars_used=len(bars),
        data_start=str(pd.to_datetime(bars.iloc[0]["date"]).date()),
        data_end=str(pd.to_datetime(bars.iloc[-1]["date"]).date()),
        timestamp=datetime.now().isoformat(),
    )


def batch_scan(
    family: StrategyFamily,
    risk: RiskProfile = "均衡",
    enhanced: bool = True,
    mode: ProviderMode = "csv",
    filter_category: str | None = None,
) -> list[LiveSignal]:
    """
    批量扫描所有标的的最新信号。

    Args:
        family: 策略族
        risk: 风险档位
        enhanced: 是否风控增强
        mode: 数据源模式
        filter_category: 只扫描特定类别（如 "宽基ETF"）

    Returns:
        信号列表（按 target_position 降序排列）
    """
    market = DataProviderFactory.create_market(mode)
    symbols = market.symbols()
    if filter_category:
        symbols = [s for s in symbols if filter_category in s.category]

    signals: list[LiveSignal] = []
    errors: list[dict[str, str]] = []

    for symbol in symbols:
        try:
            signal = generate_live_signal(
                symbol=symbol,
                family=family,
                risk=risk,
                enhanced=enhanced,
                mode=mode,
            )
            signals.append(signal)
        except Exception as exc:
            errors.append({"code": symbol.code, "name": symbol.name, "error": str(exc)})

    # 按目标仓位降序
    signals.sort(key=lambda s: s.target_position, reverse=True)

    if errors:
        print(f"\n[警告] {len(errors)} 个标的生成信号失败:")
        for err in errors:
            print(f"  {err['code']} {err['name']}: {err['error']}")

    return signals


# ── 格式化输出 ──────────────────────────────────────────────


def print_signal_report(signal: LiveSignal) -> None:
    """打印单标信号报告。"""
    params = risk_parameters(signal.risk_profile)
    print()
    print("=" * 56)
    print("  智塔 Strata · 实盘信号校验")
    print("=" * 56)
    print(f"  标的        : {signal.code} {signal.name}")
    print(f"  策略        : {signal.strategy_family} {'· 增强' if signal.enhanced else '· 基础'}")
    print(f"  风险        : {signal.risk_profile} (仓位{params['position']:.0%}, 止损{params['stop_loss']:.0%})")
    print(f"  数据源      : {signal.source} ({signal.bars_used} 根 bar)")
    print(f"  数据范围    : {signal.data_start} ~ {signal.data_end}")
    print(f"  信号日期    : {signal.date}")
    print()

    print("─" * 56)
    print("  信号")
    print("─" * 56)
    print(f"  最新价格    : {signal.close:.4f}")
    print(f"  原始信号    : {signal.signal_raw:.4f}")
    print(f"  目标仓位    : {signal.target_position:.2%}")
    print(f"  当前持仓    : {signal.current_position:.2%}")
    print(f"  建议动作    : {signal.action}")
    print()

    # 风险提示
    print("─" * 56)
    print("  ⚠ 重要提示")
    print("─" * 56)
    print("  本信号为纸面校验，不代表实盘买卖指令。")
    print("  所有实盘决策需经用户确认和风控审核。")
    print("  历史信号表现不代表未来结果。")
    print()


def print_scan_table(signals: list[LiveSignal]) -> None:
    """打印批量扫描结果表。"""
    if not signals:
        print("[提示] 未生成任何信号")
        return

    print(f"\n批量扫描结果 ({len(signals)} 个标的)\n")
    print(f"{'代码':<10} {'名称':<14} {'价格':>8} {'目标仓位':>8} {'动作':<6} {'策略':<12}")
    print("-" * 60)
    for s in signals:
        print(f"{s.code:<10} {s.name:<14} {s.close:>8.3f} {s.target_position:>7.1%} {s.action:<6} {s.strategy_family:<12}")

    # 汇总
    long_count = sum(1 for s in signals if s.target_position > 0.05)
    print(f"\n做多信号: {long_count}/{len(signals)} 个标的")


def export_signals_json(signals: list[LiveSignal], path: str | Path) -> None:
    """导出信号为 JSON 文件。"""
    out = Path(path)
    payload = [
        {
            "code": s.code,
            "name": s.name,
            "date": s.date,
            "close": s.close,
            "target_position": s.target_position,
            "current_position": s.current_position,
            "action": s.action,
            "family": s.strategy_family,
            "risk": s.risk_profile,
            "enhanced": s.enhanced,
            "source": s.source,
            "timestamp": s.timestamp,
        }
        for s in signals
    ]
    with out.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
    print(f"[已导出] 信号 JSON → {out}")


# ── CLI ─────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="智塔 Strata 实盘校验工具 — 在最新行情上运行策略生成纸面信号",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python live_validator.py --symbol 510300 --family 趋势跟踪
  python live_validator.py --symbol 510300 --family 趋势跟踪 --mode eastmoney
  python live_validator.py --scan --family 趋势跟踪
  python live_validator.py --scan --family 多策略投票 --output signals.json
        """,
    )
    parser.add_argument("--symbol", type=str, default=None, help="标的代码")
    parser.add_argument("--scan", action="store_true", help="批量扫描所有标的")
    parser.add_argument("--family", type=str, default="趋势跟踪",
                        choices=["趋势跟踪", "均值回归", "布林带反转", "多策略投票", "基础模板"])
    parser.add_argument("--risk", type=str, default="均衡",
                        choices=["保守", "均衡", "进取"])
    parser.add_argument("--mode", type=str, default="csv",
                        choices=list(VALID_MODES),
                        help="数据源: csv=离线, eastmoney=实时")
    parser.add_argument("--position", type=float, default=0.0,
                        help="当前持仓（0.0~1.0）")
    parser.add_argument("--category", type=str, default=None,
                        help="批量扫描时只扫描指定类别（如 宽基ETF、股票）")
    parser.add_argument("--output", type=str, default=None,
                        help="导出信号 JSON 文件路径")
    parser.add_argument("--no-enhance", action="store_true",
                        help="禁用风控增强")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.scan:
        signals = batch_scan(
            family=args.family,
            risk=args.risk,
            enhanced=not args.no_enhance,
            mode=args.mode,
            filter_category=args.category,
        )
        print_scan_table(signals)
        if args.output:
            export_signals_json(signals, args.output)
        return

    if not args.symbol:
        parser.print_help()
        print("\n[提示] 使用 --symbol 指定标的，或 --scan 批量扫描")
        sys.exit(1)

    market = DataProviderFactory.create_market(args.mode)
    symbol = next((s for s in market.symbols() if s.code == args.symbol), None)
    if symbol is None:
        print(f"[错误] 标的不存在: {args.symbol}")
        sys.exit(1)

    try:
        signal = generate_live_signal(
            symbol=symbol,
            family=args.family,
            risk=args.risk,
            enhanced=not args.no_enhance,
            current_position=args.position,
            mode=args.mode,
        )
    except Exception as exc:
        print(f"[异常] 信号生成失败: {exc}")
        print("[提示] 尝试离线模式: --mode csv")
        sys.exit(1)

    print_signal_report(signal)

    if args.output:
        export_signals_json([signal], args.output)


if __name__ == "__main__":
    main()
