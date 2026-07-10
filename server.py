#!/usr/bin/env python3
"""GameVault Server — clean, simple, works."""

import os
import json
import shutil
import subprocess
import re
import shlex
import signal
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime

HOST = "192.168.29.158"
PORT = 8080
GAME_ROOT = "/tank/games"
LOG_FILE = "/root/gamemanager/transfer.log"
HTML_FILE = "/root/gamemanager/index.html"
LEGENDARY = "/root/.local/bin/legendary"
EPIC_INSTALL_ROOT = "/tank/games/epic"
EPIC_LOG = "/root/gamemanager/epic-install.log"
EPIC_STATE = "/root/gamemanager/epic-state.json"
SKIP_DIRS = {"steam", "epic", "pirated", "savedata", "setups", "gog"}

def get_nics():
    """Detect active network interfaces with IPs only."""
    nics = []
    try:
        out = subprocess.check_output(["ip", "-o", "link", "show"], text=True)
    except:
        return nics
    
    ip_out_all = ""
    try:
        ip_out_all = subprocess.check_output(["ip", "-o", "addr", "show"], text=True)
    except:
        pass
    
    iface_ips = {}
    for line in ip_out_all.strip().split('\n'):
        m = re.search(r'^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)', line)
        if m:
            iface_ips[m.group(1)] = m.group(2)
    
    # Get interface state (UP/DOWN)
    state_map = {}
    for line in out.strip().split('\n'):
        parts = line.split(':')
        if len(parts) < 2:
            continue
        iface = parts[1].strip()
        if 'state UP' in line or 'state UNKNOWN' in line:
            state_map[iface] = 'up'
        elif 'state DOWN' in line:
            state_map[iface] = 'down'
    
    # Find bridge members (slave interfaces)
    bridge_members = set()
    try:
        ctrl_out = subprocess.check_output(
            ["brctl", "show"], text=True, stderr=subprocess.DEVNULL
        )
        lines = ctrl_out.strip().split('\n')
        # Skip header lines (empty, just ID, or contain 'bridge name')
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 4:
                # Bridge name is parts[0], interfaces are parts[3:]
                bridge_name = parts[0]
                members = parts[3:]
                bridge_members.update(members)
    except:
        pass
    
    ifaces_seen = set()
    for line in out.strip().split('\n'):
        parts = line.split(':')
        if len(parts) < 2:
            continue
        iface = parts[1].strip()
        if iface in ('lo', 'docker0') or iface in ifaces_seen:
            continue
        
        # Skip bridge slave interfaces - they have no IP and aren't directly usable
        if iface in bridge_members:
            continue
        
        ip = iface_ips.get(iface)
        if not ip and state_map.get(iface) != 'up':
            continue
        
        ifaces_seen.add(iface)
        
        # Get speed based on interface type
        speed = "?"
        is_bridge = False
        link_type = ""
        try:
            link_type = subprocess.check_output(
                ["ip", "-o", "link", "show", iface], text=True, stderr=subprocess.DEVNULL
            )
            if "bridge" in link_type:
                is_bridge = True
            if "state DOWN" in link_type and not ip:
                continue  # skip down interfaces without IP
            
            if "wlan" in link_type or "wl" in iface.lower():
                # Wireless - try iw, fallback to generic speed
                try:
                    iw_out = subprocess.check_output(
                        ["iw", "dev", iface, "link"], text=True, stderr=subprocess.DEVNULL
                    )
                    sm = re.search(r'(?:rx|tx) bitrate:\s+([\d.]+)\s*(MBit/s|Mbps)', iw_out)
                    if sm:
                        speed = sm.group(1) + " MBit/s"
                except:
                    speed = "WiFi"
            else:
                # Wired - use ethtool
                try:
                    eth_out = subprocess.check_output(
                        ["ethtool", iface], text=True, stderr=subprocess.DEVNULL
                    )
                    sm = re.search(r'Speed: (\d+[Mm]b/s|Unknown)', eth_out)
                    if sm:
                        speed = sm.group(1)
                except:
                    pass
        except:
            pass
        
        status = "active"
        if state_map.get(iface) == 'down':
            status = "down"
        
        nics.append({
            "name": iface,
            "ip": ip if ip else "none",
            "speed": speed,
            "is_fast": False,
            "is_bridge": is_bridge,
            "status": status
        })
    
    return nics

