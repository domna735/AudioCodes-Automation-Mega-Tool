import concurrent.futures
import csv
import json
import logging
import os
import time
from argparse import ArgumentParser
from difflib import unified_diff
from logging.handlers import QueueHandler, QueueListener
from queue import Queue
from threading import Lock

import requests
import urllib3
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException

try:
    from tqdm import tqdm  # type: ignore[import-not-found]
except ImportError:
    tqdm = None

# ====== 可調整設定 ======
USERNAME = "admin"
PASSWORD = "1234"
NETWORK_PREFIX = "172.16.11."
TIMEOUT = 3

USE_HTTPS = False
TRY_ALTERNATE_SCHEME = True
VERIFY_TLS = False
CA_CERT_PATH = ""

LOG_FILE = "tool.log"
PATCH_FILE = "patch.json"
PASSWORDS_CSV = "passwords.csv"
TEMPLATE_FILE = "template.cfg"
VALIDATION_FILE = "validation_rules.json"

FALLBACK_PASSWORDS = ["1111", "0000"]
ENABLE_PROGRESS = True
ENABLE_RETRY = True
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 0.6
RETRY_BACKOFF_MAX = 3.0
REBOOT_AFTER_UPLOAD = False
DRY_RUN = False

BACKUP_DIR = "backup_configs"
MODIFIED_DIR = "modified_configs"
OUTPUT_DIR = "generated_cfg"
DIFF_DIR = "diff_reports"

SCAN_WORKERS = 50
PROCESS_WORKERS = 20
# ========================

EXPORT_PATHS = [
    "/AdminPage/conf_export.cgi",
    "/AdminPage/export_cfg.cgi",
]

IMPORT_PATHS = [
    "/AdminPage/conf_import.cgi",
    "/AdminPage/import_cfg.cgi",
    "/AdminPage/import_config.cgi",
]

MAC_PATHS = [
    "/AdminPage/get_mac_address.cgi",
    "/AdminPage/get_device_info.cgi",
]

REBOOT_PATHS = [
    "/AdminPage/reboot.cgi",
    "/AdminPage/restart.cgi",
]

TEMPLATE = """
voip/line/0/auth_name={USER}
voip/line/0/auth_password={PASSWORD}
voip/line/0/description={USER}
voip/line/0/enabled=1
"""

DEFAULT_PATCH_RULES = {
    "replace": [
        {
            "from": "voip/line/0/auth_password=1234",
            "to": "voip/line/0/auth_password=9999",
        }
    ],
    "set": {},
}

LOGGER = logging.getLogger("audiocodes_tool")
ERRORS = []
ERROR_LOCK = Lock()
IP_CREDENTIALS = {}
GLOBAL_CREDENTIALS = []
PATH_CACHE = {
    "mac": {},
    "export": {},
    "import": {},
    "reboot": {},
}
REQUEST_LOCK = Lock()
LOG_QUEUE = Queue(-1)
LOG_LISTENER = None


if not VERIFY_TLS:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# -------------------------------
# 工具共用功能
# -------------------------------
def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def setup_logging():
    global LOG_LISTENER

    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    queue_handler = QueueHandler(LOG_QUEUE)
    LOGGER.addHandler(queue_handler)

    LOG_LISTENER = QueueListener(LOG_QUEUE, file_handler, stream_handler)
    LOG_LISTENER.start()


def shutdown_logging():
    global LOG_LISTENER
    if LOG_LISTENER is not None:
        LOG_LISTENER.stop()
        LOG_LISTENER = None


def verify_tls_value():
    if not VERIFY_TLS:
        return False
    if CA_CERT_PATH:
        return CA_CERT_PATH
    return True


def progress_iter(iterable, total, desc):
    if ENABLE_PROGRESS and tqdm is not None:
        return tqdm(iterable, total=total, desc=desc, ncols=90)
    return iterable


def record_error(ip, stage, reason):
    with ERROR_LOCK:
        ERRORS.append({"ip": ip, "stage": stage, "reason": reason})
    LOGGER.error("[%s][%s] %s", ip, stage, reason)


