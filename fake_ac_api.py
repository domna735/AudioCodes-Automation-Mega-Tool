from flask import Flask, request, Response
import base64
import random
import time
import os
import json
import argparse

app = Flask(__name__)

USERNAME = "admin"
PASSWORD = "1234"
FAKE_MAC = "00:11:22:33:44:55"

# ============================================================
#  Case Loader
# ============================================================

def load_case(case_arg=None):
    """Load case JSON from file path or case ID."""
    if not case_arg:
        case_arg = os.environ.get("ACSA_CASE")

    if not case_arg:
        return None

    # direct file path
    if os.path.exists(case_arg) and case_arg.endswith(".json"):
        with open(case_arg, "r", encoding="utf-8") as f:
            return json.load(f)

    # search common names
    candidates = [
        f"cases/case_{case_arg}.json",
        f"cases/acsa_case_{case_arg}.json",
        f"cases/acsa_case_{case_arg}_patch.json",
        f"case_{case_arg}.json",
        f"acsa_case_{case_arg}.json",
    ]

    for p in candidates:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)

    return None


# ============================================================
#  Load Case at Startup
# ============================================================

CASE = None
try:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--case")
    ns, _ = parser.parse_known_args()
    CASE = load_case(ns.case)
except Exception:
    CASE = load_case(os.environ.get("ACSA_CASE"))

# Default config (fallback)
DEFAULT_CONFIG = {
    "voip/line/0/auth_name": "user123",
    "voip/line/0/auth_password": "pass123",
    "voip/codec/codec_info/0/name": "PCMU",
    "voip/codec/codec_info/1/name": "PCMA",
}

# Case-driven config
CONFIG_MAP = CASE.get("config", DEFAULT_CONFIG) if CASE else DEFAULT_CONFIG

# Convert config dict → key=value text
FAKE_CONFIG = "\n".join(f"{k}={v}" for k, v in CONFIG_MAP.items()) + "\n"

# Global behavior
GLOBAL_BEHAVIOR = CASE.get("behavior", {}) if CASE else {}

# Per-host behavior map
BEHAVIOR_MAP = CASE.get("behavior_map", {}) if CASE else {}

# Endpoint behavior map (global overrides by route)
ENDPOINT_BEHAVIOR = CASE.get("endpoint_behavior", {}) if CASE else {}


# ============================================================
#  Behavior Resolver
# ============================================================

def resolve_behavior(host_ip, endpoint=None):
    """Return behavior dict for this host and optional endpoint."""
    last = host_ip.split(".")[-1]
    behavior = {}

    # 1) Per-host behavior_map
    if last in BEHAVIOR_MAP:
        behavior.update(BEHAVIOR_MAP[last])

    # 2) Global behavior
    if GLOBAL_BEHAVIOR:
        behavior.update(GLOBAL_BEHAVIOR)

    # 3) Endpoint behavior (route-specific)
    if endpoint and endpoint in ENDPOINT_BEHAVIOR:
        endpoint_behavior = ENDPOINT_BEHAVIOR[endpoint]
        if isinstance(endpoint_behavior, dict):
            behavior.update(endpoint_behavior)

    # 4) Default behavior (legacy)
    if not behavior:
        behavior = {"mode": "normal"}

    return behavior


def apply_behavior(behavior):
    """Apply latency, timeout, or error based on behavior dict."""
    # random error injection (resilience testing)
    error_rate = behavior.get("random_error_rate", 0)
    try:
        error_rate = float(error_rate)
    except Exception:
        error_rate = 0

    if error_rate > 0 and random.random() < error_rate:
        outcome = random.choice(["500", "503", "timeout"])
        if outcome == "500":
            return Response("Random Server Error", status=500)
        if outcome == "503":
            return Response("Random Service Unavailable", status=503)
        time.sleep(999)
        return Response("Random Timeout", status=504)

    # timeout
    if behavior.get("timeout"):
        time.sleep(999)
        return Response("Timeout", status=504)

    # latency
    latency = behavior.get("latency_ms")
    if latency:
        time.sleep(latency / 1000)

    # forced status code
    status = behavior.get("status_code")
    if status and status != 200:
        return Response(f"Error {status}", status=status)

    # mode override
    mode = behavior.get("mode")
    if mode == "slow":
        time.sleep(1.5)
    elif mode == "error":
        return Response("Server Error", status=500)
    elif mode == "unavailable":
        return Response("Service Unavailable", status=503)
    elif mode == "timeout":
        time.sleep(999)
        return Response("Timeout", status=504)

    return None  # no override → continue normally


# ============================================================
#  Auth
# ============================================================

def check_auth(req):
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    encoded = auth.split(" ", 1)[1]
    decoded = base64.b64decode(encoded).decode()
    user, pw = decoded.split(":", 1)
    return user == USERNAME and pw == PASSWORD


def require_auth():
    return Response("Unauthorized", 401, {
        "WWW-Authenticate": 'Basic realm="Login Required"'
    })


# ============================================================
#  Routes
# ============================================================

@app.route("/AdminPage/")
def admin_page():
    host = request.host.split(":")[0]
    behavior = resolve_behavior(host, "/AdminPage/")

    override = apply_behavior(behavior)
    if override:
        return override

    return Response("AudioCodes Fake Device", mimetype="text/plain")


@app.route("/AdminPage/get_mac_address.cgi")
def get_mac():
    if not check_auth(request):
        return require_auth()

    host = request.host.split(":")[0]
    behavior = resolve_behavior(host, "/AdminPage/get_mac_address.cgi")

    override = apply_behavior(behavior)
    if override:
        return override

    return Response(FAKE_MAC, mimetype="text/plain")


@app.route("/AdminPage/get_device_info.cgi")
def get_device_info():
    if not check_auth(request):
        return require_auth()
    return Response(f"MAC={FAKE_MAC}", mimetype="text/plain")


@app.route("/AdminPage/conf_export.cgi")
@app.route("/AdminPage/export_cfg.cgi")
def export_cfg():
    if not check_auth(request):
        return require_auth()

    host = request.host.split(":")[0]
    behavior = resolve_behavior(host, "/AdminPage/conf_export.cgi")

    override = apply_behavior(behavior)
    if override:
        return override

    return Response(FAKE_CONFIG, mimetype="text/plain")


@app.route("/AdminPage/conf_import.cgi", methods=["POST"])
@app.route("/AdminPage/import_cfg.cgi", methods=["POST"])
@app.route("/AdminPage/import_config.cgi", methods=["POST"])
def import_cfg():
    if not check_auth(request):
        return require_auth()

    file = request.files.get("file")
    if file:
        print("=== Received Config Upload ===")
        print(file.read().decode())
        print("==============================")

    return "OK", 200


@app.route("/AdminPage/reboot.cgi", methods=["POST"])
@app.route("/AdminPage/restart.cgi", methods=["POST"])
def reboot():
    if not check_auth(request):
        return require_auth()
    return "Rebooting", 200


# ============================================================
#  Main
# ============================================================

if __name__ == "__main__":
    print("Loaded Case:", CASE)
    app.run(host="0.0.0.0", port=5000)

