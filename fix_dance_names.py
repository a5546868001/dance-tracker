#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fix script: clean dance names in existing Feishu records.
Strips suffixes like （续）, （升级版）, （宫廷风）, （广西科目三） from 舞蹈名称 field.

Runs on GitHub Actions (needs FEISHU_APP_ID, FEISHU_APP_SECRET).
"""

import os
import re
import requests

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")

BASE_TOKEN = "KY46b07m4anEIbs31xJcgaFznMg"
TABLE_ID = "tblVsVYhYEPmN3nF"
FEISHU_API = "https://open.feishu.cn/open-apis"

DANCE_NAME_FIELD = "\u821e\u8e48\u540d\u79f0"  # 舞蹈名称


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


def update_record(token, record_id, fields):
    url = f"{FEISHU_API}/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records/{record_id}"
    headers = {"Authorization": f"Bearer {token}"}
    body = {"fields": fields}
    resp = requests.put(url, json=body, headers=headers, timeout=30)
    return resp.json()


def clean_name(name):
    """Strip suffixes in parentheses."""
    if not name:
        return name
    name = name.strip()
    name = re.sub(r'[（(].*?[）)]\s*$', '', name)
    return name.strip()


def main():
    print(f"\n{'='*60}")
    print(f"  Fix Dance Names (strip suffixes)")
    print(f"{'='*60}\n")

    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        print("[ERROR] Missing FEISHU_APP_ID or FEISHU_APP_SECRET")
        return

    print("[1/3] Getting Feishu token...")
    token = get_token()
    print("  OK")

    print("[2/3] Listing all records...")
    records = list_all_records(token)
    print(f"  Found {len(records)} total records")

    # Find records with suffixes
    to_fix = []
    for r in records:
        fields = r.get("fields", {})
        raw_name = extract_text(fields.get(DANCE_NAME_FIELD))
        cleaned = clean_name(raw_name)
        if cleaned != raw_name and cleaned:
            to_fix.append((r["record_id"], raw_name, cleaned))

    print(f"\n  Found {len(to_fix)} records to fix:")
    for rid, old, new in to_fix:
        print(f"    - '{old}' -> '{new}' (record_id={rid})")

    if not to_fix:
        print("\n[3/3] No records need fixing. Done.")
        return

    # Fix each record
    print(f"\n[3/3] Fixing {len(to_fix)} records...")
    fixed_count = 0
    for rid, old_name, new_name in to_fix:
        result = update_record(token, rid, {DANCE_NAME_FIELD: new_name})
        if result.get("code") == 0:
            fixed_count += 1
            print(f"  Fixed: '{old_name}' -> '{new_name}'")
        else:
            print(f"  [ERROR] Failed to fix '{old_name}': {result}")
        import time
        time.sleep(0.3)

    print(f"\n  Successfully fixed {fixed_count}/{len(to_fix)} records.")
    print(f"\n{'='*60}")
    print(f"  Fix Complete")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