def get_base_urls(ip):
    preferred = "https" if USE_HTTPS else "http"
    alternate = "http" if preferred == "https" else "https"

    urls = [f"{preferred}://{ip}"]
    if TRY_ALTERNATE_SCHEME:
        urls.append(f"{alternate}://{ip}")
    return urls


def safe_request(method, url, **kwargs):
    attempts = RETRY_ATTEMPTS if ENABLE_RETRY else 1
    last_error = None
    status_for_retry = {408, 429, 500, 502, 503, 504}

    for idx in range(attempts):
        try:
            response = requests.request(
                method,
                url,
                timeout=TIMEOUT,
                verify=verify_tls_value(),
                **kwargs,
            )

            if response.status_code in status_for_retry and idx < attempts - 1:
                delay = min(RETRY_BACKOFF_BASE * (2 ** idx), RETRY_BACKOFF_MAX)
                time.sleep(delay)
                continue
            return response, None
        except RequestException as exc:
            last_error = str(exc)
            if idx < attempts - 1:
                delay = min(RETRY_BACKOFF_BASE * (2 ** idx), RETRY_BACKOFF_MAX)
                time.sleep(delay)

    return None, last_error


def get_cached_paths(ip, path_group):
    with REQUEST_LOCK:
        cached = PATH_CACHE[path_group].get(ip)
    if cached:
        return [cached]
    return []


def cache_path(ip, path_group, path):
    with REQUEST_LOCK:
        PATH_CACHE[path_group][ip] = path


def get_paths_for_ip(ip, path_group, default_paths):
    cached = get_cached_paths(ip, path_group)
    if not cached:
        return list(default_paths)

    ordered = list(cached)
    for item in default_paths:
        if item not in ordered:
            ordered.append(item)
    return ordered


def load_credentials():
    ip_credentials = {}
    global_credentials = []

    if os.path.exists(PASSWORDS_CSV):
        try:
            with open(PASSWORDS_CSV, "r", encoding="utf-8", newline="") as csv_file:
                reader = csv.DictReader(csv_file)
                for row in reader:
                    username = (row.get("username") or USERNAME).strip()
                    password = (row.get("password") or "").strip()
                    ip = (row.get("ip") or "").strip()
                    if not password:
                        continue

                    credential = (username, password)
                    if ip:
                        ip_credentials.setdefault(ip, []).append(credential)
                    else:
                        global_credentials.append(credential)
        except Exception as exc:
            record_error("N/A", "credential-load", f"讀取 {PASSWORDS_CSV} 失敗: {exc}")

    default_credentials = [(USERNAME, PASSWORD)]
    default_credentials.extend([(USERNAME, pw) for pw in FALLBACK_PASSWORDS])

    def dedupe(items):
        seen = set()
        unique = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
        return unique

    for ip, creds in ip_credentials.items():
        ip_credentials[ip] = dedupe(creds + global_credentials + default_credentials)

    global_credentials = dedupe(global_credentials + default_credentials)
    return ip_credentials, global_credentials


def get_auth_candidates(ip):
    return IP_CREDENTIALS.get(ip, GLOBAL_CREDENTIALS)


def load_patch_rules():
    if not os.path.exists(PATCH_FILE):
        return DEFAULT_PATCH_RULES


def load_validation_rules():
    default_rules = {
        "required_keys": [
            "voip/line/0/auth_name",
            "voip/line/0/auth_password",
            "voip/line/0/enabled",
        ],
        "forbidden_patterns": [
            ";;",
            "auth_password=",
        ],
    }

    if not os.path.exists(VALIDATION_FILE):
        return default_rules

    try:
        with open(VALIDATION_FILE, "r", encoding="utf-8") as rules_file:
            data = json.load(rules_file)

        required_keys = data.get("required_keys", default_rules["required_keys"])
        forbidden_patterns = data.get("forbidden_patterns", [])

        if not isinstance(required_keys, list):
            required_keys = default_rules["required_keys"]
        if not isinstance(forbidden_patterns, list):
            forbidden_patterns = []

        return {
            "required_keys": required_keys,
            "forbidden_patterns": forbidden_patterns,
        }
    except Exception as exc:
        record_error("N/A", "validation-load", f"讀取 {VALIDATION_FILE} 失敗，改用預設驗證規則: {exc}")
        return default_rules


