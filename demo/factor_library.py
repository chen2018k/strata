from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from interview_agent import StrategyPrototype
    from strategyforge import RiskProfile, StrategyFamily
except ModuleNotFoundError:
    from .interview_agent import StrategyPrototype
    from .strategyforge import RiskProfile, StrategyFamily


FACTOR_LIBRARY_PATH = Path(__file__).resolve().parent / "factor_library.json"


@dataclass(frozen=True)
class BaseFactor:
    id: str
    name: str
    family: StrategyFamily
    description: str
    default_risk: RiskProfile
    enhanced: bool
    tags: tuple[str, ...]


@dataclass(frozen=True)
class UserFactor:
    name: str
    hypothesis: str
    proxy_metrics: tuple[str, ...]
    target_universe: str
    confidence_notes: str


@dataclass(frozen=True)
class FactorBlend:
    base_factor: BaseFactor
    user_factor: UserFactor
    user_weight: float
    reason: str


DEFAULT_BASE_FACTORS: tuple[BaseFactor, ...] = (
    BaseFactor(
        id="trend_ma_20_60",
        name="20/60 日均线趋势",
        family="趋势跟踪",
        description="用 20 日均线和 60 日均线判断中短期趋势。",
        default_risk="均衡",
        enhanced=True,
        tags=("趋势", "均线", "动量", "中期"),
    ),
    BaseFactor(
        id="rsi_reversal_14",
        name="RSI 超跌修复",
        family="均值回归",
        description="用 RSI 识别短期超跌后的修复机会。",
        default_risk="均衡",
        enhanced=True,
        tags=("反转", "RSI", "超跌", "短期"),
    ),
    BaseFactor(
        id="bollinger_reversion_20",
        name="20 日布林带边界",
        family="布林带反转",
        description="用价格偏离正常波动区间来捕捉修复机会。",
        default_risk="均衡",
        enhanced=True,
        tags=("布林带", "波动", "反转", "短期"),
    ),
    BaseFactor(
        id="multi_signal_vote",
        name="趋势/RSI/布林带投票",
        family="多策略投票",
        description="多个基础信号同时确认后才入场，降低单一信号误判。",
        default_risk="保守",
        enhanced=True,
        tags=("多策略", "确认", "稳健", "组合"),
    ),
)


def load_base_factors(path: Path = FACTOR_LIBRARY_PATH) -> list[BaseFactor]:
    if not path.exists():
        return list(DEFAULT_BASE_FACTORS)
    payload = json.loads(path.read_text(encoding="utf-8"))
    factors: list[BaseFactor] = []
    for item in payload.get("factors", []):
        factors.append(
            BaseFactor(
                id=str(item["id"]),
                name=str(item["name"]),
                family=item["family"],
                description=str(item.get("description") or ""),
                default_risk=item.get("default_risk") or "均衡",
                enhanced=bool(item.get("enhanced", True)),
                tags=tuple(str(tag) for tag in item.get("tags", [])),
            )
        )
    return factors or list(DEFAULT_BASE_FACTORS)


def user_factor_from_prototype(prototype: StrategyPrototype, answers: dict[str, str]) -> UserFactor:
    proxy = answers.get("factor_translation") or "用户观察对应的可跟踪代理指标"
    confidence = answers.get("source_quality") or "需要继续确认信息来源和稳定性"
    return UserFactor(
        name=prototype.title,
        hypothesis=prototype.factor_hypothesis,
        proxy_metrics=tuple(item.strip() for item in proxy.replace("、", ",").split(",") if item.strip()),
        target_universe=prototype.target_universe,
        confidence_notes=confidence,
    )


def choose_base_factor(
    user_factor: UserFactor,
    base_factors: list[BaseFactor] | None = None,
) -> BaseFactor:
    factors = base_factors or load_base_factors()
    text = f"{user_factor.name} {user_factor.hypothesis} {user_factor.target_universe} {' '.join(user_factor.proxy_metrics)}"
    scored: list[tuple[int, BaseFactor]] = []
    for factor in factors:
        score = sum(1 for tag in factor.tags if tag.lower() in text.lower())
        if factor.family in text:
            score += 2
        scored.append((score, factor))
    return sorted(scored, key=lambda item: item[0], reverse=True)[0][1]


def blend_factors(prototype: StrategyPrototype, answers: dict[str, str]) -> FactorBlend:
    user_factor = user_factor_from_prototype(prototype, answers)
    base_factor = choose_base_factor(user_factor)
    source_quality = answers.get("source_quality", "")
    confidence_bonus = 0.15 if any(item in source_quality for item in ("高", "确定", "订单", "客户", "渠道")) else 0.0
    user_weight = min(0.45, 0.2 + confidence_bonus)
    return FactorBlend(
        base_factor=base_factor,
        user_factor=user_factor,
        user_weight=user_weight,
        reason=(
            f"基础因子使用 {base_factor.name} 保证策略可回测；"
            f"用户因子作为 {round(user_weight * 100)}% 的解释与筛选权重，后续可接外部数据源强化。"
        ),
    )


def factor_blend_payload(prototype: StrategyPrototype, answers: dict[str, str]) -> dict[str, Any]:
    blend = blend_factors(prototype, answers)
    return {
        "base_factor": {
            "id": blend.base_factor.id,
            "name": blend.base_factor.name,
            "family": blend.base_factor.family,
            "description": blend.base_factor.description,
            "default_risk": blend.base_factor.default_risk,
            "enhanced": blend.base_factor.enhanced,
            "tags": list(blend.base_factor.tags),
        },
        "user_factor": {
            "name": blend.user_factor.name,
            "hypothesis": blend.user_factor.hypothesis,
            "proxy_metrics": list(blend.user_factor.proxy_metrics),
            "target_universe": blend.user_factor.target_universe,
            "confidence_notes": blend.user_factor.confidence_notes,
        },
        "user_weight": blend.user_weight,
        "reason": blend.reason,
    }
