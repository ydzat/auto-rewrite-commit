"""通用工具函数模块."""

import os
import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime


def setup_logging(level: str = "INFO") -> logging.Logger:
    """设置日志配置."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger(__name__)


def get_timestamp() -> str:
    """获取当前时间戳字符串."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def safe_json_loads(data: str, default: Any = None) -> Any:
    """安全地解析 JSON 字符串."""
    try:
        return json.loads(data) if data else default
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_dumps(data: Any) -> str:
    """安全地序列化为 JSON 字符串."""
    try:
        return json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    except (TypeError, ValueError):
        return "{}"


def truncate_text(text: str, max_length: int = 2000) -> str:
    """截断文本到指定长度."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def format_file_list(files: List[str]) -> str:
    """格式化文件列表为可读字符串."""
    if not files:
        return "无文件修改"
    
    if len(files) <= 5:
        return ", ".join(files)
    
    return f"{', '.join(files[:5])} 等 {len(files)} 个文件"


def ensure_directory(path: str) -> None:
    """确保目录存在."""
    os.makedirs(path, exist_ok=True)


def get_relative_path(absolute_path: str, base_path: str) -> str:
    """获取相对路径."""
    try:
        return os.path.relpath(absolute_path, base_path)
    except ValueError:
        return absolute_path


def validate_git_repo(path: str) -> bool:
    """验证路径是否为有效的 Git 仓库."""
    git_dir = os.path.join(path, '.git')
    return os.path.exists(git_dir) and os.path.isdir(git_dir)


def calculate_text_similarity(text1: str, text2: str) -> float:
    """计算两个文本的简单相似度（Jaccard 相似度）."""
    if not text1 or not text2:
        return 0.0
    
    # 转换为小写并分词
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    
    if not words1 and not words2:
        return 1.0
    
    intersection = len(words1.intersection(words2))
    union = len(words1.union(words2))
    
    return intersection / union if union > 0 else 0.0


def calculate_path_similarity(paths1: List[str], paths2: List[str]) -> float:
    """计算文件路径列表的相似度."""
    if not paths1 or not paths2:
        return 0.0
    
    # 提取目录结构
    dirs1 = set()
    dirs2 = set()
    
    for path in paths1:
        dirs1.add(os.path.dirname(path))
    
    for path in paths2:
        dirs2.add(os.path.dirname(path))
    
    if not dirs1 and not dirs2:
        return 1.0
    
    intersection = len(dirs1.intersection(dirs2))
    union = len(dirs1.union(dirs2))
    
    return intersection / union if union > 0 else 0.0