def validate_config_text(text):
    rules = load_validation_rules()
    errors = []

    keys = set()
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            errors.append(f"Line {idx}: 缺少 '='")
            continue
        key, _ = line.split("=", 1)
        keys.add(key)

    for key in rules["required_keys"]:
        if key not in keys:
            errors.append(f"缺少必要 key: {key}")

    for pattern in rules["forbidden_patterns"]:
        if pattern == "auth_password=":
            if "auth_password=" in text and text.count("auth_password=") > 1:
                errors.append("發現重複 auth_password 設定")
            continue
        if pattern and pattern in text:
            errors.append(f"發現禁止字串: {pattern}")

    return len(errors) == 0, errors


def write_diff_report(mac, original_text, modified_text):
    ensure_dir(DIFF_DIR)

    diff_lines = unified_diff(
        original_text.splitlines(keepends=True),
        modified_text.splitlines(keepends=True),
        fromfile=f"{mac}.orig.cfg",
        tofile=f"{mac}.modified.cfg",
        lineterm="",
    )
    diff_text = "\n".join(diff_lines)
    if not diff_text:
        diff_text = "# No differences detected\n"

    diff_path = os.path.join(DIFF_DIR, f"{mac}.diff")
    with open(diff_path, "w", encoding="utf-8") as diff_file:
        diff_file.write(diff_text)
    return diff_path

    try:
        with open(PATCH_FILE, "r", encoding="utf-8") as patch_file:
            data = json.load(patch_file)

        replace_rules = data.get("replace")
        set_rules = data.get("set")

        if not isinstance(replace_rules, list):
            replace_rules = []
        if not isinstance(set_rules, dict):
            set_rules = {}

        return {"replace": replace_rules, "set": set_rules}
    except Exception as exc:
        record_error("N/A", "patch-load", f"讀取 {PATCH_FILE} 失敗，改用預設 patch: {exc}")
        return DEFAULT_PATCH_RULES


def apply_patch_rules(text, rules):
    output = text
    for item in rules.get("replace", []):
        source = item.get("from", "")
        target = item.get("to", "")
        if source:
            output = output.replace(source, target)

    set_rules = rules.get("set", {})
    if not set_rules:
        return output

    lines = output.splitlines()
    seen_keys = set()
    new_lines = []

    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            if key in set_rules:
                line = f"{key}={set_rules[key]}"
                seen_keys.add(key)
        new_lines.append(line)

    for key, value in set_rules.items():
        if key not in seen_keys:
            new_lines.append(f"{key}={value}")

    output = "\n".join(new_lines)
    if text.endswith("\n"):
        output += "\n"
    return output


def get_template_text():
    if os.path.exists(TEMPLATE_FILE):
        try:
            with open(TEMPLATE_FILE, "r", encoding="utf-8") as template_file:
                return template_file.read()
        except Exception as exc:
            record_error("N/A", "template-load", f"讀取 {TEMPLATE_FILE} 失敗，改用內建模板: {exc}")
    return TEMPLATE


def print_error_summary():
    if not ERRORS:
        print("\n[SUMMARY] 全部流程完成，沒有錯誤。")
        LOGGER.info("無錯誤，流程完成")
        return

    print("\n===== Error Summary =====")
    LOGGER.info("===== Error Summary =====")
    for idx, err in enumerate(ERRORS, start=1):
        line = f"{idx}. IP={err['ip']} | Stage={err['stage']} | Reason={err['reason']}"
        print(line)
        LOGGER.info(line)


