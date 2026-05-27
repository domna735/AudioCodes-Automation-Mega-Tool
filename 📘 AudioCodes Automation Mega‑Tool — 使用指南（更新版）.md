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