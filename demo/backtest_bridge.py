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
        StrategyParams,
        StrategyFamily,
        StrategyVariant,
        compare_variants,
        format_pct,
        load_price_data,
        load_symbols,
        score_summary,
        summarize_backtest,
        backtest,
    )
except ModuleNotFoundError:
    from .agent_runtime import LLMClient
    from .factor_library import factor_blend_payload, load_base_factors
    from .interview_agent import StrategyPrototype
    from .market_data import load_universe, preferred_benchmarks
    from .strategyforge import (
        RiskProfile,
        StrategyParams,
        StrategyFamily,
        StrategyVariant,
        compare_variants,
        format_pct,
        load_price_data,
        load_symbols,
        score_summary,
        summarize_backtest,
        backtest,
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
    candidate_reasons: tuple[tuple[str, str], ...] = ()
    fast_ma: int = 20
    slow_ma: int = 60
    rsi_entry: float = 30.0
    rsi_exit: float = 55.0
    max_hold_days: int = 20
    stop_loss: float | None = None
    cost_bps: float | None = None

    def as_dict(self) -> dict[str, Any]:
        candidate_payload: list[str | dict[str, str]]
        if self.candidate_reasons:
            candidate_payload = [{"symbol": symbol, "reason": reason} for symbol, reason in self.candidate_reasons]
        else:
            candidate_payload = list(self.candidate_symbols)
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
            "candidate_symbols": candidate_payload,
            "strategy_params": {
                "fast_ma": self.fast_ma,
                "slow_ma": self.slow_ma,
                "rsi_entry": self.rsi_entry,
                "rsi_exit": self.rsi_exit,
                "max_hold_days": self.max_hold_days,
                "stop_loss": self.stop_loss,
                "cost_bps": self.cost_bps,
            },
        }

    def strategy_params(self) -> StrategyParams:
        return StrategyParams(
            fast_ma=self.fast_ma,
            slow_ma=self.slow_ma,
            rsi_entry=self.rsi_entry,
            rsi_exit=self.rsi_exit,
            max_hold_days=self.max_hold_days,
            stop_loss=self.stop_loss,
            cost_bps=self.cost_bps,
        )


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


DEFAULT_CANDIDATE_REASONS: dict[str, str] = {
    "NVDA": "GPU 与 AI 算力直接受益",
    "AMD": "GPU/CPU 供给替代与 AI 服务器配置升级",
    "AVGO": "AI 网络芯片与定制 ASIC",
    "SMCI": "AI 服务器整机与机柜需求",
    "DELL": "企业服务器与存储出货",
    "ANET": "数据中心高速网络设备",
    "VRT": "数据中心电力与散热",
    "FCX": "铜矿供给和价格弹性",
    "XLB": "材料板块 ETF 对照",
    "CAT": "矿业与工程设备景气",
    "DE": "机械设备与资本开支周期",
    "ETN": "电力设备和电气化需求",
    "GEV": "电网和电力基础设施",
    "XOM": "综合能源龙头",
    "CVX": "油气价格与能源现金流",
    "SLB": "油服资本开支弹性",
    "COP": "上游油气开采暴露",
    "EOG": "页岩油气供给弹性",
    "XLE": "能源行业 ETF 对照",
    "JPM": "大型银行与利率环境",
    "BAC": "零售银行与利率敏感性",
    "WFC": "商业银行周期暴露",
    "GS": "投行和资本市场活跃度",
    "MS": "财富管理与资本市场",
    "XLF": "金融行业 ETF 对照",
    "AMZN": "线上消费与云业务双暴露",
    "WMT": "必选零售需求韧性",
    "COST": "会员制零售与消费韧性",
    "HD": "地产后周期消费",
    "MCD": "餐饮消费与价格传导",
    "SBUX": "可选消费与门店流量",
    "XLY": "可选消费 ETF 对照",
    "LLY": "创新药景气与权重龙头",
    "UNH": "医保服务与防御属性",
    "JNJ": "综合医药防御资产",
    "MRK": "大型药企管线与现金流",
    "ABBV": "医药现金流与管线切换",
    "XLV": "医疗行业 ETF 对照",
    "2800.HK": "恒生指数宽基代表",
    "3033.HK": "港股科技 ETF 代表",
    "EWH": "香港市场 ETF 对照",
    "MCHI": "中国大盘股票 ETF",
    "FXI": "中国大盘龙头 ETF",
    "ES3.SI": "新加坡 STI 宽基代表",
    "CFA.SI": "新加坡宽基 ETF 代表",
    "EWS": "新加坡市场 ETF 对照",
}


def _candidate_reason(symbol_code: str, theme: str) -> str:
    return DEFAULT_CANDIDATE_REASONS.get(symbol_code, f"与 {theme or '用户观察'} 主题相关，可用于横向验证")


