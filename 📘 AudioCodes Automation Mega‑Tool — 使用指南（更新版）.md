# 📘 AudioCodes Automation Mega‑Tool — 使用指南（更新版）

> **主程式名稱：`audiocodes_tool.py`**

此工具用於：

- 大量 AudioCodes IP Phone 自動化設定  
- Option 160 自動部署  
- 自動掃描、下載、修改、上載設定  
- 自動生成 `<MAC>.cfg`  
- 自動備份、差異比較、驗證設定  

---

## 1️⃣ 準備 Python 執行環境

在專案目錄（例如 `C:\project of auto conf download`）開 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install requests tqdm
```

---

## 2️⃣ 確認檔案結構

```
C:\project of auto conf download\
  ├─ .venv\
  ├─ audiocodes_tool.py
  ├─ patch.json
  ├─ template.cfg
  ├─ passwords.csv
  ├─ validation_rules.json
```

> `patch.json`、`template.cfg`、`passwords.csv` 都係 optional，但建議使用。

---

## 3️⃣ 設定掃描網段

在 `audiocodes_tool.py` 頂部找到：

```python
NETWORK_PREFIX = "172.16.11."
```

根據實際電話網段修改：

| 電話 IP | NETWORK_PREFIX |
|--------|----------------|
| 172.16.11.x | `"172.16.11."` |
| 10.10.20.x | `"10.10.20."` |
| 192.168.1.x | `"192.168.1."` |

---

## 4️⃣ 設定登入帳密（如需要）

如果電話唔係用 `admin / 1234`：

```python
USERNAME = "admin"
PASSWORD = "1234"
```

你亦可以用 `passwords.csv` 做 per‑IP 密碼 mapping：

```
ip,username,password
172.16.11.23,admin,9999
,admin,1234
```

---

## 5️⃣ 執行工具

在 PowerShell（已啟動 venv）：

```powershell
(.venv) PS C:\project of auto conf download> python .\audiocodes_tool.py
```

你會見到主選單：

```
1. Full Flow（掃描 → 下載 → 修改 → 上載）
2. Generate MAC.cfg（Option 160）
3. Download‑Only（掃描 → 下載）
```

---

# 🔵 模式 1：Full Flow  
（掃描 → 下載 → 修改 → 上載 → optional reboot）

適合：

- 大量電話更新設定  
- 批次修改 ext / display number / VLAN / syslog / codec  
- 自動備份 + diff + validation  

流程：

1. 掃描電話  
2. 讀 MAC  
3. 下載設定  
4. 套用 patch.json  
5. 驗證設定  
6. 上載設定  
7. optional reboot  

---

# 🟢 模式 2：Generate MAC.cfg  
（Option 160 自動部署）

執行：

```
python audiocodes_tool.py --mode gen
```

工具會：

- 掃描電話  
- 讀 MAC  
- 自動生成 `<MAC>.cfg`  
- 放入 `generated_cfg/`  

內容類似：

```text
voip/line/0/auth_name=agent_4D5E
voip/line/0/auth_password=pw_4D5E
voip/line/0/description=agent_4D5E
voip/line/0/enabled=1
```

---

# 🟡 模式 3：Download‑Only  
（掃描 → 下載設定）

適合：

- 備份所有電話設定  
- Audit / 設定比對  
- 分行搬遷前後比較  

下載後會放入：

```
backup_configs\
  ├─ <MAC>.cfg
