# 智塔 Strata Workspace

智塔是一个对话式量化策略 Agent 原型：通过采访用户的一手行业观察，整理成策略因子和策略雏形，再映射到基础因子库与确定性回测接口。

## 目录结构

```text
apps/strata/          Streamlit 原型应用
data/                 可提交的数据源说明和连接模板
docs/product/         产品设计、Agent 结构、竞品调研
docs/learning_local/  本地学习资料，默认不进 Git
local_data/           本地数据库和 CSV，默认不进 Git
local_artifacts/      zip、原始导入包和临时文件，默认不进 Git
references/ui/        UI 参考导出文件
```

## 本地运行

```powershell
cd D:\workspace\交易系统设计
streamlit run apps\strata\app.py
```

如果使用 DeepSeek 或其他 OpenAI-compatible 模型，在本地创建：

```text
apps/strata/.env.local
```

参考：

```text
apps/strata/.env.example
```

不要提交 `.env.local`。

## 数据接口

默认数据目录：

```text
local_data/DATASET/
```

也可以通过环境变量指定：

```powershell
$env:STRATA_DATASET_DIR="D:\path\to\DATASET"
```

GitHub 只保存 `data/` 下的数据源说明，不保存本地 CSV、数据库或大文件。

## 主要接口预留

- `agent_runtime.py`：大模型 API 兼容层
- `interview_agent.py`：采访模板、对话状态、策略雏形生成
- `factor_library.py`：基础因子库和用户因子拆分
- `backtest_bridge.py`：LLM 输出到确定性回测参数的桥接
- `strategyforge.py`：确定性策略、信号和回测核心

## 版本管理策略

当前 workspace 已按 GitHub 上传做了清理：

- 代码、产品文档、接口模板可以提交
- API key、本地数据、大型压缩包、临时 tunnel 工具不会提交
- 每次加入关键 feature 后，可以提交一个清晰版本

保存本地版本：

```powershell
.\scripts\save_version.ps1 -Message "feat: describe the feature"
```

配置远程仓库后可以追加 `-Push`。