def scan_ip(ip):
    for base_url in get_base_urls(ip):
        url = f"{base_url}/AdminPage/"
        response, error = safe_request("GET", url)
        if error:
            continue
        if response is not None and response.status_code == 200 and "AudioCodes" in response.text:
            print(f"[FOUND] AudioCodes 電話 → {ip}")
            LOGGER.info("找到電話 %s (%s)", ip, url)
            return ip
    return None


def discover_phones(multithread=True):
    print("[INFO] 正在掃描網段尋找 AudioCodes 電話...")
    LOGGER.info("開始掃描網段 %s1-254", NETWORK_PREFIX)

    ips = [f"{NETWORK_PREFIX}{i}" for i in range(1, 255)]
    found = []

    if multithread:
        with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_WORKERS) as executor:
            futures = {executor.submit(scan_ip, ip): ip for ip in ips}
            iterator = progress_iter(
                concurrent.futures.as_completed(futures),
                total=len(futures),
                desc="掃描中",
            )
            for future in iterator:
                result = future.result()
                if result:
                    found.append(result)
    else:
        iterator = progress_iter(ips, total=len(ips), desc="掃描中")
        for ip in iterator:
            result = scan_ip(ip)
            if result:
                found.append(result)

    print(f"[INFO] 共發現 {len(found)} 部電話")
    LOGGER.info("掃描完成，共發現 %s 部電話", len(found))
    return found


def get_mac_address(ip):
    last_reason = "無可用 MAC API 回應"
    candidates = get_auth_candidates(ip)

    paths = get_paths_for_ip(ip, "mac", MAC_PATHS)
    for path in paths:
        for base_url in get_base_urls(ip):
            url = f"{base_url}{path}"
            for username, password in candidates:
                response, error = safe_request(
                    "GET",
                    url,
                    auth=HTTPBasicAuth(username, password),
                )
                if error:
                    last_reason = f"connection error: {error}"
                    continue

                if response.status_code == 401:
                    last_reason = "401 Unauthorized"
                    continue

                if response.status_code == 404:
                    last_reason = "404 API not found"
                    break

                if response.status_code >= 500:
                    last_reason = f"{response.status_code} Server Error"
                    continue

                if response.status_code == 200:
                    text = response.text.upper()
                    for token in text.split():
                        if len(token) == 17 and token.count(":") == 5:
                            cache_path(ip, "mac", path)
                            return token.replace(":", "")
                    last_reason = "MAC format not found in response"

    record_error(ip, "get-mac", last_reason)
    return None


# -------------------------------
# Full Flow：下載 → 修改 → 上載
# -------------------------------
def download_config(ip):
    last_reason = "無可用下載 API 回應"
    candidates = get_auth_candidates(ip)

    paths = get_paths_for_ip(ip, "export", EXPORT_PATHS)
    for path in paths:
        for base_url in get_base_urls(ip):
            url = f"{base_url}{path}"
            for username, password in candidates:
                response, error = safe_request(
                    "GET",
                    url,
                    auth=HTTPBasicAuth(username, password),
                )
                if error:
                    last_reason = f"connection error: {error}"
                    continue

                if response.status_code == 401:
                    last_reason = "401 Unauthorized"
                    continue

                if response.status_code == 404:
                    last_reason = "404 API not found"
                    break

                if response.status_code >= 500:
                    last_reason = f"{response.status_code} Server Error"
                    continue

                if response.status_code == 200 and len(response.content) > 50:
                    cache_path(ip, "export", path)
                    return response.content

                if response.status_code == 200:
                    last_reason = "下載內容過短，疑似無效設定檔"

    record_error(ip, "download-config", last_reason)
    return None


def modify_config(raw_bytes):
    text = raw_bytes.decode("utf-8", errors="ignore")
    patch_rules = load_patch_rules()
    updated = apply_patch_rules(text, patch_rules)
    return updated.encode("utf-8")


