from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

try:
    from agent_runtime import LLMClient
    from factor_library import factor_blend_payload, load_base_factors
    from interview_agent import StrategyPrototype
    from market_data import load_universe, preferred_benchmarks
    from strategyforge import (
        RiskProfile,
        StrategyFamily,
        StrategyVariant,
        compare_variants,
        format_pct,
        load_price_data,
        load_symbols,
    )
except ModuleNotFoundError:
    from .agent_runtime import LLMClient
    from .factor_library import factor_blend_payload, load_base_factors
    from .interview_agent import StrategyPrototype
    from .market_data import load_universe, preferred_benchmarks
    from .strategyforge import (
        RiskProfile,
        StrategyFamily,
        StrategyVariant,
        compare_variants,
        format_pct,
        load_price_data,
        load_symbols,
    )


VALID_FAMILIES: tuple[StrategyFamily, ...] = ("趋势跟踪", "均值回归", "布林带反转", "多策略投票", "基础模板")
VALID_RISKS: tuple[RiskProfile, ...] = ("保守", "均衡", "进取")
VALID_WINDOWS = ("近6个月", "近1年", "近3年", "近5年", "全部")


@dataclass(frozen=True)
class BacktestSpec:
    symbol_code: str
    benchmark_code: str
    family: StrategyFamily
    risk_profile: RiskProfile
    enhanced: bool
    window: str = "近3年"
    base_factor_id: str = ""
    user_factor_weight: float = 0.0
    market: str = "US"
    theme: str = ""
    user_factor: str = ""
    candidate_symbols: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "benchmark_code": self.benchmark_code,
            "family": self.family,
            "risk_profile": self.risk_profile,
            "enhanced": self.enhanced,
            "window": self.window,
            "base_factor_id": self.base_factor_id,
            "user_factor_weight": self.user_factor_weight,
            "market": self.market,
            "theme": self.theme,
            "user_factor": self.user_factor,
            "candidate_symbols": list(self.candidate_symbols),
        }


def _symbol_by_code(code: str):
    symbols = load_symbols()
    return next((item for item in symbols if item.code == code), symbols[0])


def _pick_symbol(text: str, fallback_code: str = "SPY") -> str:
    symbols = load_symbols()
    compact = text.lower()
    tokens = set(re.findall(r"[a-z0-9.-]+", compact))
    for item in symbols:
        code = item.code.lower()
        code_match = code in tokens if len(code) <= 2 else code in compact
        if code_match or item.name.lower() in compact or item.category.lower() in compact:
            return item.code
    return fallback_code


def _pick_risk(text: str) -> RiskProfile:
    if "保守" in text or "少亏" in text or "回撤" in text:
        return "保守"
    if "进取" in text or "高收益" in text or "波动" in text:
        return "进取"
    return "均衡"


def _pick_family(text: str) -> StrategyFamily:
    if any(item in text for item in ("布林", "区间", "下轨", "上轨")):
        return "布林带反转"
    if any(item in text for item in ("超跌", "反弹", "修复", "rsi", "RSI", "低估")):
        return "均值回归"
    if any(item in text for item in ("综合", "确认", "投票", "多策略")):
        return "多策略投票"
    if any(item in text for item in ("趋势", "突破", "均线", "动量", "上行")):
        return "趋势跟踪"
    return "趋势跟踪"


THEME_CANDIDATES: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("ai", "server", "服务器", "算力", "gpu", "半导体", "芯片", "数据中心"), ("NVDA", "AMD", "AVGO", "SMCI", "DELL", "ANET", "VRT"), "AI infrastructure"),
    (("copper", "铜", "电网", "矿", "有色"), ("FCX", "XLB", "CAT", "DE", "ETN", "GEV"), "Copper and electrification"),
    (("oil", "energy", "原油", "能源", "油气", "天然气"), ("XOM", "CVX", "SLB", "COP", "EOG", "XLE"), "Energy"),
    (("bank", "银行", "利率", "金融"), ("JPM", "BAC", "WFC", "GS", "MS", "XLF"), "Financials"),
    (("消费", "零售", "餐饮", "订单", "库存"), ("AMZN", "WMT", "COST", "HD", "MCD", "SBUX", "XLY"), "Consumer demand"),
    (("medical", "health", "医药", "医疗", "药"), ("LLY", "UNH", "JNJ", "MRK", "ABBV", "XLV"), "Health care"),
    (("港股", "香港", "恒生", "互联网"), ("2800.HK", "3033.HK", "EWH", "MCHI", "FXI"), "Hong Kong equity"),
    (("新加坡", "singapore", "reits", "reit"), ("ES3.SI", "CFA.SI", "EWS"), "Singapore equity"),
)


