# Strata 应用

这是智塔当前的 Streamlit 原型应用。

## 启动

```powershell
streamlit run apps\strata\app.py
```

## 大模型配置

在 `apps/strata/.env.local` 中配置，文件不会进入 Git：

```text
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

也支持通用变量：

```text
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
```

## 数据配置

默认读取：

```text
local_data/DATASET/
```

可通过 `STRATA_DATASET_DIR` 覆盖。

## 接口边界

- 对话采访：`interview_agent.py`
- LLM 客户端：`agent_runtime.py`
- 因子拆分：`factor_library.py`
- 回测桥接：`backtest_bridge.py`
- 确定性回测：`strategyforge.py`
