#!/usr/bin/env python3
"""
搜索商业航天概念板块成分股
通过东方财富 API 获取概念板块列表和成分股
"""
import requests
import json

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
TIMEOUT = 15

# 已有列表（用于对比去重）
EXISTING = {
    '600118': '中国卫星',
    '688066': '航天宏图',
    '001270': '铖昌科技',
    '688270': '臻镭科技',
    '688102': '斯瑞新材',
    '301005': '超捷股份',
    '688522': '上海瀚讯',
    '002025': '航天电器',
    '603267': '鸿远电子',
    '600501': '航天晨光',
    '002465': '海格通信',
    '300342': '天银机电',
    '600879': '航天电子',
    '688568': '中科星图',
    '002389': '航天彩虹',
}


def fetch_concept_boards():
    """获取所有概念板块列表"""
    url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&fs=m:90+t:3&fields=f12,f14"
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()["data"]["diff"]


def fetch_board_stocks(board_code):
    """获取板块成分股"""
    url = f"https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=200&fs=b:{board_code}&fields=f12,f14"
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()["data"]["diff"]


def main():
    # 第一步：搜索相关概念板块
    print("=" * 60)
    print("第一步：搜索包含「航天」「卫星」「商业航」的概念板块")
    print("=" * 60)

    boards = fetch_concept_boards()
    matched = []
    for item in boards:
        name = item["f14"]
        if "航天" in name or "卫星" in name or "商业航" in name:
            matched.append((item["f12"], name))
            print(f"  板块代码: {item['f12']}, 板块名称: {name}")

    if not matched:
        print("  未找到匹配板块，尝试扩大搜索范围...")
        for item in boards:
            name = item["f14"]
            if "航" in name or "星" in name:
                matched.append((item["f12"], name))
                print(f"  板块代码: {item['f12']}, 板块名称: {name}")

    print(f"\n共匹配到 {len(matched)} 个相关板块\n")

    # 第二步：获取各板块成分股
    all_stocks = {}  # code -> (name, boards)

    for code, name in matched:
        print("=" * 60)
        print(f"板块: {name} ({code}) 成分股")
        print("=" * 60)

        stocks = fetch_board_stocks(code)
        print(f"共 {len(stocks)} 只成分股：\n")

        for item in stocks:
            s_code = item["f12"]
            s_name = item["f14"]
            tag = " ★已有" if s_code in EXISTING else ""
            print(f"  {s_name}({s_code}){tag}")

            if s_code not in all_stocks:
                all_stocks[s_code] = (s_name, [])
            all_stocks[s_code][1].append(name)

        print()

    # 第三步：对比分析
    print("=" * 60)
    print("对比分析")
    print("=" * 60)

    # 已有但不在API结果中的
    api_codes = set(all_stocks.keys())
    existing_codes = set(EXISTING.keys())

    missing_in_api = existing_codes - api_codes
    new_from_api = api_codes - existing_codes

    print(f"\n已有列表共 {len(EXISTING)} 只，API 获取共 {len(all_stocks)} 只")
    print(f"重叠: {len(existing_codes & api_codes)} 只")
    print(f"已有但 API 未覆盖: {len(missing_in_api)} 只")
    print(f"API 有但已有列表缺失: {len(new_from_api)} 只")

    if missing_in_api:
        print("\n--- 已有但 API 结果中未出现 ---")
        for code in sorted(missing_in_api):
            print(f"  {EXISTING[code]}({code})")

    if new_from_api:
        print("\n--- API 新增（已有列表缺失的）---")
        for code in sorted(new_from_api):
            name, boards = all_stocks[code]
            print(f"  {name}({code})  所属板块: {', '.join(boards)}")

    # 第四步：输出完整合并列表
    print("\n" + "=" * 60)
    print("完整合并列表（去重）")
    print("=" * 60)

    merged = dict(EXISTING)
    for code, (name, _) in all_stocks.items():
        if code not in merged:
            merged[code] = name

    for code in sorted(merged.keys()):
        source = "已有" if code in EXISTING else "新增"
        boards_str = ""
        if code in all_stocks:
            boards_str = f"  板块: {', '.join(all_stocks[code][1])}"
        print(f"  {merged[code]}({code})  [{source}]{boards_str}")

    print(f"\n合并后共 {len(merged)} 只")


if __name__ == "__main__":
    main()
