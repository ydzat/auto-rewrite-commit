# Auto Git History Rewriter 实现计划（完整验证版）

## 技术栈

- **Python 版本**: 3.12.11
- **包管理**: uv（现代、快速的包管理工具）
- **数据库**: SQLite（轻量级、本地存储）
- **CLI 框架**: Typer（可选静默运行）
- **Git 操作**: GitPython
- **配置管理**: YAML + 环境变量
- **AI SDK**: OpenAI SDK（兼容 DeepSeek API）
- **UI 增强**: Rich（进度条、美化输出）

## 核心架构

### 1. 数据库设计（SQLite）

```sql
-- commits: 存储提交信息和 diff
CREATE TABLE commits (
    hash TEXT PRIMARY KEY,
    parent_hash TEXT,
    message TEXT,
    diff_content TEXT,      -- 存储完整 diff
    modified_files TEXT,    -- JSON 格式文件列表
    author TEXT,
    author_email TEXT,
    commit_date INTEGER,
    tree_hash TEXT,
    status TEXT DEFAULT 'pending',
    created_at INTEGER
);
CREATE INDEX idx_status ON commits(status);
CREATE INDEX idx_parent ON commits(parent_hash);

-- hash_mapping: 哈希映射
CREATE TABLE hash_mapping (
    old_hash TEXT PRIMARY KEY,
    new_hash TEXT NOT NULL,
    created_at INTEGER
);
CREATE INDEX idx_new_hash ON hash_mapping(new_hash);

-- commit_groups: 聚类分组
CREATE TABLE commit_groups (
    group_id INTEGER PRIMARY KEY AUTOINCREMENT,
    commit_hash TEXT NOT NULL,
    group_order INTEGER,
    similarity REAL,
    created_at INTEGER,
    FOREIGN KEY (commit_hash) REFERENCES commits(hash)
);
CREATE INDEX idx_group_id ON commit_groups(group_id);

-- session_state: 会话状态（单例表）
CREATE TABLE session_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    branch TEXT NOT NULL,
    backup_branch TEXT,
    current_position TEXT,
    total_commits INTEGER,
    processed_commits INTEGER,
    last_updated INTEGER
);
```

### 2. 核心模块

- `src/database.py` - 数据库管理（SQLite CRUD）
- `src/git_operations.py` - Git 操作（GitPython 封装）
- `src/clustering.py` - **基于 diff 的聚类算法**
- `src/ai_rewriter.py` - AI 重写（OpenAI SDK + 重试）
- `src/state_manager.py` - 状态管理与断点恢复
- `src/executor.py` - 核心执行引擎
- `src/main.py` - CLI 入口（Typer）
- `src/utils.py` - 工具函数

### 3. 关键逻辑设计

#### 聚类算法（修正版 - 基于 diff + 连续性）

```python
def find_groups(commits, threshold=0.8):
    if not commits:
        return
    
    group = [commits[0]]
    
    for commit in commits[1:]:
        # 1. 检查连续性
        if not is_continuous(commit, group[-1]):
            yield group
            group = [commit]
            continue
        
        # 2. 计算 diff 相似度
        similarity = calculate_diff_similarity(
            commit.diff_content,
            group[-1].diff_content
        )
        
        if similarity > threshold:
            group.append(commit)
        else:
            yield group
            group = [commit]
    
    if group:
        yield group

def is_continuous(commit_a, commit_b, mapping):
    """检查 a 的 parent 是否是 b（或其映射）"""
    if not commit_a.parents:
        return False
    parent_hash = commit_a.parents[0].hexsha
    return parent_hash in [commit_b.hash, mapping.get(commit_b.hash)]

def calculate_diff_similarity(diff1, diff2):
    """基于 diff 内容计算相似度"""
    # 方法 1: 简单文本相似度（Jaccard/余弦）
    # 方法 2: 文件路径匹配
    # 方法 3: TF-IDF 向量化（可选）
    pass
```

#### AI 输入：代码 diff（修正版）

