# 智塔 Strata 后端核心 — 架构与接口文档

> **目标读者**：前端优化 / 设计协作 Agent
> **目的**：理解新增的后端能力，在前端正确调用并设计对应的 UI
> **日期**：2026-07-04

---

## 总览：新增了哪些能力

```
                   ┌─ 之前已有 ─┐    ┌────────── 本次新增 ──────────┐
                   │             │    │                              │
用户自然语言 ──→ 采访Agent ──→ 策略雏形 ──→ 回测 ──→ 信号输出      │
                   │             │    │  ┌─────────────────────┐     │
                   │ interview_  │    │  │ 双引擎回测层          │     │
                   │ agent.py    │    │  │                      │     │
                   │ strategyforge│   │  │ native: strategyforge │     │
                   │ factor_     │    │  │   确定性代码，可审计   │     │
                   │ library     │    │  │                      │     │
                   │             │    │  │ vbt: vbt_adapter     │     │
                   │             │    │  │   向量化加速，批量对比 │     │
                   │             │    │  └─────────────────────┘     │
                   │             │    │  ┌─────────────────────┐     │
                   │             │    │  │ 统一数据接口层        │     │
                   │             │    │  │ data_provider.py     │     │
                   │             │    │  │ csv / eastmoney /    │     │
                   │             │    │  │ yfinance 一键切换    │     │
                   │             │    │  └─────────────────────┘     │
                   │             │    │  ┌─────────────────────┐     │
                   │             │    │  │ 三模信号源            │     │
                   │             │    │  │ 1. 内部策略族 (5种)   │     │
                   │             │    │  │ 2. 外部因子注入       │     │
                   │             │    │  │ 3. 基准线相对策略     │     │
                   │             │    │  └─────────────────────┘     │
                   │             │    │  ┌─────────────────────┐     │
                   │             │    │  │ CLI 工具              │     │
                   │             │    │  │ run_backtest.py      │     │
                   │             │    │  │ live_validator.py    │     │
                   │             │    │  └─────────────────────┘     │
```

文件位置：

| 文件 | 路径 | 行数 |
|------|------|------|
| 数据接口层 | `apps/strata/data_provider.py` | ~430 |
| VBT 适配层 | `apps/strata/vbt_adapter.py` | ~380 |
| CLI 回测 | `apps/strata/run_backtest.py` | ~480 |
| 实盘校验 | `apps/strata/live_validator.py` | ~270 |
| 因子库定义 | `apps/strata/factor_library.json` | ~70 |
| 因子库逻辑 | `apps/strata/factor_library.py` | ~170 |

---

## 一、可插拔数据接口 (`data_provider.py`)

### 一句话

> 一个 `mode` 字符串切换三种数据源，上层代码不感知底层实现。

### 对外 API（前端直接可调）

```python
from data_provider import DataProviderFactory

# ── 创建数据提供者 ──
market = DataProviderFactory.create_market("csv")        # 离线 CSV
market = DataProviderFactory.create_market("eastmoney")  # 东方财富实时
market = DataProviderFactory.create_market("yfinance")   # 港美股

live   = DataProviderFactory.create_live("csv")          # 离线模拟实时
live   = DataProviderFactory.create_live("eastmoney")    # 真实实时行情

# ── 获取标的列表 ──
symbols = market.symbols()
# → list[SymbolInfo]
# SymbolInfo 属性: .code("510300") .name("沪深300ETF") .market("SH") .category("宽基ETF")

# ── 获取历史数据 ──
df = market.history(symbols[0])
# → pd.DataFrame: date, open, high, low, close, volume, amount, pct_change, turnover, return

# ── 快速查询 ──
market.find(code="510300")           # → SymbolInfo or None
market.list_symbols()                 # → pd.DataFrame (可渲染为表格)

# ── 获取最新行情 ──
bars = live.latest_bars(symbol, lookback=260)   # → 最近260根日线
quote = CsvLiveDataProvider(market).latest_quote(symbol)
# → {"code": "510300", "date": "2026-07-01", "close": 4.998, "pct_change": -0.42, ...}
```

### 三种模式对比

| mode | 数据来源 | 需要网络 | 延迟 | 覆盖面 |
|------|---------|:---:|------|--------|
| `csv` | 本地 DATASET CSV 文件 | ❌ | 截至数据导出日 | A股 8 标的 |
| `eastmoney` | 东方财富 push2his API | ✅ | 当日收盘后 | A股全市场 |
| `yfinance` | Yahoo Finance | ✅ | 15分钟延迟 | 美股/港股 |

### 前端集成建议

```python
# 在 app.py 中添加数据源选择器
mode = st.sidebar.selectbox("数据源", ["csv", "eastmoney", "yfinance"])
market = DataProviderFactory.create_market(mode)
symbols = market.symbols()
# 渲染标的列表供用户选择
```

---

## 二、双引擎回测架构

### 一句话

> `native` 引擎保证可审计（确定性代码），`vbt` 引擎保证速度（向量化）。一个 `--engine` 参数切换。