def get_games():
    games = []
    if not os.path.exists(GAME_ROOT):
        return games
    # Scan each top-level directory
    for item in sorted(os.listdir(GAME_ROOT)):
        item_path = os.path.join(GAME_ROOT, item)
        if not os.path.isdir(item_path) or item.startswith('.'):
            continue
        
        if item in SKIP_DIRS:
            # For steam/epic/pirated, look inside for games
            if item in ("savedata", "setups", "gog"):
                continue  # skip utility dirs completely
            for sub in os.listdir(item_path):
                sub_path = os.path.join(item_path, sub)
                if not os.path.isdir(sub_path) or sub.startswith('.'):
                    continue
                info = scan_game_folder(sub_path, source_override=item)
                if info:
                    games.append(info)
        else:
            # Top-level folder is itself a game/category
            info = scan_game_folder(item_path)
            if info:
                games.append(info)
    return games

def scan_game_folder(folder_path, source_override=None):
    """Scan a single folder and return game info, or None if empty."""
    size = 0
    files = 0
    mtime = None
    for dp, dn, fn in os.walk(folder_path):
        for f in fn:
            fp = os.path.join(dp, f)
            try:
                s = os.stat(fp)
                size += s.st_size
                files += 1
                if mtime is None or s.st_mtime > mtime:
                    mtime = s.st_mtime
            except OSError:
                pass
    if files == 0:
        return None  # skip empty folders
    
    name = os.path.basename(folder_path)
    
    # Detect source: check if any subpath is a known source dir
    source = source_override
    if not source:
        source = "custom"
        # Check parent path for steam/epic/pirated/gog
        parent = os.path.basename(os.path.dirname(folder_path))
        if parent in ("steam", "epic", "pirated", "gog"):
            source = parent
    
    return {
        "name": name,
        "size_gb": round(size / 1073741824, 2),
        "file_count": files,
        "last_modified": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else "N/A",
        "source": source,
    }

def get_system():
    total, used, free = shutil.disk_usage(GAME_ROOT)
    games = get_games()
    total_size = sum(g["size_gb"] for g in games)
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
            uptime = f"{int(secs//3600)}h {int((secs%3600)//60)}m"
    except:
        uptime = "?"
    try:
        ip = [l for l in os.popen("hostname -I").read().split() if l.startswith("192.")][0]
    except:
        ip = "?"
    return {
        "total_gb": round(total / 1073741824, 1),
        "used_gb": round(used / 1073741824, 1),
        "free_gb": round(free / 1073741824, 1),
        "percent": round(used / total * 100, 1),
        "game_count": len(games),
        "total_size_gb": round(total_size, 1),
        "uptime": uptime,
        "ip": ip,
        "port": PORT,
        "nics": get_nics(),
    }

def get_utils():
    utils = []
    for name in ["savedata", "setups"]:
        path = os.path.join(GAME_ROOT, name)
        if not os.path.isdir(path):
            continue
        size = 0
        files = 0
        mtime = None
        for dp, dn, fn in os.walk(path):
            for f in fn:
                fp = os.path.join(dp, f)
                try:
                    s = os.stat(fp)
                    size += s.st_size
                    files += 1
                    if mtime is None or s.st_mtime > mtime:
                        mtime = s.st_mtime
                except OSError:
                    pass
        utils.append({
            "name": name,
            "size_gb": round(size / 1073741824, 2),
            "file_count": files,
            "last_modified": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else "N/A",
        })
    return utils

def log_line(path, line):
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")

def run_legendary(args, timeout=60):
    env = os.environ.copy()
    env["PATH"] = "/root/.local/bin:" + env.get("PATH", "")
    try:
        cp = subprocess.run([LEGENDARY] + args, text=True, capture_output=True, timeout=timeout, env=env)
        return {"ok": cp.returncode == 0, "code": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr}
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "code": 124, "stdout": e.stdout or "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "code": 1, "stdout": "", "stderr": str(e)}

def legendary_logged_in():
    res = run_legendary(["status"], timeout=20)
    text = (res.get("stdout", "") + res.get("stderr", ""))
    return "Epic account: <not logged in>" not in text and "No saved credentials" not in text

