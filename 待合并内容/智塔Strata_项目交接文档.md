# 智塔 Strata — 项目交接文档

> **目标读者**：前端优化 / 设计协作的智能体
> **日期**：2026-07-04
> **GitHub**：https://github.com/chen2018k/strata

---

## 一、项目一句话概括

> 智塔 Strata 是一个 **把普通人一手行业观察变成可验证量化策略** 的智能塔台。
> 用户用自然语言说出行业变化 → Agent 采访追问 → 策略因子化 → 历史回测 → 输出可部署信号。

---

## 二、完整文件地图

```
D:\workspace\交易系统设计\                   ← 工作区根目录
│
├── apps\strata\                            ← 🔥 GitHub 仓库 (已推送)
│   ├── app.py                  40 KB       ← Streamlit 前端主应用 ★★★
│   ├── agent_runtime.py        12 KB       ← LLM 客户端 + 数据协议
│   ├── interview_agent.py      13 KB       ← 采访对话 Agent
│   ├── backtest_bridge.py      10 KB       ← 策略→回测参数桥接
│   ├── strategyforge.py        24 KB       ← 确定性回测引擎 ★★
│   ├── data_provider.py        15 KB       ← 可插拔数据接口层 ★★
│   ├── vbt_adapter.py          17 KB       ← VectorBT 加速适配层
│   ├── factor_library.py        6 KB       ← 基础/用户因子拆分
│   ├── factor_library.json      3 KB       ← 因子库定义 (7个因子)
│   ├── fetch_a_share_data.py    5 KB       ← 东财数据拉取脚本
│   ├── run_backtest.py         16 KB       ← CLI 回测工具
│   ├── live_validator.py       10 KB       ← 实盘校验工具
│   ├── interviews\
│   │   └── industry_strategy_interview.json ← 采访脚本模板
│   ├── .streamlit\
│   │   └── config.toml                     ← Streamlit 配置
│   ├── requirements.txt                    ← pip 依赖
│   ├── .env.example                        ← 环境变量模板
│   ├── .env.local                          ← 🔒 真实 API Key (不入Git)
│   ├── .gitignore
│   └── README.md
│
├── data\
│   └── DATASET\                            ← A股日线数据 (不在Git中)
│       ├── 510300_沪深300ETF.csv    1572行  2020-01-02 ~ 2026-07-01
│       ├── 510500_中证500ETF.csv    1572行
│       ├── 588000_科创50ETF.csv     1363行
│       ├── 159915_创业板ETF.csv      1571行
│       ├── 512100_中证1000ETF.csv   1571行
│       ├── 600519_贵州茅台.csv      1572行
│       ├── 000001_平安银行.csv      1572行
│       ├── 300750_宁德时代.csv      1572行
│       └── metadata.json                     ← 符号索引
│
├── 学习材料\                               ← 参考文档 (不在Git中)
│   ├── 智塔_Strata_产品流程设计.md          ← ★ 产品定义
│   ├── 智塔_Strata_对话Agent结构设计.md      ← ★ Agent 架构
│   ├── 智塔_Strata_竞品与生态调研.md         ← 竞品分析
│   ├── 港美股公开数据源汇总.pdf              ← 数据源手册
│   └── 策略共创agent.v1.pdf                 ← 原始策略文档
│
└── 桌面\备用系统\demo\                      ← 开发工作区 (含outputs/)
```

### 路径约定

- **代码根目录**：`D:\workspace\交易系统设计`
- **Streamlit 应用**：`apps\strata\app.py`
- **数据目录**：`data\DATASET\`（由 `strategyforge.py` 中 `ROOT / "data" / "DATASET"` 解析）
- **启动命令**：在根目录执行 `streamlit run apps\strata\app.py`

---

## 三、技术栈

| 层 | 技术 | 版本 |
|----|------|------|
| 前端框架 | Streamlit | 1.58+ |
| 后端语言 | Python | 3.12 |
| 数据处理 | pandas, numpy | ≥2.0 / ≥1.24 |
| 图表 | Altair (Streamlit 内置) | 5.0+ |
| 加速回测 | VectorBT | 1.0.0 |
| LLM | DeepSeek (OpenAI 兼容) | deepseek-v4-flash |
| 数据源 | 东方财富 API / yfinance | — |

---

## 四、核心架构与数据流

```
用户输入 (自然语言)
       │
       ▼
