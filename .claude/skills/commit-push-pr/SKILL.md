---
name: commit-push-pr
description: Use when 用户说"git提交""提交代码""推送""push""创建PR""提PR""commit and push"等需要标准化 git 提交流程时
version: 1.0.0
updated: 2026-06-30
---

# Git 提交推送与 PR 创建

## 概述

标准化 git 提交流程：状态检查 → 暂存 → 提交（符合项目规范）→ 推送 → PR（可选）。确保提交信息安全、格式统一、非破坏性操作。

## 执行流程

```
git status
    ↓
选择性暂存（排除不相关文件）
    ↓
git commit（Conventional Commits + 中文描述 + Co-Authored-By）
    ↓
git push
    ↓
（可选）gh pr create
```

## 提交规范

### 格式

```
<type>: <中文简短描述>

- <要点1>
- <要点2>

Co-Authored-By: Claude <noreply@anthropic.com>
```

### Type 选择

| Type | 场景 |
|------|------|
| `feat` | 新增分析报告、skill、功能 |
| `fix` | 修复错误 |
| `docs` | 纯文档更新 |
| `refactor` | 重构（不改变行为） |
| `chore` | 配置、脚本等杂项 |

### PR 正文尾部

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## 安全规则

1. **暂存前检查**：`git status` → 确认哪些文件需要提交，排除不相关的 untracked 文件
2. **破坏性操作确认**：`git reset --hard`、`git clean -fd`、`git push --force` 等必须先 `AskUserQuestion`
3. **分支保护**：不在 `main` 分支直接提交，先切 feature 分支
4. **大文件警告**：超过 1MB 的文件提醒用户确认

## 常见场景

### 场景 1：常规提交推送

```bash
git status                    # 检查状态
git add <files>               # 选择性暂存
git commit -m "..."           # 规范格式
git push                      # 推送
```

### 场景 2：提交并创建 PR

```bash
# 完成场景 1 后
gh pr create --base main --title "feat: <描述>" --body "<详细说明>

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

### 场景 3：amend 最近提交

```bash
# 仅当尚未 push 时可用
git add <遗漏文件>
git commit --amend -m "修正后的信息"
```

## 禁止行为

- ❌ `git add -A` / `git add .`（可能误加不相关文件）
- ❌ `git push --force` 到共享分支（除非用户明确要求 + 已确认）
- ❌ 在 `main` 分支直接提交
- ❌ 提交包含 API key / 密码 / token 的文件