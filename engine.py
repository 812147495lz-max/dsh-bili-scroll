# -*- coding: utf-8 -*-
"""
BiliPick 引擎 —— 搜索 / 分类 / 质量分 / 去重 / 粗排 / 精判 / 加入稍后再看 / 日报
不依赖 DSH 插件：只依赖 bilibili_api + aiohttp + qrcode。
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bilibili_api import Credential, comment, search, user, video
from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

_FROZEN = bool(getattr(sys, "frozen", False))
BASE = Path(sys.executable).resolve().parent if _FROZEN else Path(__file__).resolve().parent
DATA = BASE / "data"
BJ = timezone(timedelta(hours=8))
CRED_FILE = DATA / "credential.json"

_log_sink = None


def log(msg: str) -> None:
    line = f"[{datetime.now(BJ).strftime('%H:%M:%S')}] {msg}"
    if _log_sink:
        try:
            _log_sink(line)
        except Exception:
            pass


def set_log_sink(fn) -> None:
    global _log_sink
    _log_sink = fn


# ────────────────────────────── 凭证 / 登录 ──────────────────────────────
def load_cred() -> Credential | None:
    if not CRED_FILE.exists():
        return None
    try:
        d = json.loads(CRED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    return Credential(sessdata=d.get("sessdata", ""), bili_jct=d.get("bili_jct", ""),
                      buvid3=d.get("buvid3", ""), dedeuserid=d.get("dedeuserid", ""))


_login: QrCodeLogin | None = None


async def login_start() -> dict:
    """生成二维码，返回 png 的 base64"""
    global _login
    _login = QrCodeLogin()
    await _login.generate_qrcode()
    pic = _login.get_qrcode_picture()
    import base64
    return {"ok": True, "png": "data:image/png;base64," + base64.b64encode(pic.content).decode()}


async def login_poll() -> dict:
    global _login
    if _login is None:
        return {"ok": False, "state": "no-session"}
    try:
        state = await _login.check_state()
    except Exception as e:
        return {"ok": False, "state": "error", "error": str(e)}
    name = {QrCodeLoginEvents.SCAN: "scanned", QrCodeLoginEvents.CONF: "confirm",
            QrCodeLoginEvents.TIMEOUT: "expired", QrCodeLoginEvents.DONE: "ok"}.get(state, "waiting")
    if name == "ok":
        cred = _login.get_credential()
        DATA.mkdir(parents=True, exist_ok=True)
        CRED_FILE.write_text(json.dumps({
            "sessdata": cred.sessdata or "", "bili_jct": cred.bili_jct or "",
            "buvid3": cred.buvid3 or "", "dedeuserid": cred.dedeuserid or "",
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        who = await whoami()
        _login = None
        return {"ok": True, "state": "ok", "who": who}
    return {"ok": True, "state": name}


async def whoami() -> dict:
    cred = load_cred()
    if not cred:
        return {"logged_in": False}
    try:
        me = await user.get_self_info(cred)
        return {"logged_in": True, "name": me.get("name"), "mid": me.get("mid"), "following": me.get("following")}
    except Exception as e:
        return {"logged_in": False, "error": str(e)}


# ────────────────────────────── 抓取 ──────────────────────────────
def parse_duration(s) -> int:
    if isinstance(s, (int, float)):
        return int(s)
    s = str(s or "").strip()
    if not s:
        return 0
    try:
        parts = [int(x) for x in s.split(":")]
    except ValueError:
        return 0
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec


def _clean(t: str) -> str:
    return re.sub(r"<[^>]+>", "", str(t or ""))


def classify(c: dict, cfg: dict) -> str:
    blob = " ".join([_clean(c.get("title")), str(c.get("typename") or ""), str(c.get("tags") or ""), str(c.get("desc") or "")]).lower()
    for cat in cfg["categories"]:
        pats = [str(x).lower() for x in (cat.get("match") or cat.get("keywords") or []) if str(x).strip()]
        if pats and any(p in blob for p in pats):
            return cat["id"]
    ids = [c["id"] for c in cfg["categories"]]
    return "other" if "other" in ids else ids[-1]


def quality_score(c: dict) -> float:
    def lg(n):
        return math.log10(1 + max(0, int(n or 0)))
    return round(1.0 * lg(c.get("play")) + 1.5 * lg(c.get("like")) + 1.5 * lg(c.get("favorite"))
                 + 1.0 * lg(c.get("danmaku")) + 1.0 * lg(c.get("comment_cnt")), 1)


async def collect_candidates(cfg: dict, cred: Credential) -> list[dict]:
    orders = {"click": search.OrderVideo.CLICK, "pubdate": search.OrderVideo.PUBDATE}
    end = datetime.now(BJ).strftime("%Y-%m-%d")
    start = (datetime.now(BJ) - timedelta(days=int(cfg["days_back"]))).strftime("%Y-%m-%d")
    seen: dict[str, dict] = {}
    for cat in cfg["categories"]:
        for kw in cat.get("keywords") or []:
            for order_name in cfg.get("search_orders") or ["click"]:
                order = orders.get(order_name, search.OrderVideo.CLICK)
                for page in range(1, int(cfg.get("search_pages", 1)) + 1):
                    try:
                        res = await search.search_by_type(kw, search_type=search.SearchObjectType.VIDEO,
                                                          order_type=order, time_start=start, time_end=end, page=page)
                    except Exception as e:
                        log(f"搜索失败 {kw}/{order_name}: {type(e).__name__}: {e}")
                        continue
                    for it in (res or {}).get("result") or []:
                        bv = it.get("bvid")
                        if not bv or bv in seen:
                            continue
                        seen[bv] = {
                            "bvid": bv, "mid": int(it.get("mid") or it.get("uid") or 0),
                            "title": _clean(it.get("title")), "up": it.get("author") or "",
                            "typename": str(it.get("typename") or it.get("tname") or ""),
                            "play": int(it.get("play") or 0), "like": int(it.get("like") or 0),
                            "favorite": int(it.get("favorites") or 0),
                            "danmaku": int(it.get("danmaku") or it.get("video_review") or 0),
                            "comment_cnt": int(it.get("review") or 0),
                            "seconds": parse_duration(it.get("duration")),
                            "pubdate": int(it.get("pubdate") or 0),
                            "desc": (it.get("description") or "").strip(),
                            "tags": (it.get("tag") or "") + "," + (it.get("tags") or ""),
                            "url": f"https://www.bilibili.com/video/{bv}", "kw": kw,
                        }
                    await asyncio.sleep(0.35)
    for c in seen.values():
        c["cat"] = classify(c, cfg)
        c["quality"] = quality_score(c)
    return list(seen.values())


async def get_subtitle(cred: Credential, bvid: str) -> str:
    v = video.Video(bvid=bvid, credential=cred)
    info = await v.get_info()
    subs = await v.get_subtitle(cid=info["cid"])
    lst = (subs or {}).get("subtitles") or []
    if not lst:
        return ""
    target = next((s for s in lst if s.get("lan") in ("ai-zh", "zh-CN", "zh")), lst[0])
    url = target.get("subtitle_url", "")
    if url.startswith("//"):
        url = "https:" + url
    import aiohttp
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            data = await r.json()
    return "\n".join(x.get("content", "") for x in data.get("body") or [])


async def get_comments(cred: Credential, bvid: str, num: int = 30) -> str:
    v = video.Video(bvid=bvid, credential=cred)
    info = await v.get_info()
    resp = await comment.get_comments(oid=info["aid"], type_=comment.CommentResourceType.VIDEO,
                                      page_index=1, order=comment.OrderType.LIKE, credential=cred)
    parts = []
    for r in (resp.get("replies") or [])[:num]:
        msg = re.sub(r"\s+", " ", str((r.get("content") or {}).get("message") or "")).strip()
        if msg:
            parts.append(f"[{int(r.get('like') or 0)}赞] {msg[:90]}")
    return " / ".join(parts)


async def toview_bv(cred: Credential) -> set[str]:
    try:
        d = await user.get_toview_list(cred)
        payload = d.get("data") if isinstance(d, dict) and isinstance(d.get("data"), dict) else d
        return {it.get("bvid") for it in (payload or {}).get("list") or [] if it.get("bvid")}
    except Exception:
        return set()


async def load_followed(cred: Credential, cfg: dict) -> set[int]:
    if not cfg.get("skip_followed", True):
        return set()
    mids: set[int] = set()
    try:
        me = await user.get_self_info(cred)
        uid = int(me.get("mid") or 0)
        if not uid:
            return mids
        u = user.User(uid, credential=cred)
        pn = 1
        total = int(me.get("following") or 0)
        while pn <= 20:
            d = await u.get_followings(pn=pn, ps=50)
            lst = (d or {}).get("list") or []
            if d.get("total"):
                total = int(d["total"])
            mids |= {int(x["mid"]) for x in lst if x.get("mid")}
            if not lst or (total and len(mids) >= total):
                break
            pn += 1
            await asyncio.sleep(0.3)
        log(f"已关注 UP：{len(mids)}/{total or '?'}")
    except Exception as e:
        log(f"拉关注列表失败：{e}")
    return mids


async def load_watched(cred: Credential, cfg: dict) -> set[str]:
    out: set[str] = set()
    try:
        for pn in range(1, int(cfg.get("history_pages", 5)) + 1):
            d = await user.get_self_history(page_num=pn, per_page_item=50, credential=cred)
            lst = d if isinstance(d, list) else (d.get("list") or [])
            if not lst:
                break
            for it in lst:
                bv = (it.get("history") or {}).get("bvid") or it.get("bvid")
                if bv:
                    out.add(bv)
            if len(lst) < 50:
                break
            await asyncio.sleep(0.3)
        log(f"观看历史：{len(out)} 条")
    except Exception as e:
        log(f"拉观看历史失败：{e}")
    return out


# ────────────────────────────── 状态 ──────────────────────────────
def _seen_file() -> Path:
    return DATA / "seen.json"


def load_seen() -> dict:
    try:
        return json.loads(_seen_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_seen(picks: list[dict], skipped: list[dict]) -> None:
    data = load_seen()
    today = datetime.now(BJ).strftime("%Y-%m-%d")
    for p in picks:
        data[p["bvid"]] = {"date": today, "score": p.get("score"), "verdict": "picked", "cat": p.get("cat")}
    for s in skipped:
        data.setdefault(s["bvid"], {"date": today, "score": s.get("score"), "verdict": "skipped", "cat": s.get("cat")})
    DATA.mkdir(parents=True, exist_ok=True)
    _seen_file().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ────────────────────────────── 记账 ──────────────────────────────
class CostTracker:
    def __init__(self, cfg: dict):
        p = cfg.get("prices") or {}
        self.p = {"hit": float(p.get("input_cache_hit", 0.02)),
                  "miss_idle": float(p.get("input_cache_miss_idle", 1.0)),
                  "miss_peak": float(p.get("input_cache_miss_peak", 2.0)),
                  "out_idle": float(p.get("output_idle", 4.0)),
                  "out_peak": float(p.get("output_peak", 8.0))}
        self.budget = float(cfg.get("budget_cny", 3.0)) * float(cfg.get("budget_stop_ratio", 0.9))
        self.spent = self.in_tokens = self.out_tokens = self.calls = 0
        self.t0 = time.time()

    @staticmethod
    def is_peak() -> bool:
        dt = datetime.now(BJ)
        return dt.weekday() < 5 and (9 <= dt.hour < 12 or 14 <= dt.hour < 18)

    def price(self):
        peak = self.is_peak()
        return {"miss": self.p["miss_peak"] if peak else self.p["miss_idle"],
                "out": self.p["out_peak"] if peak else self.p["out_idle"], "hit": self.p["hit"]}

    def add_usage(self, usage: dict) -> float:
        pr = self.price()
        hit = int(usage.get("prompt_cache_hit_tokens") or 0)
        miss = int(usage.get("prompt_cache_miss_tokens") or 0)
        if hit + miss == 0:
            miss = int(usage.get("prompt_tokens") or 0)
        out = int(usage.get("completion_tokens") or 0)
        cost = (hit * pr["hit"] + miss * pr["miss"] + out * pr["out"]) / 1_000_000
        self.spent += cost
        self.in_tokens += hit + miss
        self.out_tokens += out
        self.calls += 1
        return cost

    def estimate(self, chars: int, out_tokens: int = 800) -> float:
        pr = self.price()
        return (chars / 1.6 * pr["miss"] + out_tokens * pr["out"]) / 1_000_000

    def can_afford(self, chars: int) -> bool:
        return self.spent + self.estimate(chars) <= self.budget

    def ledger(self, note: str) -> None:
        DATA.mkdir(parents=True, exist_ok=True)
        with open(DATA / "cost.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(BJ).isoformat(timespec="seconds"),
                                "day": datetime.now(BJ).strftime("%Y-%m-%d"), "note": note,
                                "calls": self.calls, "in_tokens": self.in_tokens,
                                "out_tokens": self.out_tokens, "cny": round(self.spent, 4)},
                               ensure_ascii=False) + "\n")


# ────────────────────────────── LLM ──────────────────────────────
class LLMError(RuntimeError):
    pass


def _parse_json(text: str) -> dict:
    t = re.sub(r"^```(?:json)?", "", text.strip()).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", t)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    pairs = re.findall(r'"bvid"\s*:\s*"(BV[0-9A-Za-z]{10})"[^}]*?"score"\s*:\s*([0-9.]+)', t)
    if pairs:
        return {"scores": [{"bvid": b, "score": float(s)} for b, s in pairs]}
    raise LLMError("模型返回的不是合法 JSON")


PROVIDER_DEFAULTS = {
    "openai": {"base": "https://api.deepseek.com", "model": "deepseek-flash"},
    "anthropic": {"base": "https://api.anthropic.com", "model": "claude-sonnet-4-5"},
    "gemini": {"base": "https://generativelanguage.googleapis.com", "model": "gemini-2.5-pro"},
    "jsonl": {"base": "", "model": ""},
}


def _post_json(url: str, body: dict, headers: dict, timeout: int = 150) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _find_text(obj) -> str:
    """从各种响应结构里尽量捞出文本（OpenAI/Anthropic/Gemini/自定义）"""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return "".join(_find_text(x) for x in obj)
    if not isinstance(obj, dict):
        return ""
    for key in ("content", "text", "output_text", "response"):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, (dict, list)):
            got = _find_text(v)
            if got:
                return got
    if isinstance(obj.get("choices"), list):
        ch = obj["choices"][0] if obj["choices"] else {}
        got = _find_text(ch.get("message") or ch.get("delta") or {})
        if got:
            return got
    if isinstance(obj.get("candidates"), list):
        cand = obj["candidates"][0] if obj["candidates"] else {}
        got = _find_text(cand.get("content") or "")
        if got:
            return got
    if isinstance(obj.get("generations"), list):
        got = _find_text(obj["generations"])
        if got:
            return got
    if isinstance(obj.get("content"), list):
        return "".join(_find_text(x) for x in obj["content"])
    if isinstance(obj.get("parts"), list):
        return _find_text(obj["parts"])
    return ""


def _usage_prompt_completion(u: dict) -> dict:
    """统一成 prompt_tokens / completion_tokens"""
    if not isinstance(u, dict):
        return {}
    if "prompt_tokens" in u or "completion_tokens" in u:
        return {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                "prompt_cache_hit_tokens": u.get("prompt_cache_hit_tokens"),
                "prompt_cache_miss_tokens": u.get("prompt_cache_miss_tokens")}
    if "input_tokens" in u or "output_tokens" in u:
        return {"prompt_tokens": u.get("input_tokens"), "completion_tokens": u.get("output_tokens")}
    for k in ("promptTokenCount", "candidatesTokenCount"):
        if k in u:
            return {"prompt_tokens": u.get("promptTokenCount"), "completion_tokens": u.get("candidatesTokenCount")}
    return {}


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
    rest = [m for m in messages if m.get("role") != "system"]
    return system, rest


def _request_openai(cfg, messages, out_tokens, key):
    base = (cfg.get("api_base") or PROVIDER_DEFAULTS["openai"]["base"]).rstrip("/")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    body = {"model": cfg.get("model") or PROVIDER_DEFAULTS["openai"]["model"], "messages": messages,
            "temperature": 0.2, "max_tokens": int(out_tokens), "stream": False}
    data = json.loads(_post_json(url, body, {"Content-Type": "application/json",
                                             "Authorization": f"Bearer {key}"}))
    text = _find_text(data)
    return text, data.get("usage") or {}


def _request_anthropic(cfg, messages, out_tokens, key):
    base = (cfg.get("api_base") or PROVIDER_DEFAULTS["anthropic"]["base"]).rstrip("/")
    url = base if base.endswith("/messages") else (base + "/messages" if base.endswith("/v1") else base + "/v1/messages")
    system, rest = _split_system(messages)
    body = {"model": cfg.get("model") or PROVIDER_DEFAULTS["anthropic"]["model"],
            "max_tokens": int(out_tokens), "temperature": 0.2,
            "messages": [{"role": ("assistant" if m.get("role") == "assistant" else "user"),
                          "content": m.get("content", "")} for m in rest]}
    if system:
        body["system"] = system
    data = json.loads(_post_json(url, body, {"Content-Type": "application/json",
                                             "x-api-key": key,
                                             "anthropic-version": "2023-06-01"}))
    text = _find_text(data)
    return text, data.get("usage") or {}


def _request_gemini(cfg, messages, out_tokens, key):
    from urllib.parse import quote
    base = (cfg.get("api_base") or PROVIDER_DEFAULTS["gemini"]["base"]).rstrip("/")
    model = cfg.get("model") or PROVIDER_DEFAULTS["gemini"]["model"]
    url = f"{base}/v1beta/models/{quote(model)}:generateContent?key={quote(key)}"
    system, rest = _split_system(messages)
    contents = []
    for m in rest:
        role = "model" if m.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})
    body = {"contents": contents,
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": int(out_tokens),
                                 "responseMimeType": "application/json"}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    data = json.loads(_post_json(url, body, {"Content-Type": "application/json"}))
    text = _find_text(data)
    return text, data.get("usageMetadata") or {}


def _request_jsonl(cfg, messages, out_tokens, key):
    """自定义 JSONL/流式接口：POST 到用户填的完整 URL，按行拼接文本"""
    base = (cfg.get("api_base") or "").strip()
    if not base:
        raise LLMError("jsonl 接口需要填完整的 Base URL（例如 https://your-gateway/v1/chat）")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": cfg.get("model") or "", "messages": messages, "temperature": 0.2,
            "max_tokens": int(out_tokens), "stream": True}
    raw = _post_json(base, body, headers)
    text = raw.decode("utf-8", "replace")
    ctype = ""
    try:
        ctype = (raw[:1] and "json")
    except Exception:
        pass
    chunks, usage = [], {}
    try:
        obj = json.loads(text)
        return _find_text(obj), obj.get("usage") or {}
    except Exception:
        pass
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if line in ("[DONE]", "DONE"):
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        chunks.append(_find_text(ev))
        if isinstance(ev, dict) and ev.get("usage"):
            usage = ev["usage"]
    if not chunks:
        raise LLMError("jsonl 接口没有返回可解析的文本")
    return "".join(chunks), usage


def llm_chat(cfg: dict, tracker: CostTracker, messages: list[dict], out_tokens: int = 900) -> dict:
    import urllib.error
    provider = str(cfg.get("provider") or "openai").lower()
    if provider not in PROVIDER_DEFAULTS:
        provider = "openai"
    key = str(cfg.get("api_key") or "").strip()
    if not key and provider != "jsonl":
        raise LLMError(f"还没填 API key（{provider}）")
    chars = sum(len(m.get("content", "")) for m in messages)
    if not tracker.can_afford(chars):
        raise LLMError(f"预算不足（已花 ¥{tracker.spent:.3f} / 上限 ¥{tracker.budget:.2f}）")
    fn = {"openai": _request_openai, "anthropic": _request_anthropic,
          "gemini": _request_gemini, "jsonl": _request_jsonl}[provider]
    last = None
    for attempt in range(3):
        try:
            text, usage = fn(cfg, messages, out_tokens, key)
            tracker.add_usage(_usage_prompt_completion(usage))
            if not text.strip():
                raise LLMError("模型返回了空内容")
            return _parse_json(text)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            last = f"HTTP {e.code}: {raw[:260]}"
            if e.code == 401:
                raise LLMError(f"API key 无效或没有权限（401）。{raw[:160]}")
            if e.code == 404:
                raise LLMError(f"接口 404：检查 Base URL 和模型名。{raw[:160]}")
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise LLMError(last)
        except LLMError:
            raise
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.0 * (attempt + 1))
    raise LLMError(f"调用失败：{last}")


def triage(cfg: dict, tracker: CostTracker, cands: list[dict], taste: list[str]) -> list[dict]:
    if not cands:
        return []
    sys_p = ("你是帮人挑视频的编辑。按信息密度、实操性、相关性、新颖度打分 0-100；标题党/注水/纯广告低分。"
             '只输出 JSON：{"scores":[{"bvid":"BV...","score":85}]}，不要别的文字。')
    batch = int(cfg.get("triage_batch", 120))
    scores: dict[str, float] = {}
    for i in range(0, len(cands), batch):
        chunk = cands[i:i + batch]
        payload = [{"bvid": c["bvid"], "title": c["title"][:60], "up": c["up"][:20],
                    "minutes": round(c["seconds"] / 60), "play": c["play"],
                    "typename": c.get("typename", ""), "desc": c["desc"][:160]} for c in chunk]
        try:
            data = llm_chat(cfg, tracker, [
                {"role": "system", "content": sys_p},
                {"role": "user", "content": f"他的兴趣：{cfg.get('interests','')}\n参考品味：{json.dumps(taste[:20], ensure_ascii=False)}\n候选：{json.dumps(payload, ensure_ascii=False)}"},
            ], out_tokens=min(4000, 18 * len(payload) + 200))
        except LLMError as e:
            log(f"粗排失败：{e}")
            continue
        for it in data.get("scores") or []:
            if it.get("bvid"):
                try:
                    scores[it["bvid"]] = float(it.get("score") or 0)
                except (TypeError, ValueError):
                    scores[it["bvid"]] = 0.0
    for c in cands:
        c["triage"] = scores.get(c["bvid"], 0.0)
    return sorted(cands, key=lambda x: x["triage"], reverse=True)


async def deep_judge(cfg: dict, tracker: CostTracker, cands: list[dict], cred: Credential, taste: list[str]) -> list[dict]:
    if not cands:
        return []
    sem = asyncio.Semaphore(4)
    limit = int(cfg.get("subtitle_chars", 8000))

    async def fetch(c):
        async with sem:
            try:
                c["subtitle"] = (await get_subtitle(cred, c["bvid"]))[:limit]
                c["sub_ok"] = bool(c["subtitle"])
            except Exception as e:
                c["sub_ok"] = False
                c["sub_why"] = f"{type(e).__name__}: {e}"
            try:
                c["comments"] = (await get_comments(cred, c["bvid"], int(cfg.get("comments_per_video", 30))))[: int(cfg.get("comment_chars", 1200))]
            except Exception:
                c["comments"] = ""
            await asyncio.sleep(0.3)

    await asyncio.gather(*[fetch(c) for c in cands])
    ok = [c for c in cands if c.get("sub_ok")]
    log(f"字幕 {len(ok)}/{len(cands)} 条读到（没字幕跳过）")
    sys_p = ("你是严格的审片编辑。评分 0-10；必须从字幕摘一句原文作依据；理由≤60字说明『为什么该看』。"
             "结合观众评论：高赞骂标题党/注水扣分，补干货加分。平庸/复述常识/广告低分；宁缺毋滥。"
             '只输出 JSON：{"judgments":[{"bvid":"BV...","score":8.5,"reason":"...","quote":"字幕原句","comment_signal":"观众评论说明了什么"}]}。')
    batch = int(cfg.get("deep_batch", 6))
    max_min = float(cfg.get("max_minutes", 10))
    out: list[dict] = []
    for i in range(0, len(ok), batch):
        if time.time() - tracker.t0 > max_min * 60:
            log(f"到 {max_min:.0f} 分钟上限，收尾（判完 {len(out)}/{len(ok)}）")
            break
        chunk = ok[i:i + batch]
        chars = sum(len(c["subtitle"]) + len(c.get("comments") or "") for c in chunk) + 800
        if not tracker.can_afford(chars):
            log("预算到顶，停止精判")
            break
        items = [{"bvid": c["bvid"], "title": c["title"][:60], "up": c["up"][:20],
                  "minutes": round(c["seconds"] / 60), "play": c["play"],
                  "subtitle": c["subtitle"], "comments": c.get("comments") or "（没抓到评论）"} for c in chunk]
        try:
            data = llm_chat(cfg, tracker, [
                {"role": "system", "content": sys_p},
                {"role": "user", "content": f"他的兴趣：{cfg.get('interests','')}\n参考品味：{json.dumps(taste[:15], ensure_ascii=False)}\n{json.dumps(items, ensure_ascii=False)}"},
            ], out_tokens=min(4000, 360 * len(items)))
        except LLMError as e:
            log(f"精判失败：{e}")
            continue
        by = {it["bvid"]: it for it in (data.get("judgments") or []) if isinstance(it, dict) and it.get("bvid")}
        for c in chunk:
            it = by.get(c["bvid"])
            if not it:
                continue
            try:
                c["score"] = float(it.get("score") or 0)
            except (TypeError, ValueError):
                c["score"] = 0.0
            c["reason"] = (it.get("reason") or "").strip()
            c["quote"] = (it.get("quote") or "").strip()
            c["comment_signal"] = (it.get("comment_signal") or "").strip()
            out.append(c)
    return out


# ────────────────────────────── 主流程 ──────────────────────────────
def _known_bv() -> set[str]:
    return set(load_seen().keys())


async def run(cfg: dict, progress=None) -> dict:
    """跑一轮；progress(stage, message) 可选"""
    cred = load_cred()
    if not cred:
        return {"ok": False, "error": "还没登录 B站：先在「B站 登录」里扫码"}
    if not str(cfg.get("api_key") or "").strip():
        return {"ok": False, "error": "还没填 DeepSeek API key：先在「API 设置」里填写"}
    notes: list[str] = []

    def note(msg):
        notes.append(msg)
        log(msg)
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    DATA.mkdir(parents=True, exist_ok=True)
    tracker = CostTracker(cfg)
    # ⭐ 每天只挑满一次：今天已挑够配额就跳过（避免手动/定时重复加）
    per_day = int(sum(int(c.get("quota") or 0) for c in cfg["categories"]))
    try:
        seen = load_seen()
        today = datetime.now(BJ).strftime("%Y-%m-%d")
        done = sum(1 for v in seen.values() if v.get("date") == today and v.get("verdict") == "picked")
        if per_day and done >= per_day:
            msg = f"今天已经挑够 {done} 条（目标 {per_day}），跳过；明天再跑。"
            log(msg)
            return {"ok": True, "skipped": True, "picked": 0, "added": 0, "cost": 0.0, "notes": [msg]}
    except Exception:
        pass
    known = _known_bv()
    toview = await toview_bv(cred)
    followed = await load_followed(cred, cfg)
    watched = await load_watched(cred, cfg)
    known |= watched
    note(f"去重：已推荐/看过 {len(known)} 条 · 已关注 {len(followed)} 个 UP · 稍后再看 {len(toview)} 条")

    taste = []
    try:
        d = await user.get_toview_list(cred)
        payload = d.get("data") if isinstance(d, dict) and isinstance(d.get("data"), dict) else d
        taste = [it.get("title", "") for it in (payload or {}).get("list") or []][:30]
    except Exception:
        pass

    note("开始搜索…")
    cands = await collect_candidates(cfg, cred)
    note(f"原始候选 {len(cands)} 条，开始过滤")

    excl = [x.strip().lower() for x in cfg.get("exclude_keywords") or [] if x.strip()]
    now = time.time()
    pools: dict[str, list[dict]] = {c["id"]: [] for c in cfg["categories"]}
    drops = {"seen": 0, "toview": 0, "followed": 0, "excluded": 0, "quality": 0, "old": 0}
    cat_spec = {c["id"]: c for c in cfg["categories"]}
    for c in cands:
        if c["bvid"] in known:
            drops["seen"] += 1
            continue
        if c["bvid"] in toview:
            drops["toview"] += 1
            continue
        if c["mid"] in followed:
            drops["followed"] += 1
            continue
        if excl:
            blob = (c["title"] + " " + c["desc"] + " " + c["tags"] + " " + c["up"]).lower()
            if any(x in blob for x in excl):
                drops["excluded"] += 1
                continue
        if c.get("pubdate") and now - c["pubdate"] > int(cfg["days_back"]) * 86400:
            drops["old"] += 1
            continue
        spec = cat_spec.get(c["cat"], {})
        if c["quality"] < float(spec.get("min_quality", 0)):
            drops["quality"] += 1
            continue
        pools.setdefault(c["cat"], []).append(c)
    for cid, lst in pools.items():
        lst.sort(key=lambda x: x["quality"], reverse=True)
        pools[cid] = lst[: int(cat_spec[cid].get("candidates", 150))]
    note("过滤后：" + "，".join(f"{cat_spec[k]['label']} {len(v)}" for k, v in pools.items())
         + f"（看过/推过{drops['seen']} 已关注{drops['followed']} 排除词{drops['excluded']} 质量分不够{drops['quality']} 太旧{drops['old']}）")

    to_judge: list[dict] = []
    for cid, lst in pools.items():
        if not lst:
            continue
        ranked = triage(cfg, tracker, lst, taste)
        n = int(cat_spec[cid].get("deep", 16))
        to_judge.extend(ranked[:n])
        note(f"{cat_spec[cid]['label']}：候选 {len(lst)} → 精判 {min(n, len(ranked))}")

    judged = await deep_judge(cfg, tracker, to_judge, cred, taste)
    by_cat: dict[str, list[dict]] = {c["id"]: [] for c in cfg["categories"]}
    for c in judged:
        by_cat.setdefault(c["cat"], []).append(c)

    picks: dict[str, list[dict]] = {}
    short = []
    for cid, spec in cat_spec.items():
        thr = float(spec.get("min_score", cfg.get("min_final_score", 6.0)))
        got = [c for c in sorted(by_cat.get(cid, []), key=lambda x: x.get("score", 0), reverse=True)
               if c.get("score", 0) >= thr][: int(spec.get("quota", 0))]
        picks[cid] = got
        if len(got) < int(spec.get("quota", 0)):
            short.append(f"{spec['label']} {len(got)}/{spec['quota']}")
    allpicks = [p for c in cfg["categories"] for p in picks.get(c["id"], [])]
    note(f"入选 {len(allpicks)} 条" + (f"（未满：{'；'.join(short)}）" if short else ""))

    ok_add = 0
    for p in allpicks:
        try:
            await video.Video(bvid=p["bvid"], credential=cred).add_to_toview()
            p["added"] = True
            ok_add += 1
        except Exception as e:
            p["added"] = False
            p["add_err"] = str(e)
        await asyncio.sleep(0.3)
    note(f"加入稍后再看：{ok_add}/{len(allpicks)}")

    report = write_report(cfg, tracker, picks, [c for c in judged if c not in allpicks])
    save_seen(allpicks, [c for c in judged if c not in allpicks])
    tracker.ledger("run")
    note(f"完成：¥{tracker.spent:.3f}（{tracker.in_tokens} in / {tracker.out_tokens} out）")
    return {"ok": True, "picked": len(allpicks), "added": ok_add, "cost": round(tracker.spent, 4),
            "report": str(report), "short": short, "notes": notes}


def write_report(cfg: dict, tracker: CostTracker, picks: dict[str, list[dict]], skipped: list[dict]) -> Path:
    day = datetime.now(BJ).strftime("%Y-%m-%d")
    outdir = DATA / "reports"
    outdir.mkdir(parents=True, exist_ok=True)
    f = outdir / f"{day}.md"
    spec = {c["id"]: c for c in cfg["categories"]}
    picks_by = {c["id"]: picks.get(c["id"], []) for c in cfg["categories"]}
    total = sum(len(v) for v in picks_by.values())
    lines = [f"# {day} · BiliPick 精选", "",
             "- 配额：" + " · ".join(f"{spec[k]['label']} {len(v)}/{spec[k]['quota']}" for k, v in picks_by.items()) + f"（共 {total} 条）",
             f"- 花费：**¥{tracker.spent:.3f}**（{tracker.calls} 次调用，输入 {tracker.in_tokens} / 输出 {tracker.out_tokens} tokens）",
             "", "---", ""]
    n = 0
    for c in cfg["categories"]:
        plist = picks_by.get(c["id"], [])
        if not plist:
            continue
        lines += [f"## {c['label']}（{len(plist)}/{c['quota']}）", ""]
        for p in plist:
            n += 1
            quote = re.sub(r"\s+", " ", str(p.get("quote") or "")).strip()
            sig = re.sub(r"\s+", " ", str(p.get("comment_signal") or "")).strip()
            lines += [f"### {n}. [{p['title']}]({p['url']})", "",
                      f"- UP：{p['up']} ｜ 时长：{round(p['seconds']/60)} 分钟 ｜ 播放：{p['play']} ｜ "
                      f"弹幕 {p.get('danmaku',0)} · 评论 {p.get('comment_cnt',0)} · 收藏 {p.get('favorite',0)} · 点赞 {p.get('like',0)}",
                      f"- 评分：**{p.get('score', 0):.1f}/10**（质量分 {p.get('quality', 0):.1f} / 粗排 {p.get('triage', 0):.0f}）",
                      f"- 为什么值得：{p.get('reason','')}", f"- 依据：> {quote}"]
            if sig:
                lines.append(f"- 观众评论：{sig}")
            lines += [f"- 稍后再看：{'✓' if p.get('added') else '✗'}", ""]
    if skipped:
        lines += ["## 精判但没入选", ""]
        for c in skipped:
            lines.append(f"- {c['bvid']}《{c['title']}》[{spec.get(c['cat'],{}).get('label','')}] score={c.get('score',0):.1f}")
    f.write_text("\n".join(lines), encoding="utf-8")
    return f
