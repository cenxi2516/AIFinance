#!/usr/bin/env python3
"""
清理 src/ 目录下超过指定天数的旧分析目录。

安全规则：
- 仅删除符合 YYYY-MM-DD-* 命名模式的目录
- 自动跳过 _ 开头的系统目录（_templates、_analysis 等）
- 默认 dry-run 模式，需 --confirm 才执行实际删除
- 删除前打印完整清单（含目录大小）

用法：
    python3 scripts/clean_old_analysis.py              # dry-run，列出待清理目录
    python3 scripts/clean_old_analysis.py --days 60    # 自定义 60 天阈值
    python3 scripts/clean_old_analysis.py --confirm    # 确认后执行删除
    python3 scripts/clean_old_analysis.py --confirm --days 30  # 自定义天数+确认删除
"""

import os
import re
import sys
import shutil
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# 项目根目录（脚本所在目录的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

# 日期目录匹配：YYYY-MM-DD- 开头
DATE_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-")


def get_dir_size(dir_path: Path) -> int:
    """递归计算目录总大小（字节）"""
    total = 0
    try:
        for entry in dir_path.rglob("*"):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
    except (PermissionError, OSError):
        pass
    return total


def format_size(size_bytes: int) -> str:
    """人类可读的大小格式"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def parse_date_from_dirname(dirname: str) -> datetime | None:
    """从目录名提取日期，如 '2026-06-22-锡供需分析' → datetime(2026,6,22)"""
    m = DATE_DIR_PATTERN.match(dirname)
    if not m:
        return None
    date_str = dirname[:10]  # YYYY-MM-DD
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


def find_old_analysis_dirs(days: int) -> list[dict]:
    """
    递归扫描 src/ 目录，找到所有超过指定天数的分析目录。

    返回列表，每项包含 path / date / size_bytes
    """
    cutoff_date = datetime.now() - timedelta(days=days)
    results = []

    for root, dirs, _ in os.walk(SRC_DIR):
        # 跳过 _ 开头的系统目录
        dirs[:] = [d for d in dirs if not d.startswith("_")]

        root_path = Path(root)
        for dirname in dirs:
            dir_date = parse_date_from_dirname(dirname)
            if dir_date and dir_date < cutoff_date:
                dir_path = root_path / dirname
                results.append({
                    "path": dir_path,
                    "date": dir_date,
                    "size_bytes": get_dir_size(dir_path),
                })

    # 按日期从旧到新排序
    results.sort(key=lambda x: x["date"])
    return results


def print_dry_run(dirs: list[dict], days: int):
    """打印预览清单"""
    if not dirs:
        print(f"✅ src/ 下没有超过 {days} 天的旧分析目录")
        return

    total_size = sum(d["size_bytes"] for d in dirs)
    print(f"📋 待清理目录清单（{days} 天前 = {datetime.now() - timedelta(days=days):%Y-%m-%d} 之前）")
    print(f"   共 {len(dirs)} 个目录，预计释放 {format_size(total_size)}\n")

    for i, d in enumerate(dirs, 1):
        rel_path = d["path"].relative_to(PROJECT_ROOT)
        print(f"  [{i:2d}] {rel_path}")
        print(f"       日期: {d['date'].strftime('%Y-%m-%d')}  |  大小: {format_size(d['size_bytes'])}")

    print(f"\n💡 以上为预览，执行删除请加 --confirm 参数")


def confirm_and_delete(dirs: list[dict], days: int):
    """交互确认后执行删除"""
    if not dirs:
        print(f"✅ src/ 下没有超过 {days} 天的旧分析目录，无需清理")
        return

    total_size = sum(d["size_bytes"] for d in dirs)
    print(f"\n⚠️  将删除 {len(dirs)} 个超过 {days} 天的旧分析目录")
    print(f"   预计释放空间: {format_size(total_size)}\n")

    for d in dirs:
        rel_path = d["path"].relative_to(PROJECT_ROOT)
        print(f"  🗑  {rel_path}  ({d['date'].strftime('%Y-%m-%d')}, {format_size(d['size_bytes'])})")

    print(f"\n{'='*60}")
    response = input("确认删除以上目录？(输入 yes 确认): ").strip()
    if response != "yes":
        print("❌ 已取消删除操作")
        return

    deleted = 0
    failed = []
    for d in dirs:
        try:
            shutil.rmtree(d["path"])
            rel_path = d["path"].relative_to(PROJECT_ROOT)
            print(f"  ✅ 已删除: {rel_path}")
            deleted += 1
        except Exception as e:
            failed.append((d["path"], str(e)))
            print(f"  ❌ 删除失败: {d['path'].relative_to(PROJECT_ROOT)} — {e}")

    print(f"\n{'='*60}")
    print(f"✅ 完成：成功删除 {deleted} 个目录，释放 {format_size(total_size)}")
    if failed:
        print(f"⚠️  {len(failed)} 个目录删除失败")
        for path, err in failed:
            print(f"   - {path.relative_to(PROJECT_ROOT)}: {err}")


def main():
    parser = argparse.ArgumentParser(
        description="清理 src/ 下超过指定天数的旧分析目录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                     # 预览（默认 30 天）
  %(prog)s --days 60          # 预览 60 天前的目录
  %(prog)s --confirm          # 确认后删除 30 天前的目录
  %(prog)s --confirm --days 90  # 确认后删除 90 天前的目录
        """,
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=30,
        help="天数阈值，删除超过此天数的目录（默认 30）",
    )
    parser.add_argument(
        "--confirm", "-c",
        action="store_true",
        help="确认执行删除（不加此参数仅预览）",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过交互确认，直接删除（仅与 --confirm 配合使用）",
    )

    args = parser.parse_args()

    if args.days < 1:
        print("❌ 天数必须 >= 1")
        sys.exit(1)

    print(f"🔍 扫描 src/ 目录中...（阈值: {args.days} 天前 = {(datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')} 之前）\n")

    old_dirs = find_old_analysis_dirs(args.days)

    if args.confirm:
        if args.yes:
            # 非交互模式：直接删除
            total_size = sum(d["size_bytes"] for d in old_dirs)
            if not old_dirs:
                print(f"✅ 没有超过 {args.days} 天的旧分析目录")
                return
            deleted = 0
            for d in old_dirs:
                try:
                    shutil.rmtree(d["path"])
                    rel_path = d["path"].relative_to(PROJECT_ROOT)
                    print(f"  ✅ 已删除: {rel_path}")
                    deleted += 1
                except Exception as e:
                    print(f"  ❌ 删除失败: {d['path'].relative_to(PROJECT_ROOT)} — {e}")
            print(f"\n✅ 完成：成功删除 {deleted} 个目录，释放 {format_size(total_size)}")
        else:
            confirm_and_delete(old_dirs, args.days)
    else:
        print_dry_run(old_dirs, args.days)


if __name__ == "__main__":
    main()
