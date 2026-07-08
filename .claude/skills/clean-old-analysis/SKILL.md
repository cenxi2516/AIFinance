---
name: clean-old-analysis
description: 清理 src/ 目录下超过指定天数的旧分析目录。递归扫描 src/ 下所有符合日期命名规范(YYYY-MM-DD-*)的目录，dry-run 预览后经用户确认删除。适用于定期清理过期分析报告、释放磁盘空间、保持项目目录整洁。
version: 1.0.0
updated: 2026-07-07
---

# 旧分析目录清理器 V1.0

安全清理 `src/` 下超过指定天数的旧分析目录，释放磁盘空间，保持项目结构整洁。

> **设计原则：** 安全优先——默认只预览不删除，需显式确认。严格匹配日期命名模式，绝不触碰系统目录。

## When to Activate

- 用户要**清理旧分析文件**（"清理一个月前的分析""删除旧报告"）
- 用户要**释放磁盘空间**（"项目太大了，清理一下"）
- 用户要**定期维护项目目录**（"做下目录清理"）
- 关键词：`清理`、`删除旧分析`、`清理旧目录`、`释放空间`、`目录清理`

## 核心逻辑

```
扫描 src/ 所有子目录
    │
    ├─ 跳过 _ 开头的系统目录（_templates/_analysis 等）
    ├─ 匹配 YYYY-MM-DD-* 命名模式
    ├─ 检查日期是否超过阈值（默认 30 天）
    │
    ▼
dry-run 列出待清理目录（日期 + 大小）
    │
    ▼
等待用户确认后执行删除
```

## 安全规则（强制）

| 规则 | 说明 |
|------|------|
| **模式匹配** | 仅删除 `^\d{4}-\d{2}-\d{2}-` 开头的目录 |
| **系统保护** | `_` 前缀目录自动跳过（`_templates`/`_analysis`/`_index.md` 等） |
| **默认预览** | 不加 `--confirm` 只列出待删目录，不执行任何删除 |
| **确认机制** | 加 `--confirm` 后仍需输入 `yes` 确认（除非再加 `--yes`） |
| **不可恢复** | 删除操作为 `shutil.rmtree`，不走回收站，确认前务必检查清单 |

## 用法

### 基本命令

```bash
# 激活 venv（如需）
source .venv/bin/activate

# 预览 30 天前的分析目录（默认，安全）
python3 scripts/clean_old_analysis.py

# 预览 60 天前的分析目录
python3 scripts/clean_old_analysis.py --days 60

# 确认删除（会列出清单并要求输入 yes）
python3 scripts/clean_old_analysis.py --confirm

# 确认删除 90 天前的目录
python3 scripts/clean_old_analysis.py --confirm --days 90

# 非交互模式（脚本/CI 中使用，跳过 yes 确认）
python3 scripts/clean_old_analysis.py --confirm --yes --days 30
```

### 执行流程

1. **第一步**：始终先 dry-run 预览
   ```bash
   python3 scripts/clean_old_analysis.py --days 30
   ```
2. **第二步**：让用户检查清单
3. **第三步**：用户确认后执行
   ```bash
   python3 scripts/clean_old_analysis.py --confirm --days 30
   ```

## 输出示例

```
🔍 扫描 src/ 目录中...（阈值: 30 天前 = 2026-06-07 之前）

📋 待清理目录清单（30 天前 = 2026-06-07 之前）
   共 12 个目录，预计释放 45.2 MB

  [ 1] src/AI半导体/材料/2026-06-22-锡供需分析
       日期: 2026-06-22  |  大小: 3.2 MB
  [ 2] src/AI半导体/材料/2026-06-22-半导体硅片供需分析
       日期: 2026-06-22  |  大小: 5.1 MB
  ...

💡 以上为预览，执行删除请加 --confirm 参数
```

## 注意事项

- **不可逆操作**：`shutil.rmtree` 直接永久删除，无回收站
- **Git 历史**：删除的目录如果已提交 git，仍可通过 git history 找回
- **建议频率**：每月清理一次 30 天前的分析，季度清理一次 90 天前的
- **先 commit 再清理**：确保最新分析已提交后再清理旧目录