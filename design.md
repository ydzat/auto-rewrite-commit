非常好。下面是一份完整、专业级的**项目设计文档**，覆盖系统目标、架构、流程、模块、状态机逻辑、数据结构、执行安全、扩展计划等。
它基于我们之前的全部讨论，针对“轻量化 + 可循环 + 可恢复 + AI辅助 + 批量合并”这五大核心特征。
这份文档可直接作为研发文档或项目 README 的高级版使用。

---

# 🧠 项目设计文档：Auto Git History Rewriter

**版本：** v1.0
**作者：** （用户团队）
**目标语言：** Python 3.8+
**执行环境：** 任意包含 Git 的仓库
**最后更新日期：** 2025-10-15

---

## 一、项目概述

### 1.1 背景

Git 历史记录往往包含大量冗余、相似或非规范的提交信息。
手动重写这些记录不仅耗时，还容易破坏提交链。

本项目旨在提供一个**轻量级、自动化、AI 辅助**的历史优化工具，
它能在安全、可回滚的前提下自动分析、合并并重写提交历史。

---

### 1.2 项目目标

构建一个可直接在 Git 仓库中执行的命令行工具，实现以下目标：

1. **自动分析历史提交相似度**，检测可合并提交。
2. **循环式迭代执行**：从最早提交开始逐步重写，保持链路一致。
3. **AI 辅助生成新提交信息**，确保简洁、规范。
4. **状态可追踪**：支持断点恢复、避免重复处理。
5. **安全执行**：dry-run 模式验证、自动备份、避免哈希冲突。

---

### 1.3 项目特性

| 特性        | 描述                     |
| --------- | ---------------------- |
| 轻量单体结构    | 无外部依赖服务，无需守护进程         |
| AI 辅助重写   | 自动生成规范化 commit message |
| 自动聚类与合并   | 基于相似度检测批量合并相关提交        |
| 循环式执行     | 从最早到最新逐步重写，保持一致性       |
| 状态追踪与断点恢复 | 通过映射表记录每次重写关系          |
| 安全机制      | dry-run 模拟、自动备份、可回滚    |
| 易扩展       | 可接入任意 LLM API          |

---

## 二、系统架构设计

### 2.1 总体架构

```
+---------------------------------------------------------+
|                   Auto Git Rewriter                     |
+---------------------------------------------------------+
|   CLI Entry (main.py)                                   |
|   ├── Argument parser                                   |
|   ├── Dry-run / Apply control                           |
|   └── Loop control (iteration engine)                   |
+---------------------------------------------------------+
|   Core Modules                                          |
|   ├── git_ops.py        → 历史扫描与合并执行逻辑        |
|   ├── cluster.py        → 提交相似度分析与聚类          |
|   ├── ai_rewriter.py    → AI消息生成器（LLM调用）        |
|   ├── state.py          → 状态映射表管理与恢复          |
|   └── utils.py          → 通用工具                      |
+---------------------------------------------------------+
|   Config: config.yaml                                   |
|   State: .git-ai-rewrite-map.json                       |
+---------------------------------------------------------+
```

---

### 2.2 模块职责说明

| 模块                 | 功能                          |
| ------------------ | --------------------------- |
| **main.py**        | CLI 入口，负责解析参数、循环控制          |
| **git_ops.py**     | 获取历史提交、执行合并与重写操作            |
| **cluster.py**     | 通过文本与路径相似度聚类相似提交            |
| **ai_rewriter.py** | 调用 LLM 生成规范化 commit message |
| **state.py**       | 维护哈希映射表、状态标记与断点恢复           |
| **config.yaml**    | 用户配置文件，存储 LLM 接口与模板         |
| **utils.py**       | 日志、时间戳、文件操作辅助函数             |

---

## 三、执行逻辑与循环流程

### 3.1 执行顺序（迭代循环）