def _candidate_reason_pairs(candidates: tuple[str, ...], theme: str) -> tuple[tuple[str, str], ...]:
    return tuple((code, _candidate_reason(code, theme)) for code in candidates)


def _parse_candidate_payload(raw_candidates: Any, codes: set[str], theme: str) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    symbols: list[str] = []
    reasons: list[tuple[str, str]] = []
    if not isinstance(raw_candidates, list):
        return tuple(), tuple()
    for item in raw_candidates:
        if isinstance(item, dict):
            code = str(item.get("symbol") or item.get("code") or "").strip()
            reason = str(item.get("reason") or "").strip()
        else:
            code = str(item).strip()
            reason = ""
        if code in codes and code not in symbols:
            symbols.append(code)
            reasons.append((code, reason or _candidate_reason(code, theme)))
    return tuple(symbols[:10]), tuple(reasons[:10])


def _infer_theme_and_candidates(text: str, fallback_code: str) -> tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]]:
    compact = text.lower()
    available = {item.code for item in load_symbols()}
    for keywords, codes, theme in THEME_CANDIDATES:
        if any(keyword.lower() in compact for keyword in keywords):
            candidates = tuple(code for code in codes if code in available)
            if fallback_code in available and fallback_code not in candidates:
                candidates = (fallback_code, *candidates)
            candidates = candidates[:8]
            return theme, candidates, _candidate_reason_pairs(candidates, theme)
    if fallback_code in available:
        return "User observation", (fallback_code,), _candidate_reason_pairs((fallback_code,), "User observation")
    return "User observation", tuple(), tuple()


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
    theme, candidates, candidate_reasons = _infer_theme_and_candidates(text, picked_symbol)
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
        candidate_reasons=candidate_reasons,
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
        "不能发明策略代码，不能发明标的。候选池要优先从可选标的里选 5-10 个，并说明入选原因。"
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
        "candidate_symbols 可以是字符串数组，也可以是 {symbol, reason} 对象数组。"
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
    candidate_reasons: tuple[tuple[str, str], ...] = fallback.candidate_reasons
    if isinstance(raw_candidates, list):
        parsed_symbols, parsed_reasons = _parse_candidate_payload(raw_candidates, codes, str(raw.get("theme") or fallback.theme))
        candidate_symbols = parsed_symbols or tuple(str(code) for code in raw_candidates if str(code) in codes)[:8]
        if symbol_code in codes and symbol_code not in candidate_symbols:
            candidate_symbols = (symbol_code, *candidate_symbols)[:8]
        candidate_reasons = parsed_reasons or _candidate_reason_pairs(candidate_symbols, str(raw.get("theme") or fallback.theme))
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
        candidate_reasons=candidate_reasons,
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


def _benchmark_curve(symbol_code: str, window: str, column_name: str) -> pd.DataFrame:
    symbol = _symbol_by_code(symbol_code)
    history = _slice_window(load_price_data(symbol), window)
    curve = history[["date", "return"]].copy()
    curve[column_name] = (1 + curve["return"]).cumprod()
    return curve[["date", column_name]]