```python
def prepare_ai_input(group):
    """准备 AI 输入：基于代码变化而非 message"""
    code_diffs = []
    for commit in group:
        code_diffs.append({
            'hash': commit.hash,
            'files': json.loads(commit.modified_files),
            'diff': commit.diff_content,
            'original_msg': commit.message  # 仅供参考
        })
    
    prompt = prompts['analyze_diff'].format(
        diff_content=format_diffs(code_diffs),
        file_list=get_all_files(code_diffs),
        original_messages=get_messages(group)
    )
    return prompt

def format_diffs(code_diffs):
    """格式化 diff 以适合 AI 输入（限制长度）"""
    formatted = []
    for item in code_diffs:
        # 限制 diff 长度，避免 token 超限
        diff_preview = item['diff'][:2000] + '...' if len(item['diff']) > 2000 else item['diff']
        formatted.append(f"Commit {item['hash'][:8]}:\n{diff_preview}")
    return '\n\n'.join(formatted)
```

#### 父节点映射（处理 root commit 和 merge commit）

```python
def get_new_parents(commit, mapping):
    """获取新的父节点哈希"""
    if not commit.parents:  # root commit
        return []
    
    new_parents = []
    for parent in commit.parents:
        # 如果父节点已被重写，使用新哈希
        if parent.hexsha in mapping:
            new_parents.append(mapping[parent.hexsha])
        else:
            new_parents.append(parent.hexsha)
    return new_parents

def create_merged_commit(group, new_message, mapping):
    """创建合并后的新 commit"""
    # 获取第一个 commit 的 parents（经过映射）
    parents = get_new_parents(group[0], mapping)
    
    # 构建合并的 tree（最新覆盖）
    merged_tree = build_merged_tree(group)
    
    # 创建新 commit
    new_commit = repo.create_commit(
        tree=merged_tree,
        parents=parents,
        message=new_message,
        author=group[0].author,
        committer=group[0].committer
    )
    return new_commit
```

#### AI 重试与降级策略

```python
class AIRewriter:
    def rewrite_with_retry(self, prompt, max_retries=3):
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.config['model'],
                    messages=[{'role': 'user', 'content': prompt}],
                    temperature=self.config['temperature'],
                    max_tokens=self.config['max_tokens']
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                logger.warning(f"AI API 失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    return self.fallback_generate(prompt)
                time.sleep(2 ** attempt)  # 指数退避
    
    def fallback_generate(self, prompt):
        """降级策略：基于规则生成"""
        # 提取关键词，简单分类
        if 'fix' in prompt.lower() or 'bug' in prompt.lower():
            return "fix: update code"
        elif 'feature' in prompt.lower() or 'add' in prompt.lower():
            return "feat: add new feature"
        return "chore: update files"
```

### 4. 完整执行流程

```
1. 初始化
   ├─ 加载 config.yaml
   ├─ 切换到目标仓库路径
   ├─ 检查仓库状态（is_dirty、远程同步）
   ├─ 初始化数据库
   └─ 检查断点恢复

2. 备份（首次运行）
   ├─ 创建 backup/{branch}-{timestamp}
   ├─ 保存到 session_state
   └─ 提示用户备份分支

3. 扫描
   ├─ 获取 commits（oldest→newest）
   ├─ 提取 diff 和文件列表
   └─ 保存到 commits 表

4. 聚类
   ├─ 基于 diff 计算相似度
   ├─ 应用连续性约束
   └─ 生成 commit_groups

5. 执行循环
   ├─ 显示进度条
   ├─ For each group:
   │  ├─ 准备 AI 输入（diff）
   │  ├─ AI 生成 message（带重试）
   │  ├─ 合并/重写 commit
   │  ├─ 更新映射表
   │  └─ 保存 checkpoint
   └─ Dry-run 仅打印

6. 验证
   ├─ git fsck --no-reflogs
   ├─ 对比新旧分支
   └─ 提示回滚命令
```

### 5. 配置文件（config.yaml）