def upload_config(ip, cfg_path):
    last_reason = "無可用上載 API 回應"
    candidates = get_auth_candidates(ip)

    try:
        with open(cfg_path, "rb") as cfg_file:
            cfg_bytes = cfg_file.read()
    except Exception as exc:
        record_error(ip, "upload-config", f"讀取上載檔案失敗: {exc}")
        return False

    file_name = os.path.basename(cfg_path)
    paths = get_paths_for_ip(ip, "import", IMPORT_PATHS)
    for path in paths:
        for base_url in get_base_urls(ip):
            url = f"{base_url}{path}"
            for username, password in candidates:
                files = {
                    "file": (file_name, cfg_bytes, "application/octet-stream")
                }
                response, error = safe_request(
                    "POST",
                    url,
                    auth=HTTPBasicAuth(username, password),
                    files=files,
                )
                if error:
                    last_reason = f"connection error: {error}"
                    continue

                if response.status_code in (200, 302):
                    cache_path(ip, "import", path)
                    return True

                if response.status_code == 401:
                    last_reason = "401 Unauthorized"
                    continue

                if response.status_code == 404:
                    last_reason = "404 API not found"
                    break

                if response.status_code >= 500:
                    last_reason = f"{response.status_code} Server Error"
                    continue

                last_reason = f"HTTP {response.status_code}"

    record_error(ip, "upload-config", last_reason)
    return False


def reboot_phone(ip):
    last_reason = "無可用重啟 API 回應"
    candidates = get_auth_candidates(ip)
    paths = get_paths_for_ip(ip, "reboot", REBOOT_PATHS)

    for path in paths:
        for base_url in get_base_urls(ip):
            url = f"{base_url}{path}"
            for username, password in candidates:
                response, error = safe_request(
                    "POST",
                    url,
                    auth=HTTPBasicAuth(username, password),
                )
                if error:
                    last_reason = f"connection error: {error}"
                    continue

                if response.status_code in (200, 202, 302):
                    cache_path(ip, "reboot", path)
                    LOGGER.info("%s 重啟命令已送出", ip)
                    return True

                if response.status_code == 401:
                    last_reason = "401 Unauthorized"
                    continue

                if response.status_code == 404:
                    last_reason = "404 API not found"
                    break

                if response.status_code >= 500:
                    last_reason = f"{response.status_code} Server Error"
                    continue

                last_reason = f"HTTP {response.status_code}"

    record_error(ip, "reboot", last_reason)
    return False


def run_full_flow():
    ensure_dir(BACKUP_DIR)
    ensure_dir(MODIFIED_DIR)
    ensure_dir(DIFF_DIR)

    ips = discover_phones(multithread=False)

    success = 0
    fail = 0

    iterator = progress_iter(ips, total=len(ips), desc="Full Flow")
    for ip in iterator:
        print(f"\n===== 處理電話 {ip} =====")

        mac = get_mac_address(ip)
        if not mac:
            print(f"[FAIL] {ip} → 無法讀取 MAC")
            fail += 1
            continue

        raw_cfg = download_config(ip)
        if not raw_cfg:
            print(f"[FAIL] {ip} → 無法下載設定")
            fail += 1
            continue

        backup_path = os.path.join(BACKUP_DIR, f"{mac}.orig.cfg")
        try:
            with open(backup_path, "wb") as backup_file:
                backup_file.write(raw_cfg)
        except Exception as exc:
            record_error(ip, "backup-write", f"寫入備份失敗: {exc}")
            fail += 1
            continue

        modified_bytes = modify_config(raw_cfg)
        original_text = raw_cfg.decode("utf-8", errors="ignore")
        modified_text = modified_bytes.decode("utf-8", errors="ignore")

        valid, validation_errors = validate_config_text(modified_text)
        if not valid:
            record_error(ip, "config-validation", "; ".join(validation_errors[:5]))
            print(f"[FAIL] {ip} → 修改後設定驗證失敗")
            fail += 1
            continue

        modified_path = os.path.join(MODIFIED_DIR, f"{mac}.cfg")
        try:
            with open(modified_path, "wb") as modified_file:
                modified_file.write(modified_bytes)
        except Exception as exc:
            record_error(ip, "modified-write", f"寫入修改檔失敗: {exc}")
            fail += 1
            continue

        try:
            diff_path = write_diff_report(mac, original_text, modified_text)
            LOGGER.info("%s 差異檔已寫入: %s", ip, diff_path)
        except Exception as exc:
            record_error(ip, "diff-write", f"寫入差異檔失敗: {exc}")

        if DRY_RUN:
            print(f"[DRY-RUN] {ip} → 驗證完成，已跳過上載")
            LOGGER.info("%s dry-run 完成，已跳過上載", ip)
            success += 1
            continue

        if upload_config(ip, modified_path):
            print(f"[OK] {ip} → 上載成功")
            LOGGER.info("%s 上載成功", ip)

            if REBOOT_AFTER_UPLOAD:
                if reboot_phone(ip):
                    print(f"[OK] {ip} → 已送出重啟")
                else:
                    print(f"[WARN] {ip} → 重啟命令失敗")
            success += 1
        else:
            print(f"[FAIL] {ip} → 上載失敗")
            fail += 1

    print("\n===== Full Flow 結果 =====")
    print(f"成功：{success}")
    print(f"失敗：{fail}")