### 引擎对比

| 维度 | native (strategyforge.py) | vbt (vbt_adapter.py) |
|------|---------------------------|----------------------|
| 实现方式 | 逐 bar 循环，确定性代码 | NumPy/Numba 向量化 |
| 速度 | 基准速度 | ~100x 更快（批量对比） |
| 可审计 | ✅ 每行代码可读 | ⚡ 黑盒加速 |
| 外部因子 | ❌ | ✅ 支持 |
| 基准线策略 | ❌ | ✅ 支持 |
| 参数优化 | ❌ | ✅ 网格搜索 |
| 依赖 | 零额外依赖 | `pip install vectorbt` |

### 对外 API

```python
# ── native 引擎 ── (前端已有，保持兼容)
from strategyforge import compare_variants, build_strategy_variants
variants = build_strategy_variants(idea, risk_profile, base_family)
summary_df, curves_df, backtests = compare_variants(price_df, variants, risk)
# summary_df: 绩效对比表 (方案/累计收益/超额收益/最大回撤/夏普比率/胜率/交易次数/综合评分)
# curves_df:  权益曲线 (date + 各方案净值 + 买入持有基准)

# ── vbt 引擎 ── (新增)
from vbt_adapter import VbtAdapter, quick_vbt_backtest
adapter = VbtAdapter()
result = adapter.run_strategyforge(close_prices, family="趋势跟踪", risk="均衡")
# → VbtResult: .total_return, .sharpe, .max_dd, .win_rate, .trade_count, .equity_curve, ...
```

### VbtResult 数据结构（前端渲染用）

```python
@dataclass
class VbtResult:
    name: str                  # "趋势跟踪·增强"
    strategy_type: str         # "内部信号" | "外部因子" | "基准线策略"
    total_return: float        # 0.0569 (5.69%)
    benchmark_return: float    # 0.3219 (32.19%)
    excess_return: float       # -0.2649 (-26.49%)
    sharpe: float              # 夏普比率
    max_dd: float              # 最大回撤 (负数)
    win_rate: float            # 胜率
    trade_count: int           # 交易次数
    holding_ratio: float       # 持仓天数占比
    equity_curve: pd.Series    # 可直接画图
    trades: pd.DataFrame       # 交易记录
```

### 前端集成建议

在回测面板中增加引擎切换：

```python
engine = st.radio("回测引擎", ["native", "vbt"], horizontal=True)
if engine == "vbt":
    from vbt_adapter import VbtAdapter
    adapter = VbtAdapter()
    result = adapter.run_strategyforge(close, family, risk)
    st.metric("累计收益", f"{result.total_return:.2%}")
    st.metric("夏普比率", f"{result.sharpe:.2f}")
    st.line_chart(result.equity_curve)
```

---

## 三、三模信号源 (`vbt_adapter.py`)

### 一句话

> 策略信号可以来自三个渠道：系统内置策略族、用户上传的外部因子 CSV、或者标的与基准的相对偏离。

### 模式一：内部策略族

```python
adapter = VbtAdapter()
result = adapter.run_strategyforge(
    close,           # pd.Series, 收盘价
    family="趋势跟踪", # 趋势跟踪 | 均值回归 | 布林带反转 | 多策略投票
    risk="均衡",      # 保守 | 均衡 | 进取
    enhanced=True,    # 是否启用风控增强 (止损/波动率过滤/冷却期)
)
```

### 模式二：外部因子注入

```python
# 任意 pandas Series → 自动转成交易信号
result = adapter.run_external_factor(
    close,
    factor=my_custom_series,   # 任何 alpha 因子，正值=看多，负值=看空
    entry_threshold=0.3,       # 因子 > 0.3 时入场
    exit_threshold=-0.3,       # 因子 < -0.3 时出场 (None=对称)
    long_only=True,            # 只做多
    name="我的外部因子",
)
# 前端可以做一个"上传因子 CSV"的组件
```

### 模式三：基准线相对策略

```python
result = adapter.run_benchmark_relative(
    close,              # 策略标的收盘价
    benchmark,          # 基准标的价格
    entry_zscore=1.5,   # 相对强度 Z-score > 1.5 入场 (显著跑赢)
    exit_zscore=0.5,    # Z-score < 0.5 出场 (不再跑赢)
    lookback=60,        # 计算窗口
)
# 前端可以加两个标的选择器：策略标的 + 基准标的
```

### 批量对比

```python
# 一次性对比所有策略族 (前端可做"一键对比"按钮)
adapter.compare_strategy_variants(close, all_variants, benchmark=bench_close)
# → pd.DataFrame: 所有方案按超额收益排序

# 自由组合对比
adapter.compare_all(close, {
    "趋势策略": (entries1, exits1),
    "反转策略": (entries2, exits2),
    "外部因子": (entries3, exits3),
})
```

### 前端集成建议

回测面板可设计为三栏：

