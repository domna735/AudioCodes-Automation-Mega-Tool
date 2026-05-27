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
NETWORK_PREFIX = "127.0.0."
TIMEOUT = 1

USE_HTTPS = False
TRY_ALTERNATE_SCHEME = True
VERIFY_TLS = False
CA_CERT_PATH = ""
ACSA_CASE_ID = None
REVERSE_CASE_FILE = None
REVERSE_CASE_DIR = None
REVERSE_OUTPUT_DIR = "generated_cfg/reversed_cfg"

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

SCAN_WORKERS = 20
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
RESULTS = []
RESULT_LOCK = Lock()
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


def record_result(ip, status, elapsed_ms, reason=None):
    entry = {"ip": ip, "status": status, "elapsed_ms": elapsed_ms}
    if reason:
        entry["reason"] = reason
    with RESULT_LOCK:
        RESULTS.append(entry)
    LOGGER.info("Result %s: %s ms %s", ip, elapsed_ms, status)


def get_base_urls(ip):
    preferred = "https" if USE_HTTPS else "http"
    alternate = "http" if preferred == "https" else "https"

    urls = [f"{preferred}://{ip}:5000"]   # use explicit port for fake server tests
    if TRY_ALTERNATE_SCHEME:
        urls.append(f"{alternate}://{ip}:5000")
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


def load_case_config(case_id):
    """Load an ACSA case JSON by case id (flexible filenames).

    Returns dict or list (patch content) or None on failure.
    """
    # if case_id is a direct file path, load it
    if not case_id:
        return None

    if os.path.exists(case_id) and case_id.lower().endswith('.json'):
        try:
            with open(case_id, 'r', encoding='utf-8') as fh:
                return json.load(fh)
        except Exception as exc:
            record_error('N/A', 'case-load', f'讀取 {case_id} 失敗: {exc}')
            return None

    case_tokens = []
    raw_token = str(case_id).strip()
    case_tokens.append(raw_token)

    stem = os.path.splitext(os.path.basename(raw_token))[0]
    if stem and stem not in case_tokens:
        case_tokens.append(stem)

    for token in list(case_tokens):
        if token.startswith('case_'):
            suffix = token.split('_', 1)[1]
            if suffix and suffix not in case_tokens:
                case_tokens.append(suffix)
        elif token.startswith('acsa_case_'):
            suffix = token.split('acsa_case_', 1)[1]
            suffix = suffix.replace('_patch', '')
            if suffix and suffix not in case_tokens:
                case_tokens.append(suffix)

    candidates = []
    for token in case_tokens:
        candidates.extend([
            f"acsa_case_{token}_patch.json",
            f"acsa_case_{token}.json",
            f"case_{token}.json",
            os.path.join('cases', f'case_{token}.json'),
            os.path.join('cases', f'acsa_case_{token}_patch.json'),
        ])

    seen_candidates = set()
    unique_candidates = []
    for candidate in candidates:
        if candidate in seen_candidates:
            continue
        seen_candidates.add(candidate)
        unique_candidates.append(candidate)

    # try explicit names first
    for p in unique_candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception as exc:
                record_error("N/A", "case-load", f"讀取 {p} 失敗: {exc}")
                return None

    # fallback: search for any file containing the case id
    for fname in os.listdir('.'):
        low = fname.lower()
        if str(case_id) in low and fname.endswith('.json'):
            try:
                with open(fname, 'r', encoding='utf-8') as fh:
                    return json.load(fh)
            except Exception as exc:
                record_error("N/A", "case-load", f"讀取 {fname} 失敗: {exc}")
                return None

    record_error("N/A", "case-load", f"找不到 case {case_id} 的 JSON 檔案")
    return None


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


def load_json_payload(path):
    with open(path, "r", encoding="utf-8") as payload_file:
        return json.load(payload_file)


def render_cfg_from_case_payload(case_payload):
    if not isinstance(case_payload, dict):
        raise ValueError("case payload must be a JSON object")

    config_data = case_payload.get("config", case_payload)
    if not isinstance(config_data, dict):
        raise ValueError("case payload config must be a JSON object")

    config_map = {str(key): str(value) for key, value in config_data.items()}

    text_lines = [f"{key}={value}" for key, value in config_map.items()]
    rendered_text = "\n".join(text_lines)
    if rendered_text and not rendered_text.endswith("\n"):
        rendered_text += "\n"

    for patch in case_payload.get("patches", []):
        if not isinstance(patch, dict):
            continue

        replace_rules = patch.get("replace", [])
        if isinstance(replace_rules, list):
            for item in replace_rules:
                if not isinstance(item, dict):
                    continue
                source = str(item.get("from", ""))
                target = str(item.get("to", ""))
                if source:
                    rendered_text = rendered_text.replace(source, target)

        set_rules = patch.get("set", {})
        if isinstance(set_rules, dict):
            rendered_text = apply_patch_rules(rendered_text, {"replace": [], "set": {str(key): str(value) for key, value in set_rules.items()}})

    valid, errors = validate_config_text(rendered_text)
    if not valid:
        raise ValueError("; ".join(errors[:5]))

    return rendered_text