def get_epic_status():
    res = run_legendary(["status"], timeout=20)
    text = (res.get("stdout", "") + res.get("stderr", "")).strip()
    account = "not logged in"
    for line in text.splitlines():
        if line.startswith("Epic account:"):
            account = line.split(":", 1)[1].strip()
            break
    state = {}
    if os.path.exists(EPIC_STATE):
        try:
            with open(EPIC_STATE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}
    # Refresh process status so UI is live, not fake
    if state.get("running") and state.get("pid"):
        try:
            os.kill(int(state["pid"]), 0)
        except ProcessLookupError:
            state["running"] = False
            state["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                with open(EPIC_STATE, "w", encoding="utf-8") as f:
                    json.dump(state, f)
            except Exception:
                pass
        except PermissionError:
            pass
    tail = []
    if os.path.exists(EPIC_LOG):
        try:
            with open(EPIC_LOG, "r", encoding="utf-8", errors="ignore") as f:
                tail = [x.rstrip() for x in f.readlines()[-30:]]
        except Exception:
            pass
    progress = parse_epic_progress()
    return {"logged_in": legendary_logged_in(), "account": account, "raw": text[-2000:], "install_state": state, "progress": progress, "log_tail": tail}

def get_epic_library():
    if not legendary_logged_in():
        return {"success": False, "error": "not_logged_in", "games": []}
    res = run_legendary(["list", "--json"], timeout=120)
    if not res["ok"]:
        return {"success": False, "error": (res["stderr"] or res["stdout"])[-2000:], "games": []}
    try:
        data = json.loads(res["stdout"])
    except Exception as e:
        return {"success": False, "error": f"bad json: {e}", "games": []}
    games = []
    for g in data:
        games.append({
            "app_name": g.get("app_name") or g.get("appName") or g.get("app_title") or "",
            "title": g.get("app_title") or g.get("title") or g.get("app_name") or "Unknown",
            "version": g.get("version", ""),
            "can_run_offline": g.get("can_run_offline", False),
        })
    games.sort(key=lambda x: x["title"].lower())
    return {"success": True, "games": games}

def start_epic_install(app_name, title=None):
    if not legendary_logged_in():
        return {"success": False, "error": "Epic not logged in"}
    if not app_name:
        return {"success": False, "error": "Missing app_name"}
    os.makedirs(EPIC_INSTALL_ROOT, exist_ok=True)
    safe_title = title or app_name
    state = {"running": True, "app_name": app_name, "title": safe_title, "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    with open(EPIC_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f)
    log_line(EPIC_LOG, f"=== {state['started']} starting Epic install: {safe_title} ({app_name}) ===")
    # Legendary asks for confirmation on installs. In web mode there is no stdin,
    # so auto-confirm with `yes` and skip optional prompts. Run in its own process
    # group so Pause can stop the full pipeline cleanly.
    cmd = [LEGENDARY, "install", app_name, "--base-path", EPIC_INSTALL_ROOT, "--skip-sdl", "--skip-dlcs"]
    shell_cmd = "yes | " + " ".join(shlex.quote(x) for x in cmd)
    env = os.environ.copy()
    env["PATH"] = "/root/.local/bin:" + env.get("PATH", "")
    with open(EPIC_LOG, "ab", buffering=0) as lf:
        p = subprocess.Popen(["/bin/bash", "-lc", shell_cmd], stdout=lf, stderr=subprocess.STDOUT, env=env, preexec_fn=os.setsid)
    state["pid"] = p.pid
    state["pgid"] = os.getpgid(p.pid)
    state["command"] = shell_cmd
    with open(EPIC_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f)
    return {"success": True, "pid": p.pid, "install_root": EPIC_INSTALL_ROOT, "message": f"Started downloading {safe_title} to {EPIC_INSTALL_ROOT}"}

def parse_epic_progress():
    """Parse real Legendary log output for percent/speed/eta from latest run only."""
    lines = []
    if os.path.exists(EPIC_LOG):
        try:
            with open(EPIC_LOG, "r", encoding="utf-8", errors="ignore") as f:
                lines = [x.rstrip() for x in f.readlines()[-400:]]
        except Exception:
            lines = []
    # Only look at latest install block; prevents old crash/progress lines contaminating UI.
    last_start = -1
    for i, line in enumerate(lines):
        if line.startswith("=== ") and " starting Epic install:" in line:
            last_start = i
    if last_start >= 0:
        lines = lines[last_start:]
    percent = None
    speed = None
    eta = None
    downloaded = None
    failed = any(("EOFError" in x or "Traceback" in x) for x in lines)
    # Generic but conservative parser: ignore metadata percentages like compression savings.
    for line in reversed(lines):
        low = line.lower()
        if "compression savings" in low or "download size" in low or "install size" in low:
            continue
        if percent is None and ("progress" in low or "download" in low or "dlm" in low or "eta" in low):
            m = re.search(r'(\d{1,3}(?:\.\d+)?)\s*%', line)
            if m:
                try: percent = min(100.0, float(m.group(1)))
                except Exception: pass
        if speed is None:
            m = re.search(r'([\d.]+\s*(?:KiB|MiB|GiB|KB|MB|GB)/s)', line, re.I)
            if m: speed = m.group(1)
        if eta is None:
            m = re.search(r'ETA[:\s]+([^\s,;]+)', line, re.I)
            if m: eta = m.group(1)
        if downloaded is None:
            m = re.search(r'([\d.]+\s*(?:KiB|MiB|GiB|KB|MB|GB))\s*/\s*([\d.]+\s*(?:KiB|MiB|GiB|KB|MB|GB))', line, re.I)
            if m: downloaded = m.group(0)
    return {"percent": percent, "speed": speed, "eta": eta, "downloaded": downloaded, "failed": failed, "tail": lines[-30:]}

def safe_child(base, name):
    base = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base, name))
    if not (target == base or target.startswith(base + os.sep)):
        raise ValueError("invalid path")
    return target

