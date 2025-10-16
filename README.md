# Auto Git History Rewriter

> [!WARNING]
> ## ⚠️ 重要警告
>
> **提交时间丢失**: 使用本工具重写 Git 历史时，原始提交的时间戳将会丢失。这是因为工具会创建新的提交来替换原有提交。
>
> **LLM 配置说明**:
> - 本程序默认使用 DeepSeek LLM，通过 OpenAI 兼容 API 调用
> - 如需使用其他 LLM 提供商，请手动编辑 `config.yaml` 配置文件
> - ⚠️ **重要**: 本程序未对其他 LLM 进行测试和适配。如果其他 LLM 的返回结果格式与预期不符，可能导致程序出错
>
> **Token 限制注意**: 请注意所选 LLM 的最大上下文长度限制。如果单个提交的 diff 内容过长（超出 LLM 的 token 限制），可能会导致 API 调用失败或结果异常。
>
> **合并功能说明**（当前有BUG）: 程序默认禁用提交合并功能（`disable_merging: true`），所有提交都会作为单个提交处理。如需启用智能合并，请将配置中的 `disable_merging` 设置为 `false`，但请注意合并功能可能在某些仓库中导致问题。
>
> **安全提醒**: 虽然本程序会自动创建备份分支，但仍强烈建议您在使用前手动备份重要代码，以确保数据安全。
>
> ## 🚨 数据丢失风险警告
>
> **⚠️ 强烈警告：本工具可能导致文件丢失！**
>
> 尽管本工具实现了多种安全机制，但在某些情况下仍可能发生数据丢失：
>
> ### 已知风险场景：
> - **分支合并冲突**: 如果仓库历史包含复杂的分支合并，自动冲突解决可能导致文件被意外删除或覆盖
> - **二进制文件冲突**: 大文件或二进制文件的冲突处理可能导致数据损坏
> - **未跟踪文件**: 工作目录中的未跟踪文件可能在重写过程中丢失
> - **中断恢复**: 如果程序在执行过程中被强制中断，可能导致仓库处于不一致状态
>
> ### 📋 强制安全措施：
> 1. **必须手动备份**: 在运行本工具前，请手动备份整个项目目录到安全位置
> 2. **测试环境优先**: 强烈建议先在项目的副本或测试仓库中试用
> 3. **验证备份**: 确认备份文件完整且可恢复
> 4. **避免生产环境**: 不要在生产环境或重要项目的原始仓库上直接运行
>
> ### 💾 备份机制说明：
> - 工具会在项目根目录创建 `git-rewrite-backup-{timestamp}` 文件夹
> - 备份包含工作目录中所有未跟踪和修改的文件
> - **重要**: 备份文件不会被自动删除，请手动检查和清理
> - 如果执行失败，备份文件将保留在项目根目录中供手动恢复使用
>
> ### 🔄 恢复建议：
> - 如果发生问题，首先检查项目根目录的备份文件夹
> - 可以使用 `git reflog` 查看操作历史
> - 必要时从备份分支恢复：`git reset --hard backup/main-YYYYMMDD-HHMMSS`
> - 最安全的方法是从头重新克隆仓库并手动恢复备份文件

一个轻量级、AI 辅助的 Git 历史重写工具，支持自动聚类、合并提交、状态恢复和安全回滚。

## ✨ 特性

- **🤖 AI 辅助重写**: 基于代码 diff 内容生成规范的 conventional commit message
- **🔗 智能聚类**: 基于代码相似度和连续性约束自动合并相关提交（默认禁用，可通过配置启用）
- **💾 状态持久化**: SQLite 数据库存储，支持断点恢复
- **🛡️ 安全机制**: dry-run 模式、自动备份、完整性验证
- **📊 进度追踪**: 实时显示处理进度和统计信息
- **🔄 可恢复**: 支持中断后继续执行

## 🚀 快速开始

### 安装

使用 uv 管理依赖：

```bash
# 克隆项目
git clone https://github.com/ydzat/auto-rewrite-commit.git
cd auto-rewrite-commit

# 创建虚拟环境
uv venv
source .venv/bin/activate  # Linux/Mac
# 或 .venv\Scripts\activate  # Windows

# 安装依赖
uv pip install -e .
```

### 配置

1. **初始化配置**：

```bash
# 初始化配置文件
python -m src.main init /path/to/your/repo --api-key your-deepseek-api-key
```

2. **编辑配置文件** `config.yaml`：

```yaml
repository:
  path: "/path/to/your/repo"
  branch: "main"

ai:
  provider: "deepseek"
  api_key: "your-api-key"
  base_url: "https://api.deepseek.com/v1"
  model: "deepseek-chat"

clustering:
  similarity_threshold: 0.8
  max_group_size: 10
  require_continuity: true
  disable_merging: true
```

### 使用

```bash
# 分析相似提交（不修改仓库）
python -m src.main analyze

# Dry-run 模式（预览修改）
python -m src.main run --dry-run

# 实际执行
python -m src.main run --apply

# 查看状态
python -m src.main status

# 从断点恢复
python -m src.main resume

# 列出备份分支
python -m src.main list-backups

# 回滚到备份
python -m src.main rollback backup/main-20250115-120000
```

## 📋 命令详解

### `analyze`
分析提交相似度，显示聚类结果，不修改仓库。

```bash
python -m src.main analyze [OPTIONS]

Options:
  -c, --config PATH     配置文件路径 [default: config.yaml]
  -t, --threshold FLOAT 相似度阈值 [default: 0.8]
  -g, --max-group INT   最大分组大小 [default: 10]
```

### `run`
执行 Git 历史重写。

