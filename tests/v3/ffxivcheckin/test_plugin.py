"""FFXIVCheckin 的最小离线检查。"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path


class _Response:
    """模拟 HTTP 响应。"""

    status_code = 200
    text = '{"message":"签到成功"}'

    def json(self):
        """返回模拟 JSON。"""
        return {"message": "签到成功"}

    def close(self):
        """模拟关闭响应。"""


class _RequestUtils:
    """记录离线测试中的 HTTP 请求。"""

    calls = []

    def __init__(self, **kwargs):
        """保存客户端构造参数。"""
        self.kwargs = kwargs

    def request(self, **kwargs):
        """记录请求并返回成功响应。"""
        self.calls.append(kwargs)
        return _Response()


def _load_plugin():
    """注入最小 MoviePilot SDK 替身并加载待测插件。"""
    app = types.ModuleType("app")
    plugins = types.ModuleType("app.plugins")
    schemas = types.ModuleType("app.schemas")
    sdk = types.ModuleType("app.sdk")
    config = types.ModuleType("app.sdk.config")
    logging = types.ModuleType("app.sdk.logging")
    network = types.ModuleType("app.sdk.network")

    class _Base:
        """最小插件基类。"""

        def __init__(self):
            """初始化内存状态。"""
            self.data = {}

        def save_data(self, key, value):
            """保存测试数据。"""
            self.data[key] = value

        def get_data(self, key):
            """读取测试数据。"""
            return self.data.get(key)

        def update_config(self, config):
            """模拟配置保存。"""
            self.config = config

        def post_message(self, **kwargs):
            """模拟通知发送。"""

    class _Logger:
        """最小日志器。"""

        def warning(self, *args):
            """忽略测试日志。"""

        def error(self, *args):
            """忽略测试日志。"""

    plugins._PluginBase = _Base
    schemas.NotificationType = types.SimpleNamespace(SiteMessage="site")
    config.settings = types.SimpleNamespace(PROXY=None)
    logging.logger = _Logger()
    network.RequestUtils = _RequestUtils
    sys.modules.update({"app": app, "app.plugins": plugins, "app.schemas": schemas, "app.sdk": sdk, "app.sdk.config": config, "app.sdk.logging": logging, "app.sdk.network": network})

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
    """验证两个站点的最小请求合同。"""

    def test_checkin_calls_both_signin_endpoints(self):
        """填写全部凭证后应提交两个签到请求。"""
        plugin = _load_plugin()()
        plugin.init_plugin({"notify": False, "risingstones_cookie": "ff14risingstones=value", "risingstones_user_agent": "test-agent", "mall_cookie": "sessionId=value"})
        result = plugin.checkin()
        signin_calls = [call for call in _RequestUtils.calls if call["method"] != "get"]
        self.assertTrue(result["success"])
        self.assertEqual([call["method"] for call in signin_calls], ["post", "put"])
        self.assertIn("signIn", signin_calls[0]["url"])
        self.assertIn("integration/checkIn", signin_calls[1]["url"])


if __name__ == "__main__":
    unittest.main()