def write_cfg_from_case_file(case_path, output_dir):
    case_payload = load_json_payload(case_path)
    rendered_text = render_cfg_from_case_payload(case_payload)

    base_name = os.path.splitext(os.path.basename(case_path))[0]
    if base_name.endswith("_patch"):
        base_name = base_name[:-6]

    ensure_dir(output_dir)
    output_path = os.path.join(output_dir, f"{base_name}.cfg")
    with open(output_path, "w", encoding="utf-8") as cfg_file:
        cfg_file.write(rendered_text)

    return output_path


def run_reverse_generate_cfg(case_file=None, case_dir=None, output_dir=REVERSE_OUTPUT_DIR):
    ensure_dir(output_dir)

    case_paths = []
    if case_file:
        case_paths.append(case_file)
    if case_dir:
        for name in sorted(os.listdir(case_dir)):
            if name.lower().endswith(".json"):
                case_paths.append(os.path.join(case_dir, name))

    seen = set()
    unique_paths = []
    for path in case_paths:
        normalized = os.path.normpath(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(path)

    if not unique_paths:
        print("[ERROR] 未提供任何 case JSON 檔案")
        return

    success = 0
    fail = 0
    for case_path in unique_paths:
        try:
            output_path = write_cfg_from_case_file(case_path, output_dir)
            print(f"[OK] {case_path} → {output_path}")
            LOGGER.info("Reverse generated cfg: %s -> %s", case_path, output_path)
            success += 1
        except Exception as exc:
            record_error(case_path, "reverse-generate", f"JSON → cfg 失敗: {exc}")
            print(f"[FAIL] {case_path} → 轉換失敗: {exc}")
            fail += 1

    print("\n===== Reverse 生成結果 =====")
    print(f"成功：{success}")
    print(f"失敗：{fail}")


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
    start = time.time()
    last_reason = None
    for base_url in get_base_urls(ip):
        url = f"{base_url}/AdminPage/"
        response, error = safe_request("GET", url)
        elapsed = int((time.time() - start) * 1000)
        if error:
            last_reason = error
            continue
        if response is not None and response.status_code == 200 and "AudioCodes" in response.text:
            print(f"[FOUND] AudioCodes 電話 → {ip}")
            LOGGER.info("找到電話 %s (%s)", ip, url)
            record_result(ip, "FOUND", elapsed)
            return ip
        last_reason = f"HTTP {response.status_code}"

    elapsed = int((time.time() - start) * 1000)
    reason = last_reason or "not found"
    record_result(ip, "NOT_FOUND", elapsed, reason)
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

    # write per-IP results summary
    try:
        with open("results_scan.json", "w", encoding="utf-8") as rf:
            import json as _json

            with RESULT_LOCK:
                _json.dump({"results": RESULTS}, rf, indent=2, ensure_ascii=False)
    except Exception as exc:
        LOGGER.error("寫入 results_scan.json 失敗: %s", exc)
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


def process_single_device(ip, args):
    LOGGER.info(f"[{ip}] 開始處理單一設備")

    mac = get_mac_address(ip)
    if not mac:
        LOGGER.error(f"[{ip}] 無法取得 MAC")
        return

    LOGGER.info(f"[{ip}] MAC = {mac}")

    cfg = download_config(ip)
    if not cfg:
        LOGGER.error(f"[{ip}] 無法下載設定")
        return

    modified_cfg = modify_config(cfg)

    if args.dry_run:
        LOGGER.info(f"[{ip}] Dry Run 模式，不上載設定")
        write_diff_report(mac, cfg.decode("utf-8", errors="ignore"), modified_cfg.decode("utf-8", errors="ignore"))
        return

    upload_ok = upload_config(ip, modified_cfg)
    if not upload_ok:
        LOGGER.error(f"[{ip}] 上載失敗")
        return

    LOGGER.info(f"[{ip}] 上載成功")

    if args.reboot:
        reboot_phone(ip)
        LOGGER.info(f"[{ip}] 已送出 reboot 指令")


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
    

def run_acsa_fix():
    """Apply predefined ACSA fixes (Case 5, Case 43) to all discovered phones."""
    ensure_dir(BACKUP_DIR)
    ensure_dir(MODIFIED_DIR)
    ensure_dir(DIFF_DIR)

    # load patches: prefer selected case if provided, else auto-load known candidates
    patches = []
    if ACSA_CASE_ID:
        case_cfg = load_case_config(ACSA_CASE_ID)
        if not case_cfg:
            print(f"[ERROR] 無法載入 ACSA case {ACSA_CASE_ID} 的 JSON 檔案")
            return
        # allow the case JSON to be either a single patch dict or a list of patches
        if isinstance(case_cfg, list):
            patches.extend(case_cfg)
        else:
            patches.append(case_cfg)
    else:
        candidates = ["acsa_case_5_patch.json", "acsa_case_43_patch.json"]
        for p in candidates:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as pf:
                        data = json.load(pf)
                        patches.append(data)
                except Exception as exc:
                    LOGGER.error("讀取 ACSA patch %s 失敗: %s", p, exc)

        if not patches:
            print("[ERROR] 未找到任何 ACSA patch 檔案")
            return

    phones = discover_phones(multithread=True)
    success = 0
    fail = 0

    for ip in progress_iter(phones, total=len(phones), desc="ACSA Fix"):
        print(f"\n===== ACSA Fix {ip} =====")
        mac = get_mac_address(ip)
        if not mac:
            record_error(ip, "acsa-get-mac", "無法讀取 MAC")
            fail += 1
            continue

        raw_cfg = download_config(ip)
        if not raw_cfg:
            record_error(ip, "acsa-download", "無法下載設定")
            fail += 1
            continue

        text = raw_cfg.decode("utf-8", errors="ignore")

        for patch in patches:
            # apply replace then set
            text = apply_patch_rules(text, patch if isinstance(patch, dict) else {})

        modified_bytes = text.encode("utf-8")

        # validate
        valid, errors_list = validate_config_text(text)
        if not valid:
            record_error(ip, "acsa-validate", "; ".join(errors_list[:5]))
            fail += 1
            continue

        # write modified and diff
        modified_path = os.path.join(MODIFIED_DIR, f"{mac}.cfg")
        try:
            with open(modified_path, "wb") as mf:
                mf.write(modified_bytes)
        except Exception as exc:
            record_error(ip, "acsa-write", f"寫入失敗: {exc}")
            fail += 1
            continue

        try:
            diff_path = write_diff_report(mac, raw_cfg.decode("utf-8", errors="ignore"), text)
            LOGGER.info("ACSA diff for %s -> %s", ip, diff_path)
        except Exception:
            pass

        # upload
        if DRY_RUN:
            print(f"[DRY-RUN] {ip} → ACSA patch 已套用但跳過上載")
            success += 1
            continue

        if upload_config(ip, modified_path):
            print(f"[OK] {ip} → ACSA patch 上載成功")
            success += 1
        else:
            print(f"[FAIL] {ip} → ACSA patch 上載失敗")
            fail += 1

    print("\n===== ACSA Fix 結果 =====")
    print(f"成功：{success}")
    print(f"失敗：{fail}")


def parse_args():
    parser = ArgumentParser(description="AudioCodes Automation Mega-Tool")
    parser.add_argument("--mode", choices=["full", "dry", "gen", "download", "acsa_fix", "reverse", "menu"], default="menu")
    parser.add_argument("--acsa-case", help="ACSA case id to apply (e.g. 5 or 43)")
    parser.add_argument("--case-file", help="Single case JSON to convert back into cfg")
    parser.add_argument("--case-dir", help="Directory of case JSON files to convert back into cfg")
    parser.add_argument("--output-dir", help="Output directory for generated cfg files")
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
    parser.add_argument("--ip", help="指定單一 IP，不掃描網段", default=None)
    return parser.parse_args()


def apply_args(args):
    global NETWORK_PREFIX
    global SCAN_WORKERS, PROCESS_WORKERS
    global USE_HTTPS, TRY_ALTERNATE_SCHEME
    global VERIFY_TLS, CA_CERT_PATH
    global RETRY_ATTEMPTS, REBOOT_AFTER_UPLOAD
    global ENABLE_PROGRESS, DRY_RUN
    global LOGGER
    global REVERSE_CASE_FILE, REVERSE_CASE_DIR, REVERSE_OUTPUT_DIR

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
    if args.ip:
        target_ip = args.ip
        LOGGER.info(f"使用單一 IP 模式：{target_ip}")

        # 直接處理單一 IP，不掃描
        process_single_device(target_ip, args)
        return
    if getattr(args, 'acsa_case', None):
        try:
            # accept numeric or string ids
            globals()['ACSA_CASE_ID'] = str(args.acsa_case).strip()
            LOGGER.info("ACSA case set to %s", ACSA_CASE_ID)
        except Exception:
            LOGGER.error("無法設定 ACSA case: %s", args.acsa_case)

    if args.case_file:
        REVERSE_CASE_FILE = args.case_file
    if args.case_dir:
        REVERSE_CASE_DIR = args.case_dir
    if args.output_dir:
        REVERSE_OUTPUT_DIR = args.output_dir


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
    if args.mode == "reverse":
        case_file = args.case_file or (args.acsa_case if args.acsa_case and os.path.exists(args.acsa_case) else None)
        run_reverse_generate_cfg(case_file=case_file, case_dir=args.case_dir, output_dir=REVERSE_OUTPUT_DIR)
        return
    if args.mode == "acsa_fix":
        if args.dry_run:
            DRY_RUN = True
        run_acsa_fix()
        return
    if args.ip:
        process_single_device(args.ip, args)
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
