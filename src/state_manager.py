"""状态管理模块 - 断点恢复和映射表管理."""

import logging
from typing import Dict, Any, Optional, List

from .database import DatabaseManager

logger = logging.getLogger(__name__)


class StateManager:
    """状态管理器."""
    
    def __init__(self, db_manager: DatabaseManager):
        """初始化状态管理器.
        
        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self._current_state = None
    
    def can_resume(self) -> bool:
        """检查是否可以恢复会话.
        
        Returns:
            是否可以恢复
        """
        return self.db_manager.can_resume()
    
    def get_current_state(self) -> Optional[Dict[str, Any]]:
        """获取当前状态.
        
        Returns:
            当前状态字典
        """
        if self._current_state is None:
            self._current_state = self.db_manager.get_session_state()
        return self._current_state
    
    def save_checkpoint(self, position: str, processed_count: int = 0) -> None:
        """保存检查点.
        
        Args:
            position: 当前位置（提交哈希）
            processed_count: 已处理的提交数量
        """
        current_state = self.get_current_state()
        if current_state:
            current_state['current_position'] = position
            current_state['processed_commits'] = processed_count
            self.db_manager.save_session_state(current_state)
            logger.info(f"检查点已保存: {position}")
    
    def load_checkpoint(self) -> Optional[Dict[str, Any]]:
        """加载检查点.
        
        Returns:
            检查点信息
        """
        state = self.get_current_state()
        if state and state.get('current_position'):
            current_position = state.get('current_position')
            logger.info(f"从检查点恢复: {current_position}")
            return state
        return None
    
    def mark_commit_processed(self, commit_hash: str, status: str) -> None:
        """标记提交为已处理.
        
        Args:
            commit_hash: 提交哈希
            status: 状态（merged/rewritten/done/skipped）
        """
        self.db_manager.update_commit_status(commit_hash, status)
        logger.debug(f"提交 {commit_hash[:8]} 标记为 {status}")
    
    def save_hash_mapping(self, old_hash: str, new_hash: str) -> None:
        """保存哈希映射.
        
        Args:
            old_hash: 旧哈希
            new_hash: 新哈希
        """
        self.db_manager.save_hash_mapping(old_hash, new_hash)
        logger.debug(f"哈希映射已保存: {old_hash[:8]} -> {new_hash[:8]}")
    
    def get_mapped_hash(self, old_hash: str) -> Optional[str]:
        """获取映射后的哈希.
        
        Args:
            old_hash: 旧哈希
            
        Returns:
            新哈希，如果不存在返回 None
        """
        return self.db_manager.get_mapped_hash(old_hash)
    
    def get_all_mappings(self) -> Dict[str, str]:
        """获取所有哈希映射.
        
        Returns:
            哈希映射字典
        """
        return self.db_manager.get_all_mappings()
    
    def initialize_session(self, branch: str, backup_branch: str = None, 
                          total_commits: int = 0) -> None:
        """初始化会话状态.
        
        Args:
            branch: 当前分支
            backup_branch: 备份分支
            total_commits: 总提交数
        """
        state = {
            'branch': branch,
            'backup_branch': backup_branch,
            'current_position': None,
            'total_commits': total_commits,
            'processed_commits': 0
        }
        
        self.db_manager.save_session_state(state)
        self._current_state = state
        logger.info(f"会话状态已初始化: {branch}")
    
    def update_session(self, **kwargs) -> None:
        """更新会话状态.
        
        Args:
            **kwargs: 要更新的字段
        """
        current_state = self.get_current_state()
        if current_state:
            current_state.update(kwargs)
            self.db_manager.save_session_state(current_state)
            self._current_state = current_state
            logger.debug(f"会话状态已更新: {kwargs}")
    
    def get_processed_commits(self) -> List[Dict[str, Any]]:
        """获取已处理的提交.
        
        Returns:
            已处理提交列表
        """
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM commits 
                WHERE status IN ('merged', 'rewritten', 'done', 'skipped')
                ORDER BY commit_date ASC
            """)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_pending_commits(self) -> List[Dict[str, Any]]:
        """获取待处理的提交.
        
        Returns:
            待处理提交列表
        """
        return self.db_manager.get_pending_commits()
    
    def get_commit_groups(self) -> List[List[Dict[str, Any]]]:
        """获取提交分组.
        
        Returns:
            分组列表
        """
        return self.db_manager.get_commit_groups()
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取处理统计信息.
        
        Returns:
            统计信息
        """
        db_stats = self.db_manager.get_statistics()
        current_state = self.get_current_state()
        
        stats = {
            'total_commits': db_stats.get('total_commits', 0),
            'total_groups': db_stats.get('total_groups', 0),
            'total_mappings': db_stats.get('total_mappings', 0),
            'status_counts': db_stats.get('status_counts', {}),
            'current_branch': current_state.get('branch') if current_state else None,
            'backup_branch': current_state.get('backup_branch') if current_state else None,
            'current_position': current_state.get('current_position') if current_state else None,
            'processed_commits': current_state.get('processed_commits', 0) if current_state else 0,
            'total_commits_in_session': current_state.get('total_commits', 0) if current_state else 0
        }
        
        # 计算进度
        if stats['total_commits_in_session'] > 0:
            stats['progress_percentage'] = (
                stats['processed_commits'] / stats['total_commits_in_session'] * 100
            )
        else:
            stats['progress_percentage'] = 0.0
        
        return stats
    
    def clear_session(self) -> None:
        """清空会话状态."""
        self.db_manager.clear_session_state()
        self._current_state = None
        logger.info("会话状态已清空")
    
    def reset_to_initial_state(self) -> None:
        """重置到初始状态."""
        # 重置所有提交状态为 pending
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE commits SET status = 'pending'")
            conn.commit()
        
        # 清空映射表
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM hash_mapping")
            conn.commit()
        
        # 清空分组表
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM commit_groups")
            conn.commit()
        
        # 清空会话状态
        self.clear_session()
        
        logger.info("已重置到初始状态")
    
    def export_state(self) -> Dict[str, Any]:
        """导出当前状态.
        
        Returns:
            状态数据
        """
        return {
            'session_state': self.get_current_state(),
            'mappings': self.get_all_mappings(),
            'statistics': self.get_statistics(),
            'commit_groups': self.get_commit_groups()
        }
    
    def import_state(self, state_data: Dict[str, Any]) -> None:
        """导入状态数据.
        
        Args:
            state_data: 状态数据
        """
        # 导入会话状态
        if 'session_state' in state_data:
            self.db_manager.save_session_state(state_data['session_state'])
        
        # 导入映射
        if 'mappings' in state_data:
            for old_hash, new_hash in state_data['mappings'].items():
                self.db_manager.save_hash_mapping(old_hash, new_hash)
        
        # 导入分组
        if 'commit_groups' in state_data:
            for i, group in enumerate(state_data['commit_groups']):
                similarities = [commit.get('similarity', 1.0) for commit in group]
                self.db_manager.save_commit_group(i, group, similarities)
        
        self._current_state = None  # 重置缓存
        logger.info("状态数据导入完成")
    
    def validate_state_consistency(self) -> List[str]:
        """验证状态一致性.
        
        Returns:
            错误列表
        """
        errors = []
        
        # 检查映射表一致性
        mappings = self.get_all_mappings()
        for old_hash, new_hash in mappings.items():
            # 检查旧哈希是否存在于提交表中
            old_commit = self.db_manager.get_commit(old_hash)
            if not old_commit:
                errors.append(f"映射中的旧哈希不存在: {old_hash}")
            
            # 检查新哈希是否存在于提交表中
            new_commit = self.db_manager.get_commit(new_hash)
            if not new_commit:
                errors.append(f"映射中的新哈希不存在: {new_hash}")
        
        # 检查分组一致性
        groups = self.get_commit_groups()
        for i, group in enumerate(groups):
            for commit in group:
                commit_data = self.db_manager.get_commit(commit['hash'])
                if not commit_data:
                    errors.append(f"分组 {i} 中的提交不存在: {commit['hash']}")
        
        # 检查会话状态一致性
        current_state = self.get_current_state()
        if current_state:
            current_position = current_state.get('current_position')
            if current_position:
                commit_data = self.db_manager.get_commit(current_position)
                if not commit_data:
                    errors.append(f"当前位置提交不存在: {current_position}")
        
        return errors
