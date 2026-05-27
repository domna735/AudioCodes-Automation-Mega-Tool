# 📘 AudioCodes 自動化設定工具（Mega‑Tool）

此工具為 AudioCodes IP Phone 提供完整自動化管理能力，  
支援三種模式：

1. **Full Flow（掃描 → 下載 → 修改 → 上載）**  
2. **Dry Run（掃描 → 下載 → 修改 → Diff → 驗證）**  
3. **Generate MAC.cfg（Option 160 自動部署）**  
4. **Download‑Only（掃描 → 下載）**

適合大量電話（100–500 部）批量維護、初次部署或設定備份。

---

# 🧩 功能總覽

| 模式 | 功能 | 用途 |
|------|------|------|
| **Full Flow** | 掃描 → 下載 → 修改 → 上載 | 現場大量更新設定 |
| **Dry Run** | 掃描 → 下載 → 修改 → Diff → 驗證 | 上線前演練 / 驗證修改 |
| **Generate MAC.cfg** | 多線程生成 `<MAC>.cfg` | Option 160 自動部署 |
| **Download‑Only** | 掃描 → 下載 | 備份設定 / Audit |

---

## ACSA Fix Pack（Jira Case 5 / Case 43）

- 目的：針對 Jira 上的兩個常見問題自動套用修補：
	- Case 5：強制 codec 順序（PCMU, PCMA，清空其餘）
	- Case 43：調整 SIP Outbound Proxy 設定
- 放置檔案：`acsa_case_5_patch.json`、`acsa_case_43_patch.json`（專案根目錄）
- 執行（先用 Dry Run 檢查差異，不上載）：

```bash
python audiocodes_tool.py --mode acsa_fix --dry-run
```

- 若 Dry Run 檢查通過，移除 `--dry-run` 即可上載：

```bash
python audiocodes_tool.py --mode acsa_fix
```

變更會產生差異檔於 `diff_reports/`，並在 `tool.log` 記錄處理結果。

## 本地 Fake Server 測試

如果你想喺本機測試工具，可以先啟動假 API：

```powershell
python fake_ac_api.py
```

呢個 mock server 只接受 `127.0.0.1` / `localhost`，所以 `127.0.0.2`、`127.0.0.3` 之類嘅 loopback alias 會直接回 `404`，唔會再被誤認為真電話。

---

# 🧰 系統需求

- Windows / Linux  
- Python 3.9+  
- `requests` 套件  
- `tqdm` 套件（可選，用於進度條）

安裝方式：

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install requests tqdm
```

---

# 📂 專案結構

```
project/
 ├─ audiocodes_tool.py
 ├─ patch.json
 ├─ passwords.csv
 ├─ template.cfg
 ├─ validation_rules.json
 ├─ tool.log
 ├─ diff_reports/
 ├─ backup_configs/
 ├─ modified_configs/
 ├─ generated_cfg/
 └─ AudioCodes 自動化設定工具.md
```

---

# ⚙️ 可調整設定（audiocodes_tool.py）

```python
USERNAME = "admin"
PASSWORD = "1234"
NETWORK_PREFIX = "172.16.11."
TIMEOUT = 3

BACKUP_DIR = "backup_configs"
MODIFIED_DIR = "modified_configs"
OUTPUT_DIR = "generated_cfg"

SCAN_WORKERS = 50
PROCESS_WORKERS = 20

USE_HTTPS = False
TRY_ALTERNATE_SCHEME = True
VERIFY_TLS = False
CA_CERT_PATH = ""

PATCH_FILE = "patch.json"
PASSWORDS_CSV = "passwords.csv"
TEMPLATE_FILE = "template.cfg"
VALIDATION_FILE = "validation_rules.json"