```text
1. 提取完整提交历史（按时间顺序）
2. 读取状态表，过滤已处理提交
3. 对未处理提交进行相似度聚类
4. 取出第一个可合并的提交组：
   ├─ 若组内仅1个 → 重写提交信息
   └─ 若组内>1个 → 执行合并
5. 调用 AI 生成新 message
6. 重写并提交新节点（更新 parent）
7. 写入映射表并保存
8. 重复步骤 2~7，直至所有提交处理完毕
```

---

### 3.2 流程图

```
┌─────────────┐
│ Load config │
└──────┬──────┘
       ▼
┌─────────────┐
│ Load state  │
└──────┬──────┘
       ▼
┌──────────────────────────┐
│ Get all commits (oldest) │
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ Filter unprocessed ones  │
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ Find similar commit group│
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ AI rewrite or merge      │
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ Apply changes to history │
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ Update state + mapping   │
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ Loop until done          │
└──────────────────────────┘
```

---

## 四、关键机制设计

### 4.1 状态追踪机制

状态表文件：`.git-ai-rewrite-map.json`
作用：防止重复处理，支持断点续跑。

示例：

```json
{
  "mapping": {
    "a1b2c3": "z9y8x7",
    "d4e5f6": "z9y8x7"
  },
  "groups": {
    "z9y8x7": ["a1b2c3", "d4e5f6"]
  },
  "status": {
    "a1b2c3": "merged",
    "d4e5f6": "merged",
    "z9y8x7": "done"
  },
  "last_updated": "2025-10-15T12:45:00Z"
}
```

#### 状态流转

| 状态          | 含义          |
| ----------- | ----------- |
| `pending`   | 待处理（默认）     |
| `merged`    | 已被合并进其他提交   |
| `rewritten` | 已重写 message |
| `done`      | 新提交已写入历史    |

#### 写入策略

每次重写或合并完成后立即更新映射表。

---

### 4.2 相似提交聚类逻辑

简易算法：

1. 使用 `git diff-tree` 提取文件路径；
2. 使用提交 message 计算文本相似度；
3. 若相似度 > 阈值（默认 0.8）或文件路径相似，则分为一组。

示例：

```python
if similarity(msg1, msg2) > 0.8 or same_directory(files1, files2):
    cluster(commit1, commit2)
```

输出格式：

```python
[
  {"commits": ["a1b2c3", "d4e5f6"], "similarity": 0.91},
  {"commits": ["e7f8g9"], "similarity": 1.0}
]
```

---

### 4.3 合并与重写执行逻辑

执行方式：使用 **GitPython** 构建新提交链。

伪代码：

```python
def apply_merge(group, new_message):
    base = group[0]
    merged_tree = merge_diffs(group)
    new_commit = repo.create_commit(
        parent=base.parents[0],
        tree=merged_tree,
        message=new_message,
        author=base.author,
        committer=base.committer
    )
    return new_commit
```

重写顺序严格为：

> oldest → newest
> 跳过 root commit

---

### 4.4 AI 辅助重写模块

配置文件：

```yaml
llm:
  url: "https://api.openai.com/v1/chat/completions"
  api_key: "sk-xxxx"
  model: "gpt-4o-mini"
```

调用逻辑：

```python
prompt = f"""
Combine and rewrite these commit messages into one concise, conventional message:
{joined_messages}
"""
response = requests.post(
    cfg["llm"]["url"],
    headers={"Authorization": f"Bearer {cfg['llm']['api_key']}"},
    json={"model": cfg["llm"]["model"], "messages": [{"role": "user", "content": prompt}]}
)
new_message = response.json()["choices"][0]["message"]["content"].strip()
```

模板匹配（硬编码规则）：

```python
if "fix" in joined_messages.lower():
    new_message = f"fix: {new_message}"
elif "feature" in joined_messages.lower():
    new_message = f"feat: {new_message}"
```

---

### 4.5 哈希冲突避免策略