def _infer_theme_and_candidates(text: str, fallback_code: str) -> tuple[str, tuple[str, ...]]:
    compact = text.lower()
    available = {item.code for item in load_symbols()}
    for keywords, codes, theme in THEME_CANDIDATES:
        if any(keyword.lower() in compact for keyword in keywords):
            candidates = tuple(code for code in codes if code in available)
            if fallback_code in available and fallback_code not in candidates:
                candidates = (fallback_code, *candidates)
            return theme, candidates[:8]
    if fallback_code in available:
        return "User observation", (fallback_code,)
    return "User observation", tuple()


def _pick_benchmark_for_symbol(symbol_code: str, fallback_code: str = "SPY") -> str:
    universe = load_universe()
    by_code = {item.code: item for item in universe.symbols}
    symbol = by_code.get(symbol_code)
    if symbol is None:
        return fallback_code
    choices = preferred_benchmarks(symbol, universe)
    return choices[0].code if choices else fallback_code


def propose_backtest_spec(
    prototype: StrategyPrototype,
    answers: dict[str, str],
    llm: LLMClient | None = None,
) -> BacktestSpec:
    symbols = load_symbols()
    factor_blend = factor_blend_payload(prototype, answers)
    text = json.dumps({**prototype.as_dict(), "answers": answers}, ensure_ascii=False)
    picked_symbol = _pick_symbol(prototype.target_universe)
    theme, candidates = _infer_theme_and_candidates(text, picked_symbol)
    if candidates and (theme != "User observation" or picked_symbol == "SPY" or picked_symbol not in candidates):
        picked_symbol = candidates[0]
    fallback = BacktestSpec(
        symbol_code=picked_symbol,
        benchmark_code=_pick_benchmark_for_symbol(picked_symbol),
        family=factor_blend["base_factor"]["family"],
        risk_profile=factor_blend["base_factor"]["default_risk"] or _pick_risk(text),
        enhanced=bool(factor_blend["base_factor"]["enhanced"]),
        window="近3年",
        base_factor_id=factor_blend["base_factor"]["id"],
        user_factor_weight=float(factor_blend["user_weight"]),
        market="US",
        theme=theme,
        user_factor=str(factor_blend["user_factor"]["hypothesis"]),
        candidate_symbols=candidates,
    )
    if llm is None:
        return fallback

    allowed_symbols = [{"code": item.code, "name": item.name, "category": item.category} for item in symbols]
    allowed_factors = [
        {
            "id": item.id,
            "name": item.name,
            "family": item.family,
            "default_risk": item.default_risk,
            "enhanced": item.enhanced,
            "tags": list(item.tags),
        }
        for item in load_base_factors()
    ]
    system_prompt = (
        "你负责把用户策略雏形映射成已有确定性回测代码可接受的参数。"
        "基础因子库和用户因子必须解耦：基础因子只能从给定列表选择；用户因子只用于解释、筛选和权重建议。"
        "不能发明策略代码，不能发明标的。"
        "只返回 JSON。"
    )
    user_prompt = (
        f"可选标的：{json.dumps(allowed_symbols, ensure_ascii=False)}\n"
        f"基础因子库：{json.dumps(allowed_factors, ensure_ascii=False)}\n"
        f"当前用户因子和基础因子组合建议：{json.dumps(factor_blend, ensure_ascii=False)}\n"
        f"可选策略类型：{list(VALID_FAMILIES)}\n"
        f"可选风险档位：{list(VALID_RISKS)}\n"
        f"可选窗口：{list(VALID_WINDOWS)}\n\n"
        f"策略雏形与答案：{text}\n\n"
        "返回 JSON 字段：symbol_code, benchmark_code, family, risk_profile, enhanced, window, market, theme, user_factor, candidate_symbols。"
    )
    try:
        raw = llm.complete_json(system_prompt, user_prompt)
    except Exception:
        return fallback

    codes = {item.code for item in symbols}
    symbol_code = str(raw.get("symbol_code") or fallback.symbol_code)
    benchmark_code = str(raw.get("benchmark_code") or fallback.benchmark_code)
    raw_candidates = raw.get("candidate_symbols")
    candidate_symbols: tuple[str, ...] = fallback.candidate_symbols
    if isinstance(raw_candidates, list):
        candidate_symbols = tuple(str(code) for code in raw_candidates if str(code) in codes)[:8]
        if symbol_code in codes and symbol_code not in candidate_symbols:
            candidate_symbols = (symbol_code, *candidate_symbols)[:8]
    family = raw.get("family") if raw.get("family") in VALID_FAMILIES else fallback.family
    risk = raw.get("risk_profile") if raw.get("risk_profile") in VALID_RISKS else fallback.risk_profile
    window = raw.get("window") if raw.get("window") in VALID_WINDOWS else fallback.window
    return BacktestSpec(
        symbol_code=symbol_code if symbol_code in codes else fallback.symbol_code,
        benchmark_code=benchmark_code if benchmark_code in codes else _pick_benchmark_for_symbol(symbol_code),
        family=family,
        risk_profile=risk,
        enhanced=bool(raw.get("enhanced", fallback.enhanced)),
        window=window,
        base_factor_id=fallback.base_factor_id,
        user_factor_weight=fallback.user_factor_weight,
        market=str(raw.get("market") or fallback.market),
        theme=str(raw.get("theme") or fallback.theme),
        user_factor=str(raw.get("user_factor") or fallback.user_factor),
        candidate_symbols=candidate_symbols,
    )


