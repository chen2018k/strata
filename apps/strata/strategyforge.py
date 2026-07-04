from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = Path(os.getenv("STRATA_DATASET_DIR", WORKSPACE_ROOT / "local_data" / "DATASET"))

RiskProfile = Literal["保守", "均衡", "进取"]
StrategyFamily = Literal["趋势跟踪", "均值回归", "布林带反转", "多策略投票", "基础模板"]


@dataclass(frozen=True)
class SymbolInfo:
    code: str
    name: str
    market: str
    category: str
    file: str
    rows: int
    start: str
    end: str
    source: str

    @property
    def label(self) -> str:
        return f"{self.code} {self.name} · {self.category}"


@dataclass(frozen=True)
class StrategyCard:
    family: StrategyFamily
    hypothesis: str
    entry_rule: str
    exit_rule: str
    risk_rule: str
    benchmark: str
    questions: list[str]
    enhancements: list[str]


@dataclass(frozen=True)
class StrategyVariant:
    name: str
    family: StrategyFamily
    risk_profile: RiskProfile
    enhanced: bool
    description: str


def load_symbols(dataset_dir: Path = DATASET_DIR) -> list[SymbolInfo]:
    metadata_path = dataset_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing dataset metadata: {metadata_path}")
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    return [SymbolInfo(**item) for item in payload.get("symbols", [])]


def load_price_data(symbol: SymbolInfo, dataset_dir: Path = DATASET_DIR) -> pd.DataFrame:
    path = dataset_dir / symbol.file
    df = pd.read_csv(path, encoding="utf-8-sig")
    numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pct_change", "change", "turnover"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
    df["return"] = df["close"].pct_change().fillna(0.0)
    return df


def classify_idea(idea: str, fallback: StrategyFamily = "基础模板") -> StrategyFamily:
    text = idea.lower()
    vote_keywords = ["稳健", "确认", "综合", "多策略", "投票", "不要太大", "降低回撤"]
    bollinger_keywords = ["布林", "区间", "震荡", "下轨", "上轨", "band", "boll"]
    reversion_keywords = ["反弹", "超跌", "跌多", "回归", "低估", "修复", "rsi", "抄底", "恐慌"]
    trend_keywords = ["趋势", "突破", "强势", "上穿", "新高", "动量", "继续涨", "均线", "顺势"]
    if any(keyword in text for keyword in vote_keywords):
        return "多策略投票"
    if any(keyword in text for keyword in bollinger_keywords):
        return "布林带反转"
    if any(keyword in text for keyword in reversion_keywords):
        return "均值回归"
    if any(keyword in text for keyword in trend_keywords):
        return "趋势跟踪"
    return fallback


def risk_parameters(risk_profile: RiskProfile) -> dict[str, float | int]:
    if risk_profile == "保守":
        return {"position": 0.55, "stop_loss": 0.07, "vol_quantile": 0.68, "cooldown": 7, "cost_bps": 8}
    if risk_profile == "进取":
        return {"position": 1.0, "stop_loss": 0.16, "vol_quantile": 0.88, "cooldown": 2, "cost_bps": 5}
    return {"position": 0.75, "stop_loss": 0.11, "vol_quantile": 0.78, "cooldown": 4, "cost_bps": 6}