┌──────────────────┐
│  app.py           │  ← Streamlit 前端 (STARTS HERE)
│  聊天界面 + 回测面板 │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ interview_agent.py│  ← 对话引擎
│ 采访追问 + 策略雏形  │     读取 interviews/*.json 采访脚本
│ StrategyPrototype │     调用 agent_runtime.py → DeepSeek API
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ factor_library.py │  ← 因子拆分
│ 用户因子 + 基础因子  │     从 factor_library.json 加载7个因子
│ FactorBlend       │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ backtest_bridge.py│  ← 回测桥接
│ BacktestSpec      │     生成受控回测参数
└──────┬───────────┘
       │
       ├──────────────────────────┐
       ▼                          ▼
┌──────────────┐          ┌──────────────┐
│ strategyforge│          │ vbt_adapter  │
│ .py          │          │ .py          │
│ 确定性回测引擎 │          │ VectorBT 加速 │
│ (native)     │          │ (--engine vbt)│
└──────┬───────┘          └──────┬───────┘
       │                         │
       └──────────┬──────────────┘
                  │
                  ▼
         ┌────────────────┐
         │ data_provider  │  ← 统一数据接口
         │ .py            │
         │                 │
         │ csv / eastmoney │
         │ / yfinance      │
         └────────┬───────┘
                  │
                  ▼
         ┌────────────────┐
         │ data/DATASET/  │  ← 8个标的 × 1572行 CSV
         │ 或 Eastmoney   │
         │ API 实时拉取    │
         └────────────────┘
```

### 三模信号源（vbt_adapter.py）

| 模式 | 方法 | 输入 | 用途 |
|------|------|------|------|
| 内部信号 | `run_strategyforge(close, family, risk)` | build_signals() 输出 | 5大策略族 |
| 外部因子 | `run_external_factor(close, factor, threshold)` | 任意 pandas Series | 基本面/情绪/另类数据 |
| 基准线策略 | `run_benchmark_relative(close, benchmark)` | 基准价格 | 相对强度 Z-score |

---

## 五、7 个策略因子（factor_library.json）

| ID | 名称 | 家族 | 引擎 | 说明 |
|----|------|------|------|------|
| `trend_ma_20_60` | 20/60日均线趋势 | 趋势跟踪 | native | 金叉入场/死叉出场 |
| `rsi_reversal_14` | RSI超跌修复 | 均值回归 | native | RSI<30入场/>55出场 |
| `bollinger_reversion_20` | 20日布林带边界 | 布林带反转 | native | 跌破下轨入场 |
| `multi_signal_vote` | 三指标投票 | 多策略投票 | native | ≥2信号确认入场 |
| `benchmark_relative_zscore` | 基准线Z-score | 趋势跟踪 | vbt | 相对基准偏离策略 |
| `benchmark_relative_ma` | 基准线均线交叉 | 趋势跟踪 | vbt | 相对强度MA交叉 |
| `external_factor_entry` | 外部因子入口 | 基础模板 | vbt | 任意pandas Series注入 |

---

## 六、启动方式

### 1. 环境准备

```powershell
cd D:\workspace\交易系统设计
pip install -r apps\strata\requirements.txt
pip install vectorbt        # VBT 加速引擎(可选)
pip install yfinance        # 港美股数据(可选)
```

### 2. 配置 LLM API Key

编辑 `apps\strata\.env.local`：

```text
DEEPSEEK_API_KEY=sk-你的key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

### 3. 启动应用

```powershell
streamlit run apps\strata\app.py
```

### 4. CLI 回测工具

```bash
# 离线回测 (零网络依赖)
python apps\strata\run_backtest.py --list
python apps\strata\run_backtest.py --symbol 510300 --family 趋势跟踪

# VectorBT 加速
python apps\strata\run_backtest.py --symbol 510300 --engine vbt --benchmark 510300

# 全策略对比
python apps\strata\run_backtest.py --symbol 510300 --compare-all

# 实盘校验
python apps\strata\live_validator.py --symbol 510300 --family 趋势跟踪
python apps\strata\live_validator.py --scan --family 趋势跟踪
```

---

## 七、当前前端架构 (app.py) 分析

### 页面结构

```
┌────────────────────────────────────────────┐
│  顶部标题栏 (strata-title)                    │
│  "智塔 Strata" + 模型连接状态 pill             │
├────────────────────────────────────────────┤
│  左侧工作流指示器 (workflow-rail)              │
│  01 对话 → 02 策略 → 03 回测 → 04 部署       │
├────────────────────────────────────────────┤
│  主内容区                                     │
│  ┌──────────────────────────────────────┐  │
│  │ 产品说明卡片 (product-shell + advisor-card) │
│  │ "小塔会先和你对话"                           │
│  ├──────────────────────────────────────┤  │
│  │ 对话消息列表 (st.chat_message)          │  │
│  │ - AI 消息：气泡框 + markdown            │  │
│  │ - 用户消息：深色气泡，右对齐            │  │
│  ├──────────────────────────────────────┤  │
│  │ 回测面板 (render_backtest_panel)       │  │
│  │ - 因子组合展示                          │  │
│  │ - 回测设置 (标的/基准/策略/风险/窗口)    │  │
│  │ - 运行回测按钮                          │  │
│  │ - 权益曲线 + 绩效摘要表                 │  │
│  └──────────────────────────────────────┘  │
├────────────────────────────────────────────┤
│  底部固定输入框 (st.chat_input)               │
│  "和小塔说说你的观察"                         │
└────────────────────────────────────────────┘
```

### 关键 Session State 变量

| 变量 | 类型 | 说明 |
|------|------|------|
| `messages` | list[dict] | 聊天历史 |
| `answers` | dict | 采访回答 |
| `prototype` | StrategyPrototype | 策略雏形对象 |
| `backtest_ready` | bool | 是否可进入回测 |
| `show_backtest_controls` | bool | 是否展开回测面板 |
| `backtest_spec` | BacktestSpec | 回测参数 |
| `backtest_result` | dict | 回测结果 |
| `follow_up_questions` | list | 追问列表 |
| `follow_up_index` | int | 当前追问进度 |

### 工作流阶段 (workflow_index)

```
0 → 对话采访 (初始状态)
1 → 策略雏形 (prototype != None)
2 → 回测验证 (show_backtest_controls 或 backtest_result)
```

### CSS 关键变量

```css
--canvas / --ink / --muted / --line
--surface / --surface-strong / --shadow
--accent: #0a84ff
```

当前使用**粗野主义/瑞士风格**设计语言：黑色边框、偏移阴影、等宽布局。

---

## 八、前端优化的建议切入点

### 💡 即刻可做的改进

1. **CSS 提取** — 目前约 600 行内联 `<style>` 在 `app.py` 中，可提取到 `.streamlit/static/style.css` 或使用 Streamlit 主题系统
2. **组件拆分** — `app.py` 近 1000 行，可将 `render_workflow_rail`、`render_backtest_panel`、`render_prototype` 等拆到独立模块
3. **响应式修复** — 移动端（`@media max-width: 780px`）的工作流指示器目前压缩为 4 列 grid，体验可优化
4. **回测面板 UX** — 回测面板目前以 `st.button` + `st.selectbox` 线性堆叠，可改为卡片式 + 步骤引导

### 🔧 中等复杂度

5. **加载状态** — 目前 LLM 调用使用 `render_thinking()` 的 CSS 动画点，可改用 Streamlit 原生 `st.status` 或骨架屏
6. **错误状态** — LLM 调用失败时目前只用 `st.warning` 提示，可以设计更友好的降级 UI
7. **因子可视化** — `factor_blend_payload` 的结果目前纯文本展示，可做成标签网格或雷达图

### 🏗️ 结构级改动

8. **多页面** — 当前是单页应用，可使用 Streamlit 的 `st.navigation` + `st.Page` 拆分为：对话页 / 回测页 / 策略库页
9. **设计系统** — 统一 design token（颜色/间距/字体/阴影），方便后续换肤
10. **接入 TradingView Lightweight Charts** — 替代 Altair 权益曲线（更专业的金融图表）

---

## 九、前端与后端协作关键接口

前端 (app.py) 通过这些模块与后端通信：

```python
# 对话
from interview_agent import InterviewTemplate, StrategyPrototype, next_question, run_interview_turn

# 因子
from factor_library import factor_blend_payload  # → {"base_factor":..., "user_factor":..., "user_weight":..., "reason":...}

# 回测
from backtest_bridge import BacktestSpec, run_backtest_from_spec, analyze_backtest_result

# 数据
from strategyforge import load_symbols, format_pct  # → list[SymbolInfo], 百分比格式化
```

### 核心数据结构

```python
# 策略雏形 (interview_agent.py)
StrategyPrototype(
    title,                    # 策略名称
    observation_summary,      # 一手观察总结
    factor_hypothesis,        # 因子假设
    naive_strategy,           # 朴素交易逻辑
    target_universe,          # 候选标的范围
    standard_modules,         # 标准量化模块 tuple
    risk_controls,            # 风控规则 tuple
    validation_plan,          # 验证计划
    missing_info,             # 仍需补充
    follow_up_questions,      # 追问列表
    source,                   # "llm" | "rules"
)

# 回测规格 (backtest_bridge.py)
BacktestSpec(
    symbol_code,              # "510300"
    benchmark_code,           # "510300"
    family,                   # "趋势跟踪"
    risk_profile,             # "均衡"
    enhanced,                 # True/False
    window,                   # "近3年"
    base_factor_id,           # "trend_ma_20_60"
    user_factor_weight,       # 0.35
)

# 回测结果 (dict)
{
    "symbol": SymbolInfo,
    "benchmark": SymbolInfo,
    "spec": BacktestSpec,
    "summary": pd.DataFrame,   # 绩效对比表
    "curves": pd.DataFrame,    # 权益曲线 (date, 各方案, 买入持有基准)
    "backtests": dict[str, pd.DataFrame],  # 每方案详细回测
}
```

### 数据获取

```python
from data_provider import DataProviderFactory, CsvMarketDataProvider

# 离线模式
market = DataProviderFactory.create_market("csv")      # → CsvMarketDataProvider
market.symbols()        # → list[SymbolInfo]  (8个标的)
market.history(symbol)  # → pd.DataFrame (date/open/high/low/close/volume/...)
market.list_symbols()   # → pd.DataFrame (标的清单)

# 在线模式
market = DataProviderFactory.create_market("eastmoney") # → EastmoneyDataProvider
live   = DataProviderFactory.create_live("eastmoney")   # → 同上 (支持 latest_bars)
```

---

## 十、已知限制和注意事项

| 限制 | 说明 | 影响 |
|------|------|------|
| 数据源耦合 | `strategyforge.py` 默认从 `ROOT / "data" / "DATASET"` 读 CSV | 部署时需确保数据目录存在 |
| .env.local | 包含真实 DeepSeek API Key，通过 .gitignore 排除 | 新环境需手动创建 |
| Streamlit 单文件 | app.py 约 950 行，CSS 内联 | 维护和协作成本高 |
| 无用户认证 | 当前无登录/多用户隔离 | 仅适合本地 demo |
| A股数据 | 仅 8 个标的，无港股/美股实际数据 | 扩展需额外数据源 |
| VBT 引擎 | 需要 `pip install vectorbt` | 可选依赖，不安装也能用 native 引擎 |

---

## 十一、给协作 Agent 的建议

### 如果要做前端重设计

1. **先读** `app.py` 的 CSS 部分（第 30-550 行）了解当前设计语言
2. **再读** 产品流程设计文档了解用户旅程
3. 保持 Streamlit 框架不变的前提下，CSS 提取 + 组件拆分是最低风险的第一步
4. 不要改 session_state 变量的 key 名称（后端依赖它们）

### 如果要做后端集成

1. **不要改** `StrategyPrototype` 和 `BacktestSpec` 的字段结构（接口契约）
2. 新增数据源实现 `data_provider.py` 中的协议即可
3. 新增因子在 `factor_library.json` 中添加条目
4. CLI 工具 (`run_backtest.py`, `live_validator.py`) 是独立脚本，改它们不影响 Streamlit 主应用

### 项目启动最小步骤

```powershell
cd D:\workspace\交易系统设计
pip install -r apps\strata\requirements.txt
# 配置 apps\strata\.env.local (从 .env.example 复制并填入 key)
streamlit run apps\strata\app.py
# 在浏览器打开 http://localhost:8501
```

---

## 十二、快速参考卡

| 你要做什么 | 看哪个文件 |
|-----------|-----------|
| 改界面样式 | `app.py` (CSS 在 30-550 行，HTML 结构在 887-940 行) |
| 改对话流程 | `interview_agent.py` + `interviews/*.json` |
| 加新策略 | `strategyforge.py` (build_signals) + `factor_library.json` |
| 切数据源 | `data_provider.py` (DataProviderFactory) |
| 加速回测 | `vbt_adapter.py` |
| 命令行回测 | `run_backtest.py` |
| 实时信号 | `live_validator.py` |
| 了解产品定位 | `学习材料/智塔_Strata_产品流程设计.md` |
| 了解 Agent 设计 | `学习材料/智塔_Strata_对话Agent结构设计.md` |
| 了解竞品 | `学习材料/智塔_Strata_竞品与生态调研.md` |
