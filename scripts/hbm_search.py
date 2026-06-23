#!/usr/bin/env python3
"""HBM供需缺口与价格数据搜索工具"""

import requests
from bs4 import BeautifulSoup
import json
import time
import re

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8'
}

def google_search(query, num=10):
    """Google搜索并返回链接列表"""
    try:
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}&num={num}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/url?q=' in href:
                real_url = href.split('/url?q=')[1].split('&')[0]
                if 'google.com' not in real_url and 'youtube.com' not in real_url:
                    links.append(real_url)
        return links[:num]
    except Exception as e:
        return [f"Error: {e}"]

def fetch_page(url, timeout=15):
    """获取网页内容"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        # 移除script和style
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        text = soup.get_text(separator='\n', strip=True)
        # 清理多余空行
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        return '\n'.join(lines[:300])  # 限制长度
    except Exception as e:
        return f"Error fetching {url}: {e}"

def main():
    queries = {
        "HBM供需缺口": "HBM supply demand gap 2025 2026 shortage forecast TrendForce",
        "HBM价格走势": "HBM price per GB 2025 2026 quarterly trend DRAMeXchange",
        "HBM溢价倍数": "HBM price premium over DRAM 2025 multiple comparison",
        "TSV产能瓶颈": "HBM TSV capacity bottleneck 2025 2026 supply constraint",
        "CoWoS封装约束": "CoWoS packaging capacity HBM constraint 2025 2026 TSMC",
        "HBM供需平衡预测": "HBM supply demand balance forecast when equilibrium 2026 2027",
    }

    all_data = {}

    for key, query in queries.items():
        print(f"\n{'='*60}")
        print(f"搜索: {key}")
        print(f"查询: {query}")
        print('='*60)

        links = google_search(query)
        all_data[key] = {"query": query, "links": links}

        print(f"找到 {len(links)} 个链接:")
        for i, link in enumerate(links[:5], 1):
            print(f"  {i}. {link}")

        # 尝试抓取前3个页面的摘要
        for i, link in enumerate(links[:3]):
            print(f"\n--- 抓取页面 {i+1}: {link[:60]}... ---")
            content = fetch_page(link)
            # 提取HBM相关段落
            relevant_lines = []
            for line in content.split('\n'):
                if any(kw in line.lower() for kw in ['hbm', 'high bandwidth', 'tsv', 'cowos', 'dram', 'supply', 'demand', 'price', 'shortage', 'gap', 'capacity']):
                    relevant_lines.append(line)
            if relevant_lines:
                print('\n'.join(relevant_lines[:30]))
            else:
                print("(未找到HBM相关内容)")
            time.sleep(1)

    # 保存所有数据
    with open('/tmp/hbm_research_data.json', 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

    print(f"\n\n数据已保存到 /tmp/hbm_research_data.json")

if __name__ == '__main__':
    main()
