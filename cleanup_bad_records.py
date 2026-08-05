#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cleanup script: delete bad records from Feishu Bitable.
These records contain generic dance category names instead of specific dance names.

Runs on GitHub Actions (needs FEISHU_APP_ID, FEISHU_APP_SECRET).
"""

import os
import json
import requests

# ===================== Configuration =====================

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")

BASE_TOKEN = "KY46b07m4anEIbs31xJcgaFznMg"
TABLE_ID = "tblVsVYhYEPmN3nF"
FEISHU_API = "https://open.feishu.cn/open-apis"

# Bad dance names to delete (generic category names, not specific dances)
BAD_NAMES = [
    "科目三", "青海摇", "卡点舞", "手势舞", "KPOP翻跳",
    "游戏破圈舞", "非遗改编舞", "明星带动舞", "影视联动舞",
    "古风舞", "机械舞", "广场舞", "手指舞", "扭胯舞",
    "甩手舞", "奥特曼舞", "螃蟹舞", "孔雀舞", "街舞",
    "爵士舞", "拉丁舞", "肚皮舞", "芭蕾舞", "民族舞",
    "儿童舞蹈",
]


def get_token():
    url = f"{FEISHU_API}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    }, timeout=30)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"Feishu auth failed: {data}")
    return data["tenant_access_token"]


def extract_text(val):
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


def list_all_records(token):
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
            print(f"[ERROR] list records: {data}")
            break
        all_items.extend(data["data"].get("items", []))
        if not data["data"].get("has_more"):
            break
        page_token = data["data"].get("page_token")
    return all_items


def batch_delete(token, record_ids):
    url = f"{FEISHU_API}/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records/batch_delete"
    headers = {"Authorization": f"Bearer {token}"}
    body = {"records": record_ids}
    resp = requests.post(url, json=body, headers=headers, timeout=30)
    return resp.json()


def main():
    print(f"\n{'='*60}")
    print(f"  Cleanup Bad Records")
    print(f"{'='*60}\n")

    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        print("[ERROR] Missing FEISHU_APP_ID or FEISHU_APP_SECRET")
        return

    print(f"[1/3] Getting Feishu token...")
    token = get_token()
    print(f"  OK")

    print(f"[2/3] Listing all records...")
    records = list_all_records(token)
    print(f"  Found {len(records)} total records")

    # Find bad records
    bad_names_set = set(BAD_NAMES)
    to_delete = []
    for r in records:
        fields = r.get("fields", {})
        name = extract_text(fields.get("\u821e\u8e48\u540d\u79f0")).strip()
        if name in bad_names_set:
            to_delete.append((r["record_id"], name))

    print(f"\n  Found {len(to_delete)} bad records to delete:")
    for rid, name in to_delete:
        print(f"    - {name} (record_id={rid})")

    if not to_delete:
        print("\n[3/3] No bad records found. Nothing to delete.")
        return

    # Delete in batches of 10 (Feishu API limit)
    print(f"\n[3/3] Deleting {len(to_delete)} bad records...")
    all_ids = [rid for rid, _ in to_delete]
    deleted_count = 0
    for i in range(0, len(all_ids), 10):
        batch = all_ids[i:i+10]
        result = batch_delete(token, batch)
        if result.get("code") == 0:
            deleted_count += len(batch)
            print(f"  Deleted batch {i//10 + 1}: {len(batch)} records")
        else:
            print(f"  [ERROR] Batch delete failed: {result}")
        import time
        time.sleep(0.5)

    print(f"\n  Successfully deleted {deleted_count}/{len(to_delete)} bad records.")
    print(f"\n{'='*60}")
    print(f"  Cleanup Complete")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
