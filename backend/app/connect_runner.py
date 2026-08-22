#!/usr/bin/env python3
"""Mobius Connect runner.

Dials OUT to your Mobius instance and lets it run commands on this machine.
It only makes OUTBOUND HTTPS requests (no open ports), and it runs commands as
YOU, in your own environment -- the same trust model as running a coding CLI
locally. Remove the machine in the Connect app to revoke its token.

Pair AND install as a background service that survives reboots (recommended):
    curl -fsSL "https://YOUR-INSTANCE/api/connect/runner" | python3 - \
        --pair ABCD-EFGH --url "https://YOUR-INSTANCE" --install

Just try it in this terminal (stops on Ctrl-C):
    curl -fsSL "https://YOUR-INSTANCE/api/connect/runner" | python3 - \
        --pair ABCD-EFGH --url "https://YOUR-INSTANCE"

Manage the installed service:
    python3 ~/.mobius-connect/runner.py --uninstall
"""
import argparse
import json
import os
import platform
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CONFIG_DIR = os.path.expanduser("~/.mobius-connect")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
RUNNER_PATH = os.path.join(CONFIG_DIR, "runner.py")
LOG_PATH = os.path.join(CONFIG_DIR, "service.log")
LAUNCHD_LABEL = "sh.mobius.connect"
LAUNCHD_PLIST = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % LAUNCHD_LABEL)
SYSTEMD_UNIT = os.path.expanduser("~/.config/systemd/user/mobius-connect.service")


def _load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    os.chmod(CONFIG_PATH, 0o600)


def _post(url, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _pair(base, code):
    out = _post(base + "/api/connect/pair", {"code": code})
    cfg = {"url": base, "host_id": out["host_id"], "token": out["token"]}
    _save_config(cfg)
    print("Paired as '%s'." % out.get("name", "machine"))
    return cfg


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def _self_download(base):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with urllib.request.urlopen(base + "/api/connect/runner", timeout=30) as resp:
        src = resp.read()
    with open(RUNNER_PATH, "wb") as fh:
        fh.write(src)
    os.chmod(RUNNER_PATH, 0o755)


def _install_launchd(py):
    os.makedirs(os.path.dirname(LAUNCHD_PLIST), exist_ok=True)
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        "  <key>Label</key><string>%s</string>\n"
        "  <key>ProgramArguments</key><array>"
        "<string>%s</string><string>%s</string></array>\n"
        "  <key>RunAtLoad</key><true/>\n"
        "  <key>KeepAlive</key><true/>\n"
        "  <key>StandardOutPath</key><string>%s</string>\n"
        "  <key>StandardErrorPath</key><string>%s</string>\n"
        "</dict></plist>\n"
    ) % (LAUNCHD_LABEL, py, RUNNER_PATH, LOG_PATH, LOG_PATH)
    with open(LAUNCHD_PLIST, "w", encoding="utf-8") as fh:
        fh.write(plist)
    _run(["launchctl", "unload", LAUNCHD_PLIST])
    r = _run(["launchctl", "load", "-w", LAUNCHD_PLIST])
    if r.returncode != 0:
        print("launchctl load failed: %s" % r.stderr.strip())
        return False
    print("Installed as a launchd service (starts at login, restarts if it crashes).")
    print("  Logs:      tail -f %s" % LOG_PATH)
    print("  Uninstall: python3 %s --uninstall" % RUNNER_PATH)
    return True