def run_candidate_pool_backtest(spec: BacktestSpec) -> pd.DataFrame:
    candidates = list(dict.fromkeys([spec.symbol_code, *spec.candidate_symbols]))
    reason_map = {symbol: reason for symbol, reason in spec.candidate_reasons}
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
            summary, _curves, _backtests = compare_variants(history, [variant], spec.risk_profile, strategy_params=spec.strategy_params())
            row = summary.iloc[0].to_dict()
            benchmark_code, benchmark_return = _selected_benchmark_return(code, spec.window)
            row.update(
                {
                    "标的": symbol.code,
                    "名称": symbol.name,
                    "入选理由": reason_map.get(symbol.code, _candidate_reason(symbol.code, spec.theme)),
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


def _walk_forward_param_grid(spec: BacktestSpec) -> list[StrategyParams]:
    ma_pairs = [(spec.fast_ma, spec.slow_ma), (10, 50), (20, 60), (50, 200)]
    rsi_pairs = [(spec.rsi_entry, spec.rsi_exit), (25.0, 60.0), (30.0, 55.0)]
    hold_days = [int(spec.max_hold_days), 20, 40]
    stop_losses = [float(spec.stop_loss or 0.11), 0.07, 0.11, 0.16]
    seen: set[tuple[float, ...]] = set()
    params: list[StrategyParams] = []
    for fast_ma, slow_ma in ma_pairs:
        for rsi_entry, rsi_exit in rsi_pairs:
            for max_hold in hold_days:
                for stop_loss in stop_losses:
                    key = (float(fast_ma), float(slow_ma), float(rsi_entry), float(rsi_exit), float(max_hold), round(stop_loss, 4))
                    if key in seen:
                        continue
                    seen.add(key)
                    params.append(
                        StrategyParams(
                            fast_ma=int(fast_ma),
                            slow_ma=int(slow_ma),
                            rsi_entry=float(rsi_entry),
                            rsi_exit=float(rsi_exit),
                            max_hold_days=int(max_hold),
                            stop_loss=float(stop_loss),
                            cost_bps=spec.cost_bps,
                        )
                    )
                    if len(params) >= 18:
                        return params
    return params


def run_walk_forward_validation(history: pd.DataFrame, spec: BacktestSpec) -> dict[str, Any]:
    if len(history) < 240:
        return {"enabled": False, "reason": "历史数据不足，暂不做 Walk-forward 验证。"}

    split_at = max(120, int(len(history) * 0.7))
    train = history.iloc[:split_at].reset_index(drop=True)
    validate = history.iloc[split_at:].reset_index(drop=True)
    if len(validate) < 60:
        return {"enabled": False, "reason": "验证期太短，暂不做 Walk-forward 验证。"}

    rows: list[dict[str, Any]] = []
    variant = StrategyVariant(
        name="参数候选",
        family=spec.family,
        risk_profile=spec.risk_profile,
        enhanced=spec.enhanced,
        description="Walk-forward 参数候选。",
    )
    for params in _walk_forward_param_grid(spec):
        train_bt = backtest(train, variant.family, variant.enhanced, variant.risk_profile, strategy_params=params)
        summary = summarize_backtest(train_bt)
        scores = score_summary(summary, spec.risk_profile)
        rows.append(
            {
                "fast_ma": params.fast_ma,
                "slow_ma": params.slow_ma,
                "rsi_entry": params.rsi_entry,
                "rsi_exit": params.rsi_exit,
                "max_hold_days": params.max_hold_days,
                "stop_loss": params.stop_loss,
                **summary,
                **scores,
            }
        )

    if not rows:
        return {"enabled": False, "reason": "没有可用参数组合。"}

    train_grid = pd.DataFrame(rows).sort_values("综合评分", ascending=False).reset_index(drop=True)
    best = train_grid.iloc[0]
    best_params = StrategyParams(
        fast_ma=int(best["fast_ma"]),
        slow_ma=int(best["slow_ma"]),
        rsi_entry=float(best["rsi_entry"]),
        rsi_exit=float(best["rsi_exit"]),
        max_hold_days=int(best["max_hold_days"]),
        stop_loss=float(best["stop_loss"]),
        cost_bps=spec.cost_bps,
    )
    train_bt = backtest(train, spec.family, spec.enhanced, spec.risk_profile, strategy_params=best_params)
    validate_bt = backtest(validate, spec.family, spec.enhanced, spec.risk_profile, strategy_params=best_params)
    train_base_summary = summarize_backtest(train_bt)
    validate_base_summary = summarize_backtest(validate_bt)
    train_summary = {**train_base_summary, **score_summary(train_base_summary, spec.risk_profile)}
    validate_summary = {**validate_base_summary, **score_summary(validate_base_summary, spec.risk_profile)}
    report = pd.DataFrame(
        [
            {"阶段": "训练期 70%", **train_summary},
            {"阶段": "验证期 30%", **validate_summary},
        ]
    )
    return {
        "enabled": True,
        "split_date": str(validate["date"].iloc[0]),
        "best_params": {
            "均线": f"{best_params.fast_ma}/{best_params.slow_ma}",
            "RSI": f"{best_params.rsi_entry:.0f}/{best_params.rsi_exit:.0f}",
            "最大持有期": best_params.max_hold_days,
            "止损": best_params.stop_loss,
            "交易成本 bps": best_params.cost_bps,
        },
        "report": report,
        "train_grid": train_grid.head(8),
    }


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
    summary, curves, backtests = compare_variants(history, variants, spec.risk_profile, strategy_params=spec.strategy_params())

    benchmark_curve = benchmark_history[["date", "return"]].copy()
    benchmark_curve["选定基准"] = (1 + benchmark_curve["return"]).cumprod()
    curves = curves.merge(benchmark_curve[["date", "选定基准"]], on="date", how="left")
    if spec.benchmark_code != "SPY":
        try:
            curves = curves.merge(_benchmark_curve("SPY", spec.window, "SPY"), on="date", how="left")
        except Exception:
            pass
    for column in ["选定基准", "SPY"]:
        if column in curves.columns:
            curves[column] = curves[column].ffill().bfill()

    return {
        "symbol": symbol,
        "benchmark": benchmark,
        "spec": spec,
        "summary": summary,
        "curves": curves,
        "backtests": backtests,
        "candidate_pool": run_candidate_pool_backtest(spec),
        "walk_forward": run_walk_forward_validation(history, spec),
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