```yaml
repository:
  path: "/path/to/repo"
  branch: "main"

backup:
  auto_create: true
  naming_pattern: "backup/{branch}-{timestamp}"

clustering:
  similarity_threshold: 0.8
  max_group_size: 10
  require_continuity: true
  diff_based: true

ai:
  provider: "deepseek"
  api_key: "${DEEPSEEK_API_KEY}"
  base_url: "https://api.deepseek.com/v1"
  model: "deepseek-chat"
  temperature: 0.3
  max_tokens: 1000

database:
  path: ".git-rewrite.db"

safety:
  check_clean_repo: true
  check_remote_sync: false
  verify_integrity: true
  dry_run_default: true

prompts:
  analyze_diff: |
    分析以下代码变化，生成一个简洁、规范的 conventional commit message：
    
    代码变化：
    {diff_content}
    
    修改的文件：
    {file_list}
    
    原始 commit message（仅供参考）：
    {original_messages}
    
    要求：
    1. 使用 conventional commit 格式（feat/fix/refactor/docs等）
    2. 描述实际代码改动，而非原始 message
    3. 简洁明了，一行为主
```

### 6. 项目结构与依赖（uv）

```
auto-rewrite-commit/
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── executor.py
│   ├── database.py
│   ├── git_operations.py
│   ├── clustering.py
│   ├── ai_rewriter.py
│   ├── state_manager.py
│   └── utils.py
├── tests/
│   ├── test_clustering.py
│   ├── test_git_ops.py
│   └── test_executor.py
├── config.yaml
├── pyproject.toml
├── README.md
└── design.md
```

**pyproject.toml**:

```toml
[project]
name = "auto-rewrite-commit"
version = "0.1.0"
description = "AI-powered Git history rewriter"
requires-python = ">=3.12,<3.13"
dependencies = [
    "gitpython>=3.1.40",
    "typer>=0.9.0",
    "pyyaml>=6.0",
    "openai>=1.0.0",
    "rich>=13.0.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pytest>=7.4.0",
    "pytest-cov>=4.1.0",
]
```

### 7. CLI 命令（完整版）

```bash
# 初始化项目（uv）
uv venv
source .venv/bin/activate
uv pip install -e .

# 分析相似提交
python -m src.main analyze

# Dry-run 模式
python -m src.main run --dry-run

# 实际执行
python -m src.main run --apply

# 从断点恢复
python -m src.main resume

# 查看状态
python -m src.main status

# 列出备份分支
python -m src.main list-backups

# 回滚
python -m src.main rollback --backup backup/main-20251015-153000
```

### 8. 测试用例

```python
# tests/test_clustering.py
def test_continuous_commits():
    """测试连续提交聚类"""

def test_non_continuous_separated():
    """测试非连续提交被分开"""

def test_diff_similarity():
    """测试 diff 相似度计算"""

# tests/test_git_ops.py
def test_merge_commits():
    """测试提交合并"""

def test_backup_creation():
    """测试备份分支创建"""

def test_parent_mapping():
    """测试父节点映射（含 root commit）"""

def test_root_commit_handling():
    """测试 root commit 处理"""

# tests/test_executor.py
def test_dry_run_no_changes():
    """测试 dry-run 不修改仓库"""

def test_resume_from_checkpoint():
    """测试断点恢复"""

def test_ai_retry_mechanism():
    """测试 AI 重试机制"""

def test_fallback_strategy():
    """测试降级策略"""
```

## 关键风险与应对

1. **非连续提交合并** → 聚类算法强制连续性检查
2. **数据库并发** → SQLite 事务原子化
3. **AI API 失败** → 3次重试 + 降级策略
4. **大仓库性能** → 分批处理 + 索引优化
5. **diff 内容过长** → 截断处理（前 2000 字符）
6. **Root commit** → 特殊处理（无 parent）
7. **Merge commit** → 保留多个 parent

## 实现检查清单

- [ ] 使用 uv 初始化项目（Python 3.12.11）
- [ ] 创建 pyproject.toml 配置文件
- [ ] 实现数据库模块（含 diff_content 字段）
- [ ] 实现配置加载（YAML + 环境变量）
- [ ] 实现 Git 操作（提取 diff、备份、合并）
- [ ] 实现聚类算法（修正版：首元素处理）
- [ ] 实现 AI 模块（重试 + 降级）
- [ ] 实现状态管理（断点恢复）
- [ ] 实现执行引擎（完整流程）
- [ ] 实现 CLI（所有命令）
- [ ] 添加进度显示（rich 库）
- [ ] 编写测试用例（覆盖边界情况）
- [ ] 完善文档