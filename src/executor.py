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
            # 清理数据库文件
            self._cleanup_database_file()
    
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

            # 重置到 root 提交
            root_commit = self.git_ops.repo.git.rev_list('--max-parents=0', 'HEAD').strip()
            self.git_ops.repo.git.reset('--hard', root_commit)
            console.print(f"[dim]重置到根提交: {root_commit[:8]}[/dim]")

            # 获取所有提交的有序列表
            all_commits = self.db_manager.get_all_commits()
            sorted_commits = sorted(all_commits, key=lambda x: x['commit_date'])

            # 逐个 cherry-pick 并修改消息
            for i, commit in enumerate(sorted_commits):
                commit_hash = commit['hash']
                progress.update(task, advance=1, description=f"处理提交 {i+1}/{len(sorted_commits)}: {commit_hash[:8]}")

                try:
                    # Cherry-pick 提交
                    self.git_ops.repo.git.cherry_pick(commit_hash, '--allow-empty', '--keep-redundant-commits')
                    
                    # 如果需要修改消息
                    if commit_hash in commit_messages:
                        new_message = commit_messages[commit_hash]
                        self.git_ops.repo.git.commit('--amend', '-m', new_message, '--allow-empty', '--no-edit')
                        console.print(f"[dim]修改提交 {commit_hash[:8]} 的消息[/dim]")
                    
                except Exception as cherry_error:
                    console.print(f"[yellow]Cherry-pick 失败 {commit_hash[:8]}: {cherry_error}[/yellow]")
                    # 尝试继续
                    try:
                        self.git_ops.repo.git.cherry_pick('--continue')
                    except:
                        self.git_ops.repo.git.cherry_pick('--abort')
                        raise cherry_error

            # 切换回原始分支并强制更新
            console.print(f"[dim]切换回分支: {current_branch}[/dim]")
            self.git_ops.repo.git.checkout(current_branch)
            
            console.print(f"[dim]强制更新分支 {current_branch} 到 {temp_branch}[/dim]")
            self.git_ops.repo.git.reset('--hard', temp_branch)
            
            # 删除临时分支
            self.git_ops.repo.git.branch('-D', temp_branch)
            console.print(f"[dim]删除临时分支: {temp_branch}[/dim]")

            console.print("[green]✓ 顺序 cherry-pick 重写完成[/green]")

        except Exception as e:
            console.print(f"[red]顺序重写失败: {e}[/red]")
            # 尝试清理
            try:
                if 'temp_branch' in locals():
                    self.git_ops.repo.git.checkout(current_branch)
                    self.git_ops.repo.git.branch('-D', temp_branch)
            except:
                pass
            raise
    
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
        
        # 显示回滚命令
        if not self.dry_run and stats.get('backup_branch'):
            console.print(Panel(
                f"如需回滚，请执行:\n[bold]git reset --hard {stats['backup_branch']}[/bold]",
                title="回滚命令",
                border_style="yellow"
            ))
    
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
            # 清理数据库文件
            self._cleanup_database_file()
    
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
            # 清理数据库文件
            self._cleanup_database_file()
    
    def list_backups(self) -> List[str]:
        """列出备份分支."""
        try:
            self.initialize()
            return self.git_ops.get_backup_branches()
        except Exception as e:
            console.print(f"[red]获取备份分支失败: {e}[/red]")
            return []
        finally:
            # 清理数据库文件
            self._cleanup_database_file()
    
    def rollback(self, backup_branch: str) -> bool:
        """回滚到备份分支."""
        try:
            self.initialize()
            return self.git_ops.reset_to_branch(backup_branch)
        except Exception as e:
            console.print(f"[red]回滚失败: {e}[/red]")
            return False
        finally:
            # 清理数据库文件
            self._cleanup_database_file()
