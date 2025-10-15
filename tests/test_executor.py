"""执行器测试."""

import pytest
import tempfile
import os
import yaml
from unittest.mock import Mock, patch

from src.executor import RewriteExecutor


class TestRewriteExecutor:
    """重写执行器测试."""
    
    @pytest.fixture
    def temp_config(self):
        """临时配置文件."""
        config_data = {
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
                'api_key': 'test-key',
                'base_url': 'https://api.deepseek.com/v1',
                'model': 'deepseek-chat',
                'temperature': 0.3,
                'max_tokens': 1000
            },
            'database': {
                'path': '.git-rewrite-test.db'
            },
            'safety': {
                'check_clean_repo': True,
                'check_remote_sync': False,
                'verify_integrity': True,
                'dry_run_default': True
            },
            'prompts': {
                'analyze_diff': 'Test prompt: {diff_content}'
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            config_path = f.name
        
        yield config_path
        
        # 清理
        os.unlink(config_path)
        if os.path.exists('.git-rewrite-test.db'):
            os.unlink('.git-rewrite-test.db')
    
    @pytest.fixture
    def executor(self, temp_config):
        """执行器实例."""
        return RewriteExecutor(temp_config, dry_run=True)
    
    def test_initialization(self, temp_config):
        """测试初始化."""
        executor = RewriteExecutor(temp_config, dry_run=True)
        
        assert executor.dry_run == True
        assert executor.config_manager is not None
        assert executor.config is not None
    
    @patch('src.executor.GitOperations')
    @patch('src.executor.DatabaseManager')
    def test_initialize_components(self, mock_db, mock_git, executor):
        """测试组件初始化."""
        # Mock 仓库状态检查
        mock_git_instance = Mock()
        mock_git_instance.check_repo_status.return_value = {
            'is_dirty': False,
            'is_synced': True
        }
        mock_git.return_value = mock_git_instance
        
        # Mock 数据库
        mock_db_instance = Mock()
        mock_db.return_value = mock_db_instance
        
        executor.initialize()
        
        assert executor.db_manager is not None
        assert executor.git_ops is not None
        assert executor.clusterer is not None
        assert executor.ai_rewriter is not None
        assert executor.state_manager is not None
    
    @patch('src.executor.GitOperations')
    @patch('src.executor.DatabaseManager')
    def test_dry_run_mode(self, mock_db, mock_git, executor):
        """测试 dry-run 模式."""
        # Mock 所有依赖
        mock_git_instance = Mock()
        mock_git_instance.check_repo_status.return_value = {
            'is_dirty': False,
            'is_synced': True
        }
        mock_git_instance.scan_commits.return_value = []
        mock_git.return_value = mock_git_instance
        
        mock_db_instance = Mock()
        mock_db.return_value = mock_db_instance
        
        # Mock 其他组件
        with patch.object(executor, 'clusterer') as mock_clusterer, \
             patch.object(executor, 'state_manager') as mock_state_manager:
            
            mock_clusterer.analyze_similarity.return_value = []
            mock_state_manager.can_resume.return_value = False
            
            # 应该不抛出异常
            executor.run()
    
    @patch('src.executor.GitOperations')
    @patch('src.executor.DatabaseManager')
    def test_resume_execution(self, mock_db, mock_git, executor):
        """测试恢复执行."""
        # Mock 所有依赖
        mock_git_instance = Mock()
        mock_git_instance.check_repo_status.return_value = {
            'is_dirty': False,
            'is_synced': True
        }
        mock_git.return_value = mock_git_instance
        
        mock_db_instance = Mock()
        mock_db.return_value = mock_db_instance
        
        # Mock 状态管理器
        with patch.object(executor, 'state_manager') as mock_state_manager:
            mock_state_manager.can_resume.return_value = True
            mock_state_manager.load_checkpoint.return_value = {
                'current_position': 'test-hash',
                'branch': 'main'
            }
            mock_state_manager.get_commit_groups.return_value = []
            
            # 应该不抛出异常
            executor.run()
    
    def test_get_status(self, executor):
        """测试获取状态."""
        with patch.object(executor, 'initialize'), \
             patch.object(executor, 'state_manager') as mock_state_manager:
            
            mock_state_manager.get_statistics.return_value = {
                'total_commits': 10,
                'processed_commits': 5,
                'progress_percentage': 50.0
            }
            
            status = executor.get_status()
            
            assert status['total_commits'] == 10
            assert status['processed_commits'] == 5
            assert status['progress_percentage'] == 50.0
    
    def test_list_backups(self, executor):
        """测试列出备份分支."""
        with patch.object(executor, 'initialize'), \
             patch.object(executor, 'git_ops') as mock_git_ops:
            
            mock_git_ops.get_backup_branches.return_value = [
                'backup/main-20250101-120000',
                'backup/main-20250101-130000'
            ]
            
            backups = executor.list_backups()
            
            assert len(backups) == 2
            assert 'backup/main-20250101-120000' in backups
    
    def test_rollback(self, executor):
        """测试回滚."""
        with patch.object(executor, 'initialize'), \
             patch.object(executor, 'git_ops') as mock_git_ops:
            
            mock_git_ops.reset_to_branch.return_value = True
            
            success = executor.rollback('backup/main-20250101-120000')
            
            assert success == True
            mock_git_ops.reset_to_branch.assert_called_once_with('backup/main-20250101-120000')
