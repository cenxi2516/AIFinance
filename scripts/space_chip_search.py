#!/usr/bin/env python3
"""
搜索中国星载计算机/抗辐射芯片国产替代信息
通过 Google 搜索 + 页面抓取获取具体产品型号、验证状态、应用任务
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
        # Bing 结果在 <li class="b_algo"> 中
        for li in soup.find_all('li', class_='b_algo'):
            title_tag = li.find('h2')
            if title_tag:
                title = title_tag.get_text(strip=True)
                link_tag = title_tag.find('a')
                link = link_tag['href'] if link_tag and link_tag.get('href') else ''
            else:
                title = ''
                link = ''

            # 摘要
            snippet = ''
            p_tag = li.find('p')
            if p_tag:
                snippet = p_tag.get_text(strip=True)
            else:
                # 备选：找 b_caption 下的文字
                cap = li.find(class_='b_caption')
                if cap:
                    snippet = cap.get_text(strip=True)

            if title:
                results.append({
                    'title': title,
                    'link': link,
                    'snippet': snippet[:500]
                })

        return results
    except Exception as e:
        return [{'title': f'Error: {e}', 'link': '', 'snippet': ''}]


def google_search(query, num=10):
    """Google搜索并返回结果列表"""
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://www.google.com/search?q={encoded}&num={num}"
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        results = []
        for g in soup.find_all('div', class_='g'):
            title_tag = g.find('h3')
            link_tag = g.find('a')
            snippet_tag = g.find('div', class_=['VwiC3b', 'st'])

            title = title_tag.get_text(strip=True) if title_tag else ''
            link = link_tag['href'] if link_tag and link_tag.get('href') else ''
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ''

            if title:
                results.append({
                    'title': title,
                    'link': link,
                    'snippet': snippet[:500]
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
        # 移除script和style
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'iframe']):
            tag.decompose()
        text = soup.get_text(separator='\n', strip=True)
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        return '\n'.join(lines[:500])
    except Exception as e:
        return f"Error: {e}"


def extract_key_info(text):
    """从文本中提取关键信息（产品型号、验证状态等）"""
    keywords = [
        '抗辐射', 'FPGA', '星载', '航天', '国产替代', '自主可控',
        '772所', '紫光国微', '复旦微', '龙芯', '银河微', '国微思尔芯',
        '验证', '认证', '型号', '芯片', '单片机', 'CPU', 'DSP',
        '卫星', '北斗', '嫦娥', '天问', '神舟', '空间站',
        'SMIC', 'radiation', 'rad-hard', '抗辐照',
        'LSI', 'VLSI', 'ASIC', 'SoC', 'MCU',
        'CDK', '龙芯', '飞腾', '兆芯',
        '军品', '宇航级', '航天级', '弹载',
    ]
    relevant = []
    for line in text.split('\n'):
        if any(kw.lower() in line.lower() for kw in keywords):
            relevant.append(line[:300])
    return relevant[:50]


def main():
    queries = [
        # 第1组
        ("星载计算机国产替代", "中国 星载计算机 国产替代 2025"),
        ("抗辐射FPGA航天验证", "中国 抗辐射FPGA 航天验证"),
        # 第2组
        ("772所抗辐射芯片", "772所 抗辐射芯片"),
        ("紫光国微特种集成电路航天", "紫光国微 特种集成电路 航天"),
        # 第3组
        ("复旦微电子FPGA航天", "复旦微电子 FPGA 航天"),
        ("卫星芯片自主可控进展", "中国 卫星芯片 自主可控 进展"),
        # 第4组
        ("龙芯航天抗辐射", "龙芯 航天 抗辐射"),
        ("星务计算机国产化", "中国 星务计算机 国产化"),
        # 第5组
        ("银河微电子航天", "银河微电子 航天"),
        ("国微思尔芯航天验证", "国微思尔芯 航天验证"),
    ]

    all_data = {}

    for key, query in queries:
        print(f"\n{'='*80}")
        print(f"搜索: {key}")
        print(f"查询: {query}")
        print('='*80)

        # 尝试 Bing 搜索
        results = bing_search(query)

        # 如果 Bing 没结果，尝试 Google
        if not results or (len(results) == 1 and 'Error' in results[0]['title']):
            print("  Bing 搜索失败，尝试 Google...")
            results = google_search(query)

        all_data[key] = {
            "query": query,
            "results": results
        }

        print(f"\n找到 {len(results)} 个结果：\n")
        for i, r in enumerate(results[:8], 1):
            print(f"  [{i}] {r['title']}")
            if r['link']:
                print(f"      链接: {r['link'][:100]}")
            if r['snippet']:
                print(f"      摘要: {r['snippet'][:300]}")
            print()

        # 抓取前3个页面的详细内容
        for i, r in enumerate(results[:3]):
            if not r['link'] or 'Error' in r['link']:
                continue
            print(f"  --- 抓取页面 {i+1}: {r['link'][:80]}... ---")
            content = fetch_page(r['link'])
            relevant = extract_key_info(content)
            if relevant:
                for line in relevant[:20]:
                    print(f"    {line}")
            else:
                print("    (未找到相关关键信息)")
            time.sleep(2)  # 避免被封

        time.sleep(1)

    # 保存所有数据
    output_path = '/tmp/space_chip_research_data.json'
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
                print(f"  {r['snippet'][:300]}")


if __name__ == '__main__':
    main()
