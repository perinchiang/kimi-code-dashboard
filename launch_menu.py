#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kimi Code Dashboard / Web 启动菜单。

在控制台输入 `kimi dashboard` 时弹出数字选项：
1. 启动 Dashboard
2. 启动本地 Kimi Code Web
3. 启动外网访问 Kimi Code Web
4. 停止 Kimi Code Web（按 PID 结束）
5. 更新 Kimi Code
6. 更新 Dashboard
7. 完全卸载 Dashboard
8. 重启 Dashboard

也可以直接传入选项数字跳过菜单，例如 `kimi dashboard 1`。
"""

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

from config import DASHBOARD_PORT, DASHBOARD_URL, load_dashboard_config

DASHBOARD_DIR = Path(__file__).resolve().parent

_dashboard_config = load_dashboard_config()
KIMI_WEB_PORT = _dashboard_config["kimi_web"]["port"]
PREVIOUS_DASHBOARD_PORT = _dashboard_config["dashboard"].get("previous_port", DASHBOARD_PORT)


def _kimi_bin() -> Path:
    """返回跨平台的 Kimi CLI 路径。"""
    base = Path.home() / ".kimi-code" / "bin"
    for name in ("kimi.exe", "kimi"):
        candidate = base / name
        if candidate.exists():
            return candidate
    return base / ("kimi.exe" if sys.platform == "win32" else "kimi")


def _tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _public_urls(cfg: dict) -> list[str]:
    """返回配置中的公网访问 URL。"""
    urls = cfg.get("public_urls") or []
    if isinstance(urls, str):
        urls = [urls]
    return [str(url).strip().rstrip("/") for url in urls if str(url).strip()]


def _public_url_hosts(cfg: dict) -> list[str]:
    """从公网访问 URL 提取 Host header 白名单。"""
    hosts = []
    for url in _public_urls(cfg):
        candidate = url if "://" in url else "https://" + url
        host = urllib.parse.urlparse(candidate).hostname
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _print_external_urls(cfg: dict, port: int) -> None:
    """打印配置的公网访问地址及其监听提示。"""
    urls = _public_urls(cfg)
    if urls:
        print("外网访问地址：")
        for url in urls:
            print(f"  {url}")
    else:
        print(f"未配置公网访问 URL；服务监听在 0.0.0.0:{port}。")


def _kimi_server_bind_mode() -> str:
    """根据 server instances 判断当前 Kimi server 的绑定模式。

    返回 "external"（0.0.0.0）、"local"（127.0.0.1）或 ""（未知）。
    kimi-code >= 0.28 使用 server/instances/<id>.json，旧版 server/lock 已废弃。
    """
    instances_dir = Path.home() / ".kimi-code" / "server" / "instances"
    if not instances_dir.exists():
        return ""
    for f in instances_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("port") != KIMI_WEB_PORT:
            continue
        host = data.get("host", "")
        if host == "0.0.0.0":
            return "external"
        if host == "127.0.0.1":
            return "local"
    return ""


def _kimi_instance_pids() -> list[int]:
    """返回 Kimi Web 实例文件登记的进程 PID。"""
    instances_dir = Path.home() / ".kimi-code" / "server" / "instances"
    if not instances_dir.exists():
        return []
    pids = []
    for f in instances_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            pid = int(data.get("pid", 0))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return pids


def _terminate_kimi_pid(pid: int) -> tuple[bool, str]:
    """结束一个 Kimi Web 进程及其子进程，并返回失败原因。"""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                errors="replace",
            )
            detail = ((result.stdout or "") + (result.stderr or "")).strip()
            return result.returncode == 0, detail
        import signal
        os.kill(pid, signal.SIGTERM)
        return True, ""
    except (OSError, ValueError) as exc:
        return False, str(exc)


def _start_detached(args: list[str], cwd: str | None = None) -> subprocess.Popen:
    """在后台无控制台窗口启动进程（跨平台）。"""
    kwargs: dict = {
        "cwd": cwd,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(args, **kwargs)


def start_dashboard() -> None:
    """启动 Dashboard 并打开浏览器。"""
    if _tcp_open("127.0.0.1", DASHBOARD_PORT):
        print(f"Dashboard 已经在 {DASHBOARD_URL} 运行，直接打开浏览器...")
        webbrowser.open(DASHBOARD_URL)
        return

    candidates = [
        DASHBOARD_DIR / ".venv" / "Scripts" / "pythonw.exe",  # Windows
        DASHBOARD_DIR / ".venv" / "bin" / "python",  # macOS / Linux
    ]
    py = None
    for candidate in candidates:
        if candidate.exists():
            py = str(candidate)
            break
    if py is None:
        py = "python"
    _start_detached([py, str(DASHBOARD_DIR / "app.py")], cwd=str(DASHBOARD_DIR))
    print("Dashboard 已后台启动，等待 2 秒后打开浏览器...")
    time.sleep(2)
    webbrowser.open(DASHBOARD_URL)


def start_kimi_web_local() -> None:
    """启动仅本地访问的 Kimi Code Web。"""
    if _tcp_open("127.0.0.1", KIMI_WEB_PORT):
        mode = _kimi_server_bind_mode()
        if mode == "local":
            print(f"Kimi Code Web 已经在本地模式运行：http://127.0.0.1:{KIMI_WEB_PORT}")
            return
        if mode == "external":
            print(f"Kimi Code Web 当前在外网模式运行：http://127.0.0.1:{KIMI_WEB_PORT}")
            print("如需切换到本地模式，请先执行启动菜单选项 4 停止现有服务。")
            return
        print(f"Kimi Code Web 已经在 http://127.0.0.1:{KIMI_WEB_PORT} 运行。")
        return

    kimi_bin = _kimi_bin()
    if not kimi_bin.exists():
        print(f"未找到 Kimi CLI: {kimi_bin}")
        return

    cmd = [str(kimi_bin), "web", "--port", str(KIMI_WEB_PORT), "--dangerous-bypass-auth", "--no-open"]
    print("启动本地 Kimi Code Web...")
    print(" ".join(cmd))
    _start_detached(cmd)


def start_kimi_web_external() -> None:
    """按持久化配置启动外网访问的 Kimi Code Web。"""
    cfg = load_dashboard_config()["kimi_web"]
    port = cfg["port"]
    if _tcp_open("127.0.0.1", port):
        mode = _kimi_server_bind_mode()
        if mode == "external":
            print(f"Kimi Code Web 已经在 0.0.0.0:{port} 监听。")
            _print_external_urls(cfg, port)
            return
        if mode == "local":
            print(f"Kimi Code Web 当前在本地模式运行：http://127.0.0.1:{port}")
            print("如需切换到外网模式，请先执行启动菜单选项 4 停止现有服务。")
            return
        print(f"Kimi Code Web 已经在 http://127.0.0.1:{port} 运行。")
        return

    kimi_bin = _kimi_bin()
    if not kimi_bin.exists():
        print(f"未找到 Kimi CLI: {kimi_bin}")
        return

    bind = cfg["bind"] if cfg["bind"] != "127.0.0.1" else "0.0.0.0"
    cmd = [str(kimi_bin), "web", "--host", bind, "--port", str(port)]
    if cfg["bypass_auth"]:
        cmd.append("--dangerous-bypass-auth")
    cmd.append("--allow-remote-terminals")
    allowed_hosts = [item.strip() for item in cfg["allowed_hosts"].split(",") if item.strip()]
    for host in _public_url_hosts(cfg):
        if host not in allowed_hosts:
            allowed_hosts.append(host)
    for host in allowed_hosts:
        cmd.extend(["--allowed-host", host])
    cmd.append("--no-open")

    print("启动外网访问 Kimi Code Web...")
    print(" ".join(cmd))
    _start_detached(cmd)
    _print_external_urls(cfg, port)


def stop_kimi_web() -> None:
    """结束实例文件或配置端口记录的 Kimi Web 前台进程。"""
    print("正在停止 Kimi Code Web...")
    pids = _kimi_instance_pids()
    if not pids:
        pid = _pid_listening_on(KIMI_WEB_PORT)
        if pid:
            pids = [pid]
    if not pids:
        print("未发现运行中的 Kimi Code Web。")
        return

    failed = []
    for pid in pids:
        stopped, detail = _terminate_kimi_pid(pid)
        if stopped:
            print(f"已停止 Kimi Code Web 进程 (pid {pid})。")
        else:
            failed.append((pid, detail))
    if failed:
        print("无法停止 Kimi Code Web 进程：")
        for pid, detail in failed:
            print(f"  pid {pid}: {detail or '系统未返回具体错误'}")
        if sys.platform == "win32":
            print("请以管理员身份运行 PowerShell 后重试选项 4。")
        else:
            print("请确认当前终端用户有权限结束该进程后重试选项 4。")
        print("如果启用了 Kimi Code Web 开机启动，请先在 Dashboard 设置中关闭。")
        return
    for _ in range(10):
        if not _tcp_open("127.0.0.1", KIMI_WEB_PORT):
            break
        time.sleep(0.5)
    print("Kimi Code Web 已停止。")


def update_kimi_code() -> None:
    """执行 kimi upgrade 更新 Kimi Code CLI。"""
    kimi_bin = _kimi_bin()
    if not kimi_bin.exists():
        print(f"未找到 Kimi CLI: {kimi_bin}")
        return

    cmd = [str(kimi_bin), "upgrade"]
    print("正在更新 Kimi Code...")
    print(" ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print("Kimi Code 更新完成。")
        if _tcp_open("127.0.0.1", KIMI_WEB_PORT):
            print("提示：Kimi Code Web 正在运行，请用选项 4 停止后重新启动，以使用新版本。")
    else:
        print(f"更新命令返回非零退出码: {result.returncode}")


def _pid_listening_on(port: int) -> int | None:
    """返回监听指定端口的进程 PID，找不到返回 None。"""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, errors="replace"
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if (
                    len(parts) >= 5
                    and "LISTENING" in line
                    and parts[1].endswith(f":{port}")
                    and parts[-1].isdigit()
                ):
                    return int(parts[-1])
        else:
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                capture_output=True, text=True, errors="replace",
            )
            pids = result.stdout.strip().splitlines()
            if pids and pids[0].strip().isdigit():
                return int(pids[0].strip())
    except Exception:
        pass
    return None


def restart_dashboard() -> None:
    """重启 Dashboard：结束占用当前或上一个配置端口的旧进程。"""
    ports = list(dict.fromkeys([PREVIOUS_DASHBOARD_PORT, DASHBOARD_PORT]))
    for port in ports:
        pid = _pid_listening_on(port)
        if not pid:
            continue
        print(f"正在停止端口 {port} 上的旧 Dashboard 进程 (pid {pid})...")
        killed = False
        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"], capture_output=True
                )
                killed = result.returncode == 0
            else:
                import signal
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed = True
                except OSError:
                    killed = False
        except Exception as exc:
            print(f"停止旧进程失败: {exc}")
            return
        if not killed:
            print("无法结束旧 Dashboard 进程（权限不足，旧进程可能是以管理员身份启动的）。")
            print("请以管理员身份运行终端后重试，或在任务管理器中手动结束 pythonw.exe。")
            return
        # 等待端口释放，最多 5 秒
        for _ in range(10):
            if not _tcp_open("127.0.0.1", port):
                break
            time.sleep(0.5)
    start_dashboard()


def update_dashboard() -> None:
    """在 Dashboard 目录执行 git pull origin master 更新代码并重启生效。"""
    if shutil.which("git") is None:
        print("未找到 git 命令，请确认 Git 已安装并加入 PATH。")
        return

    cmd = ["git", "-C", str(DASHBOARD_DIR), "pull", "origin", "master"]
    print("正在更新 Dashboard...")
    print(" ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    output = (result.stdout or "") + (result.stderr or "")
    if output.strip():
        print(output.strip())
    if result.returncode != 0:
        print(f"更新命令返回非零退出码: {result.returncode}")
        return
    if "Already up to date" in output:
        print("Dashboard 已是最新。")
        return
    print("Dashboard 更新完成，正在重启以生效...")
    restart_dashboard()


def uninstall_dashboard() -> None:
    """完全卸载 Dashboard：删除 wrapper 和 dashboard 目录。

    由于脚本本身在 dashboard 目录中运行，采用延迟子进程删除策略。
    Kimi Code CLI 本身不受影响，如需卸载请另行处理。
    """
    bin_dir = Path.home() / ".kimi-code" / "bin"
    wrappers = [bin_dir / "kimi-dashboard.bat", bin_dir / "kimi-dashboard"]

    print("\n===== 完全卸载 Dashboard =====")
    print(f"将删除:")
    for w in wrappers:
        if w.exists():
            print(f"  - {w}")
    print(f"  - {DASHBOARD_DIR}")
    print("\n注意:")
    print("  - Kimi Code CLI 本身不会被卸载")
    print("  - 正在运行的 Dashboard 进程需先手动关闭（任务管理器结束 pythonw.exe）")

    confirm = input("\n确认卸载？输入 yes 继续，其他取消: ").strip().lower()
    if confirm != "yes":
        print("已取消")
        return

    # 1. 立即删除 wrapper（不在运行目录中，可安全删除）
    for w in wrappers:
        if w.exists():
            try:
                w.unlink()
                print(f"已删除: {w}")
            except OSError as exc:
                print(f"删除失败 {w}: {exc}")

    # 2. 延迟 3 秒删除 dashboard 目录（脚本本身正在其中运行）
    if sys.platform == "win32":
        cmd = f'timeout /t 3 /nobreak >nul & rmdir /s /q "{DASHBOARD_DIR}"'
        subprocess.Popen(
            ["cmd", "/c", cmd],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        )
    else:
        cmd = f'sleep 3 && rm -rf "{DASHBOARD_DIR}"'
        subprocess.Popen(["bash", "-c", cmd], start_new_session=True)

    print(f"\n将在 3 秒后删除目录: {DASHBOARD_DIR}")
    print("卸载已启动，请关闭此窗口。")
    print("\n如需重新安装：")
    print("  Windows:  irm https://raw.githubusercontent.com/perinchiang/kimi-code-dashboard/master/install.ps1 | iex")
    print("  macOS/Linux:  curl -fsSL https://raw.githubusercontent.com/perinchiang/kimi-code-dashboard/master/install.sh | bash")


def show_menu() -> str:
    print("\n===== Kimi Code 启动菜单 =====")
    print("1. 启动 Dashboard")
    print("2. 启动本地 Kimi Code Web")
    print("3. 启动外网访问 Kimi Code Web")
    print("4. 停止 Kimi Code Web（按 PID 结束）")
    print("5. 更新 Kimi Code")
    print("6. 更新 Dashboard")
    print("7. 完全卸载 Dashboard")
    print("8. 重启 Dashboard")
    print("0. 退出")
    print("==============================")
    return input("请输入数字选项: ").strip()


def _configure_console_encoding() -> None:
    """Keep Chinese menu output writable on Windows hosts with non-UTF-8 locales."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def main() -> None:
    _configure_console_encoding()
    choice = sys.argv[1].strip() if len(sys.argv) > 1 else show_menu()

    if choice == "1":
        start_dashboard()
    elif choice == "2":
        start_kimi_web_local()
    elif choice == "3":
        start_kimi_web_external()
    elif choice == "4":
        stop_kimi_web()
    elif choice == "5":
        update_kimi_code()
    elif choice == "6":
        update_dashboard()
    elif choice == "7":
        uninstall_dashboard()
    elif choice == "8":
        restart_dashboard()
    elif choice in ("0", "q", "quit", "exit"):
        print("已取消")
    else:
        print("无效选项，请输入 1/2/3/4/5/6/7/8/0。")
        sys.exit(1)


if __name__ == "__main__":
    main()
