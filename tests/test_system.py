import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from routes import system as system_route


class KimiWebCommandTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.saved_config = {
            "kimi_web": {
                "bind": "0.0.0.0",
                "port": 5494,
                "bypass_auth": True,
                "allowed_hosts": "",
                "public_urls": [],
            }
        }

    def _post_commands(self, **config):
        with patch.object(system_route, "load_dashboard_config", return_value=self.saved_config), \
                patch.object(system_route, "KIMI_BIN", Path("kimi")):
            return self.client.post("/api/kimi-web-commands", json=config)

    def test_preview_separates_local_and_external_arguments(self):
        response = self._post_commands(
            port=17168,
            bypass_auth=True,
            allowed_hosts="proxy.example.com,ai.r3ppx952a.nyat.app",
            public_urls=["https://ai.r3ppx952a.nyat.app:17168/"],
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(
            data["local"]["argv"],
            ["kimi", "web", "--port", "17168", "--dangerous-bypass-auth", "--no-open"],
        )
        external = data["external"]["argv"]
        self.assertIn("--host", external)
        self.assertIn("0.0.0.0", external)
        self.assertIn("--allow-remote-terminals", external)
        self.assertEqual(external.count("--allowed-host"), 2)
        self.assertIn("proxy.example.com", external)
        self.assertIn("ai.r3ppx952a.nyat.app", external)
        self.assertEqual(external.count("ai.r3ppx952a.nyat.app"), 1)
        self.assertTrue(data["local"]["command"].endswith("--no-open"))
        self.assertEqual(
            data["local"]["summary"],
            {"bind": "127.0.0.1", "port": 17168, "hosts": []},
        )
        self.assertEqual(data["external"]["summary"]["bind"], "0.0.0.0")
        self.assertEqual(data["external"]["summary"]["port"], 17168)
        self.assertEqual(
            data["external"]["summary"]["hosts"],
            ["proxy.example.com", "ai.r3ppx952a.nyat.app"],
        )

    def test_invalid_port_is_rejected_without_persisting(self):
        with patch.object(system_route, "load_dashboard_config", return_value=self.saved_config), \
                patch.object(system_route, "save_dashboard_config") as save_config:
            response = self.client.post("/api/kimi-web-commands", json={"port": 0})

        self.assertEqual(response.status_code, 400)
        self.assertIn("1-65535", response.get_json()["error"])
        save_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
