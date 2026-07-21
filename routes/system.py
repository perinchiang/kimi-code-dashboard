"""System routes: Kimi Web launch, health, and index page."""

import json
import os
import platform
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from config import (
    APP_DIR,
    DASHBOARD_VERSION,
    KIMI_BIN,
    KIMI_CODE_DIR,
    load_dashboard_config,
    log,
    save_dashboard_config,
    validate_port,
)
from services.helpers import atomic_write_text, config_lock, lock_for, no_window_kwargs, tcp_open

bp = Blueprint("system", __name__)

KIMI_CONFIG = KIMI_CODE_DIR / "config.toml"

# --- Startup service constants ---
STARTUP_SUPPORTED_SYSTEMS = ("Darwin", "Windows")
STARTUP_SERVICES = {
    "dashboard": {
        "label": "com.perinchiang.kimi-code-dashboard",
        "windows_name": "KimiCodeDashboard",
    },
    "kimi": {
        "label": "com.perinchiang.kimi-code-server",
        "windows_name": "KimiCodeServer",
    },
}

# Windows elevated startup task name (separate from non-elevated Startup folder)
WINDOWS_ELEVATED_TASK_NAME = "KimiCodeDashboardAdmin"


def _read_default_permission_mode() -> str:
    """Read default_permission_mode from Kimi config.toml."""
    try:
        text = KIMI_CONFIG.read_text(encoding="utf-8-sig")
        m = re.search(r'^default_permission_mode\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m:
            return m.group(1)
    except Exception as e:
        log.warning("Failed to read %s: %s", KIMI_CONFIG, e)
    return "manual"


def _write_default_permission_mode(mode: str) -> bool:
    """Write default_permission_mode to Kimi config.toml, preserving other content."""
    try:
        with config_lock(lock_for(KIMI_CONFIG)):
            text = KIMI_CONFIG.read_text(encoding="utf-8-sig")
            new_line = f'default_permission_mode = "{mode}"'
            if re.search(r'^default_permission_mode\s*=\s*"', text, re.MULTILINE):
                text = re.sub(
                    r'^default_permission_mode\s*=.*$',
                    new_line,
                    text,
                    flags=re.MULTILINE,
                )
            else:
                text = new_line + "\n" + text
            atomic_write_text(KIMI_CONFIG, text)
        return True
    except Exception as e:
        log.error("Failed to write %s: %s", KIMI_CONFIG, e)
        return False


def _clean_stale_instances():
    """Remove instance files of kimi servers whose PID is dead.

    kimi-code >= 0.28 使用 server/instances/<id>.json，旧版 server/lock 已废弃。
    """
    instances_dir = KIMI_CODE_DIR / "server" / "instances"
    if not instances_dir.exists():
        return
    for f in instances_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            pid = data.get("pid")
            if pid and not _pid_alive(pid):
                log.info("Removing stale kimi server instance %s (pid=%s is dead)", f.name, pid)
                f.unlink(missing_ok=True)
        except Exception as e:
            log.debug("Failed to check stale instance %s: %s", f, e)


def _pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running (cross-platform)."""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            # Windows: os.kill(pid, 0) 对不存在的进程抛 OSError 而非 ProcessLookupError
            # 用 ctypes OpenProcess 更可靠
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False  # OpenProcess 失败 = 进程不存在或无权限
            kernel32.CloseHandle(handle)
            return True
        else:
            # POSIX: 信号 0 = 不实际发信号,只检测存在性
            os.kill(pid, 0)
            return True
    except ProcessLookupError:
        return False  # POSIX: 进程不存在
    except PermissionError:
        return True  # POSIX: 进程存在但无权限
    except Exception:
        # 其他异常 — 保守返回 True,与原行为一致
        return True


def _build_url(cfg):
    """根据配置生成访问 URL。仅外网模式才使用自定义 URL。

    支持 public_urls 列表，返回第一个有效 URL；兼容旧版 public_url 字符串。
    """
    bind = cfg.get("bind", "127.0.0.1")
    port = cfg.get("port", 5494)
    if bind == "0.0.0.0":
        pubs = cfg.get("public_urls") or []
        if isinstance(pubs, str):
            pubs = [pubs]
        # 兼容旧版单个 public_url
        legacy = (cfg.get("public_url") or "").strip()
        if legacy:
            pubs = [legacy] + [p for p in pubs if p != legacy]
        for pub in pubs:
            pub = str(pub or "").strip()
            if not pub:
                continue
            pub = pub.rstrip("/")
            if not pub.startswith(("http://", "https://")):
                pub = "https://" + pub
            return pub
        return f"http://127.0.0.1:{port}"
    # 本机模式固定用 127.0.0.1
    return f"http://127.0.0.1:{port}"


def _get_running_bind(port: int) -> str:
    """读取 server instances 获取指定端口当前运行的 bind 模式。"""
    instances_dir = KIMI_CODE_DIR / "server" / "instances"
    if not instances_dir.exists():
        return ""
    for f in instances_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("port") == port:
                return data.get("host", "")
        except Exception:
            continue
    return ""


def _kill_kimi_server():
    """Kill 当前运行的 kimi server 进程并清理已死实例。"""
    try:
        subprocess.run(
            [str(KIMI_BIN), "web", "kill"],
            capture_output=True, text=True, errors="replace", timeout=10,
            **no_window_kwargs(),
        )
        time.sleep(1)
    except Exception as e:
        log.warning("kimi web kill failed: %s", e)
    # 清理 PID 已死的 instance 文件
    _clean_stale_instances()


def _extract_host(url_str: str) -> str:
    """从 URL 中提取主机名，用于 --allowed-host。"""
    try:
        parsed = urllib.parse.urlparse(url_str.strip())
        return parsed.hostname or ""
    except Exception:
        return ""


def _build_cmd(cfg):
    """根据配置组装 kimi web 启动命令（kimi-code >= 0.28）。"""
    cmd = [str(KIMI_BIN), "web", "--port", str(cfg.get("port", 5494))]
    bind = cfg.get("bind", "127.0.0.1")
    if bind == "0.0.0.0":
        cmd.extend(["--host", "0.0.0.0"])
    elif bind and bind != "127.0.0.1":
        cmd.extend(["--host", bind])
    # 127.0.0.1 时不传 --host
    if cfg.get("bypass_auth", True):
        cmd.append("--dangerous-bypass-auth")
    # 非回环绑定时新版默认禁用 PTY 路由，需显式开启，否则 Web 终端不可用
    if bind and bind != "127.0.0.1":
        cmd.append("--allow-remote-terminals")
    # 合并 allowed_hosts 和从 public_urls 提取的主机名
    allowed_hosts = list(cfg.get("allowed_hosts_list", []))
    pubs = cfg.get("public_urls") or []
    if isinstance(pubs, str):
        pubs = [pubs]
    # 兼容旧版单个 public_url
    legacy = (cfg.get("public_url") or "").strip()
    if legacy:
        pubs = [legacy] + [p for p in pubs if p != legacy]
    for pub in pubs:
        pub_host = _extract_host(pub)
        if pub_host and pub_host not in allowed_hosts:
            allowed_hosts.append(pub_host)
    for h in allowed_hosts:
        cmd.extend(["--allowed-host", h])
    # 后台启动时不弹浏览器
    cmd.append("--no-open")
    return cmd


def _normalize_kimi_web_config(cfg: dict | None, persist: bool = False) -> dict:
    """Merge request values with persisted Kimi Web settings and validate the port."""
    cfg = cfg if isinstance(cfg, dict) else {}
    saved = load_dashboard_config()
    current = saved["kimi_web"]
    allowed_hosts_raw = cfg.get("allowed_hosts", current["allowed_hosts"]) or ""
    if isinstance(allowed_hosts_raw, list):
        allowed_hosts_raw = ",".join(str(item).strip() for item in allowed_hosts_raw if str(item).strip())
    allowed_hosts_list = [h.strip() for h in str(allowed_hosts_raw).split(",") if h.strip()]
    public_urls = cfg.get("public_urls", current["public_urls"]) or []
    if isinstance(public_urls, str):
        public_urls = [public_urls]
    legacy_public_url = (cfg.get("public_url") or "").strip().strip("`'").strip()
    if legacy_public_url:
        public_urls = [legacy_public_url] + [p for p in public_urls if p != legacy_public_url]

    persisted = {
        "bind": str(cfg.get("bind", current["bind"]) or "127.0.0.1").strip(),
        "port": validate_port(cfg.get("port", current["port"]), "port"),
        "bypass_auth": bool(cfg.get("bypass_auth", current["bypass_auth"])),
        "allowed_hosts": str(allowed_hosts_raw),
        "public_urls": [str(url).strip() for url in public_urls if str(url).strip()],
    }
    if persist:
        saved["kimi_web"] = persisted
        save_dashboard_config(saved)
    return {**persisted, "allowed_hosts_list": allowed_hosts_list}


def _format_command(cmd: list[str]) -> str:
    """Format argv as a command users can paste into the current shell."""
    if os.name == "nt":
        return subprocess.list2cmdline(cmd)
    return shlex.join(cmd)


def _build_preview_cmd(cfg: dict, bind: str) -> list[str]:
    """Build a local or external preview without changing persisted settings."""
    preview_cfg = dict(cfg)
    preview_cfg["bind"] = bind
    if bind == "127.0.0.1":
        # Local mode has no reason to trust or expose reverse-proxy hosts.
        preview_cfg["allowed_hosts_list"] = []
        preview_cfg["public_urls"] = []
    return _build_cmd(preview_cfg)


def _build_preview_summary(cfg: dict, bind: str) -> dict:
    """Return the compact address summary shown in the settings pill."""
    hosts = []
    if bind != "127.0.0.1":
        for host in cfg.get("allowed_hosts_list", []):
            if host and host not in hosts:
                hosts.append(host)
        for public_url in cfg.get("public_urls", []):
            host = _extract_host(public_url)
            if host and host not in hosts:
                hosts.append(host)
    return {"bind": bind, "port": cfg["port"], "hosts": hosts}


def _capture_token(proc, timeout=4):
    """尝试从进程 stdout 捕获 bearer token。"""
    if not proc.stdout:
        return None
    lines = []
    def reader():
        try:
            for line in proc.stdout:
                lines.append(line)
        except Exception:
            pass
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(timeout=timeout)
    text = "".join(lines)
    # token 通常是一串长字符
    for pattern in [
        r"token[:\s]*['\"]?([a-zA-Z0-9_\-]{20,})",
        r"['\"]?token['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{20,})",
    ]:
        m = re.search(pattern, text, re.I)
        if m:
            return m.group(1)
    return None


@bp.route("/api/kimi-web-commands", methods=["POST"])
def api_kimi_web_commands():
    """Return copyable local and external Kimi Web commands without launching."""
    try:
        cfg = _normalize_kimi_web_config(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    local_bind = "127.0.0.1"
    external_bind = "0.0.0.0"
    local_cmd = _build_preview_cmd(cfg, local_bind)
    external_cmd = _build_preview_cmd(cfg, external_bind)
    return jsonify({
        "local": {
            "argv": local_cmd,
            "command": _format_command(local_cmd),
            "summary": _build_preview_summary(cfg, local_bind),
        },
        "external": {
            "argv": external_cmd,
            "command": _format_command(external_cmd),
            "summary": _build_preview_summary(cfg, external_bind),
        },
    })


@bp.route("/api/kimi-web-status", methods=["POST"])
def api_kimi_web_status():
    """检查 Kimi Web 是否在请求或持久化配置的端口运行。"""
    try:
        cfg = _normalize_kimi_web_config(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"running": False, "error": str(exc)}), 400
    port = cfg["port"]
    running = tcp_open("127.0.0.1", port)
    return jsonify({"running": running, "port": port, "url": _build_url(cfg)})


@bp.route("/api/launch-kimi-web", methods=["POST"])
def api_launch_kimi_web():
    """持久化前端配置并据此启动 kimi web。"""
    request_cfg = request.get_json(silent=True) or {}
    try:
        norm_cfg = _normalize_kimi_web_config(request_cfg, persist=True)
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400
    except OSError as exc:
        log.error("Failed to save dashboard config: %s", exc)
        return jsonify({"status": "error", "error": "保存 Dashboard 配置失败"}), 500
    port = norm_cfg["port"]
    bind = norm_cfg["bind"]
    bypass_auth = norm_cfg["bypass_auth"]
    url = _build_url(norm_cfg)
    log.info("launch-kimi-web cfg: %s -> url=%s", norm_cfg, url)

    # 检查端口是否已被占用
    if tcp_open("127.0.0.1", port):
        running_bind = _get_running_bind(port)
        if running_bind == bind and not bool(request_cfg.get("restart", False)):
            # bind 模式相同且未请求重启，无需重复启动
            return jsonify({"status": "already_running", "port": port, "url": url})
        # bind 模式变化，或用户确认重启，需要先停止旧进程
        log.info("restarting kimi web (bind=%s, running_bind=%s)", bind, running_bind)
        _kill_kimi_server()

    # 清理僵尸 instance 文件
    _clean_stale_instances()

    try:
        cmd = _build_cmd(norm_cfg)
        kwargs = {}
        # 不 bypass auth 时需要捕获 stdout 拿 token
        if not bypass_auth:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.DEVNULL
            kwargs["text"] = True
        else:
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
        kwargs.update(no_window_kwargs())

        proc = subprocess.Popen(cmd, **kwargs)
        log.info("Launched Kimi Web: %s", " ".join(cmd))

        # 如果需要认证，尝试捕获 token
        token = None
        if not bypass_auth:
            token = _capture_token(proc)

        # 等待 HTTP 服务就绪，最多 12 秒
        import urllib.request
        ready = False
        for _ in range(24):
            # 如果进程已退出（非 None），说明启动失败
            if proc.poll() is not None:
                log.error("kimi server exited immediately with code %s", proc.returncode)
                return jsonify({"status": "error", "error": "kimi server 启动后立即退出，请检查端口或实例文件"})
            if tcp_open("127.0.0.1", port):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
                    ready = True
                    break
                except Exception:
                    pass
            time.sleep(0.5)

        if not ready:
            log.warning("kimi server did not become ready within 12s, returning URL anyway")

        final_url = url
        if token:
            final_url = f"{url}?token={token}"

        return jsonify({
            "status": "launched",
            "port": port,
            "url": final_url,
            "token": token,
        })
    except Exception as e:
        log.error("Failed to launch kimi web: %s", e)
        return jsonify({"status": "error", "error": str(e)})


# --- Startup service helpers ---

def _startup_service_supported() -> bool:
    """Startup service management works on macOS (launchd) and Windows (Task Scheduler)."""
    return platform.system() in STARTUP_SUPPORTED_SYSTEMS


# macOS launchd helpers

def _macos_plist_path(service: str) -> Path:
    label = STARTUP_SERVICES[service]["label"]
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def _macos_plist_exists(service: str) -> bool:
    return _macos_plist_path(service).exists()


def _macos_service_loaded(service: str) -> bool:
    label = STARTUP_SERVICES[service]["label"]
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, errors="replace", timeout=10,
            **no_window_kwargs(),
        )
        return result.returncode == 0 and label in result.stdout
    except Exception:
        return False


def _macos_create_dashboard_plist() -> None:
    plist_path = _macos_plist_path("dashboard")
    python_path = _escape_xml(str((APP_DIR / ".venv" / "bin" / "python").resolve()))
    working_directory = _escape_xml(str(APP_DIR.resolve()))
    log_path = _escape_xml(str((KIMI_CODE_DIR / "dashboard.log").resolve()))
    plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.perinchiang.kimi-code-dashboard</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>app.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{working_directory}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>'''
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist, encoding="utf-8")


def _macos_create_kimi_plist(cfg: dict) -> None:
    plist_path = _macos_plist_path("kimi")
    working_directory = _escape_xml(str(KIMI_CODE_DIR.resolve()))
    log_path = _escape_xml(str((KIMI_CODE_DIR / "kimi-server.log").resolve()))
    # Reuse command builder for launchd
    cmd = _build_cmd(cfg)
    args_xml = "\n".join(f"        <string>{_escape_xml(str(arg))}</string>" for arg in cmd)
    plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.perinchiang.kimi-code-server</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{working_directory}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>'''
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist, encoding="utf-8")


def _macos_remove_plist(service: str) -> None:
    plist_path = _macos_plist_path(service)
    if plist_path.exists():
        plist_path.unlink()


def _escape_xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


# Windows Startup folder helpers
# Avoid Task Scheduler (often requires elevation); use the user's Startup folder instead.

def _windows_startup_folder() -> Path:
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _windows_startup_file(service: str) -> Path:
    name = "StartKimiDashboard.vbs" if service == "dashboard" else "StartKimiServer.vbs"
    return _windows_startup_folder() / name


def _windows_startup_exists(service: str) -> bool:
    return _windows_startup_file(service).exists()


def _escape_vbs_string(value: str) -> str:
    """Escape a string for embedding inside a VBScript string literal."""
    return value.replace('"', '""')


def _windows_pythonw() -> str:
    """Return the pythonw.exe path, falling back to sys.executable if not found.

    Borrowed from launch_menu.py's candidate-probing pattern.
    """
    candidates = [
        APP_DIR / ".venv" / "Scripts" / "pythonw.exe",
        APP_DIR / ".venv" / "Scripts" / "python.exe",  # Conda 等
    ]
    for c in candidates:
        if c.exists():
            return str(c.resolve())
    return sys.executable  # 最终 fallback:当前解释器


def _windows_create_dashboard_startup() -> None:
    vbs_path = _windows_startup_file("dashboard")
    dashboard_dir = str(APP_DIR.resolve())
    pythonw = _windows_pythonw()
    run_cmd = f'cmd /c cd /d "{dashboard_dir}" && "{pythonw}" app.py'
    vbs = f'''Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "{_escape_vbs_string(run_cmd)}", 0, False
Set WshShell = Nothing
'''
    _windows_startup_folder().mkdir(parents=True, exist_ok=True)
    vbs_path.write_text(vbs, encoding="utf-8")


def _windows_create_kimi_startup(cfg: dict) -> None:
    vbs_path = _windows_startup_file("kimi")
    cmd = _build_cmd(cfg)
    # Build a single command line with each argument quoted if it contains spaces.
    cmd_line = " ".join(f'"{str(arg)}"' if " " in str(arg) else str(arg) for arg in cmd)
    vbs = f'''Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "{_escape_vbs_string(cmd_line)}", 0, False
Set WshShell = Nothing
'''
    _windows_startup_folder().mkdir(parents=True, exist_ok=True)
    vbs_path.write_text(vbs, encoding="utf-8")


def _windows_remove_startup(service: str) -> None:
    vbs_path = _windows_startup_file(service)
    if vbs_path.exists():
        vbs_path.unlink()


# Windows elevated startup via Task Scheduler (highest privileges)

def _windows_elevated_task_exists() -> bool:
    """Check whether the elevated dashboard startup task exists."""
    if platform.system() != "Windows":
        return False
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-ScheduledTask -TaskName '{WINDOWS_ELEVATED_TASK_NAME}' -ErrorAction SilentlyContinue | Select-Object -First 1"],
            capture_output=True, text=True, errors="replace", timeout=10, **no_window_kwargs()
        )
        return WINDOWS_ELEVATED_TASK_NAME in result.stdout
    except Exception as e:
        log.debug("Failed to check elevated task: %s", e)
        return False


def _windows_elevated_task_ps(enable: bool) -> str:
    """Return PowerShell code to create or remove the elevated startup task."""
    dashboard_dir = str(APP_DIR.resolve())
    pythonw = _windows_pythonw()
    log_path = str((KIMI_CODE_DIR / "dashboard.log").resolve())

    if enable:
        action = f'New-ScheduledTaskAction -Execute "{pythonw}" -Argument "app.py" -WorkingDirectory "{dashboard_dir}"'
        trigger = 'New-ScheduledTaskTrigger -AtLogon'
        principal = 'New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -RunLevel Highest -LogonType Interactive'
        settings_cmd = 'New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable'
        return (
            f'Unregister-ScheduledTask -TaskName "{WINDOWS_ELEVATED_TASK_NAME}" -Confirm:$false -ErrorAction SilentlyContinue; '
            f'$action = {action}; '
            f'$trigger = {trigger}; '
            f'$principal = {principal}; '
            f'$settings = {settings_cmd}; '
            f'Register-ScheduledTask -TaskName "{WINDOWS_ELEVATED_TASK_NAME}" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force; '
            f'Write-Output "created"'
        )
    return (
        f'Unregister-ScheduledTask -TaskName "{WINDOWS_ELEVATED_TASK_NAME}" -Confirm:$false -ErrorAction SilentlyContinue; '
        f'Write-Output "removed"'
    )


def _windows_run_elevated_ps(ps_code: str) -> tuple[bool, str]:
    """Run PowerShell code with UAC elevation (shows prompt)."""
    import tempfile
    script_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as f:
            f.write(ps_code)
            script_path = f.name
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f'Start-Process powershell -Verb runAs -Wait -ArgumentList \'-NoProfile -ExecutionPolicy Bypass -File "{script_path}"\''],
            capture_output=True, text=True, timeout=60, **no_window_kwargs()
        )
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        if script_path:
            try:
                Path(script_path).unlink(missing_ok=True)
            except Exception:
                pass


# Cross-platform status/toggle

def _get_startup_status(service: str) -> dict:
    if not _startup_service_supported():
        return {"supported": False, "enabled": False, "mode": "off"}
    system = platform.system()
    if system == "Darwin":
        exists = _macos_plist_exists(service)
        loaded = _macos_service_loaded(service) if exists else False
        enabled = exists and loaded
        mode = "normal" if enabled else "off"
        return {"supported": True, "enabled": enabled, "mode": mode}
    if system == "Windows":
        if service == "dashboard":
            if _windows_elevated_task_exists():
                return {"supported": True, "enabled": True, "mode": "elevated"}
            if _windows_startup_exists("dashboard"):
                return {"supported": True, "enabled": True, "mode": "normal"}
            return {"supported": True, "enabled": False, "mode": "off"}
        return {"supported": True, "enabled": _windows_startup_exists(service), "mode": "off"}
    return {"supported": False, "enabled": False, "mode": "off"}


def _set_startup_service(service: str, enable: bool, cfg: dict = None) -> dict:
    if not _startup_service_supported():
        return {"success": False, "error": "当前操作系统不支持开机自启"}
    system = platform.system()
    try:
        if system == "Darwin":
            label = STARTUP_SERVICES[service]["label"]
            plist_path = _macos_plist_path(service)
            if enable:
                # Unload first to avoid "already loaded" errors
                subprocess.run(["launchctl", "unload", "-w", str(plist_path)], capture_output=True, text=True, errors="replace", timeout=15, **no_window_kwargs())
                if service == "dashboard":
                    _macos_create_dashboard_plist()
                else:
                    _macos_create_kimi_plist(cfg or {})
                result = subprocess.run(["launchctl", "load", "-w", str(plist_path)], capture_output=True, text=True, errors="replace", timeout=15, **no_window_kwargs())
            else:
                result = subprocess.run(["launchctl", "unload", "-w", str(plist_path)], capture_output=True, text=True, errors="replace", timeout=15, **no_window_kwargs())
                _macos_remove_plist(service)
            if result.returncode != 0 and "No such process" not in result.stderr:
                return {"success": False, "error": result.stderr or "launchctl 失败"}
            return {"success": True, "enabled": enable}
        if system == "Windows":
            if enable:
                _windows_remove_startup(service)  # recreate to update parameters
                if service == "dashboard":
                    _windows_create_dashboard_startup()
                else:
                    _windows_create_kimi_startup(cfg or {})
            else:
                _windows_remove_startup(service)
            return {"success": True, "enabled": enable}
        return {"success": False, "error": "不支持的操作系统"}
    except Exception as e:
        log.error("Failed to toggle %s startup service: %s", service, e)
        return {"success": False, "error": str(e)}


def _set_dashboard_startup_mode(mode: str) -> dict:
    """Set dashboard startup mode: normal (Startup folder), elevated (Task Scheduler), or off."""
    if not _startup_service_supported():
        return {"success": False, "error": "当前操作系统不支持开机自启"}
    if mode not in ("normal", "elevated", "off"):
        return {"success": False, "error": "mode 必须是 normal/elevated/off 之一"}

    system = platform.system()
    try:
        if system == "Darwin":
            plist_path = _macos_plist_path("dashboard")
            if mode == "off":
                subprocess.run(
                    ["launchctl", "unload", "-w", str(plist_path)],
                    capture_output=True, text=True, errors="replace", timeout=15,
                    **no_window_kwargs(),
                )
                _macos_remove_plist("dashboard")
            else:
                # macOS has no separate elevated mode; treat both as launchd
                subprocess.run(
                    ["launchctl", "unload", "-w", str(plist_path)],
                    capture_output=True, text=True, errors="replace", timeout=15,
                    **no_window_kwargs(),
                )
                _macos_create_dashboard_plist()
                result = subprocess.run(
                    ["launchctl", "load", "-w", str(plist_path)],
                    capture_output=True, text=True, errors="replace", timeout=15,
                    **no_window_kwargs(),
                )
                if result.returncode != 0 and "No such process" not in result.stderr:
                    return {"success": False, "error": result.stderr or "launchctl 失败"}
            return {"success": True, "mode": mode}

        if system == "Windows":
            # Remove non-elevated startup first
            _windows_remove_startup("dashboard")
            # Remove elevated task (may trigger UAC when disabling)
            ps_code = _windows_elevated_task_ps(False)
            _windows_run_elevated_ps(ps_code)

            if mode == "normal":
                _windows_create_dashboard_startup()
                return {"success": True, "mode": "normal"}
            if mode == "elevated":
                ps_code = _windows_elevated_task_ps(True)
                ok, error = _windows_run_elevated_ps(ps_code)
                if not ok:
                    return {"success": False, "error": error}
                return {"success": True, "mode": "elevated", "note": "UAC 提示已处理，请刷新页面查看最新状态"}
            return {"success": True, "mode": "off"}

        return {"success": False, "error": "不支持的操作系统"}
    except Exception as e:
        log.error("Failed to set dashboard startup mode: %s", e)
        return {"success": False, "error": str(e)}


@bp.route("/api/startup-status")
def api_startup_status():
    """Check whether dashboard and Kimi Code startup services are enabled."""
    return jsonify({
        "supported": _startup_service_supported(),
        "dashboard": _get_startup_status("dashboard"),
        "kimi": _get_startup_status("kimi"),
    })


@bp.route("/api/startup-toggle", methods=["POST"])
def api_startup_toggle():
    """Enable or disable Kimi Code startup service, or set dashboard startup mode."""
    body = request.get_json(silent=True) or {}
    service = body.get("service")
    if service == "dashboard":
        mode = body.get("mode", "off")
        result = _set_dashboard_startup_mode(mode)
        return jsonify(result)
    if service not in STARTUP_SERVICES:
        return jsonify({"success": False, "error": f"service 必须是 {list(STARTUP_SERVICES.keys())} 之一"}), 400

    enable = bool(body.get("enable"))
    cfg = {}
    if service == "kimi":
        try:
            cfg = _normalize_kimi_web_config(body, persist=enable)
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except OSError as exc:
            log.error("Failed to save dashboard config: %s", exc)
            return jsonify({"success": False, "error": "保存 Dashboard 配置失败"}), 500
    result = _set_startup_service(service, enable, cfg)
    return jsonify(result)


@bp.route("/api/startup-elevated-status")
def api_startup_elevated_status():
    """Check whether the Windows elevated dashboard startup task exists."""
    return jsonify({
        "supported": platform.system() == "Windows",
        "enabled": _windows_elevated_task_exists(),
    })


@bp.route("/api/startup-elevated-toggle", methods=["POST"])
def api_startup_elevated_toggle():
    """Enable or disable the Windows elevated dashboard startup task (requires UAC)."""
    if platform.system() != "Windows":
        return jsonify({"success": False, "error": "仅 Windows 可用"}), 400
    body = request.get_json(silent=True) or {}
    enable = bool(body.get("enable"))

    # If enabling, remove non-elevated startup to avoid double launch
    if enable:
        _windows_remove_startup("dashboard")

    ps_code = _windows_elevated_task_ps(enable)
    ok, error = _windows_run_elevated_ps(ps_code)
    if not ok:
        return jsonify({"success": False, "error": error}), 500

    return jsonify({
        "success": True,
        "enabled": _windows_elevated_task_exists(),
        "note": "UAC 提示已处理，请刷新页面查看最新状态",
    })


@bp.route("/api/dashboard-version")
def api_dashboard_version():
    """Return dashboard version."""
    return jsonify({"version": DASHBOARD_VERSION})


@bp.route("/api/dashboard-port")
def api_dashboard_port():
    """Return the persisted Dashboard listen port."""
    return jsonify({"port": load_dashboard_config()["dashboard"]["port"]})


@bp.route("/api/dashboard-port", methods=["POST"])
def api_update_dashboard_port():
    """Validate and persist the Dashboard listen port for the next restart."""
    body = request.get_json(silent=True) or {}
    try:
        port = validate_port(body.get("port"), "port")
        cfg = load_dashboard_config()
        cfg["dashboard"]["previous_port"] = cfg["dashboard"]["port"]
        cfg["dashboard"]["port"] = port
        save_dashboard_config(cfg)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except OSError as exc:
        log.error("Failed to save dashboard port: %s", exc)
        return jsonify({"success": False, "error": "保存 Dashboard 配置失败"}), 500
    return jsonify({"success": True, "port": port})


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/api/kimi-config")
def api_kimi_config():
    """Return relevant Kimi Code config values for the dashboard settings UI."""
    return jsonify({
        "default_permission_mode": _read_default_permission_mode(),
    })


@bp.route("/api/update-config", methods=["POST"])
def api_update_config():
    """Update Kimi Code config values from the dashboard settings UI."""
    body = request.get_json(silent=True) or {}
    mode = body.get("default_permission_mode")
    valid_modes = ("manual", "auto", "yolo")
    if mode not in valid_modes:
        return jsonify({"success": False, "error": f"default_permission_mode 必须是 {valid_modes} 之一"}), 400
    if _write_default_permission_mode(mode):
        log.info("Updated default_permission_mode to %s", mode)
        return jsonify({"success": True, "default_permission_mode": mode})
    return jsonify({"success": False, "error": "写入 config.toml 失败"}), 500
