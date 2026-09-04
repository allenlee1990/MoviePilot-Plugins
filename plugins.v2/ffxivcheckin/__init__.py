"""FFXIV 国服每日签到 MoviePilot V3 插件。"""

from datetime import datetime
from threading import Thread
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import NotificationType
from app.utils.http import RequestUtils

try:
    from app.helper.cookiecloud import CookieCloudHelper
except ImportError:
    CookieCloudHelper = None


class FFXIVCheckin(_PluginBase):
    """执行石之家与趣商城每日签到。"""

    plugin_name = "FFXIV 国服签到"
    plugin_desc = "使用已登录 Cookie 完成石之家及趣商城的每日签到。"
    plugin_icon = "statistic.png"
    plugin_version = "1.0.4"
    plugin_label = "FFXIV,签到"
    plugin_author = "allenlee1990"
    author_url = "https://github.com/allenlee1990"
    plugin_config_prefix = "ffxivcheckin_"
    plugin_order = 50
    auth_level = 1

    RISINGSTONES_HOME = "https://ff14risingstones.web.sdo.com/"
    RISINGSTONES_SIGNIN_URL = "https://apiff14risingstones.web.sdo.com/api/home/sign/signIn"
    MALL_SESSION_URL = "https://sqmallservice.u.sdo.com/api/us/getSessionStatus"
    MALL_SIGNIN_URL = "https://sqmallservice.u.sdo.com/api/us/integration/checkIn?merchantId=1"
    MALL_HOME = "https://qu.sdo.com/personal-center?merchantId=1"

    _enabled = False
    _onlyonce = False
    _notify = True
    _cron = "0 9 * * *"
    _risingstones_cookie = ""
    _risingstones_user_agent = ""
    _risingstones_headers = ""
    _mall_cookie = ""
    _mall_headers = ""
    _use_cookiecloud = True

    def init_plugin(self, config: dict = None) -> None:
        """根据保存的配置初始化签到任务。"""
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._onlyonce = bool(config.get("onlyonce", False))
        self._notify = bool(config.get("notify", True))
        self._cron = str(config.get("cron") or "0 9 * * *")
        self._risingstones_cookie = str(config.get("risingstones_cookie") or "").strip()
        self._risingstones_user_agent = str(config.get("risingstones_user_agent") or "").strip()
        self._risingstones_headers = str(config.get("risingstones_headers") or "").strip()
        self._mall_cookie = str(config.get("mall_cookie") or "").strip()
        self._mall_headers = str(config.get("mall_headers") or "").strip()
        self._use_cookiecloud = bool(config.get("use_cookiecloud", True))
        if self._onlyonce:
            self._onlyonce = False
            self.update_config(self._current_config())
            Thread(target=self.checkin, daemon=True).start()

    def get_state(self) -> bool:
        """返回插件是否启用定时签到。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """本插件不注册远程命令。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """返回手动触发签到的受保护接口。"""
        return [{
            "path": "/checkin",
            "endpoint": self.checkin,
            "methods": ["POST"],
            "auth": "bear",
            "summary": "立即执行 FFXIV 石之家与趣商城签到",
        }]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册每日签到计划。"""
        if not self._enabled:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except ValueError:
            logger.error("FFXIV 国服签到 Cron 表达式无效：%s", self._cron)
            return []
        return [{
            "id": "FFXIVCheckin",
            "name": "FFXIV 国服每日签到",
            "trigger": trigger,
            "func": self.checkin,
            "kwargs": {},
        }]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回 JSON 配置表单与默认值。"""
        return [{
            "component": "VForm",
            "content": [
                {"component": "VRow", "content": [
                    self._field("VSwitch", "enabled", "启用每日签到", 4),
                    self._field("VSwitch", "onlyonce", "保存后立即执行一次", 4),
                    self._field("VSwitch", "notify", "发送签到结果通知", 4),
                    self._field("VSwitch", "use_cookiecloud", "使用 CookieCloud 浏览器登录态", 4),
                ]},
                {"component": "VRow", "content": [
                    self._field("VCronField", "cron", "签到时间", 12, placeholder="5 位 Cron 表达式，例如 0 9 * * *"),
                ]},
                {"component": "VRow", "content": [
                    self._field("VTextarea", "risingstones_cookie", "石之家 Cookie（CookieCloud 不可用时备用）", 12, rows=2, type="password", hint="CookieCloud 开启时会优先使用浏览器同步的最新登录态。", persistent_hint=True),
                    self._field("VTextarea", "risingstones_user_agent", "石之家登录 User-Agent", 12, rows=2, hint="必须与登录石之家时浏览器使用的 User-Agent 一致。", persistent_hint=True),
                    self._field("VTextarea", "risingstones_headers", "石之家认证请求头（可选）", 12, rows=2, type="password", hint="从已登录请求复制除 Cookie 外的认证头，每行 Header: value。", persistent_hint=True),
                    self._field("VTextarea", "mall_cookie", "趣商城 Cookie（CookieCloud 不可用时备用）", 12, rows=2, type="password", hint="CookieCloud 开启时会优先使用浏览器同步的最新登录态。", persistent_hint=True),
                    self._field("VTextarea", "mall_headers", "趣商城认证请求头（可选）", 12, rows=2, type="password", hint="从 sqmallservice 请求复制除 Cookie 外的认证头，每行 Header: value。", persistent_hint=True),
                ]},
                {"component": "VAlert", "props": {"type": "warning", "variant": "tonal"}, "text": "Cookie 只保存在本机 MoviePilot 插件配置中。登录失效、验证码或风控拦截时，插件不会尝试自动登录；请在浏览器重新登录后更新 Cookie。"},
            ],
        }], self._current_config()

    def get_page(self) -> List[dict]:
        """展示最近一次签到结果。"""
        state = self.get_data("state") or {}
        results = state.get("results") or []
        return [
            {"component": "VAlert", "props": {"type": "info", "variant": "tonal"}, "text": f"定时签到：{'已启用' if self._enabled else '未启用'}；最近执行：{state.get('at') or '尚未执行'}"},
            {"component": "VList", "props": {"density": "compact", "lines": "two"}, "content": [
                {"component": "VListItem", "props": {"title": f"{item['name']} · {item['status']}", "subtitle": item['message']}}
                for item in results
            ]},
        ]

    def stop_service(self) -> None:
        """本插件没有自建后台线程或调度器需要停止。"""
        return None

    def checkin(self) -> Dict[str, Any]:
        """依次提交石之家和趣商城的签到请求并保存结果。"""
        results = [self._check_risingstones(), self._check_mall()]
        state = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "results": results}
        self.save_data("state", state)
        summary = "；".join(f"{item['name']}：{item['status']}（{item['message']}）" for item in results)
        if self._notify:
            self.post_message(mtype=NotificationType.SiteMessage, title="FFXIV 国服签到", text=summary)
        return {"success": all(item["success"] for item in results), "message": summary, "data": state}

    def _check_risingstones(self) -> Dict[str, Any]:
        """提交石之家签到；缺少凭证时不发起网络请求。"""
        cookie = self._site_cookie(
            self._risingstones_cookie, "sdo.com", "apiff14risingstones.web.sdo.com"
        )
        if not cookie or not self._risingstones_user_agent:
            return self._skipped("石之家", "请先填写石之家 Cookie 和登录 User-Agent")
        headers = {
            "User-Agent": self._risingstones_user_agent,
            "Origin": "https://ff14risingstones.web.sdo.com",
            "Referer": self.RISINGSTONES_HOME,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        headers.update(self._extra_headers(self._risingstones_headers))
        self._request("GET", self.RISINGSTONES_HOME, cookie, headers)
        nonce = str(uuid4())
        return self._result("石之家", self._request(
            "POST", f"{self.RISINGSTONES_SIGNIN_URL}?tempsuid={nonce}", cookie, headers, {"tempsuid": nonce}
        ))

    def _check_mall(self) -> Dict[str, Any]:
        """提交趣商城积分签到；缺少 Cookie 时不发起网络请求。"""
        cookie = self._site_cookie(
            self._mall_cookie, "sdo.com", "sqmallservice.u.sdo.com"
        )
        if not cookie:
            return self._skipped("趣商城", "请先填写趣商城 Cookie")
        headers = {
            "User-Agent": self._risingstones_user_agent or self._default_user_agent(),
            "Origin": "https://qu.sdo.com",
            "Referer": self.MALL_HOME,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "qu-merchant-id": "1",
            "qu-hardware-platform": "3",
            "qu-software-platform": "1",
            "qu-deploy-platform": "1",
            "qu-web-host": "qu.sdo.com",
        }
        headers.update(self._extra_headers(self._mall_headers))
        return self._result("趣商城", self._request("PUT", self.MALL_SIGNIN_URL, cookie, headers, {}))

    def _request(self, method: str, url: str, cookie: str, headers: Dict[str, str], data: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """通过 MoviePilot 网络工具发送请求，并将响应收敛为安全摘要。"""
        response = None
        try:
            client = RequestUtils(
                cookies=cookie,
                headers=headers,
                proxies=getattr(settings, "PROXY", None),
                timeout=20,
            )
            request = getattr(client, "request", None)
            if callable(request):
                response = request(method=method.lower(), url=url, data=data)
            else:
                request_method = getattr(client, f"{method.lower()}_res")
                response = request_method(url=url, data=data) if data else request_method(url=url)
            status_code = getattr(response, "status_code", None) if response else None
            text = (getattr(response, "text", "") or "").strip() if response else ""
            payload = self._json(response)
            return {"status_code": status_code, "text": text, "payload": payload}
        except Exception as err:
            logger.warning("FFXIV 国服签到请求失败：%s", err)
            return {"status_code": None, "text": f"请求异常：{err}", "payload": None}
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    @staticmethod
    def _json(response: Any) -> Optional[Dict[str, Any]]:
        """解析字典形态的 JSON 响应，非 JSON 响应返回空值。"""
        try:
            payload = response.json()
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _result(self, name: str, response: Dict[str, Any]) -> Dict[str, Any]:
        """将站点响应转为页面与通知可读的结果。"""
        status_code = response.get("status_code")
        payload = response.get("payload") or {}
        message = self._message(payload, response.get("text") or "")
        success = bool(status_code and 200 <= status_code < 300 and not self._is_login_error(payload, message))
        return {"name": name, "success": success, "status": "已响应" if success else "失败", "message": message}

    @staticmethod
    def _skipped(name: str, message: str) -> Dict[str, Any]:
        """构造未配置凭证时的跳过结果。"""
        return {"name": name, "success": False, "status": "未执行", "message": message}

    @staticmethod
    def _message(payload: Dict[str, Any], fallback: str) -> str:
        """从站点响应中提取提示文本，避免持久化完整响应。"""
        for key in ("message", "msg", "resultMsg", "description", "errorMessage"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:200]
        return fallback.replace("\n", " ")[:200] or "站点未返回可读提示"

    @staticmethod
    def _is_login_error(payload: Dict[str, Any], message: str) -> bool:
        """识别已知登录失效码和常见失效提示。"""
        codes = {10105, 10403, -10350174}
        return any(payload.get(key) in codes for key in ("code", "resultCode")) or any(
            word in message for word in ("未登录", "登录失效", "登录过期", "请登录")
        )

    def _current_config(self) -> Dict[str, Any]:
        """返回当前配置，供一次性执行后清除开关使用。"""
        return {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "notify": self._notify,
            "cron": self._cron,
            "risingstones_cookie": self._risingstones_cookie,
            "risingstones_user_agent": self._risingstones_user_agent,
            "risingstones_headers": self._risingstones_headers,
            "mall_cookie": self._mall_cookie,
            "mall_headers": self._mall_headers,
            "use_cookiecloud": self._use_cookiecloud,
        }

    def _site_cookie(self, fallback: str, *domains: str) -> str:
        """按实际接口域名组合 CookieCloud 登录态，失败时保留手工配置。"""
        if not self._use_cookiecloud or CookieCloudHelper is None:
            return fallback
        try:
            cookies, error = CookieCloudHelper().download()
        except Exception as err:
            logger.warning("FFXIV 国服签到读取 CookieCloud 失败：%s", err)
            return fallback
        cookie = ";".join(
            value for domain in domains if (value := (cookies or {}).get(domain))
        )
        if cookie:
            return cookie
        if error:
            logger.warning("FFXIV 国服签到未读取到 CookieCloud 目标域名登录态：%s", error)
        return fallback

    @staticmethod
    def _extra_headers(raw: str) -> Dict[str, str]:
        """解析浏览器复制的非 Cookie 请求头，拒绝会破坏 HTTP 请求的字段。"""
        blocked = {"cookie", "host", "content-length"}
        headers = {}
        for line in raw.splitlines():
            name, separator, value = line.partition(":")
            name, value = name.strip(), value.strip()
            if separator and name and value and name.lower() not in blocked:
                headers[name] = value
        return headers

    @staticmethod
    def _field(component: str, model: str, label: str, md: int, **props: Any) -> Dict[str, Any]:
        """构造统一的 Vuetify 配置字段。"""
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [{"component": component, "props": {"model": model, "label": label, **props}}],
        }

    @staticmethod
    def _default_user_agent() -> str:
        """返回商城请求使用的常见桌面浏览器标识。"""
        return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
