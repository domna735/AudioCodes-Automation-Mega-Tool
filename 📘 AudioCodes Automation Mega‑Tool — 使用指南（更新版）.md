# 📘 AudioCodes Automation Mega‑Tool — 使用指南（更新版）

以下係 **最新、完整、清晰** 的使用步驟，適合：

- 新分行部署（Option 160）
- 大量電話設定
- 自動生成 `<MAC>.cfg`
- 自動掃描 + 自動讀 MAC

---

## 1️⃣ 準備 Python 執行環境

在專案目錄（例如 `C:\project of auto conf download`）開 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install requests tqdm
```

> ✔ `tqdm` 用於進度條  
> ✔ `.venv` 係獨立環境，唔會影響系統 Python

---

## 2️⃣ 建立程式檔案

1. 在同一目錄建立：
   ```
   generate_mac_cfg_auto_mt.py
   ```
2. 將完整程式碼貼入  
3. 目錄結構應該如下：

```
C:\project of auto conf download\
  ├─ .venv\
  ├─ generate_mac_cfg_auto_mt.py
```

---

## 3️⃣ 設定掃描網段

在程式頂部找到：

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

你亦可以用 `passwords.csv` 做 per‑IP 密碼 mapping。

---

## 5️⃣ 執行程式

在 PowerShell（已啟動 venv）：

```powershell
(.venv) PS C:\project of auto conf download> python .\generate_mac_cfg_auto_mt.py
```

程式會自動：

1. 多線程掃描 `NETWORK_PREFIX.1 ~ .254`
2. 找到所有 AudioCodes 電話
3. 讀取每部電話嘅 MAC Address
4. 自動生成：
   - `USER = agent_XXXX`
   - `PASSWORD = pw_XXXX`
5. 產生 `<MAC>.cfg` 放入 `generated_cfg/`

---

## 6️⃣ 檢查輸出結果

完成後你會見到：

```
generated_cfg\
  ├─ 001A2B3C4D5E.cfg
  ├─ 00AABBCCDDEE.cfg
  ├─ ...
```

打開其中一個 `.cfg`：

```text
voip/line/0/auth_name=agent_4D5E
voip/line/0/auth_password=pw_4D5E
voip/line/0/description=agent_4D5E
voip/line/0/enabled=1
```

---

## 7️⃣ 配合 Option 160（自動部署）

### DHCP Server 設定：

```
Option 160 = http://<Provisioning Server IP>/provisioning/
```

### 將所有 `.cfg` 放入：

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
### ✔ 自動配合 Option 160  
### ✔ 多線程處理（快好多）  
### ✔ 唔使手動 login GUI  
### ✔ 唔使手動 export/import  
### ✔ 適合大量部署（100–500 部）

