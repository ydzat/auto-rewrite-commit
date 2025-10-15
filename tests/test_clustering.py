"""聚类算法测试."""

import pytest
import tempfile
import os
from unittest.mock import Mock

from src.database import DatabaseManager
from src.clustering import CommitClusterer


class TestCommitClusterer:
    """提交聚类器测试."""
    
    @pytest.fixture
    def temp_db(self):
        """临时数据库."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        db_manager = DatabaseManager(db_path)
        yield db_manager
        
        # 清理
        os.unlink(db_path)
    
    @pytest.fixture
    def clusterer(self, temp_db):
        """聚类器实例."""
        return CommitClusterer(temp_db, threshold=0.8, max_group_size=10)
    
    @pytest.fixture
    def sample_commits(self):
        """示例提交数据."""
        return [
            {
                'hash': 'a1b2c3d4',
                'parent_hash': None,
                'message': 'Initial commit',
                'diff_content': 'diff --git a/file1.txt b/file1.txt\n+Hello World',
                'modified_files': '["file1.txt"]',
                'commit_date': 1000
            },
            {
                'hash': 'e5f6g7h8',
                'parent_hash': 'a1b2c3d4',
                'message': 'Add feature',
                'diff_content': 'diff --git a/file2.txt b/file2.txt\n+Feature code',
                'modified_files': '["file2.txt"]',
                'commit_date': 2000
            },
            {
                'hash': 'i9j0k1l2',
                'parent_hash': 'e5f6g7h8',
                'message': 'Fix bug',
                'diff_content': 'diff --git a/file2.txt b/file2.txt\n-Feature code\n+Fixed code',
                'modified_files': '["file2.txt"]',
                'commit_date': 3000
            }
        ]
    
    def test_continuous_commits(self, clusterer, sample_commits):
        """测试连续提交聚类."""
        groups = clusterer.analyze_similarity(sample_commits)
        
        # 应该生成 3 个分组（相似度低）
        assert len(groups) == 3
        assert len(groups[0]) == 1  # 第一个提交
        assert len(groups[1]) == 1  # 第二个提交
        assert len(groups[2]) == 1  # 第三个提交
    
    def test_similar_commits(self, clusterer):
        """测试相似提交聚类."""
        similar_commits = [
            {
                'hash': 'a1b2c3d4',
                'parent_hash': None,
                'message': 'Fix typo',
                'diff_content': 'diff --git a/file1.txt b/file1.txt\n-typo\n+correct',
                'modified_files': '["file1.txt"]',
                'commit_date': 1000
            },
            {
                'hash': 'e5f6g7h8',
                'parent_hash': 'a1b2c3d4',
                'message': 'Fix another typo',
                'diff_content': 'diff --git a/file1.txt b/file1.txt\n-typo\n+correct',  # 相同的 diff 内容
                'modified_files': '["file1.txt"]',
                'commit_date': 2000
            }
        ]
        
        groups = clusterer.analyze_similarity(similar_commits)
        
        # 应该生成 1 个分组（相似度高）
        assert len(groups) == 1
        assert len(groups[0]) == 2
    
    def test_max_group_size(self, clusterer):
        """测试最大分组大小限制."""
        # 创建超过最大大小的相似提交
        commits = []
        for i in range(15):  # 超过 max_group_size=10
            commits.append({
                'hash': f'hash{i:02d}',
                'parent_hash': f'hash{i-1:02d}' if i > 0 else None,
                'message': f'Similar commit {i}',
                'diff_content': 'diff --git a/file.txt b/file.txt\n+similar change',
                'modified_files': '["file.txt"]',
                'commit_date': 1000 + i
            })
        
        groups = clusterer.analyze_similarity(commits)
        
        # 检查所有分组都不超过最大大小
        for group in groups:
            assert len(group) <= 10
    
    def test_non_continuous_separated(self, clusterer):
        """测试非连续提交被分开."""
        non_continuous_commits = [
            {
                'hash': 'a1b2c3d4',
                'parent_hash': None,
                'message': 'First commit',
                'diff_content': 'diff --git a/file1.txt b/file1.txt\n+content1',
                'modified_files': '["file1.txt"]',
                'commit_date': 1000
            },
            {
                'hash': 'e5f6g7h8',
                'parent_hash': 'a1b2c3d4',
                'message': 'Second commit',
                'diff_content': 'diff --git a/file2.txt b/file2.txt\n+content2',
                'modified_files': '["file2.txt"]',
                'commit_date': 2000
            },
            {
                'hash': 'i9j0k1l2',
                'parent_hash': 'a1b2c3d4',  # 不是 e5f6g7h8 的子提交
                'message': 'Third commit',
                'diff_content': 'diff --git a/file3.txt b/file3.txt\n+content3',
                'modified_files': '["file3.txt"]',
                'commit_date': 3000
            }
        ]
        
        groups = clusterer.analyze_similarity(non_continuous_commits)
        
        # 应该生成 3 个分组（每个提交都是独立的，因为 diff 内容不同且不连续）
        assert len(groups) == 3
        assert len(groups[0]) == 1  # 第一个提交
        assert len(groups[1]) == 1  # 第二个提交  
        assert len(groups[2]) == 1  # 第三个提交
    
    def test_diff_similarity_calculation(self, clusterer):
        """测试 diff 相似度计算."""
        diff1 = "diff --git a/file.txt b/file.txt\n+Hello World"
        diff2 = "diff --git a/file.txt b/file.txt\n+Hello World"
        files1 = ["file.txt"]
        files2 = ["file.txt"]
        
        similarity = clusterer._calculate_diff_similarity(diff1, diff2, str(files1), str(files2))
        
        # 相同的 diff 应该有高相似度
        assert similarity == 1.0
    
    def test_group_statistics(self, clusterer, sample_commits):
        """测试分组统计."""
        groups = clusterer.analyze_similarity(sample_commits)
        stats = clusterer.get_group_statistics(groups)
        
        assert stats['total_groups'] == 3
        assert stats['total_commits'] == 3
        assert stats['single_commits'] == 3
        assert stats['merged_groups'] == 0
        assert stats['avg_group_size'] == 1.0
    
    def test_validate_groups(self, clusterer, sample_commits):
        """测试分组验证."""
        groups = clusterer.analyze_similarity(sample_commits)
        errors = clusterer.validate_groups(groups)
        
        # 正常分组应该没有错误
        assert len(errors) == 0
