#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloud-based daily trending dance tracker.
Runs on GitHub Actions, independent of local computer.
Uses DeepSeek API for AI analysis, Bilibili API for video links,
and Feishu Open API for writing to Bitable.

Environment variables required:
  FEISHU_APP_ID       - Feishu custom app ID
  FEISHU_APP_SECRET   - Feishu custom app secret
  DEEPSEEK_API_KEY    - DeepSeek API key
"""

import os
import re
import json
import time
import hashlib
import urllib.parse
import requests
from datetime import date, datetime

# ===================== Configuration =====================

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

BASE_TOKEN = "KY46b07m4anEIbs31xJcgaFznMg"
TABLE_ID = "tblVsVYhYEPmN3nF"
COLOR_FIELD_ID = "fld2nzTjmU"
FEISHU_API = "https://open.feishu.cn/open-apis"

# Color cycle for daily color coding (Feishu select option colors)
COLOR_CYCLE = [21, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]

# 9-dimension search queries covering all dance types
SEARCH_QUERIES = [
    "全网最火舞蹈 排行 盘点 最新",
    "抖音 手势舞 热门 最新 挑战",
    "抖音 摇 舞蹈 爆款 热门",
    "抖音 卡点舞 扭腰 扭胯 热门",
    "KPOP 女团舞 翻跳 热门 抖音",
    "游戏 手势舞 破圈 热门 无畏契约",
    "非遗 舞蹈 改编 热门 民族 山歌",
    "抖音 搞笑舞蹈 魔性 社交 爆款",
    "明星 舞蹈挑战 翻跳 抖音 热门",
]

# Bilibili WBI mixin key indices (fixed, from B站 source code)
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


# ===================== Feishu API =====================

def feishu_get_token():
    """Get Feishu tenant access token."""
    url = f"{FEISHU_API}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    }, timeout=30)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"Feishu auth failed: {data}")
    return data["tenant_access_token"]


def feishu_list_records(token):
    """List all records in the Bitable table."""
    url = f"{FEISHU_API}/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}"}
    all_items = []
    page_token = None
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        data = resp.json()
        if data.get("code") != 0:
            print(f"[WARN] list records error: {data}")
            break
        all_items.extend(data["data"].get("items", []))
        if not data["data"].get("has_more"):
            break
        page_token = data["data"].get("page_token")
    return all_items


def extract_text(val):
    """Extract plain text from Feishu field value (handles array format)."""
    if not val:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        parts = []
        for item in val:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(val)


def feishu_get_existing_names(token):
    """Get set of existing dance names to avoid duplicates."""
    records = feishu_list_records(token)
    names = set()
    for r in records:
        fields = r.get("fields", {})
        name = extract_text(fields.get("\u821e\u8e48\u540d\u79f0"))  # 舞蹈名称
        if name:
            names.add(name.strip())
    return names


def feishu_batch_create(token, records_data):
    """Batch create records. records_data: list of field dicts."""
    url = f"{FEISHU_API}/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records/batch_create"
    headers = {"Authorization": f"Bearer {token}"}
    body = {"records": [{"fields": r} for r in records_data]}
    resp = requests.post(url, json=body, headers=headers, timeout=30)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"Batch create failed: {data}")
    return data


def feishu_get_field(token, field_id):
    """Get field definition. Uses list-all-fields endpoint (more reliable than single-field)."""
    url = f"{FEISHU_API}/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/fields"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=30)
    try:
        data = resp.json()
    except requests.exceptions.JSONDecodeError:
        print(f"  [WARN] Feishu list fields returned non-JSON (status {resp.status_code}):")
        print(f"  Text preview: {resp.text[:500]!r}")
        raise

    if data.get("code") != 0:
        raise Exception(f"Feishu list fields error: {data}")

    # Find target field by ID, or by name as fallback
    color_field_name = "\u65e5\u671f\u989c\u8272\u6807\u8bb0"  # 日期颜色标记
    for field in data.get("data", {}).get("items", []):
        if field.get("field_id") == field_id:
            return {"code": 0, "data": field}
    # Fallback: find by name
    for field in data.get("data", {}).get("items", []):
        if field.get("field_name") == color_field_name:
            print(f"  [INFO] Found color field by name (field_id={field.get('field_id')})")
            return {"code": 0, "data": field}

    raise Exception(f"Field {field_id} (color marker) not found in table fields")


def feishu_update_field(token, field_id, field_name, options):
    """Update single select field options."""
    url = f"{FEISHU_API}/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/fields/{field_id}"
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "field_name": field_name,
        "type": 3,  # single select
        "ui_type": "SingleSelect",
        "property": {"options": options},
    }
    resp = requests.put(url, json=body, headers=headers, timeout=30)
    try:
        return resp.json()
    except requests.exceptions.JSONDecodeError as e:
        print(f"  [WARN] Feishu update_field returned non-JSON (status {resp.status_code}):")
        print(f"  Text preview: {resp.text[:500]!r}")
        raise


def feishu_ensure_color_option(token, today_str):
    """Ensure today's date exists as a color option. Returns True on success."""
    try:
        field_data = feishu_get_field(token, COLOR_FIELD_ID)
    except Exception as e:
        print(f"  [WARN] Could not read color field, skipping color option update: {e}")
        return False

    existing_opts = (
        field_data.get("data", {})
        .get("property", {})
        .get("options", [])
    )
    field_name = field_data.get("data", {}).get("field_name", "\u65e5\u671f\u989c\u8272\u6807\u8bb0")

    # Check if today already exists
    if any(opt.get("name") == today_str for opt in existing_opts):
        print(f"  Color option '{today_str}' already exists")
        return True

    # Add new option with next color in cycle
    color_idx = len(existing_opts) % len(COLOR_CYCLE)
    new_opt = {"name": today_str, "color": COLOR_CYCLE[color_idx]}
    all_opts = existing_opts + [new_opt]

    try:
        result = feishu_update_field(token, COLOR_FIELD_ID, field_name, all_opts)
    except Exception as e:
        print(f"  [WARN] Could not update color field, skipping: {e}")
        return False

    if result.get("code") == 0:
        print(f"  Added color option: {today_str} (color={COLOR_CYCLE[color_idx]})")
        return True
    else:
        print(f"  [WARN] Failed to add color option: {result}")
        return False