def _slice_window(df: pd.DataFrame, window: str) -> pd.DataFrame:
    if window == "近6个月":
        return df.tail(126).reset_index(drop=True)
    if window == "近1年":
        return df.tail(252).reset_index(drop=True)
    if window == "近3年":
        return df.tail(756).reset_index(drop=True)
    if window == "近5年":
        return df.tail(1260).reset_index(drop=True)
    return df.reset_index(drop=True)


def _selected_benchmark_return(symbol_code: str, window: str) -> tuple[str, float]:
    benchmark_code = _pick_benchmark_for_symbol(symbol_code)
    benchmark = _symbol_by_code(benchmark_code)
    benchmark_history = _slice_window(load_price_data(benchmark), window)
    if benchmark_history.empty:
        return benchmark_code, 0.0
    return benchmark_code, float((1 + benchmark_history["return"]).cumprod().iloc[-1] - 1)


def run_candidate_pool_backtest(spec: BacktestSpec) -> pd.DataFrame:
    candidates = list(dict.fromkeys([spec.symbol_code, *spec.candidate_symbols]))
    rows: list[dict[str, Any]] = []
    for code in candidates[:8]:
        try:
            symbol = _symbol_by_code(code)
            history = _slice_window(load_price_data(symbol), spec.window)
            if len(history) < 120:
                continue
            variant = StrategyVariant(
                name="候选策略",
                family=spec.family,
                risk_profile=spec.risk_profile,
                enhanced=spec.enhanced,
                description="候选池同策略横向回测。",
            )
            summary, _curves, _backtests = compare_variants(history, [variant], spec.risk_profile)
            row = summary.iloc[0].to_dict()
            benchmark_code, benchmark_return = _selected_benchmark_return(code, spec.window)
            row.update(
                {
                    "标的": symbol.code,
                    "名称": symbol.name,
                    "市场": symbol.market,
                    "行业": symbol.category,
                    "对照基准": benchmark_code,
                    "行业基准收益": benchmark_return,
                    "相对行业超额": float(row.get("累计收益", 0.0)) - benchmark_return,
                }
            )
            rows.append(row)
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    sort_cols = [col for col in ["综合评分", "相对行业超额", "夏普比率"] if col in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=False).reset_index(drop=True)
    df["推荐"] = ["高" if idx == 0 else "中" if idx < 3 else "观察" for idx in range(len(df))]
    return df