# -------------------------------
# Mode 3：Download‑Only（掃描 → 下載）
# -------------------------------
def run_download_only():
    ensure_dir(BACKUP_DIR)

    ips = discover_phones(multithread=True)

    success = 0
    fail = 0

    iterator = progress_iter(ips, total=len(ips), desc="Download")
    for ip in iterator:
        print(f"\n===== 下載設定 {ip} =====")

        mac = get_mac_address(ip)
        if not mac:
            print(f"[FAIL] {ip} → 無法讀取 MAC")
            fail += 1
            continue

        raw_cfg = download_config(ip)
        if not raw_cfg:
            print(f"[FAIL] {ip} → 無法下載設定")
            fail += 1
            continue

        backup_path = os.path.join(BACKUP_DIR, f"{mac}.cfg")
        try:
            with open(backup_path, "wb") as backup_file:
                backup_file.write(raw_cfg)
        except Exception as exc:
            record_error(ip, "backup-write", f"寫入備份失敗: {exc}")
            fail += 1
            continue

        print(f"[OK] {ip} → 已下載設定 → {backup_path}")
        LOGGER.info("%s 下載成功: %s", ip, backup_path)
        success += 1

    print("\n===== Download‑Only 結果 =====")
    print(f"成功下載：{success}")
    print(f"失敗：{fail}")


# -------------------------------
# Option 160：生成 MAC.cfg
# -------------------------------
def generate_cfg_content(user, pw):
    template = get_template_text()
    return template.format(USER=user, PASSWORD=pw)


def process_phone(ip):
    mac = get_mac_address(ip)
    if not mac:
        print(f"[FAIL] {ip} → 無法讀取 MAC")
        return False

    user = f"agent_{mac[-4:]}"
    pw = f"pw_{mac[-4:]}"

    cfg = generate_cfg_content(user, pw)

    out_path = os.path.join(OUTPUT_DIR, f"{mac}.cfg")
    try:
        with open(out_path, "w", encoding="utf-8") as cfg_file:
            cfg_file.write(cfg)
    except Exception as exc:
        record_error(ip, "cfg-write", f"寫入 {out_path} 失敗: {exc}")
        return False

    print(f"[OK] {ip} → 已生成 {out_path}")
    LOGGER.info("%s 生成設定成功: %s", ip, out_path)
    return True


def run_generate_mac_cfg():
    ensure_dir(OUTPUT_DIR)

    phones = discover_phones(multithread=True)

    success = 0
    fail = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=PROCESS_WORKERS) as executor:
        futures = {executor.submit(process_phone, ip): ip for ip in phones}
        iterator = progress_iter(
            concurrent.futures.as_completed(futures),
            total=len(futures),
            desc="生成CFG",
        )
        for future in iterator:
            ok = future.result()
            success += 1 if ok else 0
            fail += 0 if ok else 1

    print("\n===== MAC.cfg 生成結果 =====")
    print(f"成功：{success}")
    print(f"失敗：{fail}")