# ===================== Bilibili API =====================

def _get_buvid3():
    """Get a buvid3 cookie from Bilibili SPI endpoint."""
    try:
        url = "https://api.bilibili.com/x/frontend/finger/spi"
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        data = resp.json()
        return data.get("data", {}).get("b_3", "")
    except Exception:
        return ""


def _get_wbi_keys():
    """Get WBI signing keys from Bilibili nav."""
    try:
        url = "https://api.bilibili.com/x/web-interface/nav"
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        data = resp.json()["data"]["wbi_img"]
        img_key = data["img_url"].rsplit("/", 1)[1].split(".")[0]
        sub_key = data["sub_url"].rsplit("/", 1)[1].split(".")[0]
        return img_key, sub_key
    except Exception as e:
        print(f"  [WARN] WBI key fetch failed: {e}")
        return "", ""


def _get_mixin_key(img_key, sub_key):
    """Generate mixin key from img_key + sub_key."""
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB if i < len(raw))[:32]


def _sign_wbi(params, img_key, sub_key):
    """Sign request parameters with Bilibili WBI algorithm."""
    if not img_key or not sub_key:
        return params
    mixin_key = _get_mixin_key(img_key, sub_key)
    params = dict(params)
    params["wts"] = int(time.time())
    params = dict(sorted(params.items()))
    # Standard WBI: urlencode, then restore unencoded safe chars
    query = urllib.parse.urlencode(params)
    for enc, raw in [("%21", "!"), ("%27", "'"), ("%28", "("), ("%29", ")"), ("%2A", "*")]:
        query = query.replace(enc, raw)
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
    params["w_rid"] = w_rid
    return params