ENABLE_RETRY = True
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 0.6
RETRY_BACKOFF_MAX = 3.0
REBOOT_AFTER_UPLOAD = False
```

---

# 🧱 Production‑Ready 強化（已加入）

1. 錯誤處理：每個 network call 都有錯誤捕捉，不會因單一設備失敗而中斷。  
2. Error Summary：流程結束會列出失敗電話、階段與原因。  
3. Logging：自動寫入 `tool.log`，含 timestamp、成功/失敗與錯誤訊息。  
4. Config Patch System：`modify_config()` 可讀取 `patch.json` 做 replace / key-value set。  
5. HTTPS / TLS：支援 HTTP/HTTPS 切換、TLS verify 與自訂 CA 憑證。  
6. 多密碼支援：支援 `passwords.csv`（可全域、可 per-IP）與 fallback 密碼。  
7. 進度條：掃描/下載/Full Flow/CFG 生成都有 `tqdm` 進度顯示（未安裝會自動降級）。
8. Retry + Backoff：暫時性連線錯誤會自動重試，提升現場成功率。
9. Config Diff：每部電話會生成 `.diff`（原始 vs 修改後）方便 audit。
10. Config Validation：上載前先驗證格式與必要 key，避免壞設定上載。
11. API Path Cache：每部電話會快取可用 API path，減少重複探測成本。
12. 可選 Reboot：上載成功後可送出 reboot 指令（可開關）。
13. CLI 模式：支援 `--mode` 自動化批次執行。

---

# 📄 配套檔案格式

`patch.json`

- `replace`: 文字取代規則
- `set`: key-value 覆蓋/新增規則

`passwords.csv`

- 欄位：`ip,username,password`
- `ip` 留空：全域密碼
- `ip` 有值：只針對該電話優先使用

`template.cfg`

- Option 160 產生 `MAC.cfg` 用模板
- 支援 `{USER}`、`{PASSWORD}` placeholder

`validation_rules.json`

- `required_keys`: 必須存在的設定 key
- `forbidden_patterns`: 禁止出現的內容片段

`diff_reports/`

- 每部電話一份 `MAC.diff`
- 記錄原始設定與修改後設定的差異

---

# 🤖 CLI 自動化範例

```bash
python audiocodes_tool.py --mode full --prefix 172.16.11. --retry 3
python audiocodes_tool.py --mode dry --prefix 172.16.11. --retry 3
python audiocodes_tool.py --mode gen --prefix 172.16.11.
python audiocodes_tool.py --mode download --https --verify-tls
python audiocodes_tool.py --mode full --reboot --no-progress
```

---

# 🤖 CLI 自動化範例

```bash
python audiocodes_tool.py --mode full --prefix 172.16.11. --retry 3
python audiocodes_tool.py --mode gen --prefix 172.16.11.
python audiocodes_tool.py --mode download --https --verify-tls
python audiocodes_tool.py --mode full --reboot --no-progress
```

---

# 🚀 模式說明

---

## 🔵 **模式 1：Full Flow（掃描 → 下載 → 修改 → 上載）**

流程：

1. 掃描網段  
2. 找到 AudioCodes 電話  
3. 讀取 MAC  
4. 下載設定檔  
5. 修改設定檔（可自定）  
6. 上載回電話  
7. 備份原始與修改後設定  

適用：

- 現場大量更新  
- 需要立即套用設定  

---

## 🟢 **模式 2：Generate MAC.cfg（Option 160）**

流程：

1. 多線程掃描  
2. 多線程讀取 MAC  
3. 生成 `<MAC>.cfg`  
4. 放入 Provisioning Server  
5. 電話 reboot → 自動下載設定  

適用：

- 初次部署  
- 大量電話（100–500 部）  
- DHCP Option 160  

---

## 🟡 **模式 3：Download‑Only（掃描 → 下載）**

流程：

1. 多線程掃描  
2. 讀取 MAC  
3. 下載設定檔  
4. 儲存到 `backup_configs/`  

適用：

- 設定備份  
- Audit / 檢查設定  
- 不修改、不上載  

---

# 🛠 使用方法

執行：

```bash
python audiocodes_tool.py
```

選單：

```
1. Full Flow（掃描 → 下載 → 修改 → 上載）
2. Dry Run（掃描 → 下載 → 修改 → Diff → 驗證）
3. Generate MAC.cfg（Option 160）
4. Download‑Only（掃描 → 下載）
```

---

# ⚠️ 注意事項

- 電話需可透過 HTTP 存取  
- HTTPS 需處理憑證  
- 若每部電話密碼不同，可改為 CSV mapping  
- 建議先測試 1–2 部電話再批量執行  
- 多線程模式速度快，建議在非生產時段使用  

---

# 🏁 結語

此工具可大幅降低人工維護成本，  
並提供完整 AudioCodes 自動化部署能力。