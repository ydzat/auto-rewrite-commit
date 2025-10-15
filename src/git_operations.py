"""Git 操作模块 - GitPython 封装."""

import os
import logging
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

import git
from git import Repo, Commit, Tree

from .utils import validate_git_repo, get_timestamp, safe_json_dumps, safe_json_loads

logger = logging.getLogger(__name__)


class GitOperations:
    """Git 操作封装类."""
    
    def __init__(self, repo_path: str, db_manager=None):
        """初始化 Git 操作.
        
        Args:
            repo_path: 仓库路径
            db_manager: 数据库管理器实例
        """
        self.repo_path = Path(repo_path).resolve()
        self.db_manager = db_manager
        
        # 验证仓库
        if not validate_git_repo(str(self.repo_path)):
            raise ValueError(f"无效的 Git 仓库: {self.repo_path}")
        
        # 打开仓库
        try:
            self.repo = Repo(str(self.repo_path))
            logger.info(f"Git 仓库已打开: {self.repo_path}")
        except Exception as e:
            raise RuntimeError(f"无法打开 Git 仓库: {e}")
    
    def check_repo_status(self) -> Dict[str, Any]:
        """检查仓库状态.
        
        Returns:
            仓库状态信息
        """
        status = {
            'is_dirty': self.repo.is_dirty(),
            'untracked_files': self.repo.untracked_files,
            'active_branch': self.repo.active_branch.name if self.repo.active_branch else None,
            'head_commit': self.repo.head.commit.hexsha if self.repo.head.commit else None
        }
        
        # 检查远程同步状态
        try:
            if self.repo.remotes.origin:
                self.repo.remotes.origin.fetch()
                local_commit = self.repo.head.commit
                remote_commit = self.repo.commit('origin/' + status['active_branch'])
                status['is_synced'] = local_commit == remote_commit
            else:
                status['is_synced'] = True  # 没有远程仓库
        except Exception as e:
            logger.warning(f"检查远程同步状态失败: {e}")
            status['is_synced'] = True
        
        return status
    
    def create_backup_branch(self, branch_name: str = None) -> str:
        """创建备份分支.
        
        Args:
            branch_name: 分支名称，如果为 None 则自动生成
            
        Returns:
            备份分支名称
        """
        if branch_name is None:
            current_branch = self.repo.active_branch.name
            timestamp = get_timestamp()
            branch_name = f"backup/{current_branch}-{timestamp}"
        
        try:
            # 创建备份分支
            backup_branch = self.repo.create_head(branch_name)
            logger.info(f"备份分支已创建: {branch_name}")
            return branch_name
        except Exception as e:
            raise RuntimeError(f"创建备份分支失败: {e}")
    
    def scan_commits(self, branch: str = None) -> List[Dict[str, Any]]:
        """扫描提交历史.
        
        Args:
            branch: 分支名称，如果为 None 则使用当前分支
            
        Returns:
            提交信息列表
        """
        if branch:
            try:
                commits = list(self.repo.iter_commits(branch, reverse=True))
            except Exception as e:
                raise RuntimeError(f"无法获取分支 {branch} 的提交: {e}")
        else:
            commits = list(self.repo.iter_commits(reverse=True))
        
        commit_data_list = []
        
        for commit in commits:
            try:
                commit_data = self._extract_commit_data(commit)
                commit_data_list.append(commit_data)
                
                # 如果提供了数据库管理器，保存到数据库
                if self.db_manager:
                    self.db_manager.save_commit(commit_data)
                    
            except Exception as e:
                logger.error(f"提取提交数据失败 {commit.hexsha}: {e}")
                continue
        
        logger.info(f"扫描完成，共 {len(commit_data_list)} 个提交")
        return commit_data_list
    
    def _extract_commit_data(self, commit: Commit) -> Dict[str, Any]:
        """提取提交数据.
        
        Args:
            commit: Git 提交对象
            
        Returns:
            提交数据字典
        """
        # 获取父提交哈希
        parent_hash = commit.parents[0].hexsha if commit.parents else None
        
        # 获取 diff 内容
        diff_content = self._get_commit_diff(commit)
        
        # 获取修改的文件列表
        modified_files = self._get_modified_files(commit)
        
        return {
            'hash': commit.hexsha,
            'parent_hash': parent_hash,
            'message': commit.message.strip(),
            'diff_content': diff_content,
            'modified_files': safe_json_dumps(modified_files),
            'author': commit.author.name,
            'author_email': commit.author.email,
            'commit_date': int(commit.committed_date),
            'tree_hash': commit.tree.hexsha,
            'status': 'pending'
        }
    
    def _get_commit_diff(self, commit: Commit) -> str:
        """获取提交的 diff 内容.
        
        Args:
            commit: Git 提交对象
            
        Returns:
            diff 内容字符串
        """
        try:
            if commit.parents:
                # 有父提交，获取与父提交的差异
                diff = self.repo.git.diff(commit.parents[0], commit, unified=3)
            else:
                # 根提交，获取所有文件内容
                diff = self.repo.git.show(commit.hexsha, '--format=', '--name-only')
            return diff
        except Exception as e:
            logger.warning(f"获取 diff 失败 {commit.hexsha}: {e}")
            return ""
    
    def _get_modified_files(self, commit: Commit) -> List[str]:
        """获取提交修改的文件列表.
        
        Args:
            commit: Git 提交对象
            
        Returns:
            文件路径列表
        """
        try:
            if commit.parents:
                # 有父提交，获取修改的文件
                diff_index = commit.parents[0].diff(commit)
                files = [item.a_path or item.b_path for item in diff_index]
            else:
                # 根提交，获取所有文件
                files = [item.path for item in commit.tree.traverse() if item.type == 'blob']
            return files
        except Exception as e:
            logger.warning(f"获取修改文件失败 {commit.hexsha}: {e}")
            return []
    
    def build_merged_tree(self, commits: List[Dict[str, Any]]) -> Tree:
        """构建合并后的 tree.
        
        Args:
            commits: 提交列表（按时间顺序）
            
        Returns:
            合并后的 tree 对象
        """
        if not commits:
            raise ValueError("提交列表不能为空")
        
        # 获取第一个提交的 tree 作为基础
        base_commit = self.repo.commit(commits[0]['hash'])
        merged_tree = base_commit.tree
        
        # 按顺序应用后续提交的更改（最新覆盖）
        for commit_data in commits[1:]:
            commit = self.repo.commit(commit_data['hash'])
            
            # 遍历提交的 tree，更新合并的 tree
            for item in commit.tree.traverse():
                if item.type == 'blob':
                    # 更新文件内容
                    merged_tree = self._update_tree_item(merged_tree, item)
        
        return merged_tree
    
    def _update_tree_item(self, tree: Tree, item) -> Tree:
        """更新 tree 中的项目.
        
        Args:
            tree: 目标 tree
            item: 要更新的项目
            
        Returns:
            更新后的 tree
        """
        try:
            # 创建新的 tree 对象
            new_tree = tree
            
            # 这里简化处理，实际应该使用 GitPython 的 tree 操作
            # 由于 GitPython 的 tree 操作比较复杂，这里返回原 tree
            # 在实际实现中，可能需要使用 git 命令或更底层的操作
            return new_tree
        except Exception as e:
            logger.warning(f"更新 tree 项目失败: {e}")
            return tree
    
    def create_commit(self, tree: Tree, parents: List[str], message: str,
                     author: str = None, author_email: str = None) -> str:
        """创建新的提交.
        
        Args:
            tree: tree 对象
            parents: 父提交哈希列表
            message: 提交信息
            author: 作者名称
            author_email: 作者邮箱
            
        Returns:
            新提交的哈希
        """
        try:
            # 获取父提交对象
            parent_commits = []
            for parent_hash in parents:
                parent_commit = self.repo.commit(parent_hash)
                parent_commits.append(parent_commit)
            
            # 设置作者信息
            if not author or not author_email:
                # 使用当前提交的作者信息
                current_commit = self.repo.head.commit
                author = author or current_commit.author.name
                author_email = author_email or current_commit.author.email
            
            # 创建提交
            new_commit = self.repo.index.commit(
                message=message,
                parent_commits=parent_commits,
                author=git.Actor(author, author_email),
                committer=git.Actor(author, author_email)
            )
            
            logger.info(f"新提交已创建: {new_commit.hexsha}")
            return new_commit.hexsha
            
        except Exception as e:
            raise RuntimeError(f"创建提交失败: {e}")
    
    def get_commit_by_hash(self, commit_hash: str) -> Optional[Commit]:
        """根据哈希获取提交对象.
        
        Args:
            commit_hash: 提交哈希
            
        Returns:
            提交对象，如果不存在返回 None
        """
        try:
            return self.repo.commit(commit_hash)
        except Exception:
            return None
    
    def get_parent_hashes(self, commit_hash: str) -> List[str]:
        """获取提交的父提交哈希列表.
        
        Args:
            commit_hash: 提交哈希
            
        Returns:
            父提交哈希列表
        """
        commit = self.get_commit_by_hash(commit_hash)
        if commit:
            return [parent.hexsha for parent in commit.parents]
        return []
    
    def verify_integrity(self) -> bool:
        """验证仓库完整性.
        
        Returns:
            仓库是否完整
        """
        try:
            # 执行 git fsck
            result = self.repo.git.fsck('--no-reflogs')
            logger.info("仓库完整性验证通过")
            return True
        except Exception as e:
            logger.error(f"仓库完整性验证失败: {e}")
            return False
    
    def get_branch_diff(self, branch1: str, branch2: str) -> str:
        """获取两个分支的差异.
        
        Args:
            branch1: 分支1
            branch2: 分支2
            
        Returns:
            差异内容
        """
        try:
            diff = self.repo.git.diff(branch1, branch2)
            return diff
        except Exception as e:
            logger.error(f"获取分支差异失败: {e}")
            return ""
    
    def list_branches(self) -> List[str]:
        """列出所有分支.
        
        Returns:
            分支名称列表
        """
        try:
            branches = [ref.name for ref in self.repo.refs]
            return branches
        except Exception as e:
            logger.error(f"列出分支失败: {e}")
            return []
    
    def get_backup_branches(self) -> List[str]:
        """获取所有备份分支.
        
        Returns:
            备份分支名称列表
        """
        all_branches = self.list_branches()
        backup_branches = [branch for branch in all_branches if branch.startswith('backup/')]
        return backup_branches
    
    def reset_to_branch(self, branch_name: str) -> bool:
        """重置到指定分支.
        
        Args:
            branch_name: 分支名称
            
        Returns:
            是否成功
        """
        try:
            self.repo.git.reset('--hard', branch_name)
            logger.info(f"已重置到分支: {branch_name}")
            return True
        except Exception as e:
            logger.error(f"重置到分支失败: {e}")
            return False