def bili_search_videos(keyword, max_results=5):
    """Search Bilibili for videos matching keyword.
    Returns list of {bvid, url, title, play_count} dicts.
    """
    buvid3 = _get_buvid3()
    img_key, sub_key = _get_wbi_keys()

    params = {
        "search_type": "video",
        "keyword": keyword,
        "order": "click",
        "page": 1,
        "page_size": 20,
    }
    params = _sign_wbi(params, img_key, sub_key)

    cookies = {}
    if buvid3:
        cookies["buvid3"] = buvid3

    headers = {
        "User-Agent": UA,
        "Referer": "https://search.bilibili.com",
        "Accept": "application/json",
    }

    try:
        url = "https://api.bilibili.com/x/web-interface/wbi/search/type"
        resp = requests.get(url, params=params, headers=headers, cookies=cookies, timeout=15)
        data = resp.json()
        if data.get("code") != 0:
            print(f"  [WARN] Bili search API error: {data.get('message', 'unknown')}")
            # Fallback: scrape search page HTML for BV links
            return _bili_search_fallback(keyword, max_results)

        results = []
        for item in data.get("data", {}).get("result", [])[:max_results]:
            bvid = item.get("bvid", "")
            if not bvid:
                continue
            title = re.sub(r"<[^>]+>", "", item.get("title", ""))  # Strip em tags
            play = item.get("play", 0)
            results.append({
                "bvid": bvid,
                "url": f"https://www.bilibili.com/video/{bvid}/",
                "title": title,
                "play_count": play,
            })
        return results
    except Exception as e:
        print(f"  [WARN] Bili search failed for '{keyword}': {e}")
        return _bili_search_fallback(keyword, max_results)


def _bili_search_fallback(keyword, max_results=5):
    """Fallback: scrape Bilibili search page HTML for BV links."""
    try:
        encoded = urllib.parse.quote(keyword)
        url = f"https://search.bilibili.com/all?keyword={encoded}&order=click"
        headers = {"User-Agent": UA, "Accept": "text/html"}
        resp = requests.get(url, headers=headers, timeout=15)
        html = resp.text
        # Extract BV IDs from HTML
        bv_ids = re.findall(r"/video/(BV[0-9a-zA-Z]+)", html)
        seen = set()
        unique = []
        for bv in bv_ids:
            if bv not in seen:
                seen.add(bv)
                unique.append(bv)

        results = []
        for bv in unique[:max_results * 2]:
            info = bili_get_video_info(bv)
            if info:
                results.append(info)
                time.sleep(0.3)
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        print(f"  [WARN] Bili fallback search failed: {e}")
        return []


def bili_get_video_info(bvid):
    """Get video info from Bilibili public API."""
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    headers = {"User-Agent": UA}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            v = data["data"]
            return {
                "bvid": bvid,
                "url": f"https://www.bilibili.com/video/{bvid}/",
                "title": v.get("title", ""),
                "play_count": v.get("stat", {}).get("view", 0),
            }
    except Exception as e:
        print(f"  [WARN] Video info failed for {bvid}: {e}")
    return None


def bili_search_teaching(keyword, max_results=3):
    """Search Bilibili for teaching/tutorial videos."""
    return bili_search_videos(f"{keyword} 教学", max_results)


