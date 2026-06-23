#!/usr/bin/env python3
"""
中美轨道发射次数对比数据搜索工具
搜索 China vs SpaceX 轨道发射数据 2024-2026H1
"""
import requests
from bs4 import BeautifulSoup
import json
import re
import time

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8'
}

def fetch_wiki_stats(year):
    """从 Wikipedia 年度航天页面获取统计"""
    url = f"https://en.wikipedia.org/wiki/{year}_in_spaceflight"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 移除不需要的标签
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()

        text = soup.get_text(separator='\n', strip=True)

        result = {"year": year, "url": url}

        # 搜索关键统计数据
        # 1. 搜索 China 发射次数
        china_patterns = [
            r'(?i)china.*?(\d{2,3})\s*(?:orbital\s*)?launch',
            r'(?i)china.*?launched.*?(\d{2,3})',
            r'(?i)(\d{2,3})\s*(?:orbital\s*)?launch.*?china',
            r'China.*?(\d+).*?attempt',
        ]
        for pat in china_patterns:
            m = re.findall(pat, text[:80000])
            if m:
                result[f"china_pattern_{pat[:20]}"] = m[:5]

        # 2. 搜索 SpaceX 发射次数
        spacex_patterns = [
            r'(?i)spacex.*?(\d{2,3})\s*(?:orbital\s*)?launch',
            r'(?i)spacex.*?launched.*?(\d{2,3})',
            r'(?i)(\d{2,3})\s*(?:orbital\s*)?launch.*?spacex',
            r'(?i)spacex.*?(\d+).*?(?:falcon|mission|attempt)',
        ]
        for pat in spacex_patterns:
            m = re.findall(pat, text[:80000])
            if m:
                result[f"spacex_pattern_{pat[:20]}"] = m[:5]

        # 3. 搜索总轨道发射次数
        total_patterns = [
            r'(?i)(\d{2,3})\s*orbital\s*launch\s*attempt',
            r'(?i)total.*?(\d{2,3})\s*orbital',
            r'(?i)orbital\s*launch.*?(\d{2,3})',
        ]
        for pat in total_patterns:
            m = re.findall(pat, text[:80000])
            if m:
                result[f"total_pattern_{pat[:20]}"] = m[:5]

        # 4. 搜索包含统计表格的区域
        # 找所有表格
        tables = soup.find_all('table')
        for i, table in enumerate(tables):
            table_text = table.get_text(separator=' ', strip=True)
            if any(kw in table_text.lower() for kw in ['china', 'spacex', 'orbital', 'launch']):
                # 提取表格中含有关键词的行
                lines = table_text.split('\n') if '\n' in table_text else [table_text]
                relevant = [l for l in lines if any(kw in l.lower() for kw in ['china', 'spacex', 'orbital', 'long march', 'falcon', 'launch'])]
                if relevant:
                    result[f"table_{i}_relevant"] = relevant[:20]

        # 5. 搜索特定段落
        # 找 "Statistics" 或 "By country" 部分
        sections = text.split('\n')
        stats_section = []
        capture = False
        for line in sections:
            if re.search(r'(?i)(statistic|by country|by operator|launch statistic|orbital launch)', line):
                capture = True
            if capture:
                stats_section.append(line)
                if len(stats_section) > 50:
                    break
        if stats_section:
            result["stats_section"] = stats_section

        return result
    except Exception as e:
        return {"year": year, "error": str(e)}


def google_search(query, num=5):
    """Google 搜索返回链接"""
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


def fetch_page_content(url, max_lines=200):
    """获取页面文本内容"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        text = soup.get_text(separator='\n', strip=True)
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        return '\n'.join(lines[:max_lines])
    except Exception as e:
        return f"Error: {e}"


def main():
    print("=" * 70)
    print("中美轨道发射次数对比数据搜索 (2024-2026H1)")
    print("=" * 70)

    # 第一步：Wikipedia 年度航天统计
    print("\n### 第一步：Wikipedia 年度航天统计 ###\n")
    for year in [2024, 2025]:
        print(f"\n--- {year} 年 ---")
        result = fetch_wiki_stats(year)
        for k, v in result.items():
            if k == 'stats_section':
                print(f"\n统计段落 (前30行):")
                for line in v[:30]:
                    print(f"  {line}")
            elif k.startswith('table_'):
                print(f"\n{k}:")
                for line in v[:15]:
                    print(f"  {line}")
            elif k not in ['year', 'url']:
                print(f"  {k}: {v}")
        time.sleep(2)

    # 第二步：Google 搜索特定查询
    print("\n\n### 第二步：Google 搜索 ###\n")

    queries = [
        "China orbital launches 2024 total number count",
        "SpaceX orbital launches 2024 total Falcon Starship",
        "China orbital launches 2025 total number",
        "SpaceX launches 2025 total Falcon count",
        "中国 2024年 航天发射 次数 统计",
        "中国 2025年 航天发射 次数 统计",
        "China commercial space launches 2024 2025 private rocket",
        "中国 商业航天 发射次数 2024 2025 民营火箭",
        "China Long March launches 2024 2025 breakdown by rocket type",
        "SpaceX 2026 launches first half",
        "China 2026 orbital launches H1 first half",
    ]

    all_results = {}

    for query in queries:
        print(f"\n{'='*60}")
        print(f"搜索: {query}")
        print('='*60)

        links = google_search(query)
        all_results[query] = {"links": links}

        print(f"找到 {len(links)} 个链接:")
        for i, link in enumerate(links, 1):
            print(f"  {i}. {link}")

        # 抓取前2个页面的相关内容
        for i, link in enumerate(links[:2]):
            print(f"\n  --- 页面 {i+1}: {link[:70]}... ---")
            content = fetch_page_content(link)
            # 提取发射相关段落
            relevant = []
            for line in content.split('\n'):
                if any(kw in line.lower() for kw in ['launch', 'orbit', 'spacex', 'falcon', 'china', 'long march', 'commercial', '发射', '轨道', '长征', '商业']):
                    relevant.append(line)
            if relevant:
                for line in relevant[:20]:
                    print(f"    {line}")
            else:
                print("    (未找到相关内容)")
            time.sleep(1)

        time.sleep(1)

    # 第三步：搜索专门的航天统计网站
    print("\n\n### 第三步：专业航天统计网站 ###\n")

    special_urls = [
        "https://www.space-launch.live/stats",
        "https://www.nextspaceflight.com/statistics",
        "https://planet4589.org/space/log/launchlog.pdf",
    ]

    for url in special_urls:
        print(f"\n--- {url} ---")
        content = fetch_page_content(url, max_lines=100)
        relevant = []
        for line in content.split('\n'):
            if any(kw in line.lower() for kw in ['2024', '2025', '2026', 'china', 'spacex', 'launch', 'orbital', 'total']):
                relevant.append(line)
        if relevant:
            for line in relevant[:15]:
                print(f"  {line}")
        else:
            print(f"  {content[:200]}")
        time.sleep(1)

    # 保存结果
    with open('/tmp/launch_stats_research.json', 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\n\n数据已保存到 /tmp/launch_stats_research.json")
    print("\n搜索完成！")


if __name__ == '__main__':
    main()