```

---

# 🟣 Option 160 部署流程

### DHCP Server 設定：

```
Option 160 = http://<Provisioning Server IP>/provisioning/
```

### 將所有 `<MAC>.cfg` 放入：

```
C:\inetpub\wwwroot\provisioning\
```

### 電話 reboot / factory reset 後會：

- 自動攞 Option 160  
- 自動連到 Provisioning URL  
- 自動下載 `<MAC>.cfg`  
- 自動套用設定  

---

# 🔧 ACSA Fix Pack（Jira Case 5 & 43）

若需套用 ACSA 專案的兩項 Jira 修補，工具提供專用模式：

- 放置檔案：`acsa_case_5_patch.json`（codec ordering）、`acsa_case_43_patch.json`（SIP outbound proxy）
- 先以 Dry Run 測試差異（不會上載）：

```powershell
python audiocodes_tool.py --mode acsa_fix --dry-run
```

- 若 Dry Run 檢查通過，執行上載：

```powershell
python audiocodes_tool.py --mode acsa_fix
```

差異會寫入 `diff_reports/`，處理紀錄在 `tool.log`。

---

## 實際分行 cfg 轉 case

如果你要把 `New branch MK real conf/` 內的真實分行設定檔轉成可重用 case，請用：

```powershell
python branch_case_generator.py --plan branch_plan_mk.json --output-dir cases/branch_mk
```

這個流程會輸出 baseline 與 patch 兩種 JSON，方便你後續直接接到 `--acsa-case` 或 fake server 測試。預設對應欄位如下：

- `voip/line/0/description`：分機號
- `voip/line/0/extension_display`：顯示號碼
- `network/lan/location/location_uri`：分行位置 / IPCC location
- `network/lan/vlan/priority`：priority
- `system/display/message_on_screen`：branch main line

若實際現場 key 名稱不同，改 `branch_plan_mk.json` 即可。

### ②-1. 啟動安全版 Fake Server（建議）

預設 fake server 而家只會暴露少量 mock host，不會再將整個 `127.0.0.0/8` 當成電話。要模擬多部假機，請指定 host 數量或者 host list：

```powershell
python fake_ac_api.py --case cases/case_5.json --hosts 5
```

或者：

```powershell
python fake_ac_api.py --host-list 127.0.0.1,127.0.0.2,127.0.0.3
```

如果你冇加任何參數，預設只會有 1 部假機，方便安全測試。

### 真機掃描注意

對於實際 AudioCodes 電話，工具會同時嘗試：

- `/AdminPage/`
- `/mainform.cgi?go=mainframe.htm`

而且非 `127.*` 目標會預設用 `80` 埠，不再硬加 `5000`。所以如果你張開嘅真機網址係 `http://192.168.33.203/mainform.cgi?go=mainframe.htm`，掃描就會對得上。

### 真機下載 / 上載流程

真機唔再用假機個套 `AdminPage` CGI 做核心操作。實際流程係：

1. 開 `login.cgi`
2. 用 WebGUI 表單提交 `admin / 1234`
3. 跳入 `mainform.cgi?go=mainframe.htm`
4. 去 `mainform.cgi?go=manu_config.htm` 讀取真正下載連結
5. 用同一個 session 做 download / upload / reboot

你提供嘅兩部 production phone `192.168.33.185` 同 `192.168.33.203`，現階段建議只做 download 測試，唔好做 modify / upload。建議命令：

```powershell
python audiocodes_tool.py --mode download --targets 192.168.33.185,192.168.33.203 --scan-timeout 1 --device-timeout 10 --no-progress
```

---

## Reverse Generator（JSON → cfg）

如果 case JSON 已有 `config` / `patches`，可以用下面方式轉成可上載的 `.cfg`：

```powershell
python audiocodes_tool.py --mode reverse --case-file cases/branch_mk/case_000171906FD45_patch.json --output-dir generated_cfg/reversed
```

或者批量處理整個資料夾：

```powershell
python audiocodes_tool.py --mode reverse --case-dir cases/branch_mk --output-dir generated_cfg/reversed
```

這個 reverse 流程會先讀 `config`，再套用 `patches`，最後輸出成純 `key=value` 格式，方便直接用 device import endpoint 上載。

---

## 多機 Fake Server 測試

如果你要喺 mock server 做正式前測試，建議用 `--targets` 直接指定多部假機 IP，而唔係掃整個網段：

```powershell
python audiocodes_tool.py --mode full --targets 127.0.0.1,127.0.0.2,127.0.0.3 --workers 10 --timeout 1 --no-alt-scheme --no-progress
```

好處：

- 仍然係 multi-device full flow
- 會做下載、修改、diff、上載
- 避免掃描 1–254 太慢
- 可以配合 `fake_ac_api.py` 的 `behavior_map` / `endpoint_behavior` 做 deterministic 測試

如果你係準備真機上線，建議先用 `--mode download` 收集真實 cfg，再做 branch case 生成、reverse 生成，最後先上載。

### Worker 建議

- `--workers 10`：一般 mock 測試夠用
- `--workers 20`：較接近實際大量部署
- `--workers 30+`：只建議喺穩定網絡同較強機器上使用

