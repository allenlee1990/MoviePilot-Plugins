"""FFXIVCheckin V3 的最小离线检查。"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path


class _Response:
    status_code = 200
    text = '{"message":"签到成功"}'
    cookies = {}

    def json(self):
        return {"message": "签到成功"}

    def close(self):
        pass


class _RequestUtils:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def request(self, **kwargs):
        self.calls.append({**kwargs, "headers": self.kwargs["headers"], "cookies": self.kwargs["cookies"]})
        return _Response()


def _load_plugin():
    app = types.ModuleType("app")
    adapters = types.ModuleType("app.adapters")
    external = types.ModuleType("app.adapters.external")
    cookiecloud = types.ModuleType("app.adapters.external.cookiecloud")
    plugins = types.ModuleType("app.plugins")
    schemas = types.ModuleType("app.schemas")
    sdk = types.ModuleType("app.sdk")
    logging = types.ModuleType("app.sdk.logging")
    network = types.ModuleType("app.sdk.network")

    class _Base:
        def __init__(self):
            self.data = {}

        def save_data(self, key, value):
            self.data[key] = value

        def get_data(self, key):
            return self.data.get(key)

        def update_config(self, config):
            self.config = config

        def post_message(self, **kwargs):
            pass

    class _Logger:
        def warning(self, *args):
            pass

        def error(self, *args):
            pass

    class _CookieCloudHelper:
        data = ({}, "")

        def download(self):
            return self.data

    plugins._PluginBase = _Base
    schemas.NotificationType = types.SimpleNamespace(SiteMessage="site")
    logging.logger = _Logger()
    network.RequestUtils = _RequestUtils
    cookiecloud.CookieCloudHelper = _CookieCloudHelper
    sys.modules.update({
        "app": app, "app.adapters": adapters, "app.adapters.external": external,
        "app.adapters.external.cookiecloud": cookiecloud, "app.plugins": plugins,
        "app.schemas": schemas, "app.sdk": sdk, "app.sdk.logging": logging,
        "app.sdk.network": network,
    })

    apscheduler = types.ModuleType("apscheduler")
    triggers = types.ModuleType("apscheduler.triggers")
    cron = types.ModuleType("apscheduler.triggers.cron")
    cron.CronTrigger = type("CronTrigger", (), {"from_crontab": staticmethod(lambda value: value)})
    sys.modules.update({"apscheduler": apscheduler, "apscheduler.triggers": triggers, "apscheduler.triggers.cron": cron})

    plugin_file = Path(__file__).parents[3] / "plugins.v3" / "ffxivcheckin" / "__init__.py"
    spec = importlib.util.spec_from_file_location("ffxivcheckin", plugin_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FFXIVCheckin


class FFXIVCheckinTest(unittest.TestCase):
    def setUp(self):
        _RequestUtils.calls = []

    def test_checkin_calls_both_signin_endpoints(self):
        plugin = _load_plugin()()
        plugin.init_plugin({
            "notify": False, "use_cookiecloud": False,
            "risingstones_cookie": "ff14risingstones=value",
            "risingstones_user_agent": "test-agent", "mall_cookie": "sessionId=value",
        })
        result = plugin.checkin()
        signin_calls = [call for call in _RequestUtils.calls if call["method"] != "get"]
        self.assertTrue(result["success"])
        self.assertEqual([call["method"] for call in signin_calls], ["post", "put"])
        self.assertIn("signIn", signin_calls[0]["url"])
        self.assertIn("integration/checkIn", signin_calls[1]["url"])
        self.assertEqual(next(call for call in signin_calls if call["method"] == "put")["data"], {})


if __name__ == "__main__":
    unittest.main()
