"""CLI 入口模块."""

import typer
from typing import Optional
from rich.console import Console

from .executor import RewriteExecutor

app = typer.Typer(
    name="git-ai-rewrite",
    help="AI-powered Git history rewriter",
    add_completion=False
)
console = Console()


@app.command()
def analyze(
    config: str = typer.Option("config.yaml", "--config", "-c", help="配置文件路径"),
    threshold: float = typer.Option(0.8, "--threshold", "-t", help="相似度阈值"),
    max_group: int = typer.Option(10, "--max-group", "-g", help="最大分组大小")
):
    """分析相似提交，显示聚类结果."""
    try:
        executor = RewriteExecutor(config, dry_run=True)
        
        # 更新配置
        executor.config_manager.update_config('clustering.similarity_threshold', threshold)
        executor.config_manager.update_config('clustering.max_group_size', max_group)
        
        executor.analyze_only()
        
    except Exception as e:
        console.print(f"[red]分析失败: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="预览模式，不修改仓库"),
    apply: bool = typer.Option(False, "--apply", help="实际执行修改"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="配置文件路径"),
    threshold: float = typer.Option(0.8, "--threshold", "-t", help="相似度阈值"),
    max_group: int = typer.Option(10, "--max-group", "-g", help="最大分组大小")
):
    """执行 Git 历史重写."""
    try:
        # 确定是否为 dry-run 模式
        if apply and dry_run:
            console.print("[red]错误: 不能同时使用 --dry-run 和 --apply[/red]")
            raise typer.Exit(1)
        
        # 如果两个选项都没有指定，默认为 dry-run
        if not apply and not dry_run:
            dry_run = True
        
        if apply:
            dry_run = False
        
        executor = RewriteExecutor(config, dry_run=dry_run)
        
        # 更新配置
        executor.config_manager.update_config('clustering.similarity_threshold', threshold)
        executor.config_manager.update_config('clustering.max_group_size', max_group)
        
        if dry_run:
            console.print("[yellow]运行在 DRY-RUN 模式，不会修改仓库[/yellow]")
        else:
            console.print("[red]运行在 APPLY 模式，将实际修改仓库[/red]")
            confirm = typer.confirm("确认继续？")
            if not confirm:
                console.print("已取消")
                raise typer.Exit(0)
        
        executor.run()
        
    except Exception as e:
        console.print(f"[red]执行失败: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def resume(
    config: str = typer.Option("config.yaml", "--config", "-c", help="配置文件路径")
):
    """从断点恢复执行."""
    try:
        executor = RewriteExecutor(config, dry_run=False)
        executor.run()  # run 方法会自动检测并恢复
        
    except Exception as e:
        console.print(f"[red]恢复失败: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def status(
    config: str = typer.Option("config.yaml", "--config", "-c", help="配置文件路径")
):
    """查看当前状态."""
    try:
        executor = RewriteExecutor(config, dry_run=True)
        stats = executor.get_status()
        
        if not stats:
            console.print("[yellow]没有找到状态信息[/yellow]")
            return
        
        # 显示状态信息
        console.print("[bold]当前状态:[/bold]")
        console.print(f"分支: {stats.get('current_branch', 'N/A')}")
        console.print(f"备份分支: {stats.get('backup_branch', 'N/A')}")
        console.print(f"当前位置: {stats.get('current_position', 'N/A')}")
        console.print(f"总提交数: {stats.get('total_commits', 0)}")
        console.print(f"已处理: {stats.get('processed_commits', 0)}")
        console.print(f"进度: {stats.get('progress_percentage', 0):.1f}%")
        
        # 状态统计
        status_counts = stats.get('status_counts', {})
        if status_counts:
            console.print("\n[bold]状态统计:[/bold]")
            for status, count in status_counts.items():
                console.print(f"  {status}: {count}")
        
    except Exception as e:
        console.print(f"[red]获取状态失败: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def list_backups(
    config: str = typer.Option("config.yaml", "--config", "-c", help="配置文件路径")
):
    """列出所有备份分支."""
    try:
        executor = RewriteExecutor(config, dry_run=True)
        backups = executor.list_backups()
        
        if not backups:
            console.print("[yellow]没有找到备份分支[/yellow]")
            return
        
        console.print("[bold]备份分支列表:[/bold]")
        for backup in backups:
            console.print(f"  {backup}")
        
    except Exception as e:
        console.print(f"[red]获取备份分支失败: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def rollback(
    backup: str = typer.Argument(..., help="备份分支名称"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="配置文件路径")
):
    """回滚到指定的备份分支."""
    try:
        executor = RewriteExecutor(config, dry_run=False)
        
        # 确认回滚
        console.print(f"[red]警告: 这将重置仓库到备份分支 {backup}[/red]")
        confirm = typer.confirm("确认回滚？")
        if not confirm:
            console.print("已取消")
            raise typer.Exit(0)
        
        success = executor.rollback(backup)
        if success:
            console.print(f"[green]✓ 已回滚到 {backup}[/green]")
        else:
            console.print(f"[red]✗ 回滚失败[/red]")
            raise typer.Exit(1)
        
    except Exception as e:
        console.print(f"[red]回滚失败: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def init(
    repo_path: str = typer.Argument(..., help="目标仓库路径"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="配置文件路径"),
    branch: str = typer.Option("main", "--branch", "-b", help="目标分支"),
    api_key: str = typer.Option(None, "--api-key", help="AI API Key")
):
    """初始化配置文件."""
    try:
        from .config import ConfigManager
        
        # 创建默认配置
        config_manager = ConfigManager(config)
        
        # 更新配置
        config_manager.update_config('repository.path', repo_path)
        config_manager.update_config('repository.branch', branch)
        
        if api_key:
            config_manager.update_config('ai.api_key', api_key)
        
        # 保存配置
        config_manager.save_config()
        
        console.print(f"[green]✓ 配置文件已创建: {config}[/green]")
        console.print(f"仓库路径: {repo_path}")
        console.print(f"分支: {branch}")
        if api_key:
            console.print("API Key: 已设置")
        else:
            console.print("[yellow]请手动设置 AI API Key[/yellow]")
        
    except Exception as e:
        console.print(f"[red]初始化失败: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def version():
    """显示版本信息."""
    from . import __version__
    console.print(f"Auto Git Rewriter v{__version__}")


if __name__ == "__main__":
    app()