def run_backtest_from_spec(spec: BacktestSpec) -> dict[str, Any]:
    symbol = _symbol_by_code(spec.symbol_code)
    benchmark = _symbol_by_code(spec.benchmark_code)
    history = _slice_window(load_price_data(symbol), spec.window)
    benchmark_history = _slice_window(load_price_data(benchmark), spec.window)

    variants = [
        StrategyVariant(
            name="当前策略",
            family=spec.family,
            risk_profile=spec.risk_profile,
            enhanced=spec.enhanced,
            description="由智塔把对话策略映射到确定性回测参数。",
        ),
        StrategyVariant(
            name="风控对照",
            family=spec.family,
            risk_profile=spec.risk_profile,
            enhanced=not spec.enhanced,
            description="同一策略族的风控开关对照。",
        ),
    ]
    summary, curves, backtests = compare_variants(history, variants, spec.risk_profile)

    benchmark_curve = benchmark_history[["date", "return"]].copy()
    benchmark_curve["benchmark_equity"] = (1 + benchmark_curve["return"]).cumprod()
    curves = curves.merge(benchmark_curve[["date", "benchmark_equity"]], on="date", how="left")
    curves["选定基准"] = curves["benchmark_equity"].ffill().bfill()
    curves = curves.drop(columns=["benchmark_equity"])

    return {
        "symbol": symbol,
        "benchmark": benchmark,
        "spec": spec,
        "summary": summary,
        "curves": curves,
        "backtests": backtests,
        "candidate_pool": run_candidate_pool_backtest(spec),
    }


def summarize_result_for_user(result: dict[str, Any]) -> str:
    summary = result["summary"]
    best = summary.iloc[0]
    spec: BacktestSpec = result["spec"]
    return (
        f"这轮回测使用 {result['symbol'].name}，基准是 {result['benchmark'].name}，"
        f"窗口为{spec.window}。当前评分最高的是 {best['方案']}，"
        f"累计收益 {format_pct(float(best['累计收益']))}，"
        f"最大回撤 {format_pct(float(best['最大回撤']))}，"
        f"超额收益 {format_pct(float(best['超额收益']))}。"
    )


def analyze_backtest_result(
    result: dict[str, Any],
    prototype: StrategyPrototype,
    llm: LLMClient | None = None,
) -> str:
    fallback = summarize_result_for_user(result)
    if llm is None:
        return fallback

    summary_records = result["summary"].to_dict(orient="records")
    spec: BacktestSpec = result["spec"]
    system_prompt = (
        "你是量化策略回测分析助手。你只解释回测结果，不承诺收益，不给实盘买卖指令。"
        "用普通用户能理解的话说明收益、回撤、超额收益和下一步该验证什么。只返回 JSON。"
    )
    factor_blend = result.get("factor_blend", {})
    user_prompt = (
        f"策略雏形：{json.dumps(prototype.as_dict(), ensure_ascii=False)}\n"
        f"因子组合：{json.dumps(factor_blend, ensure_ascii=False)}\n"
        f"回测参数：{json.dumps(spec.as_dict(), ensure_ascii=False)}\n"
        f"回测摘要：{json.dumps(summary_records, ensure_ascii=False, default=str)}\n\n"
        '返回 JSON：{"analysis":"不超过 180 字的分析"}'
    )
    try:
        raw = llm.complete_json(system_prompt, user_prompt)
    except Exception:
        return fallback
    return str(raw.get("analysis") or fallback)