# 🎉 而家擁有嘅能力

### ✔ 自動掃描電話  
### ✔ 自動讀 MAC  
### ✔ 自動生成 `<MAC>.cfg`  
### ✔ 自動修改設定（patch.json）  
### ✔ 自動上載設定  
### ✔ 自動 reboot  
### ✔ 自動備份  
### ✔ 自動 diff  
### ✔ 多線程處理（快好多）  
### ✔ 適合大量部署（100–500 部）

---

# ✅ **Part 1 — 常見錯誤與解決方法**

## ⚠️ 常見錯誤與解決方法

以下係現場最常見嘅錯誤訊息，以及對應嘅處理方式：

---

### **1. `Unauthorized`（401）**
**原因：**  
電話密碼錯誤、或該 IP 使用咗不同帳密。

**解決方法：**
- 檢查 `passwords.csv` 是否有對應 IP  
- 若電話密碼唔同，請加入：

```
ip,username,password
172.16.11.23,admin,9999
,admin,1234
```

---

### **2. `Not AudioCodes`（404 / 非預期 HTML）**
**原因：**  
該 IP 不是 AudioCodes 電話（例如 Printer、PC、AP）。

**解決方法：**
- 無需處理，工具會自動跳過  
- 若該 IP 應該係電話 → 請檢查網段設定 `NETWORK_PREFIX`

---

### **3. `缺少必要 key`（Validator Error）**
**原因：**  
case JSON / patch JSON 未包含 validator 要求嘅 key。

**解決方法：**
- 檢查 `validation_rules.json`  
- 補上缺少嘅 key，例如：

```
voip/line/0/enabled
voip/line/0/auth_name
voip/line/0/auth_password
```

---

### **4. `File path contains spaces`（Windows 路徑問題）**
**原因：**  
Windows PowerShell 會將含空格路徑拆開。

**解決方法：**  
所有含空格路徑必須加引號：

```
--acsa-case "C:\project of auto conf download\cases\case_43.json"
```

---

### **5. `Timeout` / `ConnectionError`**
**原因：**  
電話無回應、網絡不穩定、或 HTTPS 憑證問題。

**解決方法：**
- 開啟 retry（預設已開）  
- 若 HTTPS 有問題 → 加 `--no-verify-tls`  
- 若電話 offline → 稍後重試  

---

### **6. `Import failed`（上載失敗）**
**原因：**  
上載嘅 `.cfg` 格式錯誤或包含非法 key。

**解決方法：**
- 用 reverse generator 重新生成 `.cfg`  
- 檢查是否有多餘空白或 BOM  
- 檢查是否包含不支援嘅 key  

---

### **7. `Fake server 回傳 404`**
**原因：**  
fake server 只接受 `127.0.0.1` / `localhost`。

**解決方法：**
- 測試時請使用：

```
--prefix 127.0.0.
```

---

# （Part 1 完成）

---

# ✅ **Part 2 — 完整分行部署示例**

## 🏢 完整分行部署示例（Production Workflow）

以下示例以「旺角分行（MK）」為例，  
示範由真機 cfg → baseline → patch → reverse → 上載嘅完整流程。

---

### **① 下載真機設定（Backup）**

```powershell
python audiocodes_tool.py --mode download --prefix 172.16.11.
```

輸出：

```
backup_configs/
  ├─ 000171906FCAB.cfg
  ├─ 000171906FD45.cfg
  ├─ ...
```

---

### **② 生成 baseline + patch JSON（分行設定）**

```powershell
python branch_case_generator.py `
  --cfg-dir "New branch MK real conf" `
  --plan branch_plan_mk.json `
  --output-dir cases/branch_mk
```

輸出：

```
cases/branch_mk/
  ├─ baseline_000171906FCAB.json
  ├─ case_000171906FCAB_patch.json
  ├─ ...
```

---

### **③ Dry‑Run（驗證差異，不上載）**

```powershell
python audiocodes_tool.py `
  --mode acsa_fix `
  --acsa-case cases/branch_mk/case_000171906FCAB_patch.json `
  --dry-run
```

輸出：

```
成功：5
失敗：0
diff_reports/<MAC>.diff
```

---

### **④ 生成可上載 `.cfg`（Reverse Generator）**

