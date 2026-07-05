"""
策略注册中心 — Plugin Registry Pattern

JSON 驱动的策略管理，不改代码即可扩充因子库。

架构:
  strategy_library.json ──加载──→ StrategyRegistry (单例)
                                      │
                    ┌─────────────────┼──────────────────┐
                    │                 │                  │
              按分类查询         按标签搜索         批量对比
                    │                 │                  │
                    ▼                 ▼                  ▼
              StrategyDefinition  →  信号生成  →  回测执行

使用:
  >>> from strategy_registry import registry
  >>> registry.reload()                    # 重新加载策略库
  >>> strategies = registry.by_category("趋势跟踪")
  >>> definition = registry.get("trend_ma_cross")
  >>> summary = registry.summary()         # 完整分类概述
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from strategyforge import RiskProfile, StrategyFamily
except ModuleNotFoundError:
    from .strategyforge import RiskProfile, StrategyFamily


STRATEGY_LIBRARY_PATH = Path(__file__).resolve().parent / "strategy_library.json"

# ── 兼容旧 factor_library.json ────────────────────────────
LEGACY_FACTOR_PATH = Path(__file__).resolve().parent / "factor_library.json"


# ═══════════════════════════════════════════════════════════
# 数据定义
# ═══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class StrategyCategory:
    """策略大类"""
    id: str
    name: str
    description: str
    icon: str = ""


@dataclass(frozen=True)
class StrategyDefinition:
    """单条策略的完整元数据"""
    id: str
    category: str
    name: str
    description: str
    risk: RiskProfile
    engine: str                          # "native" | "vbt" | "external"
    tags: tuple[str, ...]
    params: dict[str, Any] = field(default_factory=dict)
    source: str = "custom"              # "classic" | "extension" | "research" | "custom" | "external"
    reference: str = ""                  # 学术引用

    @property
    def category_name(self) -> str:
        return CATEGORY_NAMES.get(self.category, self.category)

    @property
    def display_name(self) -> str:
        return f"{self.name} [{self.engine.upper()}]"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "category": self.category, "name": self.name,
            "description": self.description, "risk": self.risk,
            "engine": self.engine, "tags": list(self.tags),
            "params": self.params, "source": self.source, "reference": self.reference,
        }


CATEGORY_NAMES: dict[str, str] = {
    "trend_following": "趋势跟踪",
    "mean_reversion": "均值回归",
    "volatility": "波动率策略",
    "momentum": "动量策略",
    "multi_factor": "多因子合成",
    "benchmark_relative": "基准线相对",
    "alternative": "另类数据/外部因子",
}

CATEGORY_FAMILY_MAP: dict[str, StrategyFamily] = {
    "trend_following": "趋势跟踪",
    "mean_reversion": "均值回归",
    "volatility": "趋势跟踪",          # 波动率突破归入趋势
    "momentum": "趋势跟踪",            # 动量归入趋势
    "multi_factor": "多策略投票",
    "benchmark_relative": "趋势跟踪",
    "alternative": "基础模板",
}


# ═══════════════════════════════════════════════════════════
# 注册中心
# ═══════════════════════════════════════════════════════════

class StrategyRegistry:
    """策略注册中心（单例模式）。

    所有策略的加载、查询、验证、批量操作都通过它。
    上层代码只需要 `from strategy_registry import registry`。
    """

    _instance: "StrategyRegistry | None" = None

    def __new__(cls) -> "StrategyRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._strategies: dict[str, StrategyDefinition] = {}
        self._categories: dict[str, StrategyCategory] = {}
        self._by_category: dict[str, list[str]] = {}
        self._by_tag: dict[str, list[str]] = {}
        self._by_engine: dict[str, list[str]] = {}
        self._version: str = ""
        self._load()

    # ── 加载 ──────────────────────────────────────────────

    def _load(self) -> None:
        path = STRATEGY_LIBRARY_PATH
        if not path.exists():
            self._load_legacy()
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        self._version = payload.get("version", "0")

        # 加载分类
        for cat_data in payload.get("categories", []):
            cat = StrategyCategory(
                id=cat_data["id"], name=cat_data["name"],
                description=cat_data.get("description", ""),
                icon=cat_data.get("icon", ""),
            )
            self._categories[cat.id] = cat

        # 加载策略
        for strat_data in payload.get("strategies", []):
            definition = StrategyDefinition(
                id=strat_data["id"],
                category=strat_data["category"],
                name=strat_data["name"],
                description=strat_data.get("description", ""),
                risk=strat_data.get("risk", "均衡"),
                engine=strat_data.get("engine", "native"),
                tags=tuple(strat_data.get("tags", [])),
                params=strat_data.get("params", {}),
                source=strat_data.get("source", "custom"),
                reference=strat_data.get("reference", ""),
            )
            self._strategies[definition.id] = definition
            self._by_category.setdefault(definition.category, []).append(definition.id)
            self._by_engine.setdefault(definition.engine, []).append(definition.id)
            for tag in definition.tags:
                self._by_tag.setdefault(tag.lower(), []).append(definition.id)

    def _load_legacy(self) -> None:
        """兼容旧 factor_library.json，自动迁移到新结构。"""
        if not LEGACY_FACTOR_PATH.exists():
            return
        payload = json.loads(LEGACY_FACTOR_PATH.read_text(encoding="utf-8"))
        for factor in payload.get("factors", []):
            fid = factor["id"]
            family = factor.get("family", "基础模板")
            # 推断 category
            cat = _infer_category(fid, family)
            definition = StrategyDefinition(
                id=fid, category=cat, name=factor["name"],
                description=factor.get("description", ""),
                risk=factor.get("default_risk", "均衡"),
                engine=factor.get("engine", "native"),
                tags=tuple(factor.get("tags", [])),
                params=factor.get("vbt_params", {}),
            )
            self._strategies[definition.id] = definition
            self._by_category.setdefault(definition.category, []).append(definition.id)
            self._by_engine.setdefault(definition.engine, []).append(definition.id)
            for tag in definition.tags:
                self._by_tag.setdefault(tag.lower(), []).append(definition.id)

    def reload(self) -> "StrategyRegistry":
        """重新加载策略库（添加新策略后调用）。"""
        self._loaded = False
        self._strategies.clear()
        self._categories.clear()
        self._by_category.clear()
        self._by_tag.clear()
        self._by_engine.clear()
        StrategyRegistry._instance = None
        return StrategyRegistry()

    # ── 查询 API ──────────────────────────────────────────

    def get(self, strategy_id: str) -> StrategyDefinition | None:
        """按 ID 获取单条策略。"""
        return self._strategies.get(strategy_id)

    def all(self) -> list[StrategyDefinition]:
        """获取全部策略。"""
        return list(self._strategies.values())

    def by_category(self, category: str) -> list[StrategyDefinition]:
        """按分类查询。支持中文名 '趋势跟踪' 或 ID 'trend_following'。"""
        cat_id = _resolve_category(category)
        ids = self._by_category.get(cat_id, [])
        return [self._strategies[i] for i in ids if i in self._strategies]

    def by_tag(self, tag: str) -> list[StrategyDefinition]:
        """按标签查询。"""
        ids = self._by_tag.get(tag.lower(), [])
        return [self._strategies[i] for i in ids if i in self._strategies]

    def by_engine(self, engine: str) -> list[StrategyDefinition]:
        """按引擎查询。"""
        ids = self._by_engine.get(engine, [])
        return [self._strategies[i] for i in ids if i in self._strategies]

    def search(self, keyword: str) -> list[StrategyDefinition]:
        """模糊搜索：名称、描述、标签。"""
        kw = keyword.lower()
        results = []
        for s in self._strategies.values():
            if kw in s.name.lower() or kw in s.description.lower() or any(kw in t.lower() for t in s.tags):
                results.append(s)
        return results

    # ── 元数据 ────────────────────────────────────────────

    @property
    def version(self) -> str: return self._version

    @property
    def count(self) -> int: return len(self._strategies)

    @property
    def category_count(self) -> int: return len(self._categories)

    def categories(self) -> list[StrategyCategory]:
        return list(self._categories.values())

    def summary(self) -> pd.DataFrame:
        """以 DataFrame 形式返回策略库全景摘要。"""
        return pd.DataFrame([s.to_dict() for s in self.all()])

    # ── 导出工具 ──────────────────────────────────────────

    def export_for_factor_library(self) -> list[dict[str, Any]]:
        """导出为 factor_library.py 兼容的格式。"""
        items = []
        for s in self.all():
            items.append({
                "id": s.id,
                "name": s.name,
                "family": CATEGORY_FAMILY_MAP.get(s.category, "基础模板"),
                "description": s.description,
                "default_risk": s.risk,
                "enhanced": True,
                "tags": list(s.tags),
                "engine": s.engine,
                "vbt_params": s.params if s.engine == "vbt" else None,
            })
        return items


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def _infer_category(strategy_id: str, family: str) -> str:
    """从旧版因子推断新分类。"""
    if "benchmark" in strategy_id:
        return "benchmark_relative"
    if "external" in strategy_id:
        return "alternative"
    family_map = {
        "趋势跟踪": "trend_following",
        "均值回归": "mean_reversion",
        "布林带反转": "mean_reversion",
        "多策略投票": "multi_factor",
        "基础模板": "trend_following",
    }
    return family_map.get(family, "trend_following")


def _resolve_category(name_or_id: str) -> str:
    """解析分类名，支持 '趋势跟踪' → 'trend_following'。"""
    name_to_id = {v: k for k, v in CATEGORY_NAMES.items()}
    if name_or_id in name_to_id:
        return name_to_id[name_or_id]
    if name_or_id in CATEGORY_NAMES:
        return name_or_id
    return name_or_id


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

registry = StrategyRegistry()


# ═══════════════════════════════════════════════════════════
# 模块自检
# ═══════════════════════════════════════════════════════════

def smoke_test() -> dict[str, Any]:
    r = registry
    return {
        "version": r.version,
        "total_strategies": r.count,
        "categories": r.category_count,
        "trend_following": len(r.by_category("trend_following")),
        "mean_reversion": len(r.by_category("mean_reversion")),
        "volatility": len(r.by_category("volatility")),
        "momentum": len(r.by_category("momentum")),
        "multi_factor": len(r.by_category("multi_factor")),
        "benchmark_relative": len(r.by_category("benchmark_relative")),
        "alternative": len(r.by_category("alternative")),
        "native_engine": len(r.by_engine("native")),
        "vbt_engine": len(r.by_engine("vbt")),
        "search_趋势": len(r.search("趋势")),
        "search_动量": len(r.search("动量")),
        "get_trend_ma": r.get("trend_ma_cross").name if r.get("trend_ma_cross") else None,
    }


if __name__ == "__main__":
    print(json.dumps(smoke_test(), ensure_ascii=False, indent=2, default=str))
