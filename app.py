# -*- coding: utf-8 -*-
"""BiliPick —— 本地 App（浏览器界面）。运行后自动打开 http://127.0.0.1:61420/"""
from __future__ import annotations

import asyncio
import argparse
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import engine

_FROZEN = bool(getattr(sys, "frozen", False))
BASE = Path(sys.executable).resolve().parent if _FROZEN else Path(__file__).resolve().parent
RES = Path(getattr(sys, "_MEIPASS", str(BASE))) if _FROZEN else BASE   # 打包后的资源目录（web/）
DATA = BASE / "data"
CFG = DATA / "config.json"
WEB = RES / "web"
PORT = 61420
URL = f"http://127.0.0.1:{PORT}/"
TOKEN = secrets.token_urlsafe(18)

# 打包成无控制台 exe 时 stdout/stderr 为 None，统一接到 data/app.log
try:
    DATA.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None:
        sys.stdout = open(DATA / "app.log", "a", encoding="utf-8", buffering=1)
    if sys.stderr is None:
        sys.stderr = sys.stdout
except Exception:
    pass


# ─────────────────────────── 开机自启（Windows 启动文件夹 + VBS 静默启动） ───────────────────────────
def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_file() -> Path:
    return _startup_dir() / "BiliPick.vbs"


def _task_file() -> Path:
    return Path(r"C:\Windows\System32\Tasks\BiliPick")


def _launch_parts() -> list[str]:
    """开机自启要执行的命令行（打包后是 exe，源码运行是 pythonw + app.py）"""
    if _FROZEN:
        return [str(sys.executable), "--no-browser"]
    pyw = Path(sys.executable).with_name("pythonw.exe")
    if not pyw.exists():
        pyw = Path(sys.executable)
    return [str(pyw), str(BASE / "app.py"), "--no-browser"]


def _launch_plain() -> str:
    return " ".join(f'"{p}"' for p in _launch_parts())


def _launch_batch() -> str:
    return " ".join(f'\\"{p}\\"' for p in _launch_parts())


def _launch_vbs() -> str:
    cmdline = " ".join(f'"{p}"' for p in _launch_parts())
    return cmdline.replace('"', '""')


def _ensure_helpers() -> None:
    """生成 enable/disable-autostart.cmd（受限环境下让用户双击一次即可）"""
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        cmd_tr = _launch_batch()
        en = (
            "@echo off\r\n"
            f'schtasks /Create /TN "BiliPick" /TR "{cmd_tr}" /SC ONLOGON /F\r\n'
            "if errorlevel 1 (echo Failed. Right-click and Run as administrator.) else (echo Autostart enabled.)\r\n"
            "pause\r\n"
        )
        dis = (
            "@echo off\r\n"
            'schtasks /Delete /TN "BiliPick" /F\r\n'
            "if errorlevel 1 (echo Failed.) else (echo Autostart disabled.)\r\n"
            "pause\r\n"
        )
        (BASE / "enable-autostart.cmd").write_text(en, encoding="ascii")
        (BASE / "disable-autostart.cmd").write_text(dis, encoding="ascii")
    except Exception:
        pass


def autostart_enabled() -> bool:
    try:
        if _startup_file().exists():
            return True
        if _task_file().exists():
            return True
        return False
    except Exception:
        return False


