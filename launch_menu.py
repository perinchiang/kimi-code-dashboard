#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kimi Code Dashboard / Web 启动菜单。

在控制台输入 `kimi dashboard` 时弹出数字选项：
1. 启动 Dashboard
2. 启动本地 Kimi Code Web
3. 启动外网访问 Kimi Code Web

也可以直接传入选项数字跳过菜单，例如 `kimi dashboard 1`。
"""

import json
import platform
import re
import shlex
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent
VBS_PATH = DASHBOARD_DIR / "start-kimi-web.vbs"

DASHBOARD_URL = "http://127.0.0.1:8080"
KIMI_WEB_PORT = 5494


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
    """根据 lock 文件判断当前 Kimi server 的绑定模式。

    返回 "external"（0.0.0.0）、"local"（127.0.0.1）或 ""（未知）。
    """
    lock_path = Path.home() / ".kimi-code" / "server" / "lock"
    if not lock_path.exists():
        return ""
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        host = data.get("host", "")
        if host == "0.0.0.0":
            return "external"
        if host == "127.0.0.1":
            return "local"
    except Exception:
        pass
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
    if _tcp_open("127.0.0.1", 8080):
        print("Dashboard 已经在 http://127.0.0.1:8080 运行，直接打开浏览器...")
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
            print("如需切换到本地模式，请先执行 `kimi server kill` 停止现有服务。")
            return
        print(f"Kimi Code Web 已经在 http://127.0.0.1:{KIMI_WEB_PORT} 运行。")
        return

    kimi_bin = _kimi_bin()
    if not kimi_bin.exists():
        print(f"未找到 Kimi CLI: {kimi_bin}")
        return

    cmd = [str(kimi_bin), "server", "run", "--port", str(KIMI_WEB_PORT), "--dangerous-bypass-auth", "--foreground"]
    print("启动本地 Kimi Code Web...")
    print(" ".join(cmd))
    _start_detached(cmd)


def start_kimi_web_external() -> None:
    """读取 start-kimi-web.vbs 中的命令并启动外网访问。"""
    if _tcp_open("127.0.0.1", KIMI_WEB_PORT):
        mode = _kimi_server_bind_mode()
        if mode == "external":
            print(f"Kimi Code Web 已经在外网模式运行：http://127.0.0.1:{KIMI_WEB_PORT}")
            return
        if mode == "local":
            print(f"Kimi Code Web 当前在本地模式运行：http://127.0.0.1:{KIMI_WEB_PORT}")
            print("如需切换到外网模式，请先执行 `kimi server kill` 停止现有服务。")
            return
        print(f"Kimi Code Web 已经在 http://127.0.0.1:{KIMI_WEB_PORT} 运行。")
        return

    kimi_bin = _kimi_bin()
    if not kimi_bin.exists():
        print(f"未找到 Kimi CLI: {kimi_bin}")
        return

    if VBS_PATH.exists():
        # Windows：读取 Dashboard 设置页保存的 VBS 命令
        text = VBS_PATH.read_text(encoding="utf-8")
        run_line = ""
        for line in text.splitlines():
            if "WshShell.Run" in line:
                run_line = line
                break
        if not run_line:
            print("无法解析 start-kimi-web.vbs 中的启动命令，请检查文件格式。")
            return

        first = run_line.find('"')
        last = run_line.rfind('"')
        if first == -1 or last == -1 or last <= first:
            print("无法解析 start-kimi-web.vbs 中的启动命令，请检查引号格式。")
            return

        full_cmd = run_line[first : last + 1]
        try:
            cmd = [arg.strip('"') for arg in shlex.split(full_cmd, posix=False)]
        except ValueError as exc:
            print(f"解析启动命令失败: {exc}")
            return
    else:
        # macOS / Linux：VBS 不存在，使用默认外网参数
        print("未找到 start-kimi-web.vbs，使用默认外网启动参数。")
        print("如需自定义 allowed-host，请在 Dashboard「设置」页保存配置（Windows）或手动编辑本脚本。")
        cmd = [
            str(kimi_bin),
            "server",
            "run",
            "--host",
            "0.0.0.0",
            "--port",
            str(KIMI_WEB_PORT),
            "--dangerous-bypass-auth",
            "--foreground",
        ]

    print("启动外网访问 Kimi Code Web...")
    print(" ".join(cmd))
    _start_detached(cmd)


def stop_kimi_web() -> None:
    """执行 kimi server kill 停止所有 Kimi Code Web 进程。"""
    kimi_bin = _kimi_bin()
    if not kimi_bin.exists():
        print(f"未找到 Kimi CLI: {kimi_bin}")
        return

    print("正在停止 Kimi Code Web...")
    result = subprocess.run(
        [str(kimi_bin), "server", "kill"],
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


def show_menu() -> str:
    print("\n===== Kimi Code 启动菜单 =====")
    print("1. 启动 Dashboard")
    print("2. 启动本地 Kimi Code Web")
    print("3. 启动外网访问 Kimi Code Web")
    print("4. 停止 Kimi Code Web（kimi server kill）")
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
    elif choice in ("0", "q", "quit", "exit"):
        print("已取消")
    else:
        print("无效选项，请输入 1/2/3/4/0。")
        sys.exit(1)


if __name__ == "__main__":
    main()
