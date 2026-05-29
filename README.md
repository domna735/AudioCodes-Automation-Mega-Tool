# 📘 AudioCodes Automation Mega‑Tool  

---

# 📌 Overview

This Mega‑Tool automates AudioCodes IP Phone provisioning.  
It includes **three modes**:

本工具提供三種 AudioCodes 自動化模式：

1. **Full Flow（Scan → Download → Modify → Upload）**  
2. **Dry Run（Scan → Download → Modify → Diff → Validate）**  
3. **Generate MAC.cfg（Option 160 Provisioning）**  
4. **Download‑Only（Scan → Download）**

---

# ✨ Features

| Feature | 說明 |
|--------|------|
| Auto Network Scan | 自動掃描網段 |
| Auto MAC Retrieval | 自動讀取 MAC |
| Auto Config Download | 自動下載設定 |
| Auto Config Modify | 自動修改設定 |
| Auto Config Upload | 自動上載設定 |
| Multi‑Threaded Scan | 多線程掃描 |
| Multi‑Threaded MAC.cfg Generation | 多線程生成設定 |
| Auto Backup | 自動備份 |
| Option 160 Support | 支援 DHCP Provisioning |
| Dry Run Mode | 上線前演練，不上載 |
| Error Summary Report | 最後輸出失敗電話與原因 |
| File Logging (`tool.log`) | 記錄每次處理結果與錯誤 |
| Patch‑Based Config Modify | 支援 `patch.json` 規則化修改 |
| HTTPS / TLS Handling | 可切換 HTTP/HTTPS 與憑證驗證 |
| Multi‑Password Fallback | 支援 `passwords.csv` 與 fallback 密碼 |
| Progress Bar (`tqdm`) | 顯示掃描/處理進度 |
| Request Retry + Backoff | 暫時性錯誤自動重試 |
| Config Diff Reports | 產生修改前後差異 `.diff` |
| Config Validation | 上載前驗證格式與必要 key |
| API Path Cache | 自動記錄各電話可用 API path |
| Optional Reboot | 上載後可選擇送出 reboot |
| CLI Automation | 支援 `--mode` 與批次參數 |

---

# 🧰 Requirements

- Python 3.9+  
- `requests` library  
- `tqdm` library (optional, for progress bar)

Install:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install requests tqdm
```

---

# 📂 Project Structure

```
project/
 ├─ audiocodes_tool.py
 ├─ patch.json
 ├─ passwords.csv
 ├─ template.cfg
 ├─ validation_rules.json
 ├─ diff_reports/
 ├─ backup_configs/
 ├─ modified_configs/
 ├─ generated_cfg/
 └─ README.md
