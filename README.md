# ODPS Report Doctor

This repository packages a local read-only Alibaba Cloud MaxCompute / ODPS query gateway plus a Codex skill. The default operating model is encrypted-config Mode B: the repository never stores secrets, the human operator keeps `.env.enc` locally and unlocks the gateway in PowerShell, and the agent only uses `gateway_query.py` against `127.0.0.1`.

## Security Model: Mode B

Use this mode when another agent needs to query ODPS without seeing or handling secrets.

1. Clone this repository on the target machine.
2. Install dependencies into the project directory.
3. Put the separately shared `.env.enc` file in the project root. Do not commit it.
4. The human operator starts the local gateway and enters the `.env.enc` password in PowerShell.
5. The agent runs only `scripts\gateway_query.py` commands while the gateway window stays open.

The agent does not need to read `.env`, `.env.enc`, AK/SK, or the encryption password. Secrets are loaded only by the local `start_gateway.py` process.

## What Is Not Committed

The `.gitignore` excludes:

- `.env` and `.env.enc`
- `gateway_state.json`
- query audit logs
- `vendor`, `vendor_runtime`, pip caches, virtual environments, runtime folders
- outputs and logs
- pytest cache and Python bytecode

## Recommended Location

Prefer D drive storage, for example:

```powershell
cd "D:\tools"
git clone https://github.com/xuyujing611-a11y/odps-readonly-query.git
cd .\odps-readonly-query
```

Do not install packages into global Python or a C drive tool cache if you can avoid it. The bootstrap script installs dependencies under this project directory.

## Requirements

- Windows PowerShell
- Python 3.11 or newer
- Network access to Alibaba Cloud MaxCompute / DataWorks OpenAPI
- A separately provided `.env.enc` and its password

Python packages are listed in `requirements.txt` and installed by the bootstrap script.

## Install Dependencies

Run from the project root:

```powershell
python .\scripts\bootstrap_vendor.py
```

This creates local folders such as `vendor_runtime\` and `pip_cache\`. They are ignored by git.

## Prepare `.env.enc`

Preferred Mode B setup:

1. Receive `.env.enc` through a secure channel outside GitHub.
2. Place it in the project root:

```text
odps-readonly-query\.env.enc
```

3. Do not ask the agent to open, read, decrypt, upload, or replace `.env.enc`.

If you need to create a new encrypted file locally, create a temporary `.env` from the template:

```powershell
Copy-Item .env.example .env
notepad .env
python .\scripts\encrypt_env.py
```

After verifying `.env.enc`, delete the plaintext `.env` if the script did not already delete it.

Required values inside the plaintext before encryption:

```text
ALIBABA_CLOUD_ACCESS_KEY_ID=
ALIBABA_CLOUD_ACCESS_KEY_SECRET=
ODPS_PROJECT=
ODPS_ENDPOINT=
```

Optional DataWorks lookup values:

```text
DATAWORKS_REGION=cn-beijing
DATAWORKS_PROJECT_ENV=PROD
DATAWORKS_API_VERSION=2020-05-18
DATAWORKS_ENDPOINT=dataworks.cn-beijing.aliyuncs.com
DATAWORKS_PROJECT_ID=
DATAWORKS_PROJECT_IDENTIFIER=
```

## Start The Local Gateway

The human operator runs this in PowerShell:

```powershell
cd "D:\tools\odps-readonly-query"
python .\scripts\start_gateway.py
```

When prompted, enter the `.env.enc` password locally. Keep this PowerShell window open.

The gateway writes a local `gateway_state.json` containing a loopback URL and temporary token. This file is ignored by git and is only used by `gateway_query.py` on the same machine.

## Partition Ambiguity

`SHOW PARTITIONS` can return multiple `pt=YYYYMMDD` tokens in one displayed row. That does not mean there is a `pt2` column. Agents should verify real partition keys with:

```powershell
python .\scripts\gateway_query.py --json catalog columns <qualified_table>
```

If `latest-partition` returns `status: ambiguous`, it will include `candidates_by_token_index` instead of guessing. A human can choose a confirmed token position and rerun:

```powershell
python .\scripts\gateway_query.py latest-partition <qualified_table> --token-index 0
```
## Agent Commands

After the gateway is running, the agent can query through the local gateway:

```powershell
python .\scripts\gateway_query.py partitions yh_doc_cdm.dim_matl
python .\scripts\gateway_query.py latest-partition yh_doc_cdm.dim_matl
python .\scripts\gateway_query.py count yh_doc_cdm.dim_matl --bizdate 20260527
python .\scripts\gateway_query.py --json table-logic yh_doc_cdm.dwd_order_shipment_split_mkt
```

Safe SQL through the gateway:

```powershell
python .\scripts\gateway_query.py sql "SELECT COUNT(1) AS row_cnt FROM yh_doc_cdm.dim_matl WHERE pt = '20260527'"
```

If the gateway is not running, the agent should stop and ask the human operator to start `start_gateway.py`. It should not ask for the password or read `.env.enc`.

## Install The Codex Skill

Copy the skill folder into Codex skills:

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
New-Item -ItemType Directory -Force -Path (Join-Path $codexHome "skills") | Out-Null
Copy-Item -Recurse -Force .\skills\odps-readonly-query (Join-Path $codexHome "skills\odps-readonly-query")
```

Optionally tell agents where the tool project is:

```powershell
$env:ODPS_REPORT_DOCTOR_ROOT = "D:\tools\odps-readonly-query"
```

## Publish Check

Before pushing changes, run:

```powershell
git status --short
git check-ignore -v .env .env.enc gateway_state.json odps_query_audit.jsonl vendor_runtime pip_cache outputs logs
rg -n --hidden -g '!/.git' -g '!vendor*' -g '!packages*' -g '!wheels' -g '!pip_cache' -g '!runtime' -g '!outputs' -g '!logs' "LTAI|ALIBABA_CLOUD_ACCESS_KEY_ID\s*=\s*LTA|ALIBABA_CLOUD_ACCESS_KEY_SECRET\s*=\s*[^\r\n]*(?:[A-Za-z0-9+/]{20,})"
python -X utf8 -B -m pytest -q -p no:cacheprovider
```

Text references to `.env.enc`, passwords, or token variables in docs and source code are expected. Real secret values are not.
