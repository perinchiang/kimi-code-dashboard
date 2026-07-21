import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from routes import system as system_route


class CrossPlatformTests(unittest.TestCase):
    def test_startup_support_matches_documented_platforms(self):
        with patch.object(system_route.platform, "system", return_value="Darwin"):
            self.assertTrue(system_route._startup_service_supported())
        with patch.object(system_route.platform, "system", return_value="Windows"):
            self.assertTrue(system_route._startup_service_supported())
        with patch.object(system_route.platform, "system", return_value="Linux"):
            self.assertFalse(system_route._startup_service_supported())

    def test_macos_dashboard_plist_is_valid_with_special_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app_dir = root / "Dashboard & Tools"
            kimi_dir = root / "Kimi & Code"
            plist_path = root / "dashboard.plist"
            with patch.object(system_route, "APP_DIR", app_dir), \
                    patch.object(system_route, "KIMI_CODE_DIR", kimi_dir), \
                    patch.object(system_route, "_macos_plist_path", return_value=plist_path):
                system_route._macos_create_dashboard_plist()

            payload = plistlib.loads(plist_path.read_bytes())
            self.assertEqual(payload["Label"], "com.perinchiang.kimi-code-dashboard")
            self.assertEqual(payload["WorkingDirectory"], str(app_dir.resolve()))
            self.assertEqual(
                payload["ProgramArguments"][0],
                str((app_dir / ".venv" / "bin" / "python").resolve()),
            )
            self.assertEqual(payload["StandardOutPath"], str((kimi_dir / "dashboard.log").resolve()))

    def test_macos_kimi_plist_escapes_command_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kimi_dir = root / "Kimi & Code"
            plist_path = root / "kimi.plist"
            command = [str(kimi_dir / "bin" / "kimi"), "web", "--allowed-host", "example.test<dev>"]
            with patch.object(system_route, "KIMI_CODE_DIR", kimi_dir), \
                    patch.object(system_route, "_macos_plist_path", return_value=plist_path), \
                    patch.object(system_route, "_build_cmd", return_value=command):
                system_route._macos_create_kimi_plist({})

            payload = plistlib.loads(plist_path.read_bytes())
            self.assertEqual(payload["Label"], "com.perinchiang.kimi-code-server")
            self.assertEqual(payload["WorkingDirectory"], str(kimi_dir.resolve()))
            self.assertEqual(payload["ProgramArguments"], command)
            self.assertEqual(payload["StandardOutPath"], str((kimi_dir / "kimi-server.log").resolve()))


if __name__ == "__main__":
    unittest.main()
