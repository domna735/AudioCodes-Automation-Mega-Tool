from flask import Flask, request, Response
import base64
import time
import os
import json
import argparse

app = Flask(__name__)

FAKE_MAC = "00:11:22:33:44:55"
FAKE_CONFIG = """voip/line/0/auth_name=user123
voip/line/0/auth_password=pass123
voip/codec/codec_info/0/name=PCMU
voip/codec/codec_info/1/name=PCMA
"""

USERNAME = "admin"
PASSWORD = "1234"
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def host_allowed(req):
    host = (req.host or "").split(":", 1)[0].lower()
    return True  # allow all hosts; behavior decided per-host below


def get_behavior_for_host(host_ip):
    """Return behavior string by host_ip to simulate devices.

    behaviors:
      127.0.0.1 -> normal
      127.0.0.2 -> slow (1.5s)
      127.0.0.3 -> server error (500)
      127.0.0.4 -> service unavailable (503)
      127.0.0.5 -> timeout (sleep > tool timeout)
      others -> not found (404)
    """
    # determine by last octet to avoid prefix collisions like 127.0.0.104
    try:
        parts = host_ip.split('.')
        last = int(parts[-1])
    except Exception:
        return "notfound"

    if last == 1:
        return "normal"
    if last == 2:
        return "slow"
    if last == 3:
        return "error"
    if last == 4:
        return "unavailable"
    if last == 5:
        return "timeout"
    return "notfound"


def load_case(case_arg=None):
    """Load a case JSON from a file path or cases/case_{id}.json.

    Returns the loaded dict or None.
    """
    if not case_arg:
        case_arg = os.environ.get('ACSA_CASE')
    if not case_arg:
        return None

    # direct file
    if os.path.exists(case_arg) and case_arg.lower().endswith('.json'):
        try:
            with open(case_arg, 'r', encoding='utf-8') as fh:
                return json.load(fh)
        except Exception:
            return None

    # try common names under cases/
    candidates = [
        f"cases/case_{case_arg}.json",
        f"cases/acsa_case_{case_arg}_patch.json",
        f"acsa_case_{case_arg}_patch.json",
        f"acsa_case_{case_arg}.json",
        f"case_{case_arg}.json",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as fh:
                    return json.load(fh)
            except Exception:
                return None
    return None


# load case at startup if requested
CASE = None
CASE_ARG = None
try:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--case')
    ns, _ = parser.parse_known_args()
    CASE_ARG = ns.case
except Exception:
    CASE_ARG = None

loaded = load_case(CASE_ARG)
if not loaded:
    # also try env var
    loaded = load_case(os.environ.get('ACSA_CASE'))
CASE = loaded

if CASE:
    # override FAKE_CONFIG if case provides config mapping
    cfg = CASE.get('config')
    if isinstance(cfg, dict):
        # convert mapping to k=v lines
        lines = [f"{k}={v}" for k, v in cfg.items()]
        FAKE_CONFIG = "\n".join(lines) + "\n"


@app.before_request
def block_loopback_aliases():
    # allow request but we will decide behavior based on Host header
    return None

def check_auth(req):
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    encoded = auth.split(" ", 1)[1]
    decoded = base64.b64decode(encoded).decode()
    user, pw = decoded.split(":", 1)
    return user == USERNAME and pw == PASSWORD

def require_auth():
    return Response("Unauthorized", 401, {"WWW-Authenticate": 'Basic realm="Login Required"'})

@app.route("/AdminPage/")
def admin_page():
    host = (request.host or "").split(":", 1)[0]
    beh = get_behavior_for_host(host)
    if beh == "normal":
        return Response("AudioCodes Fake Device", mimetype="text/plain")
    if beh == "slow":
        time.sleep(1.5)
        return Response("AudioCodes Fake Device (slow)", mimetype="text/plain")
    if beh == "error":
        return Response("Server Error", status=500, mimetype="text/plain")
    if beh == "unavailable":
        return Response("Service Unavailable", status=503, mimetype="text/plain")
    if beh == "timeout":
        time.sleep(5)
        return Response("No Response", mimetype="text/plain")
    return Response("Not AudioCodes", 404, mimetype="text/plain")

@app.route("/AdminPage/get_mac_address.cgi")
def get_mac():
    host = (request.host or "").split(":", 1)[0]
    beh = get_behavior_for_host(host)
    if not check_auth(request):
        return require_auth()
    if beh == "normal":
        return Response(FAKE_MAC, mimetype="text/plain")
    if beh == "slow":
        time.sleep(1.5)
        return Response(FAKE_MAC, mimetype="text/plain")
    if beh == "error":
        return Response("", status=500)
    if beh == "unavailable":
        return Response("", status=503)
    if beh == "timeout":
        time.sleep(5)
        return Response(FAKE_MAC, mimetype="text/plain")
    return Response("Not Found", 404, mimetype="text/plain")

@app.route("/AdminPage/get_device_info.cgi")
def get_device_info():
    if not check_auth(request):
        return require_auth()
    return Response(f"MAC={FAKE_MAC}", mimetype="text/plain")

@app.route("/AdminPage/conf_export.cgi")
@app.route("/AdminPage/export_cfg.cgi")
def export_cfg():
    host = (request.host or "").split(":", 1)[0]
    beh = get_behavior_for_host(host)
    if not check_auth(request):
        return require_auth()
    if beh in ("normal", "slow", "timeout"):
        if beh == "slow":
            time.sleep(1.5)
        if beh == "timeout":
            time.sleep(5)
        return Response(FAKE_CONFIG, mimetype="text/plain")
    if beh == "error":
        return Response("", status=500)
    if beh == "unavailable":
        return Response("", status=503)
    return Response("Not Found", 404, mimetype="text/plain")

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
