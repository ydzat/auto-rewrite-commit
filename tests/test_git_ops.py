"""Git 操作测试."""

import pytest
import tempfile
import os
import shutil
from unittest.mock import Mock, patch

from src.git_operations import GitOperations


class TestGitOperations:
    """Git 操作测试."""
    
    @pytest.fixture
    def temp_repo(self):
        """临时 Git 仓库."""
        temp_dir = tempfile.mkdtemp()
        
        # 初始化 Git 仓库
        os.system(f"cd {temp_dir} && git init")
        
        # 创建一些文件并提交
        with open(os.path.join(temp_dir, "file1.txt"), "w") as f:
            f.write("Hello World")
        
        os.system(f"cd {temp_dir} && git add . && git commit -m 'Initial commit'")
        
        # 创建第二个提交
        with open(os.path.join(temp_dir, "file2.txt"), "w") as f:
            f.write("Feature code")
        
        os.system(f"cd {temp_dir} && git add . && git commit -m 'Add feature'")
        
        yield temp_dir
        
        # 清理
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def git_ops(self, temp_repo):
        """Git 操作实例."""
        return GitOperations(temp_repo)
    
    def test_repo_validation(self, temp_repo):
        """测试仓库验证."""
        # 有效仓库
        git_ops = GitOperations(temp_repo)
        assert str(git_ops.repo_path) == temp_repo
        
        # 无效仓库
        with pytest.raises(ValueError):
            GitOperations("/invalid/path")
    
    def test_check_repo_status(self, git_ops):
        """测试仓库状态检查."""
        status = git_ops.check_repo_status()
        
        assert 'is_dirty' in status
        assert 'untracked_files' in status
        assert 'active_branch' in status
        assert 'head_commit' in status
        assert status['is_dirty'] == False  # 干净仓库
    
    def test_create_backup_branch(self, git_ops):
        """测试创建备份分支."""
        backup_branch = git_ops.create_backup_branch()
        
        assert backup_branch.startswith("backup/")
        assert git_ops.repo.heads[backup_branch] is not None
    
    def test_scan_commits(self, git_ops):
        """测试扫描提交."""
        commits = git_ops.scan_commits()
        
        assert len(commits) == 2  # 两个提交
        assert commits[0]['message'] == 'Initial commit'
        assert commits[1]['message'] == 'Add feature'
        
        # 检查提交数据完整性
        for commit in commits:
            assert 'hash' in commit
            assert 'message' in commit
            assert 'diff_content' in commit
            assert 'modified_files' in commit
            assert 'author' in commit
            assert 'commit_date' in commit
    
    def test_get_commit_by_hash(self, git_ops):
        """测试根据哈希获取提交."""
        commits = git_ops.scan_commits()
        first_commit_hash = commits[0]['hash']
        
        commit = git_ops.get_commit_by_hash(first_commit_hash)
        assert commit is not None
        assert commit.hexsha == first_commit_hash
        
        # 测试不存在的哈希
        non_existent = git_ops.get_commit_by_hash("nonexistent")
        assert non_existent is None
    
    def test_get_parent_hashes(self, git_ops):
        """测试获取父提交哈希."""
        commits = git_ops.scan_commits()
        
        # 第一个提交没有父提交
        first_commit = commits[0]
        parents = git_ops.get_parent_hashes(first_commit['hash'])
        assert len(parents) == 0
        
        # 第二个提交有父提交
        second_commit = commits[1]
        parents = git_ops.get_parent_hashes(second_commit['hash'])
        assert len(parents) == 1
        assert parents[0] == first_commit['hash']
    
    def test_list_branches(self, git_ops):
        """测试列出分支."""
        branches = git_ops.list_branches()
        
        assert len(branches) >= 1  # 至少有一个分支
        assert 'main' in branches or 'master' in branches
    
    def test_get_backup_branches(self, git_ops):
        """测试获取备份分支."""
        # 创建备份分支
        backup_branch = git_ops.create_backup_branch()
        
        backup_branches = git_ops.get_backup_branches()
        assert backup_branch in backup_branches
    
    def test_verify_integrity(self, git_ops):
        """测试仓库完整性验证."""
        # 正常仓库应该通过验证
        assert git_ops.verify_integrity() == True
    
    def test_reset_to_branch(self, git_ops):
        """测试重置到分支."""
        # 创建备份分支
        backup_branch = git_ops.create_backup_branch()
        
        # 重置到备份分支
        success = git_ops.reset_to_branch(backup_branch)
        assert success == True
        
        # 测试重置到不存在的分支
        success = git_ops.reset_to_branch("nonexistent")
        assert success == False
