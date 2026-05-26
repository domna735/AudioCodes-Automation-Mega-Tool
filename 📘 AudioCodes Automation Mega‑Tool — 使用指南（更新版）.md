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

# 🎉 你而家擁有嘅能力

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

