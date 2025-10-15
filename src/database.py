"""数据库管理模块 - SQLite 操作."""

import sqlite3
import logging
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from .utils import safe_json_loads, safe_json_dumps, ensure_directory

logger = logging.getLogger(__name__)


class DatabaseManager:
    """SQLite 数据库管理器."""
    
    def __init__(self, db_path: str):
        """初始化数据库管理器.
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path)
        ensure_directory(self.db_path.parent)
        self.init_schema()
    
    def get_connection(self) -> sqlite3.Connection:
        """获取数据库连接."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # 使结果可以通过列名访问
        return conn
    
    def init_schema(self) -> None:
        """初始化数据库表结构."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # commits 表：存储提交信息
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS commits (
                    hash TEXT PRIMARY KEY,
                    parent_hash TEXT,
                    message TEXT,
                    diff_content TEXT,
                    modified_files TEXT,
                    author TEXT,
                    author_email TEXT,
                    commit_date INTEGER,
                    tree_hash TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at INTEGER DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_commits_status ON commits(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_commits_parent ON commits(parent_hash)")
            
            # hash_mapping 表：哈希映射
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hash_mapping (
                    old_hash TEXT PRIMARY KEY,
                    new_hash TEXT NOT NULL,
                    created_at INTEGER DEFAULT (strftime('%s', 'now'))
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mapping_new ON hash_mapping(new_hash)")
            
            # commit_groups 表：聚类分组
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS commit_groups (
                    group_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    commit_hash TEXT NOT NULL,
                    group_order INTEGER,
                    similarity REAL,
                    created_at INTEGER DEFAULT (strftime('%s', 'now')),
                    FOREIGN KEY (commit_hash) REFERENCES commits(hash)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_groups_id ON commit_groups(group_id)")
            
            # session_state 表：会话状态（单例表）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS session_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    branch TEXT NOT NULL,
                    backup_branch TEXT,
                    current_position TEXT,
                    total_commits INTEGER,
                    processed_commits INTEGER,
                    last_updated INTEGER DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            conn.commit()
            logger.info("数据库表结构初始化完成")
    
    def save_commit(self, commit_data: Dict[str, Any]) -> None:
        """保存提交信息到数据库.
        
        Args:
            commit_data: 提交数据字典
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO commits 
                (hash, parent_hash, message, diff_content, modified_files, 
                 author, author_email, commit_date, tree_hash, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                commit_data['hash'],
                commit_data.get('parent_hash'),
                commit_data['message'],
                commit_data.get('diff_content', ''),
                commit_data.get('modified_files', '[]'),
                commit_data.get('author', ''),
                commit_data.get('author_email', ''),
                commit_data.get('commit_date', 0),
                commit_data.get('tree_hash', ''),
                commit_data.get('status', 'pending')
            ))
            conn.commit()
    
    def get_commit(self, commit_hash: str) -> Optional[Dict[str, Any]]:
        """获取指定提交信息.
        
        Args:
            commit_hash: 提交哈希
            
        Returns:
            提交数据字典，如果不存在返回 None
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM commits WHERE hash = ?", (commit_hash,))
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return None
    
    def get_pending_commits(self) -> List[Dict[str, Any]]:
        """获取所有待处理的提交.
        
        Returns:
            待处理提交列表
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM commits 
                WHERE status = 'pending' 
                ORDER BY commit_date ASC
            """)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_all_commits(self) -> List[Dict[str, Any]]:
        """获取所有提交.
        
        Returns:
            所有提交列表，按时间排序
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM commits ORDER BY commit_date ASC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def update_commit_status(self, commit_hash: str, status: str) -> None:
        """更新提交状态.
        
        Args:
            commit_hash: 提交哈希
            status: 新状态
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE commits SET status = ? WHERE hash = ?",
                (status, commit_hash)
            )
            conn.commit()
    
    def save_hash_mapping(self, old_hash: str, new_hash: str) -> None:
        """保存哈希映射关系.
        
        Args:
            old_hash: 旧哈希
            new_hash: 新哈希
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO hash_mapping (old_hash, new_hash)
                VALUES (?, ?)
            """, (old_hash, new_hash))
            conn.commit()
    
    def get_mapped_hash(self, old_hash: str) -> Optional[str]:
        """获取映射后的新哈希.
        
        Args:
            old_hash: 旧哈希
            
        Returns:
            新哈希，如果不存在返回 None
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT new_hash FROM hash_mapping WHERE old_hash = ?", (old_hash,))
            row = cursor.fetchone()
            return row['new_hash'] if row else None
    
    def get_all_mappings(self) -> Dict[str, str]:
        """获取所有哈希映射.
        
        Returns:
            旧哈希到新哈希的映射字典
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT old_hash, new_hash FROM hash_mapping")
            rows = cursor.fetchall()
            return {row['old_hash']: row['new_hash'] for row in rows}
    
    def save_commit_group(self, group_id: int, commits: List[Dict[str, Any]], 
                         similarities: List[float]) -> None:
        """保存提交分组信息.
        
        Args:
            group_id: 分组 ID
            commits: 提交列表
            similarities: 相似度列表
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 删除旧的分组数据
            cursor.execute("DELETE FROM commit_groups WHERE group_id = ?", (group_id,))
            
            # 插入新的分组数据
            for i, (commit, similarity) in enumerate(zip(commits, similarities)):
                cursor.execute("""
                    INSERT INTO commit_groups (group_id, commit_hash, group_order, similarity)
                    VALUES (?, ?, ?, ?)
                """, (group_id, commit['hash'], i, similarity))
            
            conn.commit()
    
    def get_commit_groups(self) -> List[List[Dict[str, Any]]]:
        """获取所有提交分组.
        
        Returns:
            分组列表，每个分组包含提交信息
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT cg.group_id, cg.group_order, cg.similarity,
                       c.hash, c.parent_hash, c.message, c.diff_content,
                       c.modified_files, c.author, c.author_email,
                       c.commit_date, c.tree_hash, c.status
                FROM commit_groups cg
                JOIN commits c ON cg.commit_hash = c.hash
                ORDER BY cg.group_id, cg.group_order
            """)
            rows = cursor.fetchall()
            
            # 按分组 ID 组织数据
            groups = {}
            for row in rows:
                group_id = row['group_id']
                if group_id not in groups:
                    groups[group_id] = []
                
                commit_data = {
                    'hash': row['hash'],
                    'parent_hash': row['parent_hash'],
                    'message': row['message'],
                    'diff_content': row['diff_content'],
                    'modified_files': row['modified_files'],
                    'author': row['author'],
                    'author_email': row['author_email'],
                    'commit_date': row['commit_date'],
                    'tree_hash': row['tree_hash'],
                    'status': row['status'],
                    'similarity': row['similarity']
                }
                groups[group_id].append(commit_data)
            
            return list(groups.values())
    
    def save_session_state(self, state: Dict[str, Any]) -> None:
        """保存会话状态.
        
        Args:
            state: 状态数据字典
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO session_state 
                (id, branch, backup_branch, current_position, 
                 total_commits, processed_commits, last_updated)
                VALUES (1, ?, ?, ?, ?, ?, strftime('%s', 'now'))
            """, (
                state.get('branch', ''),
                state.get('backup_branch'),
                state.get('current_position'),
                state.get('total_commits', 0),
                state.get('processed_commits', 0)
            ))
            conn.commit()
    
    def get_session_state(self) -> Optional[Dict[str, Any]]:
        """获取会话状态.
        
        Returns:
            状态数据字典，如果不存在返回 None
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM session_state WHERE id = 1")
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return None
    
    def clear_session_state(self) -> None:
        """清空会话状态."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM session_state")
            conn.commit()
    
    def can_resume(self) -> bool:
        """检查是否可以恢复会话.
        
        Returns:
            如果可以恢复返回 True
        """
        state = self.get_session_state()
        if not state:
            return False
        
        # 检查是否有待处理的提交
        pending_count = len(self.get_pending_commits())
        return pending_count > 0
    
    def get_statistics(self) -> Dict[str, int]:
        """获取数据库统计信息.
        
        Returns:
            统计信息字典
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 统计各状态的提交数量
            cursor.execute("""
                SELECT status, COUNT(*) as count 
                FROM commits 
                GROUP BY status
            """)
            status_counts = {row['status']: row['count'] for row in cursor.fetchall()}
            
            # 统计总提交数
            cursor.execute("SELECT COUNT(*) as total FROM commits")
            total_commits = cursor.fetchone()['total']
            
            # 统计分组数
            cursor.execute("SELECT COUNT(DISTINCT group_id) as groups FROM commit_groups")
            total_groups = cursor.fetchone()['groups']
            
            # 统计映射数
            cursor.execute("SELECT COUNT(*) as mappings FROM hash_mapping")
            total_mappings = cursor.fetchone()['mappings']
            
            return {
                'total_commits': total_commits,
                'total_groups': total_groups,
                'total_mappings': total_mappings,
                'status_counts': status_counts
            }
    
    def cleanup(self) -> None:
        """清理数据库（删除所有数据）."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM commit_groups")
            cursor.execute("DELETE FROM hash_mapping")
            cursor.execute("DELETE FROM commits")
            cursor.execute("DELETE FROM session_state")
            conn.commit()
            logger.info("数据库已清理")