def parse_args():
    parser = ArgumentParser(description="AudioCodes Automation Mega-Tool")
    parser.add_argument("--mode", choices=["full", "dry", "gen", "download", "menu"], default="menu")
    parser.add_argument("--prefix", help="Network prefix, e.g. 172.16.11.")
    parser.add_argument("--scan-workers", type=int, help="Thread workers for scan")
    parser.add_argument("--process-workers", type=int, help="Thread workers for processing")
    parser.add_argument("--https", action="store_true", help="Prefer HTTPS")
    parser.add_argument("--no-alt-scheme", action="store_true", help="Disable HTTP/HTTPS fallback")
    parser.add_argument("--verify-tls", action="store_true", help="Enable TLS certificate validation")
    parser.add_argument("--ca-cert", help="Custom CA certificate file path")
    parser.add_argument("--retry", type=int, help="Retry attempts for network requests")
    parser.add_argument("--reboot", action="store_true", help="Reboot phone after successful upload")
    parser.add_argument("--dry-run", action="store_true", help="Run scan/download/modify/diff/validate only")
    parser.add_argument("--no-progress", action="store_true", help="Disable progress bars")
    return parser.parse_args()


def apply_args(args):
    global NETWORK_PREFIX
    global SCAN_WORKERS, PROCESS_WORKERS
    global USE_HTTPS, TRY_ALTERNATE_SCHEME
    global VERIFY_TLS, CA_CERT_PATH
    global RETRY_ATTEMPTS, REBOOT_AFTER_UPLOAD
    global ENABLE_PROGRESS, DRY_RUN

    if args.prefix:
        NETWORK_PREFIX = args.prefix
    if args.scan_workers:
        SCAN_WORKERS = max(1, args.scan_workers)
    if args.process_workers:
        PROCESS_WORKERS = max(1, args.process_workers)

    if args.https:
        USE_HTTPS = True
    if args.no_alt_scheme:
        TRY_ALTERNATE_SCHEME = False
    if args.verify_tls:
        VERIFY_TLS = True
    if args.ca_cert:
        CA_CERT_PATH = args.ca_cert
    if args.retry is not None:
        RETRY_ATTEMPTS = max(1, args.retry)
    if args.reboot:
        REBOOT_AFTER_UPLOAD = True
    if args.dry_run:
        DRY_RUN = True
    if args.no_progress:
        ENABLE_PROGRESS = False


# -------------------------------
# 主選單
# -------------------------------
def main():
    global IP_CREDENTIALS, GLOBAL_CREDENTIALS, DRY_RUN

    args = parse_args()
    apply_args(args)

    setup_logging()
    IP_CREDENTIALS, GLOBAL_CREDENTIALS = load_credentials()

    LOGGER.info("工具啟動，HTTPS=%s, TLS_VERIFY=%s", USE_HTTPS, VERIFY_TLS)

    if args.mode == "full":
        run_full_flow()
        return
    if args.mode == "dry":
        DRY_RUN = True
        run_full_flow()
        return
    if args.mode == "gen":
        run_generate_mac_cfg()
        return
    if args.mode == "download":
        run_download_only()
        return

    print("""
=========================================
 AudioCodes Automation Mega‑Tool
=========================================
1. Full Flow（掃描 → 下載 → 修改 → 上載）
2. Dry Run（掃描 → 下載 → 修改 → Diff → 驗證）
3. Generate MAC.cfg（Option 160）
4. Download‑Only（掃描 → 下載）
=========================================
""")

    choice = input("請選擇模式：")

    if choice == "1":
        run_full_flow()
    elif choice == "2":
        DRY_RUN = True
        run_full_flow()
    elif choice == "3":
        run_generate_mac_cfg()
    elif choice == "4":
        run_download_only()
    else:
        print("無效選項")


if __name__ == "__main__":
    try:
        main()
        print_error_summary()
        print("\n===== 結束 =====")
    finally:
        shutdown_logging()
