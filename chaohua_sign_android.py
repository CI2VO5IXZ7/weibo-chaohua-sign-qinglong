#!/usr/bin/env python3
"""安卓微博超话签到青龙脚本。

青龙依赖：requests、青龙内置 notify.py（通知可选，支持脚本位于订阅子目录）
环境变量：status_bujiaban = 完整 container_timeline_topicsub 请求 URL
运行命令：task chaohua_sign_android.py
仅执行超话签到，不包含发微博功能。不会输出登录参数或完整 URL。
"""

import os
import random
import re
import sys
import time
from urllib.parse import parse_qs, urlsplit

import requests

API = "https://api.weibo.cn"
LIST_PATH = "/2/statuses/container_timeline_topicsub"
SIGN_PATH = "/2/page/button"
USER_AGENT = "GM1910_12_weibo_16.8.2_android"
MAX_PAGES = 50
NOTIFICATION_TITLE = "微博超话签到"
BODY_DEFAULTS = {
    "sg_home_check_null": "1", "hasContent": "false",
    "flowId": "232478_-_mine_topic", "taskType": "refresh",
    "screenWidth": "360", "pageDataType": "flow", "tz": "Asia/Shanghai",
    "fid": "232478_-_mine_topic", "sgtotal_activity_enable": "1",
    "shallow_consume": "1", "sg_sub_channel_wbox_header_enable": "1",
    "filterGroupStyle": "1", "mix_media_enable": "1", "refresh": "scheme",
    "supergroup_album_v2": "1", "last_download_time": "-1",
    "flowVersion": "0.0.1", "redpacket_fly": "1", "sg_tab_config": "2",
    "invokeType": "init",
}


class TaskError(Exception):
    """只使用不包含登录凭据的固定错误说明。"""


def parse_account(raw):
    url = urlsplit(raw.strip())
    if (url.scheme != "https" or url.netloc != "api.weibo.cn"
            or url.path != LIST_PATH):
        raise TaskError("环境变量应为微博超话列表接口的完整 HTTPS 请求链接。")
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    missing = [k for k in ("aid", "c", "from", "gsid", "s") if not params.get(k)]
    if missing:
        raise TaskError("链接缺少必要参数：" + ", ".join(missing))
    return params


def request_json(session, method, path, **kwargs):
    try:
        response = session.request(method, API + path, timeout=(10, 25),
                                   allow_redirects=False, **kwargs)
        if response.status_code != 200:
            raise TaskError("微博接口 HTTP 状态：" + str(response.status_code))
        data = response.json()
    except requests.Timeout:
        raise TaskError("请求超时，请检查青龙服务器网络。") from None
    except requests.RequestException:
        raise TaskError("网络请求失败，请检查服务器到微博的连接。") from None
    except ValueError:
        raise TaskError("接口未返回 JSON，可能需要重新登录或人工验证。") from None
    if not isinstance(data, dict):
        raise TaskError("接口返回了不支持的数据结构。")
    return data


def iter_topics(node):
    """只处理明确标记为 sign_in 的按钮，忽略其他操作。"""
    if isinstance(node, list):
        for child in node:
            yield from iter_topics(child)
    elif isinstance(node, dict):
        for button in node.get("buttons", []):
            if not isinstance(button, dict) or button.get("type") != "sign_in":
                continue
            params = button.get("params") or {}
            action = params.get("action", "")
            scheme = parse_qs(urlsplit(node.get("scheme", "")).query)
            key = (scheme.get("containerid", [""])[0]
                   or button.get("ext_uid") or node.get("title_sub") or action)
            yield {
                "key": key, "title": str(node.get("title_sub", "未知超话")),
                "action": action,
                "done": button.get("name") in ("已签", "已签到", "今日已签到"),
            }
        for key, child in node.items():
            if key != "buttons" and isinstance(child, (dict, list)):
                yield from iter_topics(child)


def parse_action(action):
    outer = urlsplit(action)
    if (outer.path != SIGN_PATH or outer.netloc not in ("", "api.weibo.cn")
            or outer.scheme not in ("", "https")):
        raise TaskError("签到按钮地址结构已变化，请提供新的脱敏日志。")
    params = parse_qs(outer.query)
    target = params.get("request_url", [""])[0]
    inner = urlsplit(target)
    if (inner.hostname not in ("i.chaohua.weibo.com", "i.huati.weibo.com")
            or inner.path not in ("/mobile/shproxy/active_fcheckin",
                                  "/mobile/super/active_fcheckin")
            or inner.scheme not in ("http", "https")):
        raise TaskError("未识别的签到动作，已停止该操作。")
    # 只传给 HTTPS 微博 API，不直接访问内层 HTTP 地址。
    return target


def next_cursor(data):
    more = data.get("moreInfo") or {}
    if not isinstance(more, dict):
        return {}
    params = more.get("params") or {}
    if not isinstance(params, dict):
        return {}
    return {k: str(params[k]) for k in ("since_id", "page", "max_id")
            if k in params and params[k] is not None}


def new_progress():
    return {
        "results": [],
        "totals": {"成功": 0, "已签": 0, "失败": 0, "跳过": 0},
    }


def run_account(base, session, progress, secrets):
    totals = progress["totals"]
    body = {k: base.get(k, v) for k, v in BODY_DEFAULTS.items()}
    cursor, seen_cursors, seen_topics = {}, set(), set()
    for page in range(1, MAX_PAGES + 1):
        query = dict(base)
        form = dict(body)
        if page > 1:
            query.update(taskType="loadMore", invokeType="manual")
            form.update(taskType="loadMore", invokeType="manual")
            query.pop("refresh", None)
            form.pop("refresh", None)
        query.update(cursor)
        form.update(cursor)
        # files=(None, value) 生成与安卓抓包一致的 multipart/form-data。
        data = request_json(session, "POST", LIST_PATH, params=query,
                            files={k: (None, v) for k, v in form.items()})
        if "items" not in data or not isinstance(data["items"], list):
            raise TaskError("超话列表缺少 items：登录可能已失效，或接口发生变化。")
        topics = list(iter_topics(data["items"]))
        if not topics:
            if page == 1:
                raise TaskError("没有识别到超话签到按钮；请检查关注列表、登录状态或重新抓包。")
            break
        fresh = [topic for topic in topics if topic["key"] not in seen_topics]
        if not fresh:
            raise TaskError("分页返回重复内容，已停止；尚不能确认全部超话处理完成。")
        print("[列表] 第 {} 页，识别到 {} 个超话".format(page, len(topics)))
        for topic in fresh:
            seen_topics.add(topic["key"])
            if topic["done"]:
                state = "已签"
            elif not topic["action"]:
                state = "跳过"
            else:
                target = parse_action(topic["action"])
                params = {k: v for k, v in base.items()
                          if k not in BODY_DEFAULTS or k == "fid"}
                for k in ("since_id", "page", "max_id"):
                    params.pop(k, None)
                params["request_url"] = target
                result = request_json(session, "GET", SIGN_PATH, params=params)
                state = "成功" if str(result.get("result")) == "1" else "失败"
                time.sleep(random.uniform(5, 10))
            totals[state] += 1
            progress["results"].append((state, topic["title"]))
            print("[{}] {}".format(
                state, sanitize_text(topic["title"], secrets)), flush=True)
        upcoming = next_cursor(data)
        if not upcoming:
            break
        signature = tuple(sorted(upcoming.items()))
        if signature in seen_cursors:
            raise TaskError("分页游标重复，已停止；尚不能确认全部超话处理完成。")
        seen_cursors.add(signature)
        cursor = upcoming
    else:
        raise TaskError("达到 {} 页上限，未确认所有超话处理完成。".format(MAX_PAGES))
    print("[汇总] " + "，".join("{} {}".format(k, v) for k, v in totals.items()))
    return 1 if totals["失败"] or totals["跳过"] else 0


def sanitize_text(value, secrets=()):
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"https?://\S+", "[已隐藏链接]", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(?i)\b(?:gsid|aid|s|token|cookie|authorization)\b\s*[:=]\s*[^\s,;]+",
        "[已隐藏参数]", text)
    for secret in sorted({str(item) for item in secrets if item}, key=len, reverse=True):
        text = text.replace(secret, "[已隐藏]")
    return text


def notification_body(progress, final_message, secrets=()):
    lines = ["执行结果："]
    if progress["results"]:
        lines.extend("- [{}] {}".format(state, sanitize_text(title, secrets))
                     for state, title in progress["results"])
    else:
        lines.append("- 无超话处理结果")
    totals = progress["totals"]
    lines.append("汇总：" + "，".join("{} {}".format(k, totals[k]) for k in totals))
    lines.append("状态：" + sanitize_text(final_message, secrets))
    return "\n".join(lines)


def notify_search_dirs():
    """青龙不会把脚本目录加入 PYTHONPATH，订阅仓库运行在子目录时需手动定位 notify.py。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    dirs = [script_dir, os.getcwd()]
    parent = script_dir
    for _ in range(3):
        parent = os.path.dirname(parent)
        dirs.append(parent)
    for env in ("QL_DATA_DIR", "QL_DIR"):
        root = os.getenv(env)
        if root:
            dirs.append(os.path.join(root, "scripts"))
            dirs.append(os.path.join(root, "data", "scripts"))
    dirs.extend(["/ql/data/scripts", "/ql/scripts"])
    return list(dict.fromkeys(dirs))


def load_notifier():
    for directory in notify_search_dirs():
        if os.path.isfile(os.path.join(directory, "notify.py")):
            if directory not in sys.path:
                sys.path.insert(0, directory)
            print("[通知] 使用 notify.py：" + directory)
            break
    try:
        from notify import send
    except Exception as exc:
        print("[通知警告] 无法导入青龙 notify.py（{}），已搜索目录：{}".format(
            type(exc).__name__, "、".join(notify_search_dirs())))
        return None
    return send


def send_notification(body):
    try:
        sender = load_notifier()
        if sender is None:
            return
        sender(NOTIFICATION_TITLE, body)
        print("[通知] 已调用 notify.send，各渠道推送结果见上方 notify 输出。")
    except Exception as exc:
        print("[通知警告] 通知发送失败（{}），请检查青龙通知配置。".format(
            type(exc).__name__))


def main():
    raw = os.getenv("status_bujiaban", "")
    progress = new_progress()
    secrets = [raw] if raw else []
    exit_code = 1
    final_message = "执行失败。"
    try:
        if not raw.strip():
            raise TaskError("请在青龙添加并启用环境变量 status_bujiaban。")
        base = parse_account(raw)
        secrets.extend(base.get(key, "") for key in ("gsid", "s", "aid"))
        with requests.Session() as session:
            session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
            exit_code = run_account(base, session, progress, secrets)
        final_message = "执行完成。" if exit_code == 0 else "执行完成，但存在失败或跳过项。"
    except TaskError as exc:
        final_message = "错误：" + str(exc)
        print("[错误] " + sanitize_text(exc, secrets))
    except Exception as exc:
        final_message = "错误：未预期的接口结构或运行错误（{}）。".format(type(exc).__name__)
        # 不打印可能带有登录 URL 的异常详情或 traceback。
        print("[错误] " + final_message)
    body = notification_body(progress, final_message, secrets)
    send_notification(body)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
