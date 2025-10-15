#!/usr/bin/env python3
"""Auto Git Rewriter 使用示例."""

import os
import tempfile
import subprocess
from pathlib import Path

def create_test_repo():
    """创建一个测试 Git 仓库."""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    print(f"创建测试仓库: {temp_dir}")
    
    # 初始化 Git 仓库
    subprocess.run(["git", "init"], cwd=temp_dir, check=True)
    
    # 创建一些文件并提交
    files_and_commits = [
        ("file1.txt", "Hello World", "Initial commit"),
        ("file2.txt", "Feature code", "Add feature"),
        ("file1.txt", "Hello World\nMore content", "Update file1"),
        ("file2.txt", "Feature code\nBug fix", "Fix bug in feature"),
        ("file3.txt", "New feature", "Add new feature"),
        ("file1.txt", "Hello World\nMore content\nFinal update", "Final update to file1"),
    ]
    
    for filename, content, message in files_and_commits:
        file_path = Path(temp_dir) / filename
        file_path.write_text(content)
        
        subprocess.run(["git", "add", filename], cwd=temp_dir, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=temp_dir, check=True)
    
    return temp_dir

def create_config(repo_path, api_key="test-key"):
    """创建配置文件."""
    config_content = f"""repository:
  path: "{repo_path}"
  branch: "main"

backup:
  auto_create: true
  naming_pattern: "backup/{{branch}}-{{timestamp}}"

clustering:
  similarity_threshold: 0.8
  max_group_size: 10
  require_continuity: true
  diff_based: true

ai:
  provider: "deepseek"
  api_key: "{api_key}"
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
    {{diff_content}}
    
    修改的文件：
    {{file_list}}
    
    原始 commit message（仅供参考）：
    {{original_messages}}
    
    要求：
    1. 使用 conventional commit 格式（feat/fix/refactor/docs等）
    2. 描述实际代码改动，而非原始 message
    3. 简洁明了，一行为主
"""
    
    config_path = "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config_content)
    
    return config_path

def main():
    """主函数."""
    print("🚀 Auto Git Rewriter 使用示例")
    print("=" * 50)
    
    # 1. 创建测试仓库
    repo_path = create_test_repo()
    print(f"✓ 测试仓库已创建: {repo_path}")
    
    # 2. 创建配置文件
    config_path = create_config(repo_path)
    print(f"✓ 配置文件已创建: {config_path}")
    
    # 3. 显示使用说明
    print("\n📋 使用说明:")
    print("1. 首先分析相似提交:")
    print(f"   python -m src.main analyze --config {config_path}")
    print("\n2. Dry-run 模式预览:")
    print(f"   python -m src.main run --dry-run --config {config_path}")
    print("\n3. 实际执行 (需要有效的 API Key):")
    print(f"   python -m src.main run --apply --config {config_path}")
    print("\n4. 查看状态:")
    print(f"   python -m src.main status --config {config_path}")
    print("\n5. 列出备份分支:")
    print(f"   python -m src.main list-backups --config {config_path}")
    
    print(f"\n📁 测试仓库位置: {repo_path}")
    print("💡 提示: 请将配置文件中的 API Key 替换为真实的 DeepSeek API Key")
    
    return repo_path, config_path

if __name__ == "__main__":
    main()