def _install_systemd(py):
    os.makedirs(os.path.dirname(SYSTEMD_UNIT), exist_ok=True)
    unit = (
        "[Unit]\n"
        "Description=Mobius Connect runner\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        "ExecStart=%s %s\n"
        "Restart=always\n"
        "RestartSec=5\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    ) % (py, RUNNER_PATH)
    with open(SYSTEMD_UNIT, "w", encoding="utf-8") as fh:
        fh.write(unit)
    _run(["systemctl", "--user", "daemon-reload"])
    r = _run(["systemctl", "--user", "enable", "--now", "mobius-connect.service"])
    if r.returncode != 0:
        print("systemctl --user failed: %s" % r.stderr.strip())
        return _install_background(py)
    linger = _run(["loginctl", "enable-linger", os.environ.get("USER", "")])
    if linger.returncode != 0:
        print("note: could not enable linger; the service may pause when you log "
              "out (%s)" % linger.stderr.strip())
    print("Installed as a systemd --user service (starts at boot, restarts if it crashes).")
    print("  Status:    systemctl --user status mobius-connect")
    print("  Logs:      journalctl --user -u mobius-connect -f")
    print("  Uninstall: python3 %s --uninstall" % RUNNER_PATH)
    return True


def _install_background(py):
    # Last resort (no launchd/systemd): detached background process. Survives
    # closing the terminal, but NOT a reboot.
    with open(LOG_PATH, "ab") as log:
        subprocess.Popen(
            [py, RUNNER_PATH], stdout=log, stderr=log,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    print("Started in the background (survives closing this terminal, NOT a reboot).")
    print("  Logs: tail -f %s" % LOG_PATH)
    print("  Stop: pkill -f %s" % RUNNER_PATH)
    return True


def _install_service(cfg):
    _self_download(cfg["url"])
    py = sys.executable or "python3"
    system = platform.system()
    if system == "Darwin":
        return _install_launchd(py)
    if system == "Linux":
        return _install_systemd(py)
    return _install_background(py)


def _uninstall_service():
    system = platform.system()
    if system == "Darwin" and os.path.exists(LAUNCHD_PLIST):
        _run(["launchctl", "unload", LAUNCHD_PLIST])
        os.remove(LAUNCHD_PLIST)
        print("Removed launchd service.")
    elif system == "Linux" and os.path.exists(SYSTEMD_UNIT):
        _run(["systemctl", "--user", "disable", "--now", "mobius-connect.service"])
        os.remove(SYSTEMD_UNIT)
        _run(["systemctl", "--user", "daemon-reload"])
        print("Removed systemd service.")
    else:
        print("No service unit found. If it is running in the background, "
              "stop it with: pkill -f %s" % RUNNER_PATH)
    print("(Your token in %s is kept; remove the machine in Connect to revoke it.)"
          % CONFIG_PATH)


def _run_command(cmd, cwd, timeout):
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=(cwd or None), timeout=timeout,
        )
        return proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        return "", "command timed out after %ss" % timeout, 124
    except Exception as exc:  # noqa: BLE001 - report any spawn failure back
        return "", "runner error: %s" % exc, 1


def _serve(cfg):
    base = cfg["url"].rstrip("/")
    token = cfg["token"]
    ctx = ssl.create_default_context()
    plat = "%s %s" % (platform.system(), platform.release())
    stream_url = base + "/api/connect/stream?platform=" + urllib.parse.quote(plat)
    backoff = 1
    print("Connecting to %s ..." % base)
    while True:
        try:
            req = urllib.request.Request(stream_url)
            req.add_header("Authorization", "Bearer " + token)
            req.add_header("Accept", "text/event-stream")
            with urllib.request.urlopen(req, timeout=None, context=ctx) as stream:
                print("Connected. This machine is now reachable from Mobius.")
                backoff = 1
                for raw in stream:
                    line = raw.decode("utf-8", "replace").rstrip("\n")
                    if not line.startswith("data:"):
                        continue
                    try:
                        evt = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if evt.get("type") != "exec":
                        continue
                    print("$ " + evt.get("cmd", ""))
                    out, err, rc = _run_command(
                        evt.get("cmd", ""), evt.get("cwd"),
                        int(evt.get("timeout", 60)),
                    )
                    try:
                        _post(base + "/api/connect/result", {
                            "request_id": evt.get("request_id"),
                            "stdout": out, "stderr": err, "exit_code": rc,
                        }, token=token)
                    except urllib.error.URLError as exc:
                        print("failed to report result: %s" % exc)
        except KeyboardInterrupt:
            print("\nStopped.")
            return
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                print("Token rejected (removed from Mobius?). Re-pair to reconnect.")
                return
            print("HTTP %s; retrying in %ss" % (exc.code, backoff))
        except urllib.error.URLError as exc:
            print("connection lost (%s); retrying in %ss" % (exc.reason, backoff))
        time.sleep(backoff)
        backoff = min(backoff * 2, 30)


def main():
    ap = argparse.ArgumentParser(description="Mobius Connect runner")
    ap.add_argument("--pair", help="one-time pairing code from the Connect app")
    ap.add_argument("--url", help="your Mobius instance URL")
    ap.add_argument("--install", action="store_true",
                    help="install as a service that starts on boot")
    ap.add_argument("--uninstall", action="store_true",
                    help="remove the installed service")
    ap.add_argument("--foreground", action="store_true",
                    help="run in this terminal (Ctrl-C stops it)")
    args = ap.parse_args()

    if args.uninstall:
        _uninstall_service()
        return

    cfg = _load_config()
    if args.pair:
        base = (args.url or cfg.get("url") or "").rstrip("/")
        if not base:
            print("Missing --url")
            sys.exit(2)
        cfg = _pair(base, args.pair.strip())
    if not cfg.get("token"):
        print("Not paired. Run with --pair CODE --url URL first.")
        sys.exit(2)

    if args.install:
        _install_service(cfg)
        return

    _serve(cfg)


if __name__ == "__main__":
    main()
