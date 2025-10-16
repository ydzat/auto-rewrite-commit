"""配置管理模块."""

import os
import yaml
import logging
from typing import Any, Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# 启用调试日志
logging.getLogger('src.git_operations').setLevel(logging.DEBUG)
logging.getLogger('src.database').setLevel(logging.DEBUG)


class ConfigManager:
    """配置管理器."""
    
    def __init__(self, config_path: str = "config.yaml"):
        """初始化配置管理器.
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self._config: Optional[Dict[str, Any]] = None
        self.load_config()
    
    def load_config(self) -> None:
        """加载配置文件."""
        if not self.config_path.exists():
            logger.warning(f"配置文件不存在: {self.config_path}")
            self._config = self._get_default_config()
            return
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f)
            
            # 处理环境变量替换
            self._config = self._substitute_env_vars(self._config)
            
            logger.info(f"配置文件加载成功: {self.config_path}")
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            self._config = self._get_default_config()
    
    def _substitute_env_vars(self, config: Any) -> Any:
        """递归替换配置中的环境变量.
        
        Args:
            config: 配置对象
            
        Returns:
            替换后的配置对象
        """
        if isinstance(config, dict):
            return {k: self._substitute_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._substitute_env_vars(item) for item in config]
        elif isinstance(config, str) and config.startswith('${') and config.endswith('}'):
            # 处理 ${VAR_NAME} 格式
            env_var = config[2:-1]
            return os.getenv(env_var, config)
        else:
            return config
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置."""
        return {
            'repository': {
                'path': '.',
                'branch': 'main'
            },
            'backup': {
                'auto_create': True,
                'naming_pattern': 'backup/{branch}-{timestamp}'
            },
            'clustering': {
                'similarity_threshold': 0.8,
                'max_group_size': 10,
                'require_continuity': True,
                'diff_based': True
            },
            'ai': {
                'provider': 'deepseek',
                'api_key': '',
                'base_url': 'https://api.deepseek.com/v1',
                'model': 'deepseek-chat',
                'temperature': 0.3,
                'max_tokens': 1000
            },
            'database': {
                'path': '.git-rewrite.db'
            },
            'safety': {
                'check_clean_repo': True,
                'check_remote_sync': False,
                'verify_integrity': True,
                'dry_run_default': True
            },
            'prompts': {
                'analyze_diff': """分析以下代码变化，生成一个简洁、规范的 conventional commit message：

代码变化：
{diff_content}

修改的文件：
{file_list}

原始 commit message（仅供参考）：
{original_messages}

要求：
1. 使用 conventional commit 格式（feat/fix/refactor/docs等）
2. 描述实际代码改动，而非原始 message
3. 简洁明了，一行为主"""
            }
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值.
        
        Args:
            key: 配置键，支持点号分隔的嵌套键
            default: 默认值
            
        Returns:
            配置值
        """
        if self._config is None:
            return default
        
        keys = key.split('.')
        value = self._config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_repository_path(self) -> str:
        """获取仓库路径."""
        return self.get('repository.path', '.')
    
    def get_repository_branch(self) -> str:
        """获取仓库分支."""
        return self.get('repository.branch', 'main')
    
    def get_database_path(self) -> str:
        """获取数据库路径."""
        # 数据库文件应该在本项目目录中，而不是目标仓库目录中
        # 这样可以避免干扰目标仓库的 Git 操作
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_name = self.get('database.path', '.git-rewrite.db')
        return os.path.join(project_dir, db_name)
    
    def get_ai_config(self) -> Dict[str, Any]:
        """获取 AI 配置."""
        return self.get('ai', {})
    
    def get_clustering_config(self) -> Dict[str, Any]:
        """获取聚类配置."""
        return self.get('clustering', {})
    
    def get_safety_config(self) -> Dict[str, Any]:
        """获取安全配置."""
        return self.get('safety', {})
    
    def get_backup_config(self) -> Dict[str, Any]:
        """获取备份配置."""
        return self.get('backup', {})
    
    def get_prompts(self) -> Dict[str, str]:
        """获取提示词模板."""
        return self.get('prompts', {})
    
    def validate_config(self) -> bool:
        """验证配置的有效性.
        
        Returns:
            配置是否有效
        """
        if not self._config:
            logger.error("配置未加载")
            return False
        
        # 检查必需的配置项
        required_keys = [
            'repository.path',
            'ai.api_key',
            'database.path'
        ]
        
        for key in required_keys:
            if not self.get(key):
                logger.error(f"缺少必需的配置项: {key}")
                return False
        
        # 检查仓库路径
        repo_path = self.get_repository_path()
        if not os.path.exists(repo_path):
            logger.error(f"仓库路径不存在: {repo_path}")
            return False
        
        # 检查 AI API Key
        api_key = self.get('ai.api_key')
        if not api_key:
            logger.error("AI API Key 未配置")
            return False
        
        logger.info("配置验证通过")
        return True
    
    def save_config(self) -> None:
        """保存配置到文件."""
        if not self._config:
            logger.error("没有配置可保存")
            return
        
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self._config, f, default_flow_style=False, 
                         allow_unicode=True, indent=2)
            logger.info(f"配置已保存到: {self.config_path}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
    
    def update_config(self, key: str, value: Any) -> None:
        """更新配置值.
        
        Args:
            key: 配置键
            value: 新值
        """
        if not self._config:
            self._config = {}
        
        keys = key.split('.')
        config = self._config
        
        # 导航到目标位置
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        # 设置值
        config[keys[-1]] = value
        logger.info(f"配置已更新: {key} = {value}")
    
    def get_all_config(self) -> Dict[str, Any]:
        """获取所有配置.
        
        Returns:
            完整配置字典
        """
        return self._config or {}
