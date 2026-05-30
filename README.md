# ODPS Report Doctor

本项目把阿里云 MaxCompute / ODPS 的只读查数流程封装成一个本地工具包，并附带 Codex skill。其它 agent 下载本项目、安装依赖、配置本地 `.env` 或 `.env.enc` 后，就可以通过受控脚本查询表分区、行数、只读 SQL、系统目录和 DataWorks 节点逻辑。

## 安全边界

- 仓库不包含任何真实 AK/SK、`.env`、`.env.enc`、网关 token、查询输出、日志、依赖缓存或虚拟环境。
- 只允许 `SELECT`、`WITH`、`SHOW`、`DESC`、`DESCRIBE` 类型的只读查询。
- 默认要求 `SELECT` / `WITH` 带 `pt`、`ds` 或 `bizdate` 分区过滤。
- DataWorks 只调用元数据和节点代码读取接口，不调用发布、运行、写入或部署接口。
- 查询审计只记录 SQL 摘要、哈希、状态、返回行数和时间，不记录秘钥。

## 推荐目录

尽量把项目放在 D 盘，例如：

```powershell
cd D:\tools
git clone <repo-url> odps_report_doctor
cd .\odps_report_doctor
```

如果必须放在其它目录也可以，但不要把依赖安装到系统级 Python 或 C 盘全局目录。`scripts\bootstrap_vendor.py` 会把依赖安装到本项目下的 `vendor_runtime\`。

## 环境要求

- Windows PowerShell
- Python 3.11 或更新版本
- 能访问阿里云 MaxCompute / DataWorks OpenAPI 的网络
- 只读用途的阿里云 AK/SK

Python 包：

```text
pyodps==0.12.6
alibabacloud_dataworks_public20200518==8.0.4
requests==2.34.2
urllib3==2.7.0
idna==3.16
certifi==2026.5.20
chardet==5.2.0
```

## 安装依赖

在项目根目录执行：

```powershell
python .\scripts\bootstrap_vendor.py
```

该命令会创建：

- `vendor_runtime\`: 项目本地 Python 依赖
- `pip_cache\`: 项目本地 pip 缓存
- `pip_tmp\`: 临时目录，安装结束后自动删除

这些目录都被 `.gitignore` 排除，不应提交到 GitHub。

## 配置秘钥

复制示例配置：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填入真实值。必填项：

```text
ALIBABA_CLOUD_ACCESS_KEY_ID=
ALIBABA_CLOUD_ACCESS_KEY_SECRET=
ODPS_PROJECT=
ODPS_ENDPOINT=
```

DataWorks 节点逻辑查询可选项：

```text
DATAWORKS_REGION=cn-beijing
DATAWORKS_PROJECT_ENV=PROD
DATAWORKS_API_VERSION=2020-05-18
DATAWORKS_ENDPOINT=dataworks.cn-beijing.aliyuncs.com
DATAWORKS_PROJECT_ID=
DATAWORKS_PROJECT_IDENTIFIER=
```

也可以让秘钥提供方把一份 `.env` 或 `.env.enc` 单独发给 agent，然后 agent 在本项目根目录替换本地配置文件。不要把 `.env` 或 `.env.enc` 提交到 GitHub。

如需把明文 `.env` 加密为 `.env.enc`：

```powershell
python .\scripts\encrypt_env.py
```

之后运行脚本时会在本地 PowerShell 里要求输入 `.env.enc` 密码。密码不要发到聊天里。

## 安装 Codex Skill

把仓库内的 skill 目录复制到 Codex skill 目录：

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
New-Item -ItemType Directory -Force -Path (Join-Path $codexHome "skills") | Out-Null
Copy-Item -Recurse -Force .\skills\odps-readonly-query (Join-Path $codexHome "skills\odps-readonly-query")
```

可选：给 agent 明确工具项目位置。

```powershell
$env:ODPS_REPORT_DOCTOR_ROOT = "D:\tools\odps_report_doctor"
```

如果不设置该环境变量，skill 会要求 agent 先在当前工作区或用户给定路径中定位包含 `scripts\gateway_query.py` 和 `report_doctor\` 的项目根目录。

## 常用命令

先测连接：

```powershell
python .\scripts\safe_query.py test-connection
```

启动本地只读网关：

```powershell
python .\scripts\start_gateway.py
```

保持该 PowerShell 窗口打开，然后其它 agent 可以用网关客户端执行查询：

```powershell
python .\scripts\gateway_query.py partitions yh_doc_cdm.dim_matl
python .\scripts\gateway_query.py latest-partition yh_doc_cdm.dim_matl
python .\scripts\gateway_query.py count yh_doc_cdm.dim_matl --bizdate 20260527
python .\scripts\gateway_query.py --json table-logic yh_doc_cdm.dwd_order_shipment_split_mkt
```

执行受控 SQL：

```powershell
python .\scripts\gateway_query.py sql "SELECT COUNT(1) AS row_cnt FROM yh_doc_cdm.dim_matl WHERE pt = '20260527'"
```

执行诊断 SQL 模板：

```powershell
python .\scripts\safe_query.py run-sql .\diagnostics\mj_logistics_trans_fee_assess\01_ads_vs_dws_count.sql --bizdate 20260526
python .\scripts\safe_query.py doctor mj_logistics_trans_fee_assess --bizdate 20260526
```

## 发布检查

发布到 GitHub 前至少执行：

```powershell
git status --short
rg -n --hidden -g '!vendor*' -g '!packages*' -g '!wheels' -g '!pip_cache' -g '!runtime' -g '!outputs' -g '!logs' "ALIBABA_CLOUD_ACCESS_KEY_SECRET|\\.env\\.enc|\\.env$|AK|SK|password|token"
python -m pytest
```

`rg` 命中代码、说明文档或 `.env.example` 中的占位符是正常的；如果命中真实秘钥、`.env`、`.env.enc`、`gateway_state.json` 或查询输出，应先删除或加入 `.gitignore`，再提交。
