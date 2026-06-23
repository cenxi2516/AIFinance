#!/usr/bin/env python3
"""
搜索中国相控阵天线/平板天线 卫星互联网终端厂商信息
通过 Bing 搜索 + 页面抓取获取具体产品型号、规格、价格、技术路线
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import re
import urllib.parse

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}
TIMEOUT = 20


def bing_search(query, num=10):
    """Bing搜索并返回结果列表"""
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://www.bing.com/search?q={encoded}&count={num}"
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        results = []
        for li in soup.find_all('li', class_='b_algo'):
            title_tag = li.find('h2')
            if title_tag:
                title = title_tag.get_text(strip=True)
                link_tag = title_tag.find('a')
                link = link_tag['href'] if link_tag and link_tag.get('href') else ''
            else:
                title = ''
                link = ''

            snippet = ''
            p_tag = li.find('p')
            if p_tag:
                snippet = p_tag.get_text(strip=True)
            else:
                cap = li.find(class_='b_caption')
                if cap:
                    snippet = cap.get_text(strip=True)

            if title:
                results.append({
                    'title': title,
                    'link': link,
                    'snippet': snippet[:800]
                })

        return results
    except Exception as e:
        return [{'title': f'Error: {e}', 'link': '', 'snippet': ''}]


def fetch_page(url, timeout=15):
    """获取网页内容"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'iframe']):
            tag.decompose()
        text = soup.get_text(separator='\n', strip=True)
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        return '\n'.join(lines[:800])
    except Exception as e:
        return f"Error: {e}"


def extract_key_info(text):
    """从文本中提取关键信息"""
    keywords = [
        '相控阵', '平板天线', ' phased array', 'flat panel',
        '卫星互联网', '卫星通信', 'satellite internet', 'satellite communication',
        'Ku', 'Ka', '频段', 'frequency', 'GHz',
        '波束', 'beam', '扫描',
        '硅基', 'GaN', 'GaAs', 'CMOS', '芯片', 'T/R', 'TR',
        '航空', '航海', '车载', '便携', 'avionics', 'maritime', 'vehicle',
        '铖昌科技', '海格通信', '和德宇航', '华力创通', '银河航天',
        '中科海讯', '盛路通信', '航天发展', '雷电微力',
        '价格', '成本', '万元', '定价',
        '尺寸', '重量', '规格', '厚度',
        '电科', '14所', '38所', '54所',
        '星链', 'Starlink', 'OneWeb',
        '千帆', '国网', '星座',
        '终端', 'terminal',
    ]
    relevant = []
    for line in text.split('\n'):
        if any(kw.lower() in line.lower() for kw in keywords):
            relevant.append(line[:400])
    return relevant[:80]


def main():
    queries = [
        # 中文搜索
        ("相控阵天线卫星互联网终端", "相控阵天线 卫星互联网 终端 2025"),
        ("平板天线卫星通信厂商", "平板天线 卫星通信 厂商"),
        ("中国相控阵天线卫星厂商", "中国 相控阵天线 卫星 厂商 2025 2026"),
        ("相控阵天线卫星终端价格", "相控阵天线 卫星终端 价格 成本 2025"),
        ("Ku Ka频段平板天线中国", "Ku Ka频段 平板天线 中国 厂商"),
        ("卫星互联网车载终端相控阵", "卫星互联网 车载终端 相控阵天线"),
        # 英文搜索
        ("phased array antenna China", "phased array antenna satellite China manufacturer 2025"),
        ("flat panel antenna satellite China", "flat panel antenna satellite terminal China 2025"),
        ("Chinese phased array satellite terminal", "Chinese phased array satellite terminal product specification"),
        ("Ku Ka band flat antenna China", "Ku Ka band flat panel antenna China manufacturer price"),
    ]

    all_data = {}

    for key, query in queries:
        print(f"\n{'='*80}")
        print(f"搜索: {key}")
        print(f"查询: {query}")
        print('='*80)

        results = bing_search(query)
        all_data[key] = {
            "query": query,
            "results": results
        }

        print(f"\n找到 {len(results)} 个结果：\n")
        for i, r in enumerate(results[:10], 1):
            print(f"  [{i}] {r['title']}")
            if r['link']:
                print(f"      链接: {r['link'][:120]}")
            if r['snippet']:
                print(f"      摘要: {r['snippet'][:500]}")
            print()

        # 抓取前3个页面的详细内容
        for i, r in enumerate(results[:3]):
            if not r['link'] or 'Error' in r['link']:
                continue
            print(f"  --- 抓取页面 {i+1}: {r['link'][:100]}... ---")
            content = fetch_page(r['link'])
            relevant = extract_key_info(content)
            if relevant:
                for line in relevant[:30]:
                    print(f"    {line}")
            else:
                print("    (未找到相关关键信息)")
            time.sleep(2)

        time.sleep(1)

    # 保存所有数据
    output_path = '/tmp/antenna_research_data.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

    print(f"\n\n{'='*80}")
    print(f"所有数据已保存到 {output_path}")
    print('='*80)

    # 汇总所有关键信息
    print("\n\n" + "="*80)
    print("关键信息汇总")
    print("="*80)

    for key, data in all_data.items():
        print(f"\n--- {key} ---")
        for r in data.get('results', [])[:5]:
            if r.get('snippet'):
                print(f"  {r['snippet'][:400]}")


if __name__ == '__main__':
    main()