* 哈希由 `(tree, parent, message, author, timestamp)` 组成；
* 因为我们 **从最早到最新** 逐次重写，并维护新旧哈希映射；
* 每次重写都会使用**最新父节点哈希**；
* 故天然避免冲突。

---

### 4.6 安全机制

| 机制             | 说明                                      |
| -------------- | --------------------------------------- |
| **Dry-run 模式** | 模拟执行，打印计划与新 message，不修改仓库               |
| **备份分支**       | 每轮循环创建 `backup/original-{timestamp}`    |
| **断点恢复**       | 通过 `.git-ai-rewrite-map.json` 自动跳过已处理提交 |
| **完整性验证**      | 每次循环后执行 `git fsck --no-reflogs` 校验结构    |

---

## 五、命令行接口设计

```
$ git-ai-rewrite analyze
# 分析相似提交，输出分组结果

$ git-ai-rewrite run --dry-run
# 模拟循环执行，打印合并计划

$ git-ai-rewrite run --apply
# 实际执行，带状态保存与备份
```

参数选项：

```
--dry-run      仅展示操作计划，不修改仓库
--apply        实际执行修改
--threshold    相似度阈值（默认0.8）
--max-group    每组最大提交数（默认10）
```

---

## 六、数据与文件结构

```
auto_git_rewriter/
│
├── main.py
├── git_ops.py
├── ai_rewriter.py
├── cluster.py
├── state.py
├── utils.py
│
├── config.yaml
└── .git-ai-rewrite-map.json
```

---

## 七、性能与可扩展性

| 维度    | 当前实现        | 可扩展方向                  |
| ----- | ----------- | ---------------------- |
| 性能    | 线性遍历 + 简单聚类 | 启用多进程相似度计算             |
| AI 调用 | 同步单次请求      | 批量请求或本地缓存              |
| 状态管理  | JSON 文件持久化  | 可替换为 SQLite            |
| 聚类算法  | 文本/路径匹配     | TF-IDF / Embedding 相似度 |
| 历史操作  | GitPython   | 可切换低层 git CLI 执行以提升速度  |

---

## 八、安全性与可恢复性说明

1. 所有执行前自动备份当前 HEAD；
2. 每次迭代只修改一个提交组，降低风险；
3. 任何中断可通过：

   ```bash
   git reset --hard backup/original-*
   ```

   恢复至初始状态；
4. 状态表允许恢复未完成任务；
5. dry-run 模式提供完整操作预览。

---

## 九、运行示例

```bash
$ git-ai-rewrite analyze
Detected 2 similar groups:
  Group 1: [a1b2c3, d4e5f6]
  Group 2: [e7f8g9]

$ git-ai-rewrite run --dry-run
[DRY-RUN] Iteration 1
  Group: a1b2c3, d4e5f6
  Old messages:
    - fix typo in auth
    - fix more typos
  New message:
    fix: correct typos in authentication module

[DRY-RUN] Iteration 2
  Group: e7f8g9
  Old message:
    feature: add login ui
  New message:
    feat: add improved login interface

$ git-ai-rewrite run --apply
Backup created: backup/original-173955
Iteration 1 completed → new commit z9y8x7
Iteration 2 completed → new commit h1i2j3
All commits processed.
```

---

## 十、未来扩展方向

1. **多分支支持**：跨分支历史重写；
2. **提交类型识别**：自动分类（feat/fix/docs/test）；
3. **可视化对比**：集成 `rich` 展示前后差异；
4. **并行化分析**：大仓库加速；
5. **AI 摘要模式**：自动生成整个仓库的简短变更历史。

---

## 十一、总结

该项目以**极简结构 + 可恢复循环**为核心：

* **安全**：每步可回滚；
* **确定性**：严格从 oldest → newest；
* **智能**：AI 重写与相似度合并；
* **轻量**：无需服务，仅依赖本地 Git 与配置文件。

这使它不仅是一个“commit message 清洗工具”，
而是一个“可迭代地重构整个 Git 历史的自动化引擎”。
