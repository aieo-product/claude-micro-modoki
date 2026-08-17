"""console が使う参照系 API (#93): アクションカタログの刻印配信と既定設定。"""

from server import actions as actions_mod
from server import config as config_mod
from tests.test_events import BridgeApiTestBase


class ConsoleApiTests(BridgeApiTestBase):
    async def test_actions_include_keycap_gallery(self):
        status, body = await self._request_json("GET", "/api/actions")
        self.assertEqual(status, 200)
        self.assertEqual(body["keycaps"], actions_mod.KEYCAPS)
        # 各刻印の既定はカタログの action id (console はここから割り当てを引く)
        for k in body["keycaps"]:
            if k["default"] is not None:
                self.assertIn(k["default"], {a["id"] for a in body["actions"]})

    async def test_config_defaults_returns_default_config(self):
        """レイアウトをリセットは既定を取得して PUT する 2 段階 (取得だけでは何も変えない)。"""
        status, body = await self._request_json("GET", "/api/config/defaults")
        self.assertEqual(status, 200)
        for key in ("keys", "analog_stick", "knob", "mic_key", "options"):
            self.assertEqual(body[key], config_mod.DEFAULT_CONFIG[key])
