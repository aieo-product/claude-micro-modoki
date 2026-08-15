"""/api/learn (キー学習) の並行・タイムアウト挙動のテスト (#72)。"""

import asyncio
from unittest import mock

# server_main は test_events 側で config 読込をパッチした状態で import されたものを使う
from tests.test_events import BridgeApiTestBase, server_main


class LearnApiTests(BridgeApiTestBase):
    """後着 supersede と compare-and-clear をデバイスなしで検証する。"""

    async def _wait_learn_future(self, prev):
        """learn ハンドラが新しい future を張るまで待つ。"""
        for _ in range(500):
            fut = server_main.bridge._learn_future
            if fut is not None and fut is not prev:
                return fut
            await asyncio.sleep(0.01)
        self.fail("learn future が張られなかった")

    async def test_learn_returns_pressed_key(self):
        """単独の learn は次の物理キー押下で解決し、learn 状態を残さない。"""
        task = asyncio.create_task(self._request_json("POST", "/api/learn"))
        await self._wait_learn_future(None)

        server_main.bridge._on_raw_key("KEY_05")

        status, body = await asyncio.wait_for(task, timeout=5)
        self.assertEqual(status, 200)
        self.assertEqual(body["key_id"], "KEY_05")
        self.assertIsNone(server_main.bridge._learn_future)

    async def test_second_learn_supersedes_first(self):
        """#72: 後着が学習待ちを引き継ぎ、先行はタイムアウトを待たず 409 で応答する。"""
        task_a = asyncio.create_task(self._request_json("POST", "/api/learn"))
        fut_a = await self._wait_learn_future(None)
        task_b = asyncio.create_task(self._request_json("POST", "/api/learn"))
        fut_b = await self._wait_learn_future(fut_a)

        # 先行はキー押下なしで即 409
        status_a, body_a = await asyncio.wait_for(task_a, timeout=5)
        self.assertEqual(status_a, 409)
        self.assertEqual(body_a["error"], "superseded")
        # 先行の finally が後着の future を消していない (compare-and-clear)
        self.assertIs(server_main.bridge._learn_future, fut_b)

        server_main.bridge._on_raw_key("KEY_09")
        status_b, body_b = await asyncio.wait_for(task_b, timeout=5)
        self.assertEqual(status_b, 200)
        self.assertEqual(body_b["key_id"], "KEY_09")
        self.assertIsNone(server_main.bridge._learn_future)

    async def test_learn_times_out_with_408(self):
        """キー押下が無ければ 408 を返し、learn 状態を残さない。"""
        with mock.patch.object(server_main, "LEARN_TIMEOUT_SEC", 0.05):
            status, body = await self._request_json("POST", "/api/learn")
        self.assertEqual(status, 408)
        self.assertEqual(body["error"], "timeout")
        self.assertIsNone(server_main.bridge._learn_future)