def stop_epic_install():
    state = {}
    if os.path.exists(EPIC_STATE):
        try:
            with open(EPIC_STATE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}
    pid = state.get("pid")
    if not pid:
        return {"success": False, "error": "No active Epic install"}
    try:
        pgid = state.get("pgid")
        if pgid:
            os.killpg(int(pgid), signal.SIGTERM)
        else:
            os.kill(int(pid), signal.SIGTERM)
        state["running"] = False
        state["paused"] = True
        state["paused_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(EPIC_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f)
        log_line(EPIC_LOG, f"=== {state['paused_at']} paused install: {state.get('title','unknown')} ===")
        return {"success": True, "message": "Paused. Resume will continue from existing files."}
    except ProcessLookupError:
        state["running"] = False
        state["paused"] = True
        with open(EPIC_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f)
        return {"success": True, "message": "Process already stopped; marked paused."}
    except Exception as e:
        return {"success": False, "error": str(e)}

def resume_epic_install():
    state = {}
    if os.path.exists(EPIC_STATE):
        try:
            with open(EPIC_STATE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}
    app = state.get("app_name")
    title = state.get("title") or app
    if not app:
        return {"success": False, "error": "No paused Epic install found"}
    return start_epic_install(app, title)

def delete_game_folder(source, name):
    if source not in ("steam", "epic", "pirated", "gog", "custom"):
        return {"success": False, "error": "invalid source"}
    if not name:
        return {"success": False, "error": "missing name"}
    base = os.path.join(GAME_ROOT, source) if source != "custom" else GAME_ROOT
    try:
        target = safe_child(base, name)
    except Exception:
        return {"success": False, "error": "invalid path"}
    if not os.path.isdir(target):
        return {"success": False, "error": "folder not found"}
    try:
        shutil.rmtree(target)
        entry = f"{datetime.now():%Y-%m-%d %H:%M:%S} | delete | {source}/{name}"
        log_line(LOG_FILE, entry)
        return {"success": True, "deleted": target}
    except Exception as e:
        return {"success": False, "error": str(e)}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/" or p == "/index.html":
            with open(HTML_FILE, "rb") as f:
                html = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html)
        elif p == "/api/games":
            self._json(get_games())
        elif p == "/api/system":
            self._json(get_system())
        elif p == "/api/utils":
            self._json(get_utils())
        elif p == "/api/logs":
            logs = []
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    logs = [x.strip() for x in f.readlines()[-50:] if x.strip()]
            self._json(logs)
        elif p == "/api/network":
            self._json({"nics": get_nics()})
        elif p == "/api/epic/status":
            self._json(get_epic_status())
        elif p == "/api/epic/library":
            self._json(get_epic_library())
        else:
            self.send_error(404)

    def do_POST(self):
        p = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        if p == "/api/pull":
            name = body.get("name", "")
            size = body.get("size_gb", "?")
            # Real action: mark file as ready-to-copy + log it
            client_ip = self.client_address[0] if hasattr(self, 'client_address') else "unknown"
            entry = f"{datetime.now():%Y-%m-%d %H:%M:%S} | pull | {name} | {size}GB | from:{client_ip}"
            with open(LOG_FILE, "a") as f:
                f.write(entry + "\n")
            self._json({
                "success": True,
                "message": f"{name} ready on server share",
                "smb_path": f"\\\\192.168.29.158\\games",
                "instructions": f"Open File Explorer → {name} → copy to your laptop"
            })
        elif p == "/api/epic/auth":
            code = body.get("code", "").strip()
            if not code:
                self._json({"success": False, "error": "Paste authorizationCode from https://legendary.gl/epiclogin"})
            else:
                res = run_legendary(["auth", "--code", code], timeout=60)
                self._json({"success": res["ok"], "stdout": res["stdout"], "stderr": res["stderr"]})
        elif p == "/api/epic/install":
            self._json(start_epic_install(body.get("app_name", ""), body.get("title", "")))
        elif p == "/api/epic/pause":
            self._json(stop_epic_install())
        elif p == "/api/epic/resume":
            self._json(resume_epic_install())
        elif p == "/api/delete-game":
            self._json(delete_game_folder(body.get("source", ""), body.get("name", "")))
        else:
            self.send_error(404)

if __name__ == "__main__":
    print(f"\n  🎮 GameVault running at http://{HOST}:{PORT}\n")
    HTTPServer((HOST, PORT), Handler).serve_forever()