def bili_get_dance_ranking(rid=129, max_results=30):
    """Get Bilibili dance category ranking (no WBI signing needed, works from any IP).
    rid=129: 舞蹈综合, rid=20: 宅舞, rid=154: 舞蹈
    Returns list of {bvid, url, title, play_count} dicts.
    """
    url = "https://api.bilibili.com/x/web-interface/ranking/v2"
    params = {"rid": rid, "type": "all"}
    headers = {"User-Agent": UA, "Accept": "application/json"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        data = resp.json()
        if data.get("code") != 0:
            print(f"  [WARN] Bili ranking API error: {data.get('message', 'unknown')}")
            return []
        results = []
        for item in data.get("data", {}).get("list", [])[:max_results]:
            bvid = item.get("bvid", "")
            if not bvid:
                continue
            results.append({
                "bvid": bvid,
                "url": f"https://www.bilibili.com/video/{bvid}/",
                "title": item.get("title", ""),
                "play_count": item.get("stat", {}).get("view", 0),
            })
        return results
    except Exception as e:
        print(f"  [WARN] Bili ranking failed: {e}")
        return []


# ===================== Web Search (DuckDuckGo + Bing + Baidu) =====================

def _strip_html(html):
    """Strip HTML tags and normalize whitespace."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def search_duckduckgo(query, max_chars=3000):
    """Search DuckDuckGo HTML (works internationally, no CAPTCHA)."""
    encoded = urllib.parse.quote(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"
    headers = {
        "User-Agent": UA,
        "Accept": "text/html",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        text = _strip_html(resp.text)
        return text[:max_chars]
    except Exception as e:
        print(f"  [WARN] DuckDuckGo search failed: {e}")
        return ""


def search_bing(query, max_chars=3000):
    """Search Bing (works internationally, good Chinese content)."""
    encoded = urllib.parse.quote(query)
    url = f"https://www.bing.com/search?q={encoded}&count=20&setmkt=zh-CN&setlang=zh-CN"
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        html = resp.text
        text = _strip_html(html)
        return text[:max_chars]
    except Exception as e:
        print(f"  [WARN] Bing search failed: {e}")
        return ""


def search_baidu(query, max_chars=3000):
    """Search Baidu and return text snippets."""
    encoded = urllib.parse.quote(query)
    url = f"https://www.baidu.com/s?wd={encoded}&rn=10"
    headers = {
        "User-Agent": UA,
        "Accept": "text/html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        html = resp.text
        text = _strip_html(html)
        return text[:max_chars]
    except Exception as e:
        print(f"  [WARN] Baidu search failed: {e}")
        return ""


# ===================== DeepSeek API =====================

def deepseek_chat(system_prompt, user_prompt, temperature=0.7):
    """Call DeepSeek chat API. Returns content string."""
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=120)
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [ERROR] DeepSeek API failed: {e}")
        return None


def analyze_and_extract_dances(search_context, existing_names, today_str):
    """Use DeepSeek to analyze search results and identify trending dances.
    Returns dict with keys: all_dances, new_dances, filtered_names
    """
    system = (
        "你是中国社交媒体热门舞蹈分析专家，专注抖音、快手、微博、小红书上的舞蹈趋势。"
        "分析搜索结果并识别当前最热门的舞蹈。"
        "重点关注抖音和快手上的爆款舞蹈（普通用户会跟跳模仿的），而不是B站专业舞蹈视频。"
        "请用中文回答，只返回有效的JSON。"
    )
    user = f"""今天是 {today_str}。

已有的舞蹈（不要重复列出）：
{json.dumps(list(existing_names), ensure_ascii=False)}

搜索结果（来自B站搜索和网页搜索）：
{search_context}

基于以上搜索结果，同时结合你对中国社交媒体趋势的了解，识别当前最热门的舞蹈。

重点要求：
1. 必须是具体舞蹈名称（如"拖拉机舞"、"珠满摇"、"刀马刀马舞"），不要泛泛的"热门舞蹈"
2. 重点关注抖音和快手上的爆款舞蹈——普通用户会跟跳模仿的那种
3. 不要选B站专业舞蹈表演或ACG宅舞，要选社交媒体上病毒式传播的舞蹈
4. 包括各种类型：手势舞、摇类、卡点舞、KPOP翻跳、游戏破圈、非遗改编、搞笑魔性、明星带动、影视联动

对每个舞蹈提供：
- name: 具体舞蹈名称
- reason: 为什么火（具体：什么机制传播、哪个明星参与、什么游戏/影视带动等）
- popularity: 热度数据（播放量、话题浏览量、热搜排名等）
- source: 主要在哪个平台火（抖音/快手/微博/小红书/B站）
- category: 舞蹈类型
- search_keyword: 在B站搜索这个舞蹈视频用的最佳关键词

如果没有找到热门舞蹈，返回: {{{{"dances": []}}}}"""

    result = deepseek_chat(system, user)
    if not result:
        return {"all_dances": [], "new_dances": [], "filtered": []}
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        match = re.search(r"\{{.*\}}", result, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                return {"all_dances": [], "new_dances": [], "filtered": []}
        else:
            return {"all_dances": [], "new_dances": [], "filtered": []}

    all_dances = parsed.get("dances", [])
    new_dances = []
    filtered = []
    for d in all_dances:
        name = d.get("name", "").strip()
        if name in existing_names:
            filtered.append(name)
        else:
            new_dances.append(d)

    return {"all_dances": all_dances, "new_dances": new_dances, "filtered": filtered}


def deepseek_direct_trending(existing_names, today_str):
    """Ask DeepSeek directly about trending dances using its own knowledge.
    No search context needed — DeepSeek is a Chinese AI model that knows
    抖音/快手/微博/小红书 trends.
    Returns list of dance dicts (same format as analyze_and_extract_dances).
    """
    system = (
        "你是中国社交媒体热门舞蹈分析专家，精通抖音、快手、微博、小红书上的舞蹈趋势。"
        "你了解当前最火的舞蹈挑战、手势舞、摇类舞蹈、卡点舞等各类热门舞蹈。"
        "请用中文回答，只返回有效的JSON。"
    )
    user = f"""今天是 {today_str}。

请根据你对抖音、快手、微博、小红书等中国社交媒体的了解，列出当前最热门的具体舞蹈。

极其重要的规则：
1. 必须是具体的、有独特名称的舞蹈，不能是舞蹈类型的统称
   - 正确示例：拖拉机舞、珠满摇、刀马刀马舞、复仇摇、科目三、烫脚舞、APT舞、加绒摇、佳诺摇、鸟儿摇、q冰摇、九门摇、刀比摇、御廷摇、迷核进行曲手势舞、巴西顺拐舞、鱼块摇、目瑙纵歌
   - 错误示例（这些是类型名，绝对不要返回）：手势舞、卡点舞、KPOP翻跳、游戏破圈舞、非遗改编舞、明星带动舞、影视联动舞、古风舞、机械舞、广场舞、手指舞、扭胯舞、甩手舞、奥特曼舞、螃蟹舞、孔雀舞、街舞、爵士舞、拉丁舞、肚皮舞、芭蕾舞、民族舞、儿童舞蹈
2. 舞蹈名称必须是纯名称，不要加任何后缀
   - 正确：拖拉机舞、烫脚舞、科目三
   - 错误：拖拉机舞（续）、烫脚舞（升级版）、科目三（广西科目三）、御廷摇（宫廷风）
3. 每个舞蹈必须有一个具体的来源（某首BGM、某个明星带火、某个游戏、某个挑战话题等）
4. 重点关注抖音和快手上的爆款舞蹈——普通用户会跟跳模仿的那种
5. 列出10-20个舞蹈，包括最近新出的和还在持续热门的

已有的舞蹈（不要重复列出）：
{json.dumps(list(existing_names), ensure_ascii=False)}

对每个舞蹈提供：
- name: 具体舞蹈名称（如"拖拉机舞"，不是"手势舞"）
- reason: 为什么火（具体：什么BGM、哪个明星、什么游戏/影视带动）
- popularity: 热度数据（播放量、话题浏览量、热搜排名等，尽量具体）
- source: 主要在哪个平台火（抖音/快手/微博/小红书/B站）
- category: 舞蹈类型（手势舞/摇类/卡点舞/KPOP翻跳/游戏破圈/非遗改编/搞笑魔性/明星带动/影视联动/古风）
- search_keyword: 在B站搜索这个舞蹈视频用的最佳关键词（通常是舞蹈名本身）

返回JSON: {{{{"dances": [{{{{"name":"...","reason":"...","popularity":"...","source":"...","category":"...","search_keyword":"..."}}}}]}}}}"""

    result = deepseek_chat(system, user, temperature=0.8)
    if not result:
        return []
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", result, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                return []
        else:
            return []
    return parsed.get("dances", [])


# ===================== Helper =====================

def clean_dance_name(name):
    """Strip suffixes that DeepSeek sometimes adds: （续）, （升级版）, （宫廷风）, etc.
    Also handles full-width and half-width parentheses variants.
    """
    if not name:
        return name
    name = name.strip()
    # Remove common suffixes in parentheses (both full-width and half-width)
    # e.g. "烫脚舞（续）" -> "烫脚舞", "科目三（广西科目三）" -> "科目三"
    name = re.sub(r'[（(].*?[）)]\s*$', '', name)
    return name.strip()


def format_video_link(video):
    """Format video info for Bitable text field."""
    if not video:
        return ""
    play = f"{video['play_count']:,}" if video["play_count"] > 0 else "未知"
    return f"{video['url']} 《{video['title']}》（{play}播放）"


# ===================== Main =====================

def main():
    today_str = date.today().strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"  Daily Trending Dance Tracker - {today_str}")
    print(f"{'='*60}\n")

    # 1. Validate config
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        print("[ERROR] Missing FEISHU_APP_ID or FEISHU_APP_SECRET")
        return
    if not DEEPSEEK_API_KEY:
        print("[ERROR] Missing DEEPSEEK_API_KEY")
        return

    # 2. Get Feishu token
    print("[1/7] Getting Feishu token...")
    token = feishu_get_token()
    print(f"  OK (token length: {len(token)})")

    # 3. Get existing dance names
    print("[2/7] Getting existing dance names...")
    existing_names_raw = feishu_get_existing_names(token)
    # Also add cleaned versions (strip suffixes) to prevent duplicates
    # e.g. if "烫脚舞（续）" exists, also add "烫脚舞" so future "烫脚舞" is filtered
    existing_names = set()
    for name in existing_names_raw:
        existing_names.add(name)
        cleaned = clean_dance_name(name)
        if cleaned != name:
            existing_names.add(cleaned)
    print(f"  Found {len(existing_names_raw)} existing dances ({len(existing_names)} names after cleaning)")

    # 4. Ensure color option for today
    print("[3/7] Ensuring color option for today...")
    feishu_ensure_color_option(token, today_str)

    # 5. Search for trending dances (multi-source: Bing + Baidu + Bilibili ranking)
    print("[4/7] Searching for trending dances (multi-source)...")
    search_context = ""
    total_search_chars = 0

    # 5a. Web search: DuckDuckGo (primary) + Bing (fallback) + Baidu (last resort)
    for i, query in enumerate(SEARCH_QUERIES):
        # Try DuckDuckGo first (works internationally, no CAPTCHA)
        print(f"  [{i+1}/{len(SEARCH_QUERIES)}] DuckDuckGo: {query}")
        result = search_duckduckgo(query)
        print(f"    -> {len(result)} chars")
        if len(result) < 200:
            # DuckDuckGo returned too little, try Bing
            print(f"    Content too short, trying Bing...")
            bing_result = search_bing(query)
            print(f"    -> Bing: {len(bing_result)} chars")
            if len(bing_result) > len(result):
                result = bing_result
        if len(result) < 200:
            # Last resort: Baidu
            print(f"    Still short, trying Baidu...")
            baidu_result = search_baidu(query)
            print(f"    -> Baidu: {len(baidu_result)} chars")
            if len(baidu_result) > len(result):
                result = baidu_result
        search_context += f"\n--- Search {i+1}: {query} ---\n{result}\n"
        total_search_chars += len(result)
        time.sleep(1)  # Be polite

    # 5b. Bilibili dance category ranking (no WBI signing needed, works from any IP)
    print("  [B站] Fetching dance category ranking (rid=129)...")
    ranking_results = bili_get_dance_ranking(rid=129, max_results=30)
    print(f"    -> Got {len(ranking_results)} ranking videos")
    if ranking_results:
        for v in ranking_results[:5]:
            print(f"       TOP: 《{v['title']}》 ({v['play_count']:,}播放)")
    ranking_text = "\n".join(
        f"- {v['title']} ({v['play_count']:,} plays) {v['url']}"
        for v in ranking_results
    )
    search_context += f"\n--- Bilibili Dance Ranking (rid=129, top {len(ranking_results)}) ---\n{ranking_text}\n"
    total_search_chars += len(ranking_text)

    # 5c. Bilibili keyword searches (PRIMARY content source — works from any IP)
    #     Search all 9 queries on B站 to find 抖音/快手 dances reposted to B站
    print("  [B站] Searching 9 targeted queries on Bilibili...")
    for i, query in enumerate(SEARCH_QUERIES):
        print(f"  [B站{i+1}/{len(SEARCH_QUERIES)}] {query}")
        bili_results = bili_search_videos(query, max_results=5)
        print(f"    -> Got {len(bili_results)} results")
        if bili_results:
            for v in bili_results[:2]:
                print(f"       《{v['title']}》 ({v['play_count']:,}播放)")
        bili_text = "\n".join(
            f"- {v['title']} ({v['play_count']:,} plays) {v['url']}"
            for v in bili_results
        )
        search_context += f"\n--- B站搜索 {i+1}: {query} ---\n{bili_text}\n"
        total_search_chars += len(bili_text)
        time.sleep(0.5)

    print(f"  Total search context: {total_search_chars} chars")
    if total_search_chars < 500:
        print(f"  [WARN] Very little search content ({total_search_chars} chars). Will rely more on AI direct knowledge.")

    # 6. AI analysis — TWO sources merged
    # 6a. DeepSeek direct knowledge (asks AI directly about 抖音/快手 trends)
    print("[5/7] AI analysis (two-source: direct knowledge + search context)...")
    print("  [5a] Asking DeepSeek for trending dances (direct knowledge)...")
    direct_dances = deepseek_direct_trending(existing_names, today_str)
    print(f"    -> DeepSeek direct knowledge identified {len(direct_dances)} dances")
    if direct_dances:
        print(f"    Names: {', '.join(d.get('name', '') for d in direct_dances[:10])}")

    # 6b. Search-based analysis (analyzes B站 + DuckDuckGo search results)
    print("  [5b] Analyzing search results with DeepSeek...")
    analysis = analyze_and_extract_dances(search_context, existing_names, today_str)
    search_dances = analysis.get("all_dances", [])
    print(f"    -> Search-based analysis identified {len(search_dances)} dances")
    if search_dances:
        print(f"    Names: {', '.join(d.get('name', '') for d in search_dances[:10])}")

    # 6c. Merge results (direct knowledge + search-based), deduplicate by name
    #     Clean dance names first (strip （续）, （升级版）, etc. suffixes)
    all_dances = []
    seen_names = set()
    for d in direct_dances + search_dances:
        raw_name = d.get("name", "").strip()
        name = clean_dance_name(raw_name)
        if not name:
            continue
        if name != raw_name:
            print(f"    Cleaned: '{raw_name}' -> '{name}'")
            d["name"] = name  # Update the name in the dict
        if name not in seen_names:
            seen_names.add(name)
            all_dances.append(d)

    # Filter out existing dances
    dances = []
    filtered = []
    for d in all_dances:
        name = d.get("name", "").strip()
        if name in existing_names:
            filtered.append(name)
        else:
            dances.append(d)

    print(f"  Merged total: {len(all_dances)} dances")
    if filtered:
        print(f"  Filtered out (already exist): {', '.join(filtered)}")
    print(f"  New dances to add: {len(dances)}")
    if dances:
        print(f"  New dance names: {', '.join(d.get('name', '') for d in dances)}")

    if not dances:
        # 7a. No new dances - write confirmation row
        print("[6/7] No new dances found. Writing confirmation row...")
        reason_detail = (
            f"今日搜索了{len(SEARCH_QUERIES)}个维度+B站排行榜"
            f"，共获取{total_search_chars}字符搜索内容"
            f"，DeepSeek直接知识+搜索分析合并识别{len(all_dances)}个舞蹈"
        )
        if all_dances:
            reason_detail += f"（直接知识{len(direct_dances)}个+搜索分析{len(search_dances)}个）"
        if filtered:
            reason_detail += f"，其中{len(filtered)}个已存在于表格中被过滤"
        if not all_dances:
            reason_detail += "，未识别到任何热门舞蹈"
        reason_detail += "，自动化已正常运行"

        confirmation = {
            "\u65e5\u671f": today_str,                          # 日期
            "\u821e\u8e48\u540d\u79f0": "今日无新增热门舞蹈",    # 舞蹈名称
            "\u6765\u6e90\u5e73\u53f0": "",                     # 来源平台
            "\u539f\u59cb\u89c6\u9891\u94fe\u63a5": "",          # 原始视频链接
            "\u4e0a\u699c\u539f\u56e0": reason_detail,           # 上榜原因
            "\u70ed\u5ea6\u6307\u6807": "",                     # 热度指标
            "\u6559\u5b66\u89c6\u9891\u94fe\u63a5": "",          # 教学视频链接
            "\u6559\u5b66\u8bf4\u660e": "",                     # 教学说明
            "\u5907\u6ce8": "已检查的平台：B站/抖音/快手/微博/小红书",  # 备注
            "\u65e5\u671f\u989c\u8272\u6807\u8bb0": today_str,  # 日期颜色标记
        }
        feishu_batch_create(token, [confirmation])
        print("  Confirmation row written.")
        print("[7/7] Done.")
        return

    # 7b. Find video links for each dance
    print(f"[6/7] Finding video links for {len(dances)} dances...")
    records_to_create = []
    for i, dance in enumerate(dances):
        name = dance.get("name", "")
        keyword = dance.get("search_keyword", name)
        print(f"  [{i+1}/{len(dances)}] {name} -> searching B站...")

        # Strategy 1: Match against ranking results (already fetched, no API call needed)
        original_link = ""
        matched_video = None
        for rv in ranking_results:
            if name in rv["title"] or rv["title"] in name:
                matched_video = rv
                print(f"    Matched in ranking: 《{rv['title']}》 ({rv['play_count']:,}播放)")
                break

        # Strategy 2: Search B站 with dance name directly
        if not matched_video:
            videos = bili_search_videos(name, max_results=3)
            if videos:
                print(f"    Found {len(videos)} videos (name search), top: 《{videos[0]['title']}》 ({videos[0]['play_count']:,}播放)")
                matched_video = videos[0]

        # Strategy 3: Search with DeepSeek keyword
        if not matched_video and keyword != name:
            videos = bili_search_videos(keyword, max_results=3)
            if videos:
                print(f"    Found {len(videos)} videos (keyword: '{keyword}'), top: 《{videos[0]['title']}》 ({videos[0]['play_count']:,}播放)")
                matched_video = videos[0]

        if matched_video:
            original_link = format_video_link(matched_video)
        else:
            print(f"    [WARN] No B站 videos found for '{name}'")

        # Search for teaching video (try name + keyword)
        teaching_link = ""
        teaching_note = ""
        if original_link:
            search_terms = [name]
            if keyword != name:
                search_terms.append(keyword)
            for term in search_terms:
                teach_videos = bili_search_teaching(term, max_results=3)
                if teach_videos:
                    print(f"    Found {len(teach_videos)} teaching videos (term: '{term}')")
                    for tv in teach_videos:
                        title = tv.get("title", "")
                        if any(w in title for w in ["教学", "教程", "分解", "跟练", "拆解", "慢速"]):
                            teaching_link = format_video_link(tv)
                            teaching_note = f"含教学分解内容"
                            print(f"    Selected teaching: 《{title}》")
                            break
                if teaching_link:
                    break
            if not teaching_link:
                print(f"    No suitable teaching video found (will leave empty)")

        record = {
            "\u65e5\u671f": today_str,
            "\u821e\u8e48\u540d\u79f0": name,
            "\u6765\u6e90\u5e73\u53f0": dance.get("source", "B站"),
            "\u539f\u59cb\u89c6\u9891\u94fe\u63a5": original_link,
            "\u4e0a\u699c\u539f\u56e0": dance.get("reason", ""),
            "\u70ed\u5ea6\u6307\u6807": dance.get("popularity", ""),
            "\u6559\u5b66\u89c6\u9891\u94fe\u63a5": teaching_link,
            "\u6559\u5b66\u8bf4\u660e": teaching_note,
            "\u5907\u6ce8": dance.get("category", ""),
            "\u65e5\u671f\u989c\u8272\u6807\u8bb0": today_str,
        }
        records_to_create.append(record)
        time.sleep(1)  # Rate limit between dances

    # 8. Write to Feishu
    print(f"[7/7] Writing {len(records_to_create)} records to Feishu...")
    result = feishu_batch_create(token, records_to_create)
    print(f"  Write result: code={result.get('code', 'unknown')}")

    # Summary
    print(f"\n{'='*60}")
    print(f"  Summary - {today_str}")
    print(f"{'='*60}")
    print(f"  New dances: {len(records_to_create)}")
    for r in records_to_create:
        name = r["\u821e\u8e48\u540d\u79f0"]
        has_video = "Y" if r["\u539f\u59cb\u89c6\u9891\u94fe\u63a5"] else "N"
        has_teach = "Y" if r["\u6559\u5b66\u89c6\u9891\u94fe\u63a5"] else "N"
        print(f"  - {name}  (video:{has_video} teaching:{has_teach})")
    print()


if __name__ == "__main__":
    main()