```

---

# 🚀 Modes

---

## 🔵 Mode 1 — Full Flow  
### *(Scan → Download → Modify → Upload)*

Used for:

- Bulk updates  
- On‑site maintenance  
- Direct config modification  

---

## 🟢 Mode 2 — Generate MAC.cfg  
### *(Option 160 Provisioning)*

Used for:

- Initial deployment  
- 100–500 phones  
- DHCP Option 160  

---

## 🟡 Mode 3 — Download‑Only  
### *(Scan → Download)*

Used for:

- Backup  
- Audit  
- Config inspection  

---

## 🟣 Mode 4 — Dry Run  
### *(Scan → Download → Modify → Diff → Validate)*

Used for:

- Pre-deployment rehearsal  
- Rule validation  
- Audit without upload  

---

# 🛠 Usage

Run:

```bash
python audiocodes_tool.py
```

## 🔧 ACSA Fix Pack (Case 5 & Case 43)

 - Purpose: Apply Jira‑reported fixes (codec ordering and SIP outbound proxy) to phones via patch files.
 - Patch files: `acsa_case_5_patch.json`, `acsa_case_43_patch.json` (in repository root).
 - Dry run (no upload):

```bash
python audiocodes_tool.py --mode acsa_fix --dry-run
```

- Apply changes (will upload to phones):

```bash
python audiocodes_tool.py --mode acsa_fix
```

The tool will generate diffs in `diff_reports/` and log results to `tool.log`.

## 🧪 Local Fake Server Test

For safe local testing, run the mock API server in this repo:

```bash
python fake_ac_api.py
```

It is hardened to answer only when the request host is `127.0.0.1` or `localhost`, so scan aliases like `127.0.0.2` will return `404` instead of being treated as devices.

Menu:

```
1. Full Flow
2. Dry Run
3. Generate MAC.cfg
4. Download‑Only
```

---

# 🧩 Production Config Files

`patch.json`

- `replace`: 文字取代規則
- `set`: key-value 強制寫入/覆蓋規則

`passwords.csv`

- 欄位：`ip,username,password`
- `ip` 留空代表全域密碼
- 有填 `ip` 代表指定電話優先使用

`template.cfg`

- Mode 2 (`Generate MAC.cfg`) 使用的模板
- 支援 `{USER}`、`{PASSWORD}` placeholder

`tool.log`

- 每次執行自動生成
- 包含 timestamp、成功/失敗、錯誤原因

`validation_rules.json`

- `required_keys`: required keys in generated config
- `forbidden_patterns`: blocked patterns

`diff_reports/`

- per-phone config diff report (`<MAC>.diff`)

---

# ⚡ CLI Examples

```bash
python audiocodes_tool.py --mode full --prefix 172.16.11. --retry 3
python audiocodes_tool.py --mode dry --prefix 172.16.11. --retry 3
python audiocodes_tool.py --mode gen --prefix 172.16.11.
python audiocodes_tool.py --mode download --https --verify-tls
python audiocodes_tool.py --mode full --reboot --no-progress
```

---

# 🌐 Option 160 Integration

DHCP:

```
Option 160 = http://<server>/provisioning/
```

Place generated files:

```
/provisioning/<MAC>.cfg
```

Phone reboot → auto download.

---

# ⚠️ Notes

- HTTP access required  
- HTTPS requires certificate handling  
- Test with 1–2 phones first  
- Multi‑threaded mode recommended off‑peak  

---

# 🏁 Conclusion

This Mega‑Tool provides a complete automation solution for AudioCodes IP Phones,  
reducing manual workload and deployment time.

---

# 🔬 ACSA Case‑Driven Mode (quick start)

Use JSON case files to describe patch rules and (optionally) fake‑server behavior.

- Put cases under `cases/` or reference a JSON file directly.
- Example commands:

```
python audiocodes_tool.py --mode acsa_fix --acsa-case 5 --dry-run
python audiocodes_tool.py --mode acsa_fix --acsa-case cases/case_5.json --dry-run
python fake_ac_api.py --case cases/case_5.json
```

- Case JSON fields:
	- `random_error_rate`: optional float from `0` to `1`; injects random `500` / `503` / `timeout` responses
	- `patches`: list of patch objects (each `replace` and/or `set`)
	- `config`: optional mapping used by the fake server as exported config
	- `behavior`: optional `{ "latency_ms": <ms>, "status_code": <int>, "mode": "normal|timeout|error" }`
	- `behavior_map`: optional per-host overrides keyed by last octet or full host
	- `endpoint_behavior`: optional per-route overrides keyed by endpoint path

On Windows, quote any path that contains spaces:

```
python audiocodes_tool.py --mode acsa_fix --acsa-case "C:\project of auto conf download\cases\case_43.json" --dry-run
```

This lets you add new ACSA fixes by editing/adding JSON files — no code changes required.

## 🏢 Real Branch Case Generation

The real branch exports under `New branch MK real conf/` can be converted into reusable baseline and patch cases with the helper script:

```powershell
python branch_case_generator.py --plan branch_plan_mk.json --output-dir cases/branch_mk
```

The starter plan in `branch_plan_mk.json` covers the five Mong Kok L phones and maps the observed real cfg fields to the generated case payload:

- `voip/line/0/description` for the extension number
- `voip/line/0/extension_display` for the display number
- `network/lan/location/location_uri` for the branch location value
- `network/lan/vlan/priority` for the branch priority value
- `system/display/message_on_screen` for the branch main line

If your branch uses different target keys, edit only the plan JSON; the generator does not need to change.

## 🔁 Reverse Generator

Case JSON files can now be rendered back into uploadable `.cfg` files:

```powershell
python audiocodes_tool.py --mode reverse --case-file cases/branch_mk/case_000171906FD45_patch.json --output-dir generated_cfg/reversed
```

You can also batch-convert a directory of cases:

```powershell
python audiocodes_tool.py --mode reverse --case-dir cases/branch_mk --output-dir generated_cfg/reversed
```

This reads the `config` block, applies any `patches`, validates the final text, and writes a plain key=value cfg that can be uploaded with the device import endpoint.

## 🧪 Multi-Device Fake Server Test

For mock-server validation before real deployment, use an explicit target list instead of a full subnet scan:

```powershell
python audiocodes_tool.py --mode full --targets 127.0.0.1,127.0.0.2,127.0.0.3 --workers 10 --timeout 1 --no-alt-scheme --no-progress
```

This keeps the flow multi-device, but skips the slow scan over 1-254. It is the recommended way to validate download, modify, diff, upload, and retry behavior against `fake_ac_api.py`.
`fake_ac_api.py` is safe by default now: if you start it without options, it only exposes one mock host. To simulate more devices, pass either `--hosts 5` or an explicit `--host-list`.

```powershell
python fake_ac_api.py --case cases/case_5.json --hosts 5
python fake_ac_api.py --host-list 127.0.0.1,127.0.0.2,127.0.0.3
```

For real-device readiness, keep using `--mode download` first to collect the live configs, then run the branch-case generation and reverse-generation steps above.

## ✅ Preflight Check Before Production

Use this order before touching real phones:

1. Run fake-server multi-device tests with `--targets` and a limited `--hosts` or `--host-list`.
2. Confirm each mock phone shows a distinct MAC in the logs and `modified_configs/`.
3. Use `--workers` to tune concurrency for your environment; start with `10` for a pilot batch.
4. Run `--mode download` on a small real subnet first and review `backup_configs/`.
5. Generate branch cases, run `--dry-run`, then do a final `reverse` output check before upload.

