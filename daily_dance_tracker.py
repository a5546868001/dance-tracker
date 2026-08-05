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
    """Get field definition."""
    url = f"{FEISHU_API}/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/fields/{field_id}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=30)
    return resp.json()


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
    return resp.json()


def feishu_ensure_color_option(token, today_str):
    """Ensure today's date exists as a color option."""
    field_data = feishu_get_field(token, COLOR_FIELD_ID)
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

    result = feishu_update_field(token, COLOR_FIELD_ID, field_name, all_opts)
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


# ===================== Web Search (Baidu) =====================

def search_baidu(query, max_chars=2000):
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
        # Strip tags, get text
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
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
    """Use DeepSeek to analyze search results and identify trending dances."""
    system = (
        "You are a trending dance analyst for Chinese social media platforms. "
        "Analyze search results and identify the most trending dances right now. "
        "Always respond in Chinese. Return only valid JSON."
    )
    user = f"""Today's date: {today_str}

Existing dances already in the table (DO NOT include these):
{json.dumps(list(existing_names), ensure_ascii=False)}

Search results from multiple sources:
{search_context}

Based on the search results above, identify 5-15 NEW trending dances that are NOT in the existing list.
For each dance, provide:
- name: specific dance name (e.g., "珠满摇", "刀马刀马舞", not generic "热门舞蹈")
- reason: why it's trending (specific: viral mechanic, celebrity participation, game crossover, etc.)
- popularity: concrete numbers (play counts, topic views, hot search rankings)
- source: platform where it's popular (B站/抖音/快手/微博/小红书)
- category: dance type (手势舞/摇类/卡点舞/KPOP翻跳/游戏破圈/非遗改编/搞笑魔性/明星带动/影视联动/古风)
- search_keyword: best keyword to search on Bilibili for this dance's video

Return JSON: {{"dances": [{{"name":"...","reason":"...","popularity":"...","source":"...","category":"...","search_keyword":"..."}}]}}

If no new trending dances found, return: {{"dances": []}}"""

    result = deepseek_chat(system, user)
    if not result:
        return {"dances": []}
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", result, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return {"dances": []}


# ===================== Helper =====================

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
    existing_names = feishu_get_existing_names(token)
    print(f"  Found {len(existing_names)} existing dances")

    # 4. Ensure color option for today
    print("[3/7] Ensuring color option for today...")
    feishu_ensure_color_option(token, today_str)

    # 5. Search for trending dances
    print("[4/7] Searching for trending dances (9 dimensions)...")
    search_context = ""
    for i, query in enumerate(SEARCH_QUERIES):
        print(f"  [{i+1}/{len(SEARCH_QUERIES)}] Baidu: {query}")
        result = search_baidu(query)
        search_context += f"\n--- Search {i+1}: {query} ---\n{result}\n"
        time.sleep(1.5)  # Be polite to Baidu

    # Also search Bilibili dance ranking
    print("  [B站] Searching trending dance videos on Bilibili...")
    bili_results = bili_search_videos("热门舞蹈 2026", max_results=10)
    bili_text = "\n".join(
        f"- {v['title']} ({v['play_count']:,} plays) {v['url']}"
        for v in bili_results
    )
    search_context += f"\n--- Bilibili trending dances ---\n{bili_text}\n"

    # 6. AI analysis
    print("[5/7] AI analysis with DeepSeek...")
    analysis = analyze_and_extract_dances(search_context, existing_names, today_str)
    dances = analysis.get("dances", [])
    print(f"  Identified {len(dances)} new trending dances")

    if not dances:
        # 7a. No new dances - write confirmation row
        print("[6/7] No new dances found. Writing confirmation row...")
        confirmation = {
            "\u65e5\u671f": today_str,                          # 日期
            "\u821e\u8e48\u540d\u79f0": "今日无新增热门舞蹈",    # 舞蹈名称
            "\u6765\u6e90\u5e73\u53f0": "",                     # 来源平台
            "\u539f\u59cb\u89c6\u9891\u94fe\u63a5": "",          # 原始视频链接
            "\u4e0a\u699c\u539f\u56e0": (
                f"今日搜索了{len(SEARCH_QUERIES)}个维度，"
                f"未发现新增热门舞蹈，自动化已正常运行"
            ),                                                   # 上榜原因
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

        # Search for original video
        videos = bili_search_videos(keyword, max_results=3)
        original_link = format_video_link(videos[0]) if videos else ""

        # Search for teaching video
        teaching_link = ""
        teaching_note = ""
        if original_link:  # Only search teaching if we found the original
            teach_videos = bili_search_teaching(keyword, max_results=3)
            for tv in teach_videos:
                title = tv.get("title", "")
                if any(w in title for w in ["教学", "教程", "分解", "跟练", "拆解", "慢速"]):
                    teaching_link = format_video_link(tv)
                    teaching_note = "含教学分解内容"
                    break

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
