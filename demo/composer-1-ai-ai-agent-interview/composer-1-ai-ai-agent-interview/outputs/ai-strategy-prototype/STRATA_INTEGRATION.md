# 智塔集成说明

当前静态 UI 已作为视觉结构参考迁移到 `demo/app.py`：

- 左侧流程轨道：对话、策略、回测、部署预留
- 产品主线：行业观察采访、策略雏形生成、基础因子库映射、确定性回测
- 大模型接口：继续由 Python 后端读取 `.env.local`，避免把 API key 暴露到前端 JS
- Agent 逻辑：复用 `OpenAICompatibleClient`、`run_interview_turn`、`generate_strategy_prototype`
- 回测接口：复用 `propose_backtest_spec`、`run_backtest_from_spec`、`analyze_backtest_result`

后续如果改成真正前后端分离，可以把这些 Python 函数封装成 `/api/chat`、`/api/prototype`、`/api/backtest` 三个本地接口，再让本目录的静态页面调用接口。
