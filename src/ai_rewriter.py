"""AI 重写模块 - OpenAI SDK 集成."""

import time
import logging
from typing import List, Dict, Any, Optional

from openai import OpenAI

from .utils import truncate_text, format_file_list, safe_json_loads

logger = logging.getLogger(__name__)


class AIRewriter:
    """AI 重写器."""
    
    def __init__(self, config: Dict[str, Any]):
        """初始化 AI 重写器.
        
        Args:
            config: AI 配置
        """
        self.config = config
        self.client = None
        self._init_client()
    
    def _init_client(self) -> None:
        """初始化 OpenAI 客户端."""
        try:
            self.client = OpenAI(
                api_key=self.config.get('api_key'),
                base_url=self.config.get('base_url', 'https://api.openai.com/v1')
            )
            logger.info("OpenAI 客户端初始化成功")
        except Exception as e:
            logger.error(f"OpenAI 客户端初始化失败: {e}")
            raise
    
    def rewrite_single_commit(self, commit_data: Dict[str, Any], 
                            prompt_template: str) -> str:
        """重写单个提交的 message.
        
        Args:
            commit_data: 提交数据
            prompt_template: 提示词模板
            
        Returns:
            新的 commit message
        """
        # 准备 AI 输入
        diff_content = commit_data.get('diff_content', '')
        modified_files = safe_json_loads(commit_data.get('modified_files', '[]'), [])
        original_message = commit_data.get('message', '')
        
        # 格式化输入
        formatted_diff = self._format_single_diff(diff_content)
        file_list = format_file_list(modified_files)
        
        # 构建 prompt
        prompt = prompt_template.format(
            diff_content=formatted_diff,
            file_list=file_list,
            original_messages=original_message
        )
        
        # 调用 AI
        return self._call_ai_with_retry(prompt)
    
    def merge_commit_messages(self, group: List[Dict[str, Any]], 
                            prompt_template: str) -> str:
        """合并多个提交的 message.
        
        Args:
            group: 提交分组
            prompt_template: 提示词模板
            
        Returns:
            合并后的 commit message
        """
        # 准备 AI 输入
        formatted_diffs = []
        all_files = set()
        original_messages = []
        
        for commit in group:
            diff_content = commit.get('diff_content', '')
            modified_files = safe_json_loads(commit.get('modified_files', '[]'), [])
            original_message = commit.get('message', '')
            
            # 格式化 diff
            formatted_diff = self._format_single_diff(diff_content, commit['hash'][:8])
            formatted_diffs.append(formatted_diff)
            
            # 收集文件
            all_files.update(modified_files)
            
            # 收集原始消息
            original_messages.append(original_message)
        
        # 构建 prompt
        prompt = prompt_template.format(
            diff_content='\n\n'.join(formatted_diffs),
            file_list=format_file_list(list(all_files)),
            original_messages='\n'.join(original_messages)
        )
        
        # 调用 AI
        return self._call_ai_with_retry(prompt)
    
    def _format_single_diff(self, diff_content: str, commit_hash: str = None) -> str:
        """格式化单个 diff 内容.
        
        Args:
            diff_content: diff 内容
            commit_hash: 提交哈希（可选）
            
        Returns:
            格式化后的 diff
        """
        if not diff_content:
            return "无代码变化"
        
        # 截断过长的 diff
        truncated_diff = truncate_text(diff_content, 2000)
        
        if commit_hash:
            return f"Commit {commit_hash}:\n{truncated_diff}"
        else:
            return truncated_diff
    
    def _call_ai_with_retry(self, prompt: str, max_retries: int = 3) -> str:
        """调用 AI API 并重试.
        
        Args:
            prompt: 提示词
            max_retries: 最大重试次数
            
        Returns:
            AI 响应内容
        """
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.get('model', 'gpt-3.5-turbo'),
                    messages=[{'role': 'user', 'content': prompt}],
                    temperature=self.config.get('temperature', 0.3),
                    max_tokens=self.config.get('max_tokens', 1000)
                )
                
                result = response.choices[0].message.content.strip()
                logger.info(f"AI 调用成功 (尝试 {attempt + 1})")
                return result
                
            except Exception as e:
                logger.warning(f"AI API 失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                
                if attempt == max_retries - 1:
                    # 最后一次尝试失败，使用降级策略
                    return self._fallback_generate(prompt)
                
                # 指数退避
                time.sleep(2 ** attempt)
        
        return self._fallback_generate(prompt)
    
    def _fallback_generate(self, prompt: str) -> str:
        """降级策略：基于规则生成 commit message.
        
        Args:
            prompt: 原始提示词
            
        Returns:
            生成的 commit message
        """
        logger.info("使用降级策略生成 commit message")
        
        # 简单的关键词匹配
        prompt_lower = prompt.lower()
        
        if any(keyword in prompt_lower for keyword in ['fix', 'bug', 'error', 'issue']):
            return "fix: resolve issues"
        elif any(keyword in prompt_lower for keyword in ['feature', 'add', 'new', 'implement']):
            return "feat: add new feature"
        elif any(keyword in prompt_lower for keyword in ['refactor', 'clean', 'improve']):
            return "refactor: improve code"
        elif any(keyword in prompt_lower for keyword in ['doc', 'readme', 'comment']):
            return "docs: update documentation"
        elif any(keyword in prompt_lower for keyword in ['test', 'spec']):
            return "test: add tests"
        elif any(keyword in prompt_lower for keyword in ['style', 'format', 'lint']):
            return "style: format code"
        else:
            return "chore: update files"
    
    def apply_conventional_format(self, message: str) -> str:
        """应用 conventional commit 格式.
        
        Args:
            message: 原始消息
            
        Returns:
            格式化后的消息
        """
        message = message.strip()
        
        # 如果已经是 conventional 格式，直接返回
        conventional_types = ['feat', 'fix', 'docs', 'style', 'refactor', 
                            'test', 'chore', 'perf', 'ci', 'build', 'revert']
        
        for prefix in conventional_types:
            if message.lower().startswith(f"{prefix}:"):
                return message
        
        # 如果不是 conventional 格式，尝试添加前缀
        message_lower = message.lower()
        
        if any(keyword in message_lower for keyword in ['fix', 'bug', 'error']):
            return f"fix: {message}"
        elif any(keyword in message_lower for keyword in ['feature', 'add', 'new']):
            return f"feat: {message}"
        elif any(keyword in message_lower for keyword in ['refactor', 'clean']):
            return f"refactor: {message}"
        elif any(keyword in message_lower for keyword in ['doc', 'readme']):
            return f"docs: {message}"
        elif any(keyword in message_lower for keyword in ['test']):
            return f"test: {message}"
        else:
            return f"chore: {message}"
    
    def validate_message(self, message: str) -> bool:
        """验证 commit message 的有效性.
        
        Args:
            message: commit message
            
        Returns:
            是否有效
        """
        if not message or not message.strip():
            return False
        
        # 检查长度
        if len(message) > 100:
            logger.warning(f"Commit message 过长: {len(message)} 字符")
            return False
        
        # 检查是否包含换行符（conventional commit 通常是一行）
        if '\n' in message:
            logger.warning("Commit message 包含换行符")
            return False
        
        return True
    
    def get_ai_stats(self) -> Dict[str, Any]:
        """获取 AI 使用统计.
        
        Returns:
            统计信息
        """
        # 这里可以添加统计逻辑，比如调用次数、成功率等
        return {
            'model': self.config.get('model'),
            'provider': self.config.get('provider'),
            'base_url': self.config.get('base_url')
        }
