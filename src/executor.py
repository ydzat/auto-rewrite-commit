"""核心执行引擎模块."""

import os
import logging
import tempfile
import time
from typing import Dict, Any, List, Optional
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.panel import Panel

from .config import ConfigManager
from .database import DatabaseManager
from .git_operations import GitOperations
from .clustering import CommitClusterer
from .ai_rewriter import AIRewriter
from .state_manager import StateManager
from .utils import setup_logging

logger = logging.getLogger(__name__)
console = Console()


class RewriteExecutor:
    """重写执行器."""
    
    def __init__(self, config_path: str = "config.yaml", dry_run: bool = True):
        """初始化执行器.
        
        Args:
            config_path: 配置文件路径
            dry_run: 是否为 dry-run 模式
        """
        self.dry_run = dry_run
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.get_all_config()
        
        # 验证配置
        if not self.config_manager.validate_config():
            raise ValueError("配置验证失败")
        
        # 初始化组件
        self.db_manager = None
        self.git_ops = None
        self.clusterer = None
        self.ai_rewriter = None
        self.state_manager = None
        
        # 设置日志
        setup_logging()
        
        console.print(f"[bold blue]Auto Git Rewriter {'(DRY-RUN)' if dry_run else '(APPLY)'}[/bold blue]")
    
    def initialize(self) -> None:
        """初始化所有组件."""
        try:
            # 切换到目标仓库目录
            repo_path = self.config_manager.get_repository_path()
            os.chdir(repo_path)
            console.print(f"[green]工作目录: {os.getcwd()}[/green]")
            
            # 初始化数据库
            db_path = self.config_manager.get_database_path()
            self.db_manager = DatabaseManager(db_path)
            
            # 初始化 Git 操作
            self.git_ops = GitOperations(repo_path, self.db_manager)
            
            # 检查仓库状态
            repo_status = self.git_ops.check_repo_status()
            if repo_status['is_dirty']:
                raise RuntimeError("仓库有未提交的修改，请先提交或 stash")
            
            if not repo_status['is_synced'] and self.config_manager.get('safety.check_remote_sync'):
                raise RuntimeError("本地仓库未与远程同步")
            
            # 初始化其他组件
            clustering_config = self.config_manager.get_clustering_config()
            self.clusterer = CommitClusterer(
                self.db_manager,
                threshold=clustering_config.get('similarity_threshold', 0.8),
                max_group_size=clustering_config.get('max_group_size', 10)
            )
            
            ai_config = self.config_manager.get_ai_config()
            self.ai_rewriter = AIRewriter(ai_config)
            
            self.state_manager = StateManager(self.db_manager)
            
            console.print("[green]✓ 所有组件初始化完成[/green]")
            
        except Exception as e:
            console.print(f"[red]初始化失败: {e}[/red]")
            raise
    
    def run(self) -> None:
        """执行重写流程."""
        try:
            self.initialize()
            
            # 检查是否可以恢复
            if self.state_manager.can_resume():
                console.print("[yellow]检测到未完成的任务，是否恢复？[/yellow]")
                # 这里可以添加用户确认逻辑
                self._resume_execution()
            else:
                self._start_new_execution()
                
        except Exception as e:
            console.print(f"[red]执行失败: {e}[/red]")
            logger.exception("执行过程中发生错误")
            raise
        finally:
            # 不自动清理数据库文件，让用户手动处理
            console.print("[yellow]数据库文件已保留，如需清理请手动删除[/yellow]")
    
    def _start_new_execution(self) -> None:
        """开始新的执行流程."""
        console.print("[bold]开始新的重写流程[/bold]")
        
        # 1. 创建备份
        backup_branch = self._create_backup()
        
        # 2. 扫描提交
        commits = self._scan_commits()
        
        # 3. 聚类分析
        groups = self._cluster_commits(commits)
        
        # 4. 初始化会话状态
        self._initialize_session(backup_branch, len(commits))
        
        # 5. 执行重写
        self._execute_rewrite(groups)
        
        # 6. 验证结果
        self._verify_results()
    
    def _resume_execution(self) -> None:
        """恢复执行流程."""
        console.print("[bold]恢复执行流程[/bold]")
        
        # 获取检查点
        checkpoint = self.state_manager.load_checkpoint()
        if not checkpoint:
            console.print("[yellow]没有找到检查点，开始新的执行[/yellow]")
            self._start_new_execution()
            return
        
        # 获取分组
        groups = self.state_manager.get_commit_groups()
        if not groups:
            console.print("[yellow]没有找到分组数据，重新聚类[/yellow]")
            commits = self.state_manager.get_pending_commits()
            groups = self._cluster_commits(commits)
        
        # 继续执行
        self._execute_rewrite(groups, resume=True)
        
        # 验证结果
        self._verify_results()
    
    def _create_backup(self) -> str:
        """创建备份分支."""
        if not self.config_manager.get('backup.auto_create', True):
            return None
        
        try:
            backup_branch = self.git_ops.create_backup_branch()
            console.print(f"[green]✓ 备份分支已创建: {backup_branch}[/green]")
            return backup_branch
        except Exception as e:
            console.print(f"[red]创建备份失败: {e}[/red]")
            raise
    
    def _scan_commits(self) -> List[Dict[str, Any]]:
        """扫描提交历史."""
        console.print("[bold]扫描提交历史...[/bold]")
        
        branch = self.config_manager.get_repository_branch()
        commits = self.git_ops.scan_commits(branch)
        
        console.print(f"[green]✓ 扫描完成，共 {len(commits)} 个提交[/green]")
        return commits
    
    def _cluster_commits(self, commits: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """聚类提交."""
        console.print("[bold]分析提交相似度...[/bold]")
        
        # 检查是否禁用合并（临时解决方案）
        disable_merging = self.config_manager.get('clustering.disable_merging', False)
        if disable_merging:
            console.print("[yellow]⚠ 合并功能已禁用，所有提交将作为单个提交处理[/yellow]")
            groups = [[commit] for commit in commits]
        else:
            groups = self.clusterer.analyze_similarity(commits)
        
        # 显示聚类统计
        stats = self.clusterer.get_group_statistics(groups)
        self._display_clustering_stats(stats)
        
        # 验证分组
        errors = self.clusterer.validate_groups(groups)
        if errors:
            console.print("[yellow]分组验证警告:[/yellow]")
            for error in errors:
                console.print(f"  - {error}")
        
        return groups
    
    def _display_clustering_stats(self, stats: Dict[str, Any]) -> None:
        """显示聚类统计信息."""
        table = Table(title="聚类统计")
        table.add_column("项目", style="cyan")
        table.add_column("数量", style="magenta")
        
        table.add_row("总分组数", str(stats['total_groups']))
        table.add_row("总提交数", str(stats['total_commits']))
        table.add_row("单个提交", str(stats['single_commits']))
        table.add_row("合并分组", str(stats['merged_groups']))
        table.add_row("平均分组大小", f"{stats['avg_group_size']:.1f}")
        
        console.print(table)
    
    def _initialize_session(self, backup_branch: str, total_commits: int) -> None:
        """初始化会话状态."""
        branch = self.config_manager.get_repository_branch()
        self.state_manager.initialize_session(branch, backup_branch, total_commits)
        console.print("[green]✓ 会话状态已初始化[/green]")
    
    def _execute_rewrite(self, groups: List[List[Dict[str, Any]]], resume: bool = False) -> None:
        """执行重写循环."""
        console.print("[bold]开始执行重写...[/bold]")
        
        # 获取提示词模板
        prompts = self.config_manager.get_prompts()
        prompt_template = prompts.get('analyze_diff', '')
        
        # 创建进度条
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            
            task = progress.add_task("处理提交分组...", total=len(groups))
            
            # 执行逐步 rebase
            self._execute_stepwise_rebase(groups, prompt_template, progress, task)
        
        console.print("[green]✓ 重写执行完成[/green]")
        
        # 完成重写流程
        if not self.dry_run:
            self._finalize_rewrite()
    
    def _execute_stepwise_rebase(self, groups: List[List[Dict[str, Any]]], 
                                prompt_template: str, progress, task) -> None:
        """执行逐步 rebase：每次 LLM 返回结果后立即执行一次 rebase."""
        if self.dry_run:
            # Dry-run 模式：只显示预览
            for i, group in enumerate(groups):
                progress.update(task, advance=1, description=f"预览分组 {i+1}/{len(groups)}")
                self._process_group_dry_run(group, prompt_template)
        else:
            # 实际执行：逐步执行 rebase
            self._stepwise_rebase_execution(groups, prompt_template, progress, task)
    
    def _stepwise_rebase_execution(self, groups: List[List[Dict[str, Any]]],
                                  prompt_template: str, progress, task) -> None:
        """使用顺序重写执行逐步重写."""
        try:
            console.print("[bold]开始顺序重写...[/bold]")

            # 生成所有提交的新消息
            commit_messages = {}
            for group in groups:
                if len(group) == 1:
                    new_message = self.ai_rewriter.rewrite_single_commit(group[0], prompt_template)
                else:
                    new_message = self.ai_rewriter.rewrite_commit_messages(group, prompt_template)
                new_message = self.ai_rewriter.apply_conventional_format(new_message)

                # 为分组中的每个提交记录新消息
                for commit in group:
                    commit_messages[commit['hash']] = new_message

            # 使用顺序重写而不是交互式 rebase
            self._sequential_rewrite(commit_messages, progress, task)

            # 更新状态：标记所有处理过的提交为已完成
            self._update_state_after_rebase_all(commit_messages)

            console.print("[green]✓ 顺序重写完成[/green]")

        except Exception as e:
            console.print(f"[red]✗ 顺序重写失败: {e}[/red]")
            logger.exception("顺序重写失败")
            raise
    
    def _sequential_rewrite(self, commit_messages: Dict[str, str], progress, task) -> None:
        """使用顺序 cherry-pick 重写提交历史."""
        try:
            console.print("[bold]开始顺序 cherry-pick 重写...[/bold]")

            # 获取当前分支
            current_branch = self.git_ops.repo.active_branch.name
            console.print(f"[dim]当前分支: {current_branch}[/dim]")

            # 创建临时重写分支
            temp_branch = f"temp-rewrite-{int(time.time())}"
            self.git_ops.repo.git.checkout('-b', temp_branch)
            console.print(f"[dim]创建临时分支: {temp_branch}[/dim]")

            # 备份未跟踪的文件
            backup_dir = self._backup_untracked_files()
            
            # 清理未跟踪的文件，避免 cherry-pick 冲突
            self._cleanup_untracked_files()

            # 重置到当前分支的第一个提交，而不是整个仓库的根提交
            # 这确保我们只处理当前分支上的提交，避免复杂分支历史的冲突
            branch_root_commit = self.git_ops.repo.git.rev_list('--max-parents=0', 'HEAD').strip()
            self.git_ops.repo.git.reset('--hard', branch_root_commit)
            console.print(f"[dim]重置到当前分支的根提交: {branch_root_commit[:8]}[/dim]")

            # 获取所有提交的有序列表
            all_commits = self.db_manager.get_all_commits()
            sorted_commits = sorted(all_commits, key=lambda x: x['commit_date'])

            # 逐个 cherry-pick 并修改消息
            for i, commit in enumerate(sorted_commits):
                commit_hash = commit['hash']
                progress.update(task, advance=1, description=f"处理提交 {i+1}/{len(sorted_commits)}: {commit_hash[:8]}")

                # 每次处理提交前都执行备份/恢复，确保环境干净
                if backup_dir:
                    self._restore_untracked_files(backup_dir)
                self._cleanup_untracked_files()

                try:
                    # Cherry-pick 提交
                    self.git_ops.repo.git.cherry_pick(commit_hash, '--allow-empty', '--keep-redundant-commits')
                    
                    # 如果需要修改消息
                    if commit_hash in commit_messages:
                        new_message = commit_messages[commit_hash]
                        self.git_ops.repo.git.commit('--amend', '-m', new_message, '--allow-empty', '--no-edit', '--no-verify')
                        console.print(f"[dim]修改提交 {commit_hash[:8]} 的消息[/dim]")
                    
                except Exception as cherry_error:
                    console.print(f"[yellow]Cherry-pick 失败 {commit_hash[:8]}: {cherry_error}[/yellow]")
                    
                    # 跳过所有冲突，不尝试解决
                    console.print(f"[red]✗ 跳过冲突提交 {commit_hash[:8]}[/red]")
                    # 尝试中止 cherry-pick 并清理状态
                    try:
                        self.git_ops.repo.git.cherry_pick('--abort')
                        console.print(f"[dim]已中止 cherry-pick {commit_hash[:8]}[/dim]")
                    except Exception as abort_error:
                        console.print(f"[yellow]中止 cherry-pick 失败: {abort_error}[/yellow]")
                        # 如果中止失败，尝试强制重置到干净状态
                        try:
                            self.git_ops.repo.git.reset('--hard', 'HEAD')
                            self.git_ops.repo.git.clean('-fd')
                            console.print(f"[dim]已强制清理工作区[/dim]")
                        except Exception as reset_error:
                            console.print(f"[yellow]强制清理失败: {reset_error}[/yellow]")

            # 切换回原始分支并强制更新
            console.print(f"[dim]切换回分支: {current_branch}[/dim]")
            
            # 确保工作区干净后再切换分支
            try:
                # 提交任何剩余的更改
                status = self.git_ops.repo.git.status('--porcelain')
                if status.strip():
                    console.print("[dim]提交剩余更改...[/dim]")
                    self.git_ops.repo.git.add('.')
                    self.git_ops.repo.git.commit('-m', 'chore: resolve remaining conflicts', '--allow-empty', '--no-verify')
            except Exception as e:
                console.print(f"[yellow]提交剩余更改失败: {e}[/yellow]")
            
            # 强制切换回原始分支
            self.git_ops.repo.git.checkout(current_branch, '--force')
            
            console.print(f"[dim]强制更新分支 {current_branch} 到 {temp_branch}[/dim]")
            self.git_ops.repo.git.reset('--hard', temp_branch)
            
            # 删除临时分支
            self.git_ops.repo.git.branch('-D', temp_branch)
            console.print(f"[dim]删除临时分支: {temp_branch}[/dim]")

            # 恢复备份的未跟踪文件
            if backup_dir:
                self._restore_untracked_files(backup_dir)
                # 显示备份位置，让用户手动检查
                console.print(f"[yellow]备份文件已恢复，请检查目标仓库文件是否完整[/yellow]")
                console.print(f"[yellow]备份目录位置: {backup_dir}[/yellow]")
                console.print(f"[yellow]如文件丢失，请从备份目录手动恢复[/yellow]")

            console.print("[green]✓ 顺序 cherry-pick 重写完成[/green]")

        except Exception as e:
            console.print(f"[red]顺序重写失败: {e}[/red]")
            # 尝试清理
            try:
                if 'current_branch' in locals():
                    # 强制切换回原始分支
                    self.git_ops.repo.git.checkout(current_branch, '--force')
                if 'temp_branch' in locals():
                    # 删除临时分支
                    try:
                        self.git_ops.repo.git.branch('-D', temp_branch)
                    except:
                        pass
                # 如果有备份目录，也要尝试恢复
                if 'backup_dir' in locals() and backup_dir:
                    self._restore_untracked_files(backup_dir)
            except Exception as cleanup_error:
                console.print(f"[yellow]清理失败: {cleanup_error}[/yellow]")
            raise
    
    def _resolve_conflicts(self, commit_hash: str) -> bool:
        """解决 cherry-pick 冲突，返回是否成功解决."""
        try:
            # 检查是否有未解决的冲突
            status_output = self.git_ops.repo.git.status('--porcelain')
            conflict_files = []
            
            for line in status_output.split('\n'):
                if line.strip() and (line.startswith('UU ') or line.startswith('AA ') or 
                                   line.startswith('DD ') or line.startswith('AU ') or 
                                   line.startswith('UA ') or line.startswith('DU ')):
                    # UU: 两边都修改，二进制文件冲突
                    # AA: 两边都添加
                    # DD: 两边都删除
                    # AU/UA/DU: 混合状态
                    file_path = line[3:].strip()
                    conflict_files.append((line[:2], file_path))
            
            if not conflict_files:
                console.print("[yellow]没有检测到冲突文件[/yellow]")
                return False
            
            console.print(f"[yellow]检测到 {len(conflict_files)} 个冲突文件[/yellow]")
            
            resolved_count = 0
            for status, file_path in conflict_files:
                if self._resolve_single_conflict(status, file_path):
                    resolved_count += 1
                    console.print(f"[dim]已解决冲突: {file_path}[/dim]")
                else:
                    console.print(f"[red]无法解决冲突: {file_path}[/red]")
            
            if resolved_count == len(conflict_files):
                # 所有冲突都已解决，提交
                self.git_ops.repo.git.add('.')
                self.git_ops.repo.git.commit('--no-edit', '--allow-empty', '--no-verify')
                console.print(f"[green]✓ 所有冲突已解决并提交[/green]")
                return True
            else:
                console.print(f"[red]✗ 仅解决 {resolved_count}/{len(conflict_files)} 个冲突[/red]")
                return False
                
        except Exception as e:
            console.print(f"[red]冲突解决失败: {e}[/red]")
            return False
    
    def _resolve_single_conflict(self, status: str, file_path: str) -> bool:
        """解决单个文件的冲突."""
        try:
            if status == 'UU':
                # 二进制文件冲突或内容冲突
                # 检查是否是二进制文件
                try:
                    # 尝试读取文件内容，如果失败则是二进制文件
                    with open(os.path.join(self.git_ops.repo.working_dir, file_path), 'r', encoding='utf-8') as f:
                        f.read(1024)  # 只读取前1KB
                    # 如果能读取，可能是文本文件，尝试使用HEAD版本
                    console.print(f"[dim]文本文件冲突，使用HEAD版本: {file_path}[/dim]")
                    self.git_ops.repo.git.checkout('--theirs', file_path)
                    return True
                except (UnicodeDecodeError, IOError):
                    # 二进制文件，使用HEAD版本（保留当前状态）
                    console.print(f"[dim]二进制文件冲突，使用HEAD版本: {file_path}[/dim]")
                    # 对于二进制文件，使用 --ours 来接受当前分支的版本
                    self.git_ops.repo.git.checkout('--ours', file_path)
                    return True
                    
            elif status in ['DU', 'UD', 'AU', 'UA']:
                # modify/delete 冲突：一侧修改，另一侧删除
                # 通常选择保留删除（HEAD版本）
                console.print(f"[dim]修改/删除冲突，使用HEAD版本（删除）: {file_path}[/dim]")
                if os.path.exists(os.path.join(self.git_ops.repo.working_dir, file_path)):
                    os.remove(os.path.join(self.git_ops.repo.working_dir, file_path))
                return True
                
            elif status == 'AA':
                # 两边都添加了相同文件，使用HEAD版本
                console.print(f"[dim]两边都添加文件，使用HEAD版本: {file_path}[/dim]")
                return True
                
            elif status == 'DD':
                # 两边都删除了文件，继续
                console.print(f"[dim]两边都删除文件: {file_path}[/dim]")
                return True
                
            else:
                console.print(f"[yellow]未知冲突类型 {status}: {file_path}[/yellow]")
                return False
                
        except Exception as e:
            console.print(f"[red]解决冲突失败 {file_path}: {e}[/red]")
            return False
    
    def _cleanup_database_file(self) -> None:
        """清理数据库文件."""
        try:
            db_path = self.config_manager.get_database_path()
            if os.path.exists(db_path):
                os.remove(db_path)
                console.print(f"[dim]已清理数据库文件: {db_path}[/dim]")
        except Exception as e:
            console.print(f"[yellow]⚠ 清理数据库文件失败: {e}[/yellow]")
            logger.warning(f"清理数据库文件失败: {e}")
    
    def _cleanup_untracked_files(self) -> None:
        """清理未跟踪的文件."""
        try:
            console.print("[dim]清理未跟踪的文件...[/dim]")
            
            import os
            import shutil
            
            # 使用 git clean 强制清理所有未跟踪的文件和目录
            try:
                # 先尝试使用 git clean 清理
                result = self.git_ops.repo.git.clean('-fd')
                if result:
                    console.print(f"[dim]git clean 清理结果: {result}[/dim]")
                console.print("[green]✓ 使用 git clean 清理完成[/green]")
            except Exception as clean_error:
                console.print(f"[yellow]git clean 失败: {clean_error}[/yellow]")
                # 如果 git clean 失败，回退到手动清理
                
                # 使用 git status 获取更准确的未跟踪文件列表
                status_output = self.git_ops.repo.git.status('--porcelain')
                untracked_files = []
                
                for line in status_output.split('\n'):
                    if line.startswith('?? '):
                        # ?? 表示未跟踪的文件
                        file_path = line[3:].strip()
                        untracked_files.append(file_path)
                
                if untracked_files:
                    console.print(f"[dim]发现未跟踪文件: {untracked_files}[/dim]")
                    
                    # 删除所有未跟踪的文件和目录
                    for file in untracked_files:
                        file_path = os.path.join(self.git_ops.repo.working_dir, file)
                        if os.path.exists(file_path):
                            if os.path.isfile(file_path):
                                os.remove(file_path)
                                console.print(f"[dim]已删除文件: {file}[/dim]")
                            elif os.path.isdir(file_path):
                                shutil.rmtree(file_path)
                                console.print(f"[dim]已删除目录: {file}[/dim]")
                else:
                    console.print("[dim]没有未跟踪的文件[/dim]")
                
        except Exception as e:
            console.print(f"[yellow]⚠ 清理未跟踪文件失败: {e}[/yellow]")
            logger.warning(f"清理未跟踪文件失败: {e}")
    
    def _backup_untracked_files(self) -> Optional[str]:
        """备份未跟踪的文件，返回备份目录路径."""
        try:
            import os
            import shutil
            import tempfile
            
            # 使用 git clean --dry-run 获取将被清理的文件列表
            try:
                dry_run_output = self.git_ops.repo.git.clean('--dry-run', '-fd')
                untracked_files = []
                
                if dry_run_output:
                    # 解析 dry-run 输出
                    for line in dry_run_output.split('\n'):
                        if line.strip():
                            # 去掉 "Would remove " 前缀
                            if line.startswith('Would remove '):
                                file_path = line[13:].strip()  # "Would remove " 是13个字符
                                untracked_files.append(file_path)
                            elif line.startswith('Would not remove '):
                                # 跳过不会被删除的文件
                                continue
                            else:
                                # 其他格式，直接添加
                                untracked_files.append(line.strip())
                
                console.print(f"[dim]git clean 将清理 {len(untracked_files)} 个文件/目录[/dim]")
                
            except Exception as e:
                console.print(f"[yellow]git clean dry-run 失败，使用备用方法: {e}[/yellow]")
                # 备用方法：使用 git status
                status_output = self.git_ops.repo.git.status('--porcelain')
                untracked_files = []
                
                for line in status_output.split('\n'):
                    if line.startswith('?? '):
                        # ?? 表示未跟踪的文件
                        file_path = line[3:].strip()
                        untracked_files.append(file_path)
            
            if not untracked_files:
                console.print("[dim]没有未跟踪的文件需要备份[/dim]")
                return None
            
            # 创建临时备份目录
            backup_dir = tempfile.mkdtemp(prefix='git-rewrite-backup-')
            console.print(f"[dim]创建备份目录: {backup_dir}[/dim]")
            
            # 备份每个未跟踪文件
            for file_path in untracked_files:
                src_path = os.path.join(self.git_ops.repo.working_dir, file_path)
                dst_path = os.path.join(backup_dir, file_path)
                
                if os.path.exists(src_path):
                    # 确保目标目录存在
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    
                    if os.path.isfile(src_path):
                        shutil.copy2(src_path, dst_path)
                        console.print(f"[dim]已备份文件: {file_path}[/dim]")
                    elif os.path.isdir(src_path):
                        shutil.copytree(src_path, dst_path)
                        console.print(f"[dim]已备份目录: {file_path}[/dim]")
            
            console.print(f"[green]✓ 已备份 {len(untracked_files)} 个未跟踪文件/目录[/green]")
            return backup_dir
            
        except Exception as e:
            console.print(f"[yellow]⚠ 备份未跟踪文件失败: {e}[/yellow]")
            logger.warning(f"备份未跟踪文件失败: {e}")
            return None
    
    def _restore_untracked_files(self, backup_dir: str) -> None:
        """恢复备份的未跟踪文件."""
        try:
            import os
            import shutil
            
            if not os.path.exists(backup_dir):
                console.print(f"[yellow]备份目录不存在: {backup_dir}[/yellow]")
                return
            
            # 遍历备份目录中的所有文件
            restored_count = 0
            for root, dirs, files in os.walk(backup_dir):
                for file in files:
                    # 计算相对路径
                    rel_path = os.path.relpath(os.path.join(root, file), backup_dir)
                    src_path = os.path.join(root, file)
                    dst_path = os.path.join(self.git_ops.repo.working_dir, rel_path)
                    
                    # 确保目标目录存在
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    
                    # 复制文件
                    shutil.copy2(src_path, dst_path)
                    restored_count += 1
            
            # 不删除备份目录，让用户手动检查
            console.print(f"[green]✓ 已恢复 {restored_count} 个文件[/green]")
            console.print(f"[yellow]备份目录保留在: {backup_dir}[/yellow]")
            console.print(f"[yellow]请检查文件恢复是否完整，确认后可手动删除备份目录[/yellow]")
            
        except Exception as e:
            console.print(f"[yellow]⚠ 恢复未跟踪文件失败: {e}[/yellow]")
            logger.warning(f"恢复未跟踪文件失败: {e}")

    def _process_group_dry_run(self, group: List[Dict[str, Any]], prompt_template: str) -> None:
        """Dry-run 模式处理分组."""
        if len(group) == 1:
            # 单个提交重写
            new_message = self.ai_rewriter.rewrite_single_commit(group[0], prompt_template)
            new_message = self.ai_rewriter.apply_conventional_format(new_message)
            console.print(f"[yellow][DRY-RUN] 重写提交: {group[0]['hash'][:8]}[/yellow]")
            console.print(f"  原始: {group[0]['message']}")
            console.print(f"  新消息: {new_message}")
        else:
            # 多个提交合并
            new_message = self.ai_rewriter.merge_commit_messages(group, prompt_template)
            new_message = self.ai_rewriter.apply_conventional_format(new_message)
            console.print(f"[yellow][DRY-RUN] 合并 {len(group)} 个提交[/yellow]")
            for i, commit in enumerate(group):
                console.print(f"  {i+1}. {commit['hash'][:8]}: {commit['message']}")
            console.print(f"  合并后: {new_message}")
    
    
    def _finalize_rewrite(self) -> None:
        """完成重写流程."""
        try:
            # 强制推送以更新远程历史
            self._force_push_if_needed()
            
            # 清理悬空对象
            self._cleanup_dangling_objects()
            
        except Exception as e:
            console.print(f"[red]✗ 完成重写失败: {e}[/red]")
            logger.exception("完成重写失败")
            raise
    
    def _force_push_if_needed(self) -> None:
        """如果需要，强制推送到远程仓库."""
        try:
            # 检查是否有远程仓库
            if not self.git_ops.repo.remotes:
                console.print("[yellow]没有远程仓库，跳过推送[/yellow]")
                return
            
            # 检查当前分支是否跟踪远程分支
            current_branch = self.git_ops.repo.active_branch
            if not current_branch.tracking_branch():
                console.print("[yellow]当前分支没有跟踪远程分支，跳过推送[/yellow]")
                return
            
            # 提示用户是否强制推送
            console.print("[bold yellow]⚠ 警告：历史重写需要强制推送[/bold yellow]")
            console.print("[yellow]这将覆盖远程仓库的历史，请确保没有其他人在使用此分支[/yellow]")
            
            # 这里可以添加用户确认逻辑
            # 暂时自动执行强制推送
            remote_name = current_branch.tracking_branch().remote_name
            branch_name = current_branch.name
            
            console.print(f"[bold]强制推送到 {remote_name}/{branch_name}...[/bold]")
            self.git_ops.repo.git.push('--force-with-lease', remote_name, branch_name)
            
            console.print("[green]✓ 强制推送完成[/green]")
            
        except Exception as e:
            console.print(f"[red]✗ 强制推送失败: {e}[/red]")
            logger.exception("强制推送失败")
            # 不抛出异常，因为推送失败不应该阻止本地重写
    
    def _update_state_after_rebase_all(self, commit_messages: Dict[str, str]) -> None:
        """在 rebase 后更新所有处理过的提交的状态."""
        try:
            # 获取当前 HEAD 作为新的提交哈希
            current_head = self.git_ops.repo.head.commit.hexsha
            
            # 更新所有处理过的提交状态
            processed_count = 0
            for commit_hash, new_message in commit_messages.items():
                self.state_manager.mark_commit_processed(commit_hash, 'done')
                self.state_manager.save_hash_mapping(commit_hash, current_head)
                processed_count += 1
            
            # 更新会话状态中的已处理提交数量
            current_state = self.state_manager.get_current_state()
            if current_state:
                total_processed = current_state.get('processed_commits', 0) + processed_count
                self.state_manager.update_session(processed_commits=total_processed)
            
            console.print(f"[dim]状态已更新: {processed_count} 个提交已处理[/dim]")
            
        except Exception as e:
            console.print(f"[yellow]⚠ 更新状态失败: {e}[/yellow]")
            logger.warning(f"更新状态失败: {e}")
    
    def _cleanup_dangling_objects(self) -> None:
        """清理悬空对象."""
        try:
            # 运行 git gc 清理悬空对象
            self.git_ops.repo.git.gc('--prune=now')
            console.print("[green]✓ 已清理悬空对象[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠ 清理悬空对象失败: {e}[/yellow]")
            logger.warning(f"清理悬空对象失败: {e}")
    
    
    def _verify_results(self) -> None:
        """验证结果."""
        console.print("[bold]验证结果...[/bold]")
        
        # 验证仓库完整性
        if self.config_manager.get('safety.verify_integrity', True):
            if self.git_ops.verify_integrity():
                console.print("[green]✓ 仓库完整性验证通过[/green]")
            else:
                console.print("[red]✗ 仓库完整性验证失败[/red]")
        
        # 显示统计信息
        stats = self.state_manager.get_statistics()
        self._display_final_stats(stats)
        
        # 显示备份信息，让用户自己检查和清理
        if not self.dry_run and stats.get('backup_branch'):
            from rich.panel import Panel
            console.print(Panel(
                f"[bold yellow]重要提醒：[/bold yellow]\n\n"
                f"程序已保留备份分支和文件以供您检查。\n\n"
                f"[bold]备份分支:[/bold] {stats['backup_branch']}\n"
                f"[bold]回滚命令:[/bold] git reset --hard {stats['backup_branch']}\n\n"
                f"请检查目标仓库的文件是否完整。\n"
                f"确认无误后，可以手动删除备份分支：\n"
                f"[bold]git branch -D {stats['backup_branch']}[/bold]\n\n"
                f"如发现文件丢失，请使用备份分支恢复。",
                title="备份信息",
                border_style="yellow"
            ))
        
        # 不自动清理数据库文件，让用户手动处理
        console.print("[yellow]数据库文件已保留，如需清理请手动删除[/yellow]")
    
    def _display_final_stats(self, stats: Dict[str, Any]) -> None:
        """显示最终统计信息."""
        table = Table(title="处理统计")
        table.add_column("项目", style="cyan")
        table.add_column("数量", style="magenta")
        
        table.add_row("总提交数", str(stats['total_commits']))
        table.add_row("已处理", str(stats['processed_commits']))
        table.add_row("进度", f"{stats['progress_percentage']:.1f}%")
        
        # 状态统计
        status_counts = stats.get('status_counts', {})
        for status, count in status_counts.items():
            table.add_row(f"状态: {status}", str(count))
        
        console.print(table)
    
    def analyze_only(self) -> None:
        """仅分析模式."""
        try:
            self.initialize()
            
            # 扫描提交
            commits = self._scan_commits()
            
            # 聚类分析
            groups = self._cluster_commits(commits)
            
            # 显示详细分析
            self._display_detailed_analysis(groups)
            
        except Exception as e:
            console.print(f"[red]分析失败: {e}[/red]")
            raise
        finally:
            # 不自动清理数据库文件，让用户手动处理
            console.print("[yellow]数据库文件已保留，如需清理请手动删除[/yellow]")
    
    def _display_detailed_analysis(self, groups: List[List[Dict[str, Any]]]) -> None:
        """显示详细分析结果."""
        console.print("[bold]详细分析结果:[/bold]")
        
        # 获取提示词模板
        prompts = self.config_manager.get_prompts()
        prompt_template = prompts.get('analyze_diff', '')
        
        for i, group in enumerate(groups):
            console.print(f"\n[bold cyan]分组 {i+1}[/bold cyan] ({len(group)} 个提交):")
            
            for j, commit in enumerate(group):
                console.print(f"  {j+1}. {commit['hash'][:8]}: {commit['message']}")
            
            # 显示 AI 生成的新 message（预览）
            try:
                if len(group) == 1:
                    # 单个提交重写
                    new_message = self.ai_rewriter.rewrite_single_commit(group[0], prompt_template)
                    new_message = self.ai_rewriter.apply_conventional_format(new_message)
                    console.print(f"  [green]→ 重写为: {new_message}[/green]")
                else:
                    # 多个提交合并
                    new_message = self.ai_rewriter.merge_commit_messages(group, prompt_template)
                    new_message = self.ai_rewriter.apply_conventional_format(new_message)
                    console.print(f"  [green]→ 合并为: {new_message}[/green]")
            except Exception as e:
                console.print(f"  [red]→ AI 生成失败: {e}[/red]")
                # 使用降级策略
                fallback_msg = self.ai_rewriter._fallback_generate("")
                console.print(f"  [yellow]→ 降级策略: {fallback_msg}[/yellow]")
    
    def get_status(self) -> Dict[str, Any]:
        """获取当前状态."""
        try:
            self.initialize()
            return self.state_manager.get_statistics()
        except Exception as e:
            console.print(f"[red]获取状态失败: {e}[/red]")
            return {}
        finally:
            # 不自动清理数据库文件，让用户手动处理
            console.print("[yellow]数据库文件已保留，如需清理请手动删除[/yellow]")
    
    def list_backups(self) -> List[str]:
        """列出备份分支."""
        try:
            self.initialize()
            return self.git_ops.get_backup_branches()
        except Exception as e:
            console.print(f"[red]获取备份分支失败: {e}[/red]")
            return []
        finally:
            # 不自动清理数据库文件，让用户手动处理
            console.print("[yellow]数据库文件已保留，如需清理请手动删除[/yellow]")
    
    def rollback(self, backup_branch: str) -> bool:
        """回滚到备份分支."""
        try:
            self.initialize()
            return self.git_ops.reset_to_branch(backup_branch)
        except Exception as e:
            console.print(f"[red]回滚失败: {e}[/red]")
            return False
        finally:
            # 不自动清理数据库文件，让用户手动处理
            console.print("[yellow]数据库文件已保留，如需清理请手动删除[/yellow]")
