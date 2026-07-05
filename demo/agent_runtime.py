from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

try:
    from strategyforge import (
        RiskProfile,
        StrategyCard,
        StrategyFamily,
        StrategyVariant,
        SymbolInfo,
        build_signals,
        build_strategy_card,
        build_strategy_variants,
        classify_idea,
        compare_variants,
        load_price_data,
        load_symbols,
    )
except ModuleNotFoundError:
    from .strategyforge import (
        RiskProfile,
        StrategyCard,
        StrategyFamily,
        StrategyVariant,
        SymbolInfo,
        build_signals,
        build_strategy_card,
        build_strategy_variants,
        classify_idea,
        compare_variants,
        load_price_data,
        load_symbols,
    )


VALID_FAMILIES: set[StrategyFamily] = {"趋势跟踪", "均值回归", "布林带反转", "多策略投票", "基础模板"}
VALID_RISK_PROFILES: set[RiskProfile] = {"保守", "均衡", "进取"}


@dataclass(frozen=True)
class AgentContext:
    idea: str
    industry_observation: str = ""
    naive_strategy: str = ""
    symbol: str | None = None
    horizon: str = "中期：1-3 个月"
    risk_profile: RiskProfile = "均衡"
    goal: str = "控制回撤，同时争取跑赢买入持有基准"
    answers: dict[str, str] | None = None

    def research_brief(self) -> str:
        return (
            f"用户想法：{self.idea or '未提供明确想法'}\n"
            f"行业观察：{self.industry_observation or '未补充'}\n"
            f"朴素策略：{self.naive_strategy or '未补充'}\n"
            f"标的：{self.symbol or '未指定'}\n"
            f"周期：{self.horizon}\n"
            f"风险偏好：{self.risk_profile}\n"
            f"目标：{self.goal}\n"
            f"补充回答：{self.answers or {}}"
        )


@dataclass(frozen=True)
class AgentDraft:
    reply: str
    family: StrategyFamily
    card: StrategyCard
    variants: list[StrategyVariant]
    source: str
    questions: list[str]
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class LiveSignal:
    date: str
    strategy_name: str
    family: StrategyFamily
    target_position: float
    current_position: float
    action: str
    close: float


@dataclass(frozen=True)
class LiveValidationResult:
    signal: LiveSignal
    bars_used: int
    data_start: str
    data_end: str
    status: str


class LLMClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        ...


class MarketDataProvider(Protocol):
    def symbols(self) -> list[SymbolInfo]:
        ...

    def history(self, symbol: SymbolInfo) -> pd.DataFrame:
        ...


class LiveDataProvider(Protocol):
    def latest_bars(self, symbol: SymbolInfo, lookback: int = 260) -> pd.DataFrame:
        ...


class ExecutionGateway(Protocol):
    def submit_target_position(self, symbol: SymbolInfo, target_position: float, reason: str) -> dict[str, Any]:
        ...


class LocalDatasetProvider:
    def symbols(self) -> list[SymbolInfo]:
        return load_symbols()

    def history(self, symbol: SymbolInfo) -> pd.DataFrame:
        return load_price_data(symbol)


class OpenAICompatibleClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "OpenAICompatibleClient | None":
        load_local_env()
        api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        base_url = (
            os.getenv("LLM_BASE_URL")
            or os.getenv("DEEPSEEK_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        )
        default_model = "deepseek-v4-flash" if "deepseek" in base_url else "gpt-4.1-mini"
        model = os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL") or os.getenv("OPENAI_MODEL") or default_model
        return cls(api_key=api_key, model=model, base_url=base_url)

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc

        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("LLM response must be a JSON object")
        return parsed


class PaperExecutionGateway:
    def submit_target_position(self, symbol: SymbolInfo, target_position: float, reason: str) -> dict[str, Any]:
        return {
            "status": "paper_only",
            "symbol": symbol.code,
            "target_position": target_position,
            "reason": reason,
        }


def has_llm_env() -> bool:
    load_local_env()
    return bool(os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))


def load_local_env() -> None:
    for path in (Path(__file__).resolve().parent / ".env.local", Path(__file__).resolve().parent.parent / ".env.local"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if not item or item.startswith("#") or "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def co_create_strategy(context: AgentContext, llm: LLMClient | None = None) -> AgentDraft:
    fallback_family = classify_idea(context.research_brief())
    fallback_card = build_strategy_card(context.research_brief(), context.risk_profile, fallback_family)
    fallback_variants = build_strategy_variants(context.research_brief(), context.risk_profile, fallback_family)

    if llm is None:
        return AgentDraft(
            reply="我会先把想法整理成可检验的策略，再用历史数据验证。",
            family=fallback_family,
            card=fallback_card,
            variants=fallback_variants,
            source="rules",
            questions=fallback_card.questions,
        )

    system_prompt = (
        "你是交易策略共创 Agent。你的任务是把用户的模糊投资想法整理成可回测的研究假设。"
        "只输出 JSON，不给投资建议，不承诺收益。"
        "family 必须是：趋势跟踪、均值回归、布林带反转、多策略投票、基础模板 之一。"
        "risk_profile 必须是：保守、均衡、进取 之一。"
    )
    user_prompt = (
        f"{context.research_brief()}\n\n"
        "返回 JSON 字段：reply, family, risk_profile, key_questions, assumptions。"
        "reply 用一句话说明下一步如何验证；key_questions 最多 4 个。"
    )
    raw = llm.complete_json(system_prompt, user_prompt)
    family = raw.get("family") if raw.get("family") in VALID_FAMILIES else fallback_family
    risk = raw.get("risk_profile") if raw.get("risk_profile") in VALID_RISK_PROFILES else context.risk_profile
    card = build_strategy_card(context.research_brief(), risk, family)
    variants = build_strategy_variants(context.research_brief(), risk, family)
    questions = raw.get("key_questions") if isinstance(raw.get("key_questions"), list) else card.questions

    return AgentDraft(
        reply=str(raw.get("reply") or "我会把这个想法转成策略规则，并立刻做历史验证。"),
        family=family,
        card=card,
        variants=variants,
        source="llm",
        questions=[str(item) for item in questions[:4]],
        raw=raw,
    )


def run_research(
    context: AgentContext,
    symbol: SymbolInfo,
    data_provider: MarketDataProvider | None = None,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    provider = data_provider or LocalDatasetProvider()
    draft = co_create_strategy(context, llm)
    history = provider.history(symbol)
    summary, curves, backtests = compare_variants(history, draft.variants, context.risk_profile)
    best_name = str(summary.iloc[0]["方案"])
    live_signal = generate_live_signal(history, next(v for v in draft.variants if v.name == best_name))
    return {
        "draft": draft,
        "summary": summary,
        "curves": curves,
        "backtests": backtests,
        "live_signal": live_signal,
    }


def slice_history_window(
    df: pd.DataFrame,
    window: str = "全部",
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    result = df.copy()
    if start:
        result = result[result["date"] >= pd.to_datetime(start)]
    if end:
        result = result[result["date"] <= pd.to_datetime(end)]

    if window == "近6个月":
        result = result.tail(126)
    elif window == "近1年":
        result = result.tail(252)
    elif window == "近3年":
        result = result.tail(756)
    elif window == "近5年":
        result = result.tail(1260)

    return result.reset_index(drop=True)


def generate_live_signal(
    df: pd.DataFrame,
    variant: StrategyVariant,
    current_position: float = 0.0,
) -> LiveSignal:
    signal = build_signals(df, variant.family, enhanced=variant.enhanced, risk_profile=variant.risk_profile)
    target = float(signal.iloc[-1])
    latest = df.iloc[-1]
    delta = target - current_position
    if abs(delta) < 0.01:
        action = "保持"
    elif target <= 0:
        action = "空仓"
    elif delta > 0:
        action = "提高仓位"
    else:
        action = "降低仓位"

    return LiveSignal(
        date=str(pd.to_datetime(latest["date"]).date()),
        strategy_name=variant.name,
        family=variant.family,
        target_position=round(target, 4),
        current_position=round(current_position, 4),
        action=action,
        close=float(latest["close"]),
    )


def validate_on_live_data(
    provider: LiveDataProvider,
    symbol: SymbolInfo,
    variant: StrategyVariant,
    lookback: int = 260,
    current_position: float = 0.0,
) -> LiveValidationResult:
    bars = provider.latest_bars(symbol, lookback=lookback)
    if len(bars) < 80:
        raise ValueError("not enough live bars to validate the strategy")
    signal = generate_live_signal(bars, variant, current_position=current_position)
    return LiveValidationResult(
        signal=signal,
        bars_used=len(bars),
        data_start=str(pd.to_datetime(bars.iloc[0]["date"]).date()),
        data_end=str(pd.to_datetime(bars.iloc[-1]["date"]).date()),
        status="paper_validation",
    )
