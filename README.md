# Auto Git History Rewriter

一个轻量级、AI 辅助的 Git 历史重写工具，支持自动聚类、合并提交、状态恢复和安全回滚。

## ✨ 特性

- **🤖 AI 辅助重写**: 基于代码 diff 内容生成规范的 conventional commit message
- **🔗 智能聚类**: 基于代码相似度和连续性约束自动合并相关提交
- **💾 状态持久化**: SQLite 数据库存储，支持断点恢复
- **🛡️ 安全机制**: dry-run 模式、自动备份、完整性验证
- **📊 进度追踪**: 实时显示处理进度和统计信息
- **🔄 可恢复**: 支持中断后继续执行

## 🚀 快速开始

### 安装

使用 uv 管理依赖：

```bash
# 克隆项目
git clone <repository-url>
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
- 基于代码 diff 内容计算相似度
- 应用连续性约束（只合并连续的提交）
- 生成提交分组

### 3. 执行阶段
- 对每个分组：
  - 单个提交：AI 重写 commit message
  - 多个提交：合并 + AI 生成新 message
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
│ 总分组数    │ 5     │
│ 总提交数    │ 12    │
│ 单个提交    │ 3     │
│ 合并分组    │ 2     │
│ 平均分组大小│ 2.4   │
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