```powershell
python audiocodes_tool.py `
  --mode reverse `
  --case-dir cases/branch_mk `
  --output-dir generated_cfg/mk
```

輸出：

```
generated_cfg/mk/
  ├─ case_000171906FCAB.cfg
  ├─ case_000171906FD45.cfg
  ├─ ...
```

---

### **⑤ 上載設定（正式套用）**

```powershell
python audiocodes_tool.py `
  --mode acsa_fix `
  --acsa-cases cases/branch_mk
```

---

### **⑥（可選）Reboot 電話**

```powershell
python audiocodes_tool.py --mode acsa_fix --reboot
```

---

# （Part 2 完成）

---

# ✅ **Part 3 — Case JSON Schema Overview**

## 🧱 Case JSON 結構總覽（Schema Overview）

Case JSON 支援以下欄位：

```jsonc
{
  "config": { ... },              // 基礎設定（key=value）
  "patches": [ ... ],             // 進階修改（set / replace）
  "behavior": { ... },            // 全域假機行為
  "behavior_map": { ... },        // per-host 假機行為
  "endpoint_behavior": { ... },   // per-endpoint 假機行為
  "random_error_rate": 0.1        // 隨機錯誤注入（測 retry）
}
```

---

### **1. `config`（最常用）**

```json
"config": {
  "voip/line/0/description": "4350",
  "voip/line/0/enabled": "1",
  "system/display/message_on_screen": "36284353"
}
```

---

### **2. `patches`（set / replace）**

```json
"patches": [
  { "set": { "voip/line/0/auth_name": "admin" } },
  { "replace": { "PCMU": "PCMA" } }
]
```

---

### **3. `behavior`（全域假機行為）**

```json
"behavior": {
  "mode": "slow",
  "latency_ms": 500,
  "status_code": 200
}
```

---

### **4. `behavior_map`（per-host 行為）**

```json
"behavior_map": {
  "1": { "mode": "normal" },
  "2": { "mode": "slow" },
  "3": { "status_code": 500 },
  "4": { "status_code": 503 },
  "5": { "timeout": true }
}
```

---

### **5. `endpoint_behavior`（per-endpoint 行為）**

```json
"endpoint_behavior": {
  "/AdminPage/export_cfg.cgi": { "latency_ms": 300 },
  "/AdminPage/get_mac_address.cgi": { "status_code": 500 }
}
```

---

### **6. `random_error_rate`（隨機錯誤注入）**

```json
"random_error_rate": 0.1
```

---

# （Part 3 完成）

---

# ✅ **Part 4 — Fake Server 行為示例**

## 🧪 Fake Server 行為示例

Fake Server 支援 Case‑Driven 行為控制，可用於：

- 本地測試  
- 模擬真機 timeout / error  
- 模擬多部電話唔同行為  
- 模擬 endpoint 特定錯誤  

---

### **① 啟動 Fake Server（正常模式）**

```powershell
python fake_ac_api.py
```

---

### **② 用 Case JSON 控制假機行為**

```powershell
python fake_ac_api.py --case cases/case_5.json
```

---

### **③ 行為示例：全域行為**

```json
"behavior": {
  "mode": "slow",
  "latency_ms": 800
}
```

效果：

- 所有 API 延遲 0.8 秒  
- 適合測試 timeout handling  

---

### **④ 行為示例：per-host 行為**

```json
"behavior_map": {
  "1": { "mode": "normal" },
  "2": { "mode": "slow" },
  "3": { "status_code": 500 },
  "4": { "status_code": 503 },
  "5": { "timeout": true }
}
```

效果：

| Host | 行為 |
|------|------|
| 127.0.0.1 | 正常 |
| 127.0.0.2 | 慢 |
| 127.0.0.3 | 500 |
| 127.0.0.4 | 503 |
| 127.0.0.5 | Timeout |

---

### **⑤ 行為示例：per-endpoint 行為**

```json
"endpoint_behavior": {
  "/AdminPage/export_cfg.cgi": { "status_code": 500 },
  "/AdminPage/get_mac_address.cgi": { "latency_ms": 2000 }
}
```

---

### **⑥ 行為示例：隨機錯誤注入**

```json
"random_error_rate": 0.15
```

效果：

- 15% request → 隨機 500 / 503 / timeout  
- 適合測試 retry/backoff  

---