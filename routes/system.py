"""System routes: Kimi Web launch, health, and index page."""

import json
import os
import re
import subprocess
import threading
import time
import urllib.parse

from flask import Blueprint, jsonify, render_template, request

from config import KIMI_BIN, KIMI_CODE_DIR, log
from services.helpers import no_window_kwargs, tcp_open

bp = Blueprint("system", __name__)


def _clean_stale_lock():
    """Remove stale kimi server lock file if the PID is dead."""
    lock_path = KIMI_CODE_DIR / "server" / "lock"
    if not lock_path.exists():
        return
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        pid = data.get("pid")
        if pid and not _pid_alive(pid):
            log.info("Removing stale kimi server lock (pid=%s is dead)", pid)
            try:
                os.chmod(str(lock_path), 0o777)
            except Exception:
                pass
            lock_path.unlink(missing_ok=True)
    except Exception as e:
        log.debug("Failed to check stale lock: %s", e)


def _pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=5,
            **no_window_kwargs(),
        )
        return str(pid) in result.stdout
    except Exception:
        return True  # Assume alive to be safe


def _build_url(cfg):
    """根据配置生成访问 URL。仅外网模式才使用自定义 URL。"""
    bind = cfg.get("bind", "127.0.0.1")
    port = cfg.get("port", 5494)
    if bind == "0.0.0.0":
        pub = (cfg.get("public_url") or "").strip()
        if pub:
            pub = pub.rstrip("/")
            if not pub.startswith(("http://", "https://")):
                pub = "https://" + pub
            return pub
        return f"http://127.0.0.1:{port}"
    # 本机模式固定用 127.0.0.1
    return f"http://127.0.0.1:{port}"


def _get_running_bind() -> str:
    """读取 lock 文件获取当前运行的 bind 模式。"""
    lock_path = KIMI_CODE_DIR / "server" / "lock"
    if not lock_path.exists():
        return ""
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        return data.get("host", "")
    except Exception:
        return ""


def _kill_kimi_server():
    """Kill 当前运行的 kimi server 进程并清理 lock。"""
    try:
        subprocess.run(
            [str(KIMI_BIN), "server", "kill"],
            capture_output=True, text=True, timeout=10,
            **no_window_kwargs(),
        )
        time.sleep(1)
    except Exception as e:
        log.warning("kimi server kill failed: %s", e)
    # 确保 lock 文件被清理
    lock_path = KIMI_CODE_DIR / "server" / "lock"
    if lock_path.exists():
        try:
            os.chmod(str(lock_path), 0o777)
        except Exception:
            pass
        lock_path.unlink(missing_ok=True)


def _extract_host(url_str: str) -> str:
    """从 URL 中提取主机名，用于 --allowed-host。"""
    try:
        parsed = urllib.parse.urlparse(url_str.strip())
        return parsed.hostname or ""
    except Exception:
        return ""


def _build_cmd(cfg):
    """根据配置组装 kimi server run 命令。"""
    cmd = [str(KIMI_BIN), "server", "run", "--port", str(cfg.get("port", 5494))]
    bind = cfg.get("bind", "127.0.0.1")
    if bind == "0.0.0.0":
        cmd.append("--host")  # 不带值 = 绑定 0.0.0.0
    elif bind and bind != "127.0.0.1":
        cmd.extend(["--host", bind])
    # 127.0.0.1 时不传 --host
    if cfg.get("bypass_auth", True):
        cmd.append("--dangerous-bypass-auth")
    # 合并 allowed_hosts 和从 public_url 提取的主机名
    allowed_hosts = list(cfg.get("allowed_hosts_list", []))
    pub = (cfg.get("public_url") or "").strip()
    if pub:
        pub_host = _extract_host(pub)
        if pub_host and pub_host not in allowed_hosts:
            allowed_hosts.append(pub_host)
    for h in allowed_hosts:
        cmd.extend(["--allowed-host", h])
    cmd.append("--foreground")
    return cmd


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


@bp.route("/api/kimi-web-status", methods=["POST"])
def api_kimi_web_status():
    """检查 Kimi Web 是否在指定端口运行。"""
    cfg = request.get_json(silent=True) or {}
    port = int(cfg.get("port", 5494))
    running = tcp_open("127.0.0.1", port)
    return jsonify({"running": running, "port": port, "url": _build_url(cfg)})


@bp.route("/api/launch-kimi-web", methods=["POST"])
def api_launch_kimi_web():
    """根据前端 POST 的配置启动 kimi server run。"""
    cfg = request.get_json(silent=True) or {}
    # 规范化
    port = int(cfg.get("port", 5494))
    bind = cfg.get("bind", "127.0.0.1")
    bypass_auth = cfg.get("bypass_auth", True)
    allowed_hosts_raw = cfg.get("allowed_hosts", "") or ""
    allowed_hosts_list = [h.strip() for h in allowed_hosts_raw.split(",") if h.strip()]
    public_url = (cfg.get("public_url") or "").strip().strip("`'").strip()

    norm_cfg = {
        "bind": bind,
        "port": port,
        "bypass_auth": bypass_auth,
        "allowed_hosts_list": allowed_hosts_list,
        "public_url": public_url,
    }
    url = _build_url(norm_cfg)
    log.info("launch-kimi-web cfg: %s -> url=%s", norm_cfg, url)

    # 检查端口是否已被占用
    if tcp_open("127.0.0.1", port):
        running_bind = _get_running_bind()
        if running_bind == bind:
            # bind 模式相同，无需重启
            return jsonify({"status": "already_running", "port": port, "url": url})
        # bind 模式不同，需要 kill 旧进程再重启
        log.info("bind changed (%s -> %s), killing old server", running_bind, bind)
        _kill_kimi_server()

    # 清理僵尸 lock 文件
    _clean_stale_lock()

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
                return jsonify({"status": "error", "error": "kimi server 启动后立即退出，请检查端口或 lock 文件"})
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


@bp.route("/")
def index():
    return render_template("index.html")