```
┌─ 信号来源 ────────┐  ┌─ 策略参数 ──────────┐  ┌─ 数据设置 ────────┐
│ ○ 系统内置策略族    │  │ 策略族: [趋势跟踪  v] │  │ 数据源: [csv  v]   │
│ ○ 上传外部因子      │  │ 风险档: [均衡    v]  │  │ 窗口:   [近1年 v]  │
│ ○ 基准线相对策略    │  │ ☑ 风控增强          │  │ 基准:   [510300 v] │
│                    │  │                      │  │                    │
│ [上传CSV] (条件显示) │  │ [运行回测]           │  │                    │
└────────────────────┘  └──────────────────────┘  └────────────────────┘
```

---

## 四、CLI 工具接口

### `run_backtest.py` — 命令行回测

```bash
# 离线
python run_backtest.py --symbol 510300 --family 趋势跟踪 --risk 均衡 --window 近3年

# VectorBT 加速
python run_backtest.py --symbol 510300 --engine vbt

# 外部因子
python run_backtest.py --symbol 510300 --engine vbt --factor my_factor.csv --factor-threshold 1.0

# 基准线策略
python run_backtest.py --symbol 510300 --engine vbt --benchmark 510300

# 全量对比
python run_backtest.py --symbol 510300 --compare-all

# 输出结果
python run_backtest.py ... --output outputs/
```

### `live_validator.py` — 实盘信号

```bash
# 单标的
python live_validator.py --symbol 510300 --family 趋势跟踪

# 批量扫描
python live_validator.py --scan --family 趋势跟踪

# 在线模式
python live_validator.py --symbol 510300 --family 趋势跟踪 --mode eastmoney
```

前端可为之设计"实时信号仪表盘"页面：批量扫描结果表 + 每个标的的仓位柱状图。

---

## 五、因子库 (`factor_library.json`)

当前 7 个因子：

```json
[
  {"id": "trend_ma_20_60",          "family": "趋势跟踪",  "engine": "native"},
  {"id": "rsi_reversal_14",         "family": "均值回归",  "engine": "native"},
  {"id": "bollinger_reversion_20",  "family": "布林带反转","engine": "native"},
  {"id": "multi_signal_vote",       "family": "多策略投票","engine": "native"},
  {"id": "benchmark_relative_zscore","family": "趋势跟踪",  "engine": "vbt"},
  {"id": "benchmark_relative_ma",   "family": "趋势跟踪",  "engine": "vbt"},
  {"id": "external_factor_entry",   "family": "基础模板",  "engine": "vbt"}
]
```

前端可以渲染为因子选择器：只展示 `engine` 匹配当前选中引擎的因子。

---

## 六、前端对接 Checklist

从后端视角，以下是前端需要覆盖的 UI 状态和对应的 API 调用：

| # | UI 状态 | 需要调用的 API | 渲染内容 |
|---|---------|---------------|---------|
| 1 | 数据源选择 | `DataProviderFactory.create_market(mode)` | 下拉菜单：csv / eastmoney / yfinance |
| 2 | 标的选择 | `market.symbols()` | 表格/搜索：代码 + 名称 + 类别 + 数据范围 |
| 3 | 引擎选择 | Native vs VBT | Radio 按钮，选择 VBT 时显示额外选项 |
| 4 | 信号来源 | 三模切换 | Tab/Radio：内置策略 / 上传因子 / 基准线 |
| 5 | 上传因子 | `adapter.run_external_factor()` | 文件上传 + 阈值滑块 + 预览图表 |
| 6 | 基准线策略 | `adapter.run_benchmark_relative()` | 双标的选择器 (策略标的 + 基准标的) |
| 7 | 回测执行中 | 任一 `adapter.run_*()` | 加载动画 / 进度条 (VBT 很快但也应有 loading) |
| 8 | 回测结果 | `VbtResult` | 指标卡片行 + 权益曲线 + 交易清单 |
| 9 | 批量对比 | `adapter.compare_all()` | 绩效对比表（可排序）+ 多线权益图 |
| 10 | 实盘信号 | `live_validator` 逻辑 | 扫描结果表 + 仓位柱状图 + 信号日期 |
| 11 | 错误状态 | API 失败时 | 降级提示 + 建议切换到离线 CSV 模式 |
| 12 | 空状态 | 无数据/无回测结果 | 引导用户先完成对话采访 |

---

## 七、关键注意事项

1. **所有新增模块向后兼容**——原来的 `app.py` 不需要任何改动就能继续用 native 引擎
2. **数据源切换是运行时的**——不需要重启，改 `mode` 参数即可
3. **VBT 是可选的**——如果不装 `pip install vectorbt`，native 引擎照常运行
4. **外部因子接口接受任何 pandas Series**——前端只需关心文件上传 + 解析为 Series
5. **`quick_vbt_backtest()` 是一步式函数**——适合前端直接调用，一行代码完成数据加载+回测+结果汇总
6. **GitHub 仓库位置**：`https://github.com/chen2018k/strata`，所有新增文件已推送