def build_strategy_card(idea: str, risk_profile: RiskProfile, family: StrategyFamily | None = None) -> StrategyCard:
    selected_family = family or classify_idea(idea)
    questions = [
        "目标标的是宽基 ETF、行业 ETF，还是个股？",
        "你希望持有几天、几周，还是几个月？",
        "你更在意少亏，还是更愿意承担波动换取收益？",
        "你希望靠趋势延续赚钱，还是靠超跌反弹赚钱？",
    ]
    common_enhancements = [
        f"按“{risk_profile}”风险偏好设置仓位、止损和波动率过滤。",
        "加入买入持有基准，避免只看策略自身收益。",
        "加入交易成本，避免回测结果过度理想化。",
    ]
    if selected_family == "趋势跟踪":
        return StrategyCard(
            family="趋势跟踪",
            hypothesis="如果一个标的已经形成上行趋势，短期强势可能延续；策略应顺势持有，跌破趋势时退出。",
            entry_rule="20 日均线上穿或高于 60 日均线时入场。",
            exit_rule="20 日均线跌破 60 日均线时离场。",
            risk_rule="高波动时降低仓位；单笔回撤超过止损阈值后触发冷却期。",
            benchmark="同一标的买入并持有。",
            questions=questions,
            enhancements=["加入成交量确认，过滤弱突破。", "加入波动率降仓，避免高波动追涨。", *common_enhancements],
        )
    if selected_family == "均值回归":
        return StrategyCard(
            family="均值回归",
            hypothesis="如果价格短期下跌过快，市场可能出现修复；策略应在超跌时试探入场，在修复或过热时退出。",
            entry_rule="RSI 低于 30 时入场。",
            exit_rule="RSI 高于 55 或达到最大持有期时退出。",
            risk_rule="高波动时降低仓位；跌破止损阈值后退出并等待冷却。",
            benchmark="同一标的买入并持有。",
            questions=questions,
            enhancements=["加入最大持有期，避免长期套牢。", "加入趋势过滤，避免逆大趋势抄底。", *common_enhancements],
        )
    if selected_family == "布林带反转":
        return StrategyCard(
            family="布林带反转",
            hypothesis="如果价格短期跌破正常波动区间，可能存在修复机会；策略应在下轨附近试探入场，在回到中轨或上轨附近退出。",
            entry_rule="收盘价跌破 20 日布林带下轨时入场。",
            exit_rule="价格回到 20 日均线以上，或触及布林带上轨时退出。",
            risk_rule="高波动时降低仓位；如果跌破入场价较多则止损，并进入冷却期。",
            benchmark="同一标的买入并持有。",
            questions=questions,
            enhancements=["加入均线趋势过滤，避免接连续下跌飞刀。", "加入最大持有期，避免反转迟迟不出现。", *common_enhancements],
        )
    if selected_family == "多策略投票":
        return StrategyCard(
            family="多策略投票",
            hypothesis="单一指标容易误判；趋势、RSI、布林带三个信号中至少两个支持时再入场，可以提升信号确认度。",
            entry_rule="趋势、RSI、布林带三个子信号中至少两个为买入时入场。",
            exit_rule="投票信号不足，或触发止损/高波动风控时退出。",
            risk_rule="按用户风险偏好控制仓位；高波动时自动减半；连续亏损后等待冷却。",
            benchmark="同一标的买入并持有。",
            questions=questions,
            enhancements=["自动把用户想法拆成多个可验证子信号。", "用信号投票减少单一指标误判。", *common_enhancements],
        )
    return StrategyCard(
        family="基础模板",
        hypothesis="用户暂时没有明确策略想法时，系统用趋势和均值回归两个基础模板建立第一版研究对照。",
        entry_rule="同时生成双均线趋势策略和 RSI 均值回归策略。",
        exit_rule="按各自模板退出，并与买入持有对照。",
        risk_rule="统一加入仓位控制、交易成本、止损、波动率过滤。",
        benchmark="同一标的买入并持有。",
        questions=questions,
        enhancements=["生成两个基础策略，帮助用户从结果中选择方向。", *common_enhancements],
    )


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def bollinger_bands(close: pd.Series, window: int = 20, width: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = middle + width * std
    lower = middle - width * std
    return lower, middle, upper


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    drawdown = equity / peak - 1
    return float(drawdown.min())


def sharpe_ratio(returns: pd.Series, periods: int = 252) -> float:
    std = returns.std()
    if std == 0 or np.isnan(std):
        return 0.0
    return float((returns.mean() / std) * np.sqrt(periods))


def build_signals(df: pd.DataFrame, family: StrategyFamily, enhanced: bool, risk_profile: RiskProfile) -> pd.Series:
    close = df["close"]
    params = risk_parameters(risk_profile)
    position_size = float(params["position"])
    stop_loss = float(params["stop_loss"])
    cooldown_days = int(params["cooldown"])

    if family == "趋势跟踪":
        base_signal = (close.rolling(20).mean() > close.rolling(60).mean()).astype(float)
    elif family == "均值回归":
        rsi_value = rsi(close)
        base_signal = pd.Series(0.0, index=df.index)
        holding = False
        hold_days = 0
        for idx in range(len(df)):
            if not holding and rsi_value.iloc[idx] < 30:
                holding = True
                hold_days = 0
            elif holding and (rsi_value.iloc[idx] > 55 or hold_days >= 20):
                holding = False
                hold_days = 0
            base_signal.iloc[idx] = 1.0 if holding else 0.0
            if holding:
                hold_days += 1
    elif family == "布林带反转":
        lower, middle, upper = bollinger_bands(close)
        base_signal = pd.Series(0.0, index=df.index)
        holding = False
        hold_days = 0
        for idx in range(len(df)):
            price = close.iloc[idx]
            if not holding and price < lower.iloc[idx]:
                holding = True
                hold_days = 0
            elif holding and (price > middle.iloc[idx] or price > upper.iloc[idx] or hold_days >= 18):
                holding = False
                hold_days = 0
            base_signal.iloc[idx] = 1.0 if holding else 0.0
            if holding:
                hold_days += 1
    elif family == "多策略投票":
        lower, middle, _upper = bollinger_bands(close)
        trend_signal = (close.rolling(20).mean() > close.rolling(60).mean()).astype(float)
        rsi_signal = (rsi(close) < 35).astype(float)
        boll_signal = (close < lower).astype(float)
        base_signal = ((trend_signal + rsi_signal + boll_signal) >= 2).astype(float)
    else:
        trend = (close.rolling(20).mean() > close.rolling(60).mean()).astype(float)
        rsi_signal = (rsi(close) < 35).astype(float)
        base_signal = ((trend + rsi_signal) >= 1).astype(float)

    signal = base_signal * position_size
    if not enhanced:
        return signal.fillna(0.0)

    volatility = df["return"].rolling(20).std().fillna(0.0)
    threshold = volatility.quantile(float(params["vol_quantile"]))
    signal = signal.where(volatility <= threshold, signal * 0.5)

    protected = signal.copy()
    entry_price = 0.0
    cooldown = 0
    in_position = False
    for idx in range(len(df)):
        desired = float(signal.iloc[idx])
        price = float(close.iloc[idx])
        if cooldown > 0:
            protected.iloc[idx] = 0.0
            cooldown -= 1
            in_position = False
            continue
        if desired > 0 and not in_position:
            entry_price = price
            in_position = True
        if in_position and entry_price > 0 and price / entry_price - 1 <= -stop_loss:
            protected.iloc[idx] = 0.0
            in_position = False
            cooldown = cooldown_days
            continue
        if desired == 0:
            in_position = False
        protected.iloc[idx] = desired
    return protected.fillna(0.0)


def backtest(df: pd.DataFrame, family: StrategyFamily, enhanced: bool, risk_profile: RiskProfile) -> pd.DataFrame:
    result = df[["date", "close", "return"]].copy()
    signal = build_signals(df, family, enhanced=enhanced, risk_profile=risk_profile)
    position = signal.shift(1).fillna(0.0)
    cost_bps = float(risk_parameters(risk_profile)["cost_bps"])
    turnover = position.diff().abs().fillna(position.abs())
    cost = turnover * cost_bps / 10000
    result["position"] = position
    result["signal"] = signal
    result["strategy_return"] = position * result["return"] - cost
    result["equity"] = (1 + result["strategy_return"]).cumprod()
    result["benchmark_equity"] = (1 + result["return"]).cumprod()
    result["drawdown"] = result["equity"] / result["equity"].cummax() - 1
    result["trade"] = turnover > 0
    result["entry"] = (position > 0) & (position.shift(1).fillna(0.0) == 0)
    result["exit"] = (position == 0) & (position.shift(1).fillna(0.0) > 0)
    return result


def summarize_backtest(bt: pd.DataFrame) -> dict[str, float | int]:
    total_return = float(bt["equity"].iloc[-1] - 1)
    benchmark_return = float(bt["benchmark_equity"].iloc[-1] - 1)
    daily = bt["strategy_return"]
    wins = daily[daily != 0] > 0
    return {
        "累计收益": total_return,
        "基准收益": benchmark_return,
        "超额收益": total_return - benchmark_return,
        "最大回撤": max_drawdown(bt["equity"]),
        "夏普比率": sharpe_ratio(daily),
        "交易次数": int(bt["trade"].sum()),
        "胜率": float(wins.mean()) if len(wins) else 0.0,
        "持仓天数占比": float((bt["position"] > 0).mean()),
    }


def score_summary(summary: dict[str, float | int], preferred_risk: RiskProfile) -> dict[str, float]:
    total_return = float(summary["累计收益"])
    max_dd = abs(float(summary["最大回撤"]))
    sharpe = float(summary["夏普比率"])
    trade_count = int(summary["交易次数"])
    holding_ratio = float(summary["持仓天数占比"])

    return_score = float(np.clip(50 + total_return * 120, 0, 100))
    drawdown_score = float(np.clip(100 - max_dd * 260, 0, 100))
    stability_score = float(np.clip(45 + sharpe * 22, 0, 100))
    cost_score = float(np.clip(100 - trade_count * 0.75, 0, 100))
    activity_score = float(np.clip(100 - abs(holding_ratio - 0.45) * 120, 0, 100))

    if preferred_risk == "保守":
        fit_score = 0.45 * drawdown_score + 0.25 * stability_score + 0.15 * cost_score + 0.15 * return_score
    elif preferred_risk == "进取":
        fit_score = 0.45 * return_score + 0.2 * stability_score + 0.2 * drawdown_score + 0.15 * activity_score
    else:
        fit_score = 0.3 * return_score + 0.3 * drawdown_score + 0.25 * stability_score + 0.15 * cost_score

    composite = 0.28 * return_score + 0.25 * drawdown_score + 0.22 * stability_score + 0.12 * cost_score + 0.13 * fit_score
    return {
        "收益分": round(return_score, 1),
        "回撤分": round(drawdown_score, 1),
        "稳定性分": round(stability_score, 1),
        "成本分": round(cost_score, 1),
        "目标适配分": round(float(fit_score), 1),
        "综合评分": round(float(composite), 1),
    }


def build_strategy_variants(idea: str, risk_profile: RiskProfile, base_family: StrategyFamily | None = None) -> list[StrategyVariant]:
    detected = base_family or classify_idea(idea)
    if detected == "基础模板":
        detected = "趋势跟踪"

    variants: list[StrategyVariant] = [
        StrategyVariant(
            name="用户想法基础版",
            family=detected,
            risk_profile=risk_profile,
            enhanced=False,
            description="尽量保留用户原始想法，只做最小规则化，用来当作对照组。",
        ),
        StrategyVariant(
            name="Agent 风控增强版",
            family=detected,
            risk_profile=risk_profile,
            enhanced=True,
            description="在原始思路上加入仓位、止损、波动率过滤和交易成本。",
        ),
        StrategyVariant(
            name="稳健多策略投票版",
            family="多策略投票",
            risk_profile="保守" if risk_profile != "进取" else "均衡",
            enhanced=True,
            description="用趋势、RSI、布林带多个信号交叉确认，降低单一指标误判。",
        ),
    ]

    if detected != "均值回归":
        variants.append(
            StrategyVariant(
                name="反转备选版",
                family="均值回归",
                risk_profile=risk_profile,
                enhanced=True,
                description="提供一个相反风格的备选方案，检验当前标的更适合趋势还是反转。",
            )
        )
    if detected != "趋势跟踪":
        variants.append(
            StrategyVariant(
                name="趋势备选版",
                family="趋势跟踪",
                risk_profile=risk_profile,
                enhanced=True,
                description="提供一个趋势风格的备选方案，作为反转思路的对照。",
            )
        )
    if detected != "布林带反转":
        variants.append(
            StrategyVariant(
                name="布林带边界版",
                family="布林带反转",
                risk_profile=risk_profile,
                enhanced=True,
                description="用价格偏离波动区间来捕捉短期修复机会。",
            )
        )
    return variants


def compare_strategies(df: pd.DataFrame, card: StrategyCard, risk_profile: RiskProfile) -> tuple[pd.DataFrame, pd.DataFrame]:
    families = ["趋势跟踪", "均值回归"] if card.family == "基础模板" else [card.family]
    rows = []
    curves = pd.DataFrame({"date": df["date"], "买入持有基准": (1 + df["return"]).cumprod()})
    for family in families:
        for enhanced in [False, True]:
            label = f"{family}{'增强版' if enhanced else '基础版'}"
            bt = backtest(df, family, enhanced=enhanced, risk_profile=risk_profile)
            curves[label] = bt["equity"]
            summary = summarize_backtest(bt)
            rows.append({"方案": label, **summary})
    summary_df = pd.DataFrame(rows)
    return summary_df, curves


def compare_variants(
    df: pd.DataFrame,
    variants: list[StrategyVariant],
    preferred_risk: RiskProfile,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    rows = []
    curves = pd.DataFrame({"date": df["date"], "买入持有基准": (1 + df["return"]).cumprod()})
    backtests: dict[str, pd.DataFrame] = {}
    for variant in variants:
        bt = backtest(df, variant.family, enhanced=variant.enhanced, risk_profile=variant.risk_profile)
        summary = summarize_backtest(bt)
        scores = score_summary(summary, preferred_risk)
        rows.append(
            {
                "方案": variant.name,
                "策略类型": variant.family,
                "风险档位": variant.risk_profile,
                "是否增强": "是" if variant.enhanced else "否",
                "说明": variant.description,
                **summary,
                **scores,
            }
        )
        curves[variant.name] = bt["equity"]
        backtests[variant.name] = bt
    summary_df = pd.DataFrame(rows).sort_values("综合评分", ascending=False).reset_index(drop=True)
    return summary_df, curves, backtests


def format_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def generate_report(
    idea: str,
    symbol_name: str,
    card: StrategyCard,
    risk_profile: RiskProfile,
    summary_df: pd.DataFrame,
) -> str:
    best = summary_df.sort_values(["最大回撤", "累计收益"], ascending=[False, False]).iloc[0]
    highest = summary_df.sort_values("累计收益", ascending=False).iloc[0]
    return (
        f"用户想法：{idea or '用户没有明确想法，系统使用基础策略模板。'}\n\n"
        f"标的：{symbol_name}\n"
        f"策略类型：{card.family}\n"
        f"风险偏好：{risk_profile}\n\n"
        f"系统将想法转化为策略假设：{card.hypothesis}\n\n"
        f"收益最高方案是“{highest['方案']}”，累计收益 {format_pct(float(highest['累计收益']))}，"
        f"最大回撤 {format_pct(float(highest['最大回撤']))}。\n"
        f"风险更平衡的候选方案是“{best['方案']}”，累计收益 {format_pct(float(best['累计收益']))}，"
        f"最大回撤 {format_pct(float(best['最大回撤']))}，夏普比率 {float(best['夏普比率']):.2f}。\n\n"
        "下一轮建议：如果收益好但回撤过大，应降低仓位或加入波动率过滤；"
        "如果交易次数过多，应增加信号冷却期；如果策略跑不赢买入持有，应重新检查市场假设。"
        "本系统仅用于策略研究和模拟展示，不构成投资建议。"
    )


def generate_variant_report(
    idea: str,
    symbol_name: str,
    risk_profile: RiskProfile,
    summary_df: pd.DataFrame,
) -> str:
    top = summary_df.iloc[0]
    highest = summary_df.sort_values("累计收益", ascending=False).iloc[0]
    safest = summary_df.sort_values(["最大回撤", "综合评分"], ascending=[False, False]).iloc[0]
    baseline_comment = "跑赢" if float(top["超额收益"]) > 0 else "没有跑赢"
    return (
        f"用户原始想法：{idea or '用户未提供明确想法，系统使用基础策略模板。'}\n\n"
        f"研究标的：{symbol_name}\n"
        f"用户风险偏好：{risk_profile}\n\n"
        f"Agent 先把想法拆成候选策略，再生成多个版本进行对照。当前综合评分最高的是“{top['方案']}”，"
        f"策略类型为“{top['策略类型']}”，综合评分 {float(top['综合评分']):.1f}。"
        f"它相对买入持有基准{baseline_comment}，累计收益 {format_pct(float(top['累计收益']))}，"
        f"最大回撤 {format_pct(float(top['最大回撤']))}，夏普比率 {float(top['夏普比率']):.2f}。\n\n"
        f"收益最高的是“{highest['方案']}”，累计收益 {format_pct(float(highest['累计收益']))}；"
        f"回撤控制较好的是“{safest['方案']}”，最大回撤 {format_pct(float(safest['最大回撤']))}。\n\n"
        "下一轮优化建议：\n"
        "1. 如果用户更看重收益，可以从收益最高方案出发，逐步加入止损和波动率过滤。\n"
        "2. 如果用户更看重少亏，应优先选择综合评分和回撤分更高的方案，而不是只看累计收益。\n"
        "3. 如果所有方案都跑不赢基准，说明当前市场假设可能不适合这个标的，应换标的、换周期或换策略大类。\n\n"
        "边界声明：这是策略研究和模拟回测结果，不构成投资建议，不承诺未来收益。"
    )


def trade_points(bt: pd.DataFrame) -> pd.DataFrame:
    points = bt.loc[bt["entry"] | bt["exit"], ["date", "close", "entry", "exit"]].copy()
    points["动作"] = np.where(points["entry"], "买入", "卖出")
    points["价格"] = points["close"]
    return points[["date", "动作", "价格"]]


def smoke_test() -> dict[str, object]:
    symbols = load_symbols()
    symbol = symbols[0]
    df = load_price_data(symbol)
    card = build_strategy_card("我想做一个稳健的趋势策略", "均衡")
    summary, curves = compare_strategies(df, card, "均衡")
    return {
        "symbols": len(symbols),
        "first_symbol": symbol.label,
        "rows": len(df),
        "summary_rows": len(summary),
        "curve_columns": list(curves.columns),
        "best_total_return": float(summary["累计收益"].max()),
    }


if __name__ == "__main__":
    print(json.dumps(smoke_test(), ensure_ascii=False, indent=2))
