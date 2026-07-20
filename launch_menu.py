#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kimi Code Dashboard / Web 启动菜单。

在控制台输入 `kimi dashboard` 时弹出数字选项：
1. 启动 Dashboard
2. 启动本地 Kimi Code Web
3. 启动外网访问 Kimi Code Web
4. 停止 Kimi Code Web（kimi web kill）
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
import webbrowser
from pathlib import Path

from config import DASHBOARD_PORT, DASHBOARD_URL, load_dashboard_config

DASHBOARD_DIR = Path(__file__).resolve().parent

KIMI_WEB_PORT = load_dashboard_config()["kimi_web"]["port"]


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
            print("如需切换到本地模式，请先执行 `kimi web kill` 停止现有服务。")
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
            print(f"Kimi Code Web 已经在外网模式运行：http://127.0.0.1:{port}")
            return
        if mode == "local":
            print(f"Kimi Code Web 当前在本地模式运行：http://127.0.0.1:{port}")
            print("如需切换到外网模式，请先执行 `kimi web kill` 停止现有服务。")
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
    for host in [item.strip() for item in cfg["allowed_hosts"].split(",") if item.strip()]:
        cmd.extend(["--allowed-host", host])
    cmd.append("--no-open")

    print("启动外网访问 Kimi Code Web...")
    print(" ".join(cmd))
    _start_detached(cmd)


def stop_kimi_web() -> None:
    """执行 kimi web kill 停止所有 Kimi Code Web 进程。"""
    kimi_bin = _kimi_bin()
    if not kimi_bin.exists():
        print(f"未找到 Kimi CLI: {kimi_bin}")
        return

    print("正在停止 Kimi Code Web...")
    result = subprocess.run(
        [str(kimi_bin), "web", "kill"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip())
    if result.returncode == 0:
        print("Kimi Code Web 已停止。")
    else:
        print(f"停止命令返回非零退出码: {result.returncode}")


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
    """重启 Dashboard：结束占用配置端口的旧进程并重新启动。"""
    pid = _pid_listening_on(DASHBOARD_PORT)
    if pid:
        print(f"正在停止旧 Dashboard 进程 (pid {pid})...")
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
            if not _tcp_open("127.0.0.1", DASHBOARD_PORT):
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
    print("4. 停止 Kimi Code Web（kimi web kill）")
    print("5. 更新 Kimi Code")
    print("6. 更新 Dashboard")
    print("7. 完全卸载 Dashboard")
    print("8. 重启 Dashboard")
    print("0. 退出")
    print("==============================")
    return input("请输入数字选项: ").strip()


def main() -> None:
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
