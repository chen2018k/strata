# 数据目录说明

本目录只放可以进入 GitHub 的数据说明、数据源链接和 schema。

本地数据库和历史行情文件放在：

```text
local_data/DATASET/
```

应用默认会读取上面的目录。也可以通过环境变量覆盖：

```powershell
$env:STRATA_DATASET_DIR="D:\path\to\DATASET"
```

当前历史数据来源：

- 东方财富 push2his 日 K 线接口
- 覆盖 ETF 和少量 A 股样例标的
- 本地 CSV 不进入 Git 仓库

后续如果接入外部数据库，只提交连接说明模板，不提交真实账号、token、密码或私有地址。