```bash
python -m src.main run [OPTIONS]

Options:
  --apply              实际执行修改（默认为 dry-run）
  -c, --config PATH    配置文件路径 [default: config.yaml]
  -t, --threshold FLOAT 相似度阈值 [default: 0.8]
  -g, --max-group INT   最大分组大小 [default: 10]
```

### `resume`
从断点恢复执行。

```bash
python -m src.main resume [OPTIONS]

Options:
  -c, --config PATH    配置文件路径 [default: config.yaml]
```

### `status`
查看当前处理状态。

```bash
python -m src.main status [OPTIONS]

Options:
  -c, --config PATH    配置文件路径 [default: config.yaml]
```

### `list-backups`
列出所有备份分支。

```bash
python -m src.main list-backups [OPTIONS]

Options:
  -c, --config PATH    配置文件路径 [default: config.yaml]
```

### `rollback`
回滚到指定的备份分支。

```bash
python -m src.main rollback BACKUP [OPTIONS]

Arguments:
  BACKUP               备份分支名称

Options:
  -c, --config PATH    配置文件路径 [default: config.yaml]
```

## ⚙️ 配置说明

### 仓库配置
```yaml
repository:
  path: "/path/to/repo"    # 目标仓库路径
  branch: "main"           # 要处理的分支
```

### 备份配置
```yaml
backup:
  auto_create: true                              # 自动创建备份
  naming_pattern: "backup/{branch}-{timestamp}"  # 备份分支命名模式
```

### 聚类配置
```yaml
clustering:
  similarity_threshold: 0.8    # 相似度阈值 (0.0-1.0)
  max_group_size: 10          # 最大分组大小
  require_continuity: true    # 强制连续性约束
  diff_based: true           # 基于 diff 内容聚类
  disable_merging: true      # 禁用提交合并（默认 true，推荐设置）
```

### AI 配置
```yaml
ai:
  provider: "deepseek"                    # AI 提供商
  api_key: "${DEEPSEEK_API_KEY}"         # API 密钥（支持环境变量）
  base_url: "https://api.deepseek.com/v1" # API 基础 URL
  model: "deepseek-chat"                  # 模型名称
  temperature: 0.3                        # 温度参数
  max_tokens: 1000                       # 最大 token 数
```

### 安全配置
```yaml
safety:
  check_clean_repo: true     # 检查仓库是否干净
  check_remote_sync: false   # 检查与远程同步
  verify_integrity: true     # 验证仓库完整性
  dry_run_default: true      # 默认 dry-run 模式
```

## 🔧 工作原理

### 1. 扫描阶段
- 获取指定分支的所有提交（按时间排序）
- 提取每个提交的 diff 内容和修改文件列表
- 保存到 SQLite 数据库

### 2. 聚类阶段
- 基于代码 diff 内容计算相似度（默认禁用）
- 应用连续性约束（只合并连续的提交）
- 生成提交分组（默认每个提交单独分组）

### 3. 执行阶段
- 对每个分组：
  - 单个提交：AI 重写 commit message（当前默认行为）
  - 多个提交：合并 + AI 生成新 message（需要启用合并功能）
- 更新哈希映射表
- 保存检查点

### 4. 验证阶段
- 执行 `git fsck` 验证仓库完整性
- 显示处理统计信息
- 提供回滚命令

## 🛡️ 安全机制

### 自动备份
- 执行前自动创建备份分支：`backup/{branch}-{timestamp}`
- 支持一键回滚：`git reset --hard backup/main-20250115-120000`

### Dry-run 模式
- 默认 dry-run 模式，只显示修改计划
- 使用 `--apply` 参数才实际修改仓库

### 状态恢复
- SQLite 数据库持久化状态
- 支持中断后继续执行
- 自动跳过已处理的提交

### 完整性验证
- 执行后自动验证仓库完整性
- 检查哈希映射一致性

## 📊 输出示例

### 分析结果
```
聚类统计
┌─────────────┬──────┐
│ 项目        │ 数量  │
├─────────────┼──────┤
│ 总分组数    │ 12    │
│ 总提交数    │ 12    │
│ 单个提交    │ 12    │
│ 合并分组    │ 0     │
│ 平均分组大小│ 1.0   │
└─────────────┴──────┘
```

### 执行进度
```
处理提交分组... ████████████████████ 100% 00:02:15
✓ 重写执行完成
```

### 最终统计
```
处理统计
┌─────────────┬──────┐
│ 项目        │ 数量  │
├─────────────┼──────┤
│ 总提交数    │ 12    │
│ 已处理      │ 12    │
│ 进度        │ 100%  │
│ 状态: merged│ 8     │
│ 状态: done  │ 4     │
└─────────────┴──────┘
```

## 🧪 测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_clustering.py

# 生成覆盖率报告
pytest --cov=src --cov-report=html
```

## 🤝 贡献

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 打开 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## ⚠️ 注意事项

1. **备份重要**: 使用前请确保重要数据已备份
2. **测试环境**: 建议先在测试仓库中验证效果
3. **API 费用**: AI 调用可能产生费用，请注意使用量
4. **大仓库**: 对于大型仓库，处理时间可能较长
5. **网络依赖**: 需要网络连接调用 AI API

## 🐛 问题反馈

如果遇到问题，请：

1. 检查配置文件是否正确
2. 确认 API 密钥有效
3. 查看日志输出
4. 提交 Issue 并附上错误信息

## 📚 更多信息

- [设计文档](design.md) - 详细的技术设计说明
- [API 文档](docs/api.md) - 内部 API 参考
- [常见问题](docs/faq.md) - 常见问题解答