def _schtasks(args: list[str]) -> bool:
    import subprocess
    try:
        r = subprocess.run(["schtasks"] + args, capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def set_autostart(on: bool) -> bool:
    """开/关开机自启：优先写启动文件夹 VBS，其次计划任务；都失败就留下 helper 让用户双击。"""
    import subprocess
    try:
        if on:
            vbs = (
                'Set sh = CreateObject("WScript.Shell")\r\n'
                f'sh.Run "{_launch_vbs()}", 0, False\r\n'
            )
            DATA.mkdir(parents=True, exist_ok=True)
            tmp = DATA / "autostart.vbs"
            tmp.write_text(vbs, encoding="ascii")
            try:
                _startup_file().parent.mkdir(parents=True, exist_ok=True)
                _startup_file().write_text(vbs, encoding="ascii")
            except Exception:
                subprocess.run(["cmd", "/c", "copy", "/y", str(tmp), str(_startup_file())],
                               capture_output=True)
            if not autostart_enabled():
                _schtasks(["/Create", "/TN", "BiliPick", "/TR", _launch_plain(),
                           "/SC", "ONLOGON", "/F"])
        else:
            try:
                if _startup_file().exists():
                    _startup_file().unlink()
            except Exception:
                subprocess.run(["cmd", "/c", "del", "/f", "/q", str(_startup_file())], capture_output=True)
            if _task_file().exists():
                _schtasks(["/Delete", "/TN", "BiliPick", "/F"])
    except Exception:
        pass
    status = autostart_enabled()
    if status != on:
        _ensure_helpers()
    return status


DEFAULT_CFG = {
    "provider": "openai",
    "api_key": "",
    "api_base": "https://api.deepseek.com",
    "model": "",
    "prices": {"input_cache_hit": 0.02, "input_cache_miss_idle": 1.0, "input_cache_miss_peak": 2.0,
               "output_idle": 4.0, "output_peak": 8.0},
    "budget_cny": 3.0,
    "budget_stop_ratio": 0.9,
    "max_minutes": 10,
    "days_back": 10,
    "min_play": 500,
    "search_pages": 1,
    "search_orders": ["click", "pubdate"],
    "skip_followed": True,
    "history_pages": 5,
    "exclude_keywords": ["美妆", "护肤", "穿搭", "服装", "时尚", "健身", "减肥", "瑜伽", "母婴", "育儿",
                         "星座", "情感", "恋爱", "追星", "明星", "颜值", "口红", "香水", "美甲", "化妆", "发型"],
    "interests": "什么都看一点；只要是真精品，讨厌标题党和注水。",
    "categories": [
        {"id": "tech", "label": "科技", "quota": 5, "deep": 30, "candidates": 150, "min_quality": 12, "min_score": 5.5,
         "keywords": ["科技", "数码", "编程", "人工智能", "芯片", "机器人", "汽车", "硬件"],
         "match": ["科技", "数码", "计算机", "编程", "人工智能", "机械", "汽车", "芯片", "手机", "硬件", "软件", "互联网", "电子"]},
        {"id": "science", "label": "科普", "quota": 5, "deep": 30, "candidates": 150, "min_quality": 12, "min_score": 6.0,
         "keywords": ["科普", "科学", "物理", "数学", "天文", "历史", "军事", "心理", "经济", "财经"],
         "match": ["科学", "科普", "自然", "宇宙", "天文", "物理", "数学", "化学", "生物", "地理", "历史", "军事", "心理", "经济", "财经", "知识", "人文", "社会", "法律", "医学"]},
        {"id": "life", "label": "生活", "quota": 5, "deep": 30, "candidates": 150, "min_quality": 14, "min_score": 6.0,
         "keywords": ["美食", "做饭", "生活", "挑战", "搞笑", "手工", "旅行", "宠物", "家居"],
         "match": ["生活", "美食", "做饭", "日常", "挑战", "搞笑", "手工", "旅行", "宠物", "家居", "三农", "vlog"]},
        {"id": "acgn", "label": "ACGN", "quota": 10, "deep": 45, "candidates": 220, "min_quality": 15, "min_score": 6.0,
         "keywords": ["动画", "游戏", "番剧", "鬼畜", "二次元", "漫画", "虚拟主播"],
         "match": ["动画", "番剧", "国创", "游戏", "鬼畜", "虚拟", "mmd", "漫画", "手办", "二次元", "电竞"]},
        {"id": "other", "label": "其他", "quota": 5, "deep": 30, "candidates": 150, "min_quality": 12, "min_score": 6.0,
         "keywords": ["纪录片", "音乐", "影视", "体育", "舞蹈", "动物"],
         "match": ["纪录片", "音乐", "影视", "电影", "电视剧", "体育", "舞蹈", "运动"]},
    ],
    "triage_batch": 120,
    "deep_batch": 6,
    "subtitle_chars": 8000,
    "comments_per_video": 30,
    "comment_chars": 1200,
    "min_final_score": 6.0,
    "taste_from_toview": 30,
    "schedule": {"enabled": False, "time": "12:40"},
}

_state = {"running": False, "log": [], "last": None, "last_run_day": ""}
_lock = threading.Lock()


def load_cfg() -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    if not CFG.exists():
        CFG.write_text(json.dumps(DEFAULT_CFG, ensure_ascii=False, indent=2), encoding="utf-8")
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    for k, v in DEFAULT_CFG.items():
        cfg.setdefault(k, v)
    return cfg


def save_cfg(cfg: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def logline(line: str) -> None:
    with _lock:
        _state["log"].append(line)
        if len(_state["log"]) > 4000:
            _state["log"] = _state["log"][-3000:]


engine.set_log_sink(logline)


def _run_thread(cfg: dict) -> None:
    with _lock:
        if _state["running"]:
            return
        _state["running"] = True
        _state["last"] = None
    logline("=" * 20 + " 开始跑一轮 " + "=" * 20)
    try:
        res = asyncio.run(engine.run(cfg, progress=lambda m: None))
        with _lock:
            _state["last"] = res
            if res.get("ok"):
                _state["last_run_day"] = datetime.now().strftime("%Y-%m-%d")
        logline(json.dumps(res, ensure_ascii=False)[:800])
    except Exception as e:
        logline(f"运行失败：{type(e).__name__}: {e}")
        with _lock:
            _state["last"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        with _lock:
            _state["running"] = False
        logline("=" * 20 + " 结束 " + "=" * 20)


def _scheduler() -> None:
    while True:
        try:
            cfg = load_cfg()
            sch = cfg.get("schedule") or {}
            if sch.get("enabled") and not _state["running"]:
                target = str(sch.get("time") or "")
                now = datetime.now()
                if target and now.strftime("%H:%M") == target and _state["last_run_day"] != now.strftime("%Y-%m-%d"):
                    logline(f"定时任务触发（{target}）")
                    threading.Thread(target=_run_thread, args=(cfg,), daemon=True).start()
        except Exception as e:
            logline(f"定时器出错：{e}")
        time.sleep(20)


class BiliPickServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False   # 端口已被占用时直接抛 OSError，好让第二个实例优雅退出


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def _authed(self) -> bool:
        return self.headers.get("X-Token") == TOKEN

    def _read_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n).decode() or "{}")
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            p = WEB / "index.html"
            html = p.read_text(encoding="utf-8").replace("__BILIPICK_TOKEN__", TOKEN)
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        if not self._authed():
            return self._json({"ok": False, "error": "unauthorized"}, 403)
        if u.path == "/api/state":
            cfg = load_cfg()
            safe = dict(cfg)
            safe["api_key_set"] = bool(cfg.get("api_key"))
            safe["api_key"] = ""
            with _lock:
                st = {"running": _state["running"], "last": _state["last"], "last_run_day": _state["last_run_day"]}
            return self._json({"ok": True, "config": safe, "state": st})
        if u.path == "/api/whoami":
            return self._json({"ok": True, **asyncio.run(engine.whoami())})
        if u.path == "/api/autostart":
            return self._json({"ok": True, "enabled": autostart_enabled()})
        if u.path == "/api/log":
            since = int(parse_qs(u.query).get("since", ["0"])[0])
            with _lock:
                return self._json({"ok": True, "lines": _state["log"][since:], "next": len(_state["log"])})
        if u.path == "/api/reports":
            d = DATA / "reports"
            files = sorted([p.name for p in d.glob("*.md")], reverse=True) if d.exists() else []
            return self._json({"ok": True, "files": files[:60]})
        if u.path == "/api/report":
            day = (parse_qs(u.query).get("day", [""])[0] or "").replace("/", "").replace("..", "")
            p = DATA / "reports" / f"{day}.md"
            if not p.exists():
                return self._json({"ok": False, "error": "没有这一天的日报"})
            return self._json({"ok": True, "text": p.read_text(encoding="utf-8")})
        if u.path == "/api/cost":
            f = DATA / "cost.jsonl"
            rows = []
            if f.exists():
                rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
            today = datetime.now().strftime("%Y-%m-%d")
            return self._json({"ok": True, "today": round(sum(r["cny"] for r in rows if r["day"] == today), 4),
                               "rows": rows[-20:]})
        return self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        if not self._authed():
            return self._json({"ok": False, "error": "unauthorized"}, 403)
        u = urlparse(self.path)
        body = self._read_json()
        try:
            if u.path == "/api/config":
                cfg = load_cfg()
                incoming = body.get("config") or {}
                if incoming.get("api_key") == "__clear__":
                    cfg["api_key"] = ""
                elif str(incoming.get("api_key") or "").strip():
                    cfg["api_key"] = str(incoming["api_key"]).strip()
                incoming.pop("api_key", None)
                for k, v in incoming.items():
                    cfg[k] = v
                if str(cfg.get("provider") or "") not in ("openai", "anthropic", "gemini", "jsonl"):
                    cfg["provider"] = "openai"
                save_cfg(cfg)
                return self._json({"ok": True})
            if u.path == "/api/login/start":
                return self._json({"ok": True, **asyncio.run(engine.login_start())})
            if u.path == "/api/login/poll":
                return self._json({"ok": True, **asyncio.run(engine.login_poll())})
            if u.path == "/api/run":
                if _state["running"]:
                    return self._json({"ok": False, "error": "正在跑，等这一轮结束"})
                cfg = load_cfg()
                threading.Thread(target=_run_thread, args=(cfg,), daemon=True).start()
                return self._json({"ok": True, "started": True})
            if u.path == "/api/whoami":
                return self._json({"ok": True, **asyncio.run(engine.whoami())})
            if u.path == "/api/autostart":
                want = bool(body.get("enabled"))
                status = set_autostart(want)
                applied = (status == want)
                logline(f"开机自启：{'已开启' if status else '已关闭'}" + ("" if applied else "（自动设置失败，已生成 helper 脚本）"))
                return self._json({"ok": True, "enabled": status, "applied": applied})
        except Exception as e:
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        return self._json({"ok": False, "error": "not found"}, 404)


def main() -> None:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器（开机自启用）")
    args, _ = ap.parse_known_args()

    DATA.mkdir(parents=True, exist_ok=True)
    load_cfg()
    _ensure_helpers()
    try:
        srv = BiliPickServer(("127.0.0.1", PORT), Handler)
    except OSError:
        # 已经在跑（例如开机自启已在后台）：直接打开界面，不再起第二个实例
        if not args.no_browser:
            try:
                webbrowser.open(URL)
            except Exception:
                pass
        print(f"BiliPick 已在运行： {URL}")
        return
    threading.Thread(target=_scheduler, daemon=True).start()
    print(f"BiliPick 已启动： {URL}")
    if not args.no_browser:
        try:
            webbrowser.open(URL)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
