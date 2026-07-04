# 智塔 Strata 对话 Agent 结构设计

## 当前目标

先只实现一个清晰的对话 Agent 骨架，让用户通过采访式对话，把一手行业观察整理成策略雏形。

这一版不把回测、实盘、券商连接直接暴露给用户，只保留后续可接入的结构化出口。

## 产品流程

1. 选择采访脚本
2. Agent 按脚本逐步提问
3. 用户回答行业观察、信息来源、标的范围、交易直觉、风险偏好
4. Agent 调用用户配置的大模型 API，生成策略雏形
5. 输出结构化 JSON，后续可交给回测模块或实时验证模块

## 代码结构

```text
demo/
  app.py
  interview_agent.py
  agent_runtime.py
  factor_library.py
  factor_library.json
  backtest_bridge.py
  strategyforge.py
  interviews/
    industry_strategy_interview.json
```

`app.py` 只负责界面和用户流程。

`interview_agent.py` 负责采访脚本、问题顺序、采访摘要、策略雏形生成。

`agent_runtime.py` 负责模型 API、后续历史数据、实时数据和执行接口。

`factor_library.py` 和 `factor_library.json` 负责基础因子库。基础因子库可以独立升级，也可以后续改成外部策略库服务。

`backtest_bridge.py` 负责把 Agent 生成的策略雏形映射成确定性回测参数。

`strategyforge.py` 负责真正的确定性回测代码。大模型不能生成或修改回测逻辑，只能选择受控参数。

`interviews/*.json` 是可定制采访脚本。新增一个 JSON 文件，就能在界面里出现新的采访方式。

## 因子分层

智塔的策略不应该把用户信息和基础量化因子混在一起。当前拆成两层：

- 基础因子库：持续迭代的标准量化策略集，例如趋势、RSI、布林带、多策略投票。
- 用户策略因子：由采访组件从用户一手信息中提炼出来，例如库存压力、订单增加、渠道涨价、需求拐点。

基础因子库负责“可回测、可复用、可比较”。用户策略因子负责“体现用户独特观察”。

组合方式：

1. 采访组件提炼用户策略因子。
2. 系统从基础因子库里选择最匹配的基础因子。
3. 大模型只负责建议映射，不直接写回测代码。
4. `backtest_bridge.py` 生成受控 `BacktestSpec`。
5. `strategyforge.py` 使用确定性代码运行回测。

当前基础因子库在：

```text
demo/factor_library.json
```

新增基础因子时，先增加 JSON 条目：

```json
{
  "id": "trend_ma_20_60",
  "name": "20/60 日均线趋势",
  "family": "趋势跟踪",
  "description": "用 20 日均线和 60 日均线判断中短期趋势。",
  "default_risk": "均衡",
  "enhanced": true,
  "tags": ["趋势", "均线", "动量", "中期"]
}
```

如果后续外接外部最新量化策略库，可以让外部服务返回同样结构，再由 `factor_library.py` 加载。

## 采访脚本接口

每个采访脚本是一个 JSON 文件，包含：

```json
{
  "id": "industry_strategy_interview",
  "name": "行业一手信息到策略雏形",
  "description": "采访用户的一手行业观察，帮助用户形成朴素策略。",
  "opening_message": "我是小塔。先不用写策略，我会采访你。",
  "system_prompt": "你是智塔 Strata 的策略采访 Agent。",
  "questions": [
    {
      "id": "observation",
      "title": "一手观察",
      "prompt": "你最近观察到的行业变化是什么？",
      "purpose": "获取用户的一手信息源。",
      "stage": "观察",
      "answer_type": "text",
      "required": true,
      "examples": ["订单增加", "库存下降", "价格上调"]
    }
  ]
}
```

推荐把问题分成四类：

- `观察`：用户看到的行业事实
- `翻译`：把事实转成可跟踪指标
- `策略`：形成买卖逻辑和标的范围
- `验证`：确定周期、风险偏好和回测目标

## 大模型 API 接口

当前支持 OpenAI 兼容接口。DeepSeek 可以直接使用。

推荐把真实 key 放在本机环境变量里：

```powershell
$env:DEEPSEEK_API_KEY="你的 key"
$env:DEEPSEEK_BASE_URL="https://api.deepseek.com"
$env:DEEPSEEK_MODEL="deepseek-v4-flash"
```

也可以在 `demo/.env.local` 里配置：

```text
DEEPSEEK_API_KEY=你的 key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

`demo/.env.local` 已经被 `.gitignore` 忽略，不要把真实 key 写进示例文件或代码。

也兼容通用变量：

```powershell
$env:LLM_API_KEY="你的 key"
$env:LLM_MODEL="你的模型名"
$env:LLM_BASE_URL="https://api.openai.com/v1"
```

如果没有配置模型 API，系统会使用本地规则继续追问，保证 Demo 可以跑通。

## 自定义 Agent

当前 Agent 的可定制层在 `demo/interviews/*.json`。

你可以改三类内容：

- `opening_message`：第一句话，也就是用户进入产品后看到的开场
- `system_prompt`：Agent 的角色、边界、语气和安全规则
- `questions`：Agent 需要覆盖的采访目标

现在的实现不是固定问卷。JSON 里的问题是“采访目标”，大模型会根据用户回答动态决定下一句怎么问。也就是说，脚本负责约束方向，模型负责自然对话。

要做一个新的 Agent，复制 `demo/interviews/industry_strategy_interview.json`，改成新的文件即可。

## 策略雏形输出

Agent 输出固定结构，方便后续接回测和实时验证：

```json
{
  "title": "策略名称",
  "observation_summary": "用户一手观察总结",
  "factor_hypothesis": "可测试的策略因子假设",
  "naive_strategy": "朴素交易逻辑",
  "target_universe": "候选标的范围",
  "standard_modules": ["趋势过滤", "波动过滤", "基准比较"],
  "risk_controls": ["止损", "最大持有期", "高波动降仓"],
  "validation_plan": "历史验证计划",
  "missing_info": ["仍需补充的信息"],
  "follow_up_questions": ["需要逐个向用户确认的问题"],
  "source": "llm"
}
```

回测模块不会直接执行这个 JSON。它会先把策略雏形拆成：

- `user_factor`：用户策略因子
- `base_factor`：基础因子库中的一个因子
- `BacktestSpec`：确定性回测参数

`BacktestSpec` 示例：

```json
{
  "symbol_code": "510300",
  "benchmark_code": "510300",
  "family": "趋势跟踪",
  "risk_profile": "均衡",
  "enhanced": true,
  "window": "近3年",
  "base_factor_id": "trend_ma_20_60",
  "user_factor_weight": 0.35
}
```

这保证了大模型输出不会直接进入交易或回测执行层。

## 后续扩展

下一步可以按这个顺序加功能：

1. 在界面中支持上传或粘贴采访脚本 JSON
2. 给每个问题增加条件跳转，例如只有用户选择商品行业时才追问库存
3. 把策略雏形映射到历史数据回测参数
4. 增加实时数据验证接口，只观察信号，不直接下单
5. 最后再连接券商或模拟账户

核心原则：用户只看见下一步该回答什么；复杂的量化模块藏在系统后面。
