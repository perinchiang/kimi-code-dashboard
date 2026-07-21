import unittest
from pathlib import Path
from unittest.mock import patch

import launch_menu


class LaunchMenuTests(unittest.TestCase):
    def test_stop_uses_instance_pid_instead_of_kill_subcommand(self):
        with patch.object(launch_menu, "_kimi_instance_pids", return_value=[1234]), \
                patch.object(launch_menu, "_terminate_kimi_pid", return_value=(True, "")) as terminate, \
                patch.object(launch_menu, "_tcp_open", return_value=False):
            launch_menu.stop_kimi_web()

        terminate.assert_called_once_with(1234)

    def test_stop_reports_failure_detail_and_admin_hint(self):
        with patch.object(launch_menu, "_kimi_instance_pids", return_value=[1234]), \
                patch.object(launch_menu, "_terminate_kimi_pid", return_value=(False, "Access is denied.")), \
                patch("builtins.print") as print_mock:
            launch_menu.stop_kimi_web()

        print_mock.assert_any_call("  pid 1234: Access is denied.")
        print_mock.assert_any_call("请以管理员身份运行 PowerShell 后重试选项 4。")

    def test_stop_reports_posix_permission_hint(self):
        with patch.object(launch_menu, "_kimi_instance_pids", return_value=[1234]), \
                patch.object(launch_menu, "_terminate_kimi_pid", return_value=(False, "Operation not permitted")), \
                patch.object(launch_menu.sys, "platform", "linux"), \
                patch("builtins.print") as print_mock:
            launch_menu.stop_kimi_web()

        print_mock.assert_any_call("请确认当前终端用户有权限结束该进程后重试选项 4。")

    def test_external_start_adds_public_host_and_prints_public_url(self):
        config = {
            "kimi_web": {
                "bind": "0.0.0.0",
                "port": 5494,
                "bypass_auth": True,
                "allowed_hosts": "",
                "public_urls": ["https://ai.example.test:17168/"],
            }
        }
        with patch.object(launch_menu, "load_dashboard_config", return_value=config), \
                patch.object(launch_menu, "_tcp_open", return_value=False), \
                patch.object(launch_menu, "_kimi_bin", return_value=Path("launch_menu.py")), \
                patch.object(launch_menu, "_start_detached") as start, \
                patch("builtins.print") as print_mock:
            launch_menu.start_kimi_web_external()

        cmd = start.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--allowed-host") + 1], "ai.example.test")
        print_mock.assert_any_call("  https://ai.example.test:17168")


if __name__ == "__main__":
    unittest.main()
