"""聚类算法模块 - 基于 diff 的相似度计算和连续性约束."""

import logging
from typing import List, Dict, Any, Tuple, Generator
from collections import defaultdict

from .utils import calculate_text_similarity, calculate_path_similarity, safe_json_loads

logger = logging.getLogger(__name__)


class CommitClusterer:
    """提交聚类器."""
    
    def __init__(self, db_manager, threshold: float = 0.8, max_group_size: int = 10):
        """初始化聚类器.
        
        Args:
            db_manager: 数据库管理器
            threshold: 相似度阈值
            max_group_size: 最大分组大小
        """
        self.db_manager = db_manager
        self.threshold = threshold
        self.max_group_size = max_group_size
        self.mapping = {}  # 哈希映射缓存
    
    def analyze_similarity(self, commits: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """分析提交相似度并生成分组.
        
        Args:
            commits: 提交列表
            
        Returns:
            分组列表
        """
        if not commits:
            return []
        
        # 加载哈希映射
        self.mapping = self.db_manager.get_all_mappings()
        
        # 按时间排序（oldest -> newest）
        sorted_commits = sorted(commits, key=lambda x: x['commit_date'])
        
        # 应用聚类算法
        groups = list(self._find_groups(sorted_commits))
        
        # 保存分组到数据库
        for i, group in enumerate(groups):
            similarities = self._calculate_group_similarities(group)
            self.db_manager.save_commit_group(i, group, similarities)
        
        logger.info(f"聚类完成，共生成 {len(groups)} 个分组")
        return groups
    
    def _find_groups(self, commits: List[Dict[str, Any]]) -> Generator[List[Dict[str, Any]], None, None]:
        """查找相似提交分组（修正版算法）.
        
        Args:
            commits: 按时间排序的提交列表
            
        Yields:
            提交分组
        """
        if not commits:
            return
        
        # 第一个提交直接开始新分组
        group = [commits[0]]
        
        for commit in commits[1:]:
            # 1. 检查连续性
            if not self._is_continuous(commit, group[-1]):
                yield group
                group = [commit]
                continue
            
            # 2. 检查分组大小限制
            if len(group) >= self.max_group_size:
                yield group
                group = [commit]
                continue
            
            # 3. 计算相似度
            similarity = self._calculate_diff_similarity(
                commit['diff_content'],
                group[-1]['diff_content'],
                commit.get('modified_files', '[]'),
                group[-1].get('modified_files', '[]')
            )
            
            if similarity > self.threshold:
                group.append(commit)
            else:
                yield group
                group = [commit]
        
        # 处理最后一个分组
        if group:
            yield group
    
    def _is_continuous(self, commit_a: Dict[str, Any], commit_b: Dict[str, Any]) -> bool:
        """检查两个提交是否连续.
        
        Args:
            commit_a: 提交 A
            commit_b: 提交 B
            
        Returns:
            是否连续
        """
        # 检查 A 的父提交是否是 B（或其映射）
        parent_hash = commit_a.get('parent_hash')
        if not parent_hash:
            return False
        
        # 如果 B 已被重写，检查映射
        b_hash = commit_b['hash']
        if b_hash in self.mapping:
            b_hash = self.mapping[b_hash]
        
        return parent_hash == b_hash
    
    def _calculate_diff_similarity(self, diff1: str, diff2: str, 
                                 files1_str: str, files2_str: str) -> float:
        """计算两个提交的相似度.
        
        Args:
            diff1: 第一个提交的 diff
            diff2: 第二个提交的 diff
            files1_str: 第一个提交的文件列表（JSON 字符串）
            files2_str: 第二个提交的文件列表（JSON 字符串）
            
        Returns:
            相似度分数 (0.0 - 1.0)
        """
        # 解析文件列表
        files1 = safe_json_loads(files1_str, [])
        files2 = safe_json_loads(files2_str, [])
        
        # 1. 文件路径相似度（权重 0.4）
        path_sim = calculate_path_similarity(files1, files2)
        
        # 2. diff 内容相似度（权重 0.6）
        diff_sim = self._calculate_diff_content_similarity(diff1, diff2)
        
        # 加权平均
        similarity = 0.4 * path_sim + 0.6 * diff_sim
        
        return similarity
    
    def _calculate_diff_content_similarity(self, diff1: str, diff2: str) -> float:
        """计算 diff 内容的相似度.
        
        Args:
            diff1: 第一个 diff
            diff2: 第二个 diff
            
        Returns:
            相似度分数
        """
        if not diff1 or not diff2:
            return 0.0
        
        # 方法 1: 简单文本相似度
        text_sim = calculate_text_similarity(diff1, diff2)
        
        # 方法 2: 基于行级别的相似度
        line_sim = self._calculate_line_similarity(diff1, diff2)
        
        # 取平均值
        return (text_sim + line_sim) / 2
    
    def _calculate_line_similarity(self, diff1: str, diff2: str) -> float:
        """计算基于行的相似度.
        
        Args:
            diff1: 第一个 diff
            diff2: 第二个 diff
            
        Returns:
            相似度分数
        """
        lines1 = set(diff1.split('\n'))
        lines2 = set(diff2.split('\n'))
        
        if not lines1 and not lines2:
            return 1.0
        
        # 过滤掉空行和纯符号行
        lines1 = {line for line in lines1 if line.strip() and not line.startswith(('+++', '---', '@@'))}
        lines2 = {line for line in lines2 if line.strip() and not line.startswith(('+++', '---', '@@'))}
        
        if not lines1 and not lines2:
            return 1.0
        
        intersection = len(lines1.intersection(lines2))
        union = len(lines1.union(lines2))
        
        return intersection / union if union > 0 else 0.0
    
    def _calculate_group_similarities(self, group: List[Dict[str, Any]]) -> List[float]:
        """计算分组内各提交的相似度.
        
        Args:
            group: 提交分组
            
        Returns:
            相似度列表
        """
        similarities = []
        
        for i, commit in enumerate(group):
            if i == 0:
                # 第一个提交，相似度为 1.0
                similarities.append(1.0)
            else:
                # 与前一个提交的相似度
                similarity = self._calculate_diff_similarity(
                    commit['diff_content'],
                    group[i-1]['diff_content'],
                    commit.get('modified_files', '[]'),
                    group[i-1].get('modified_files', '[]')
                )
                similarities.append(similarity)
        
        return similarities
    
    def get_group_statistics(self, groups: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """获取分组统计信息.
        
        Args:
            groups: 分组列表
            
        Returns:
            统计信息
        """
        if not groups:
            return {
                'total_groups': 0,
                'total_commits': 0,
                'single_commits': 0,
                'merged_groups': 0,
                'avg_group_size': 0.0
            }
        
        total_commits = sum(len(group) for group in groups)
        single_commits = sum(1 for group in groups if len(group) == 1)
        merged_groups = len(groups) - single_commits
        avg_group_size = total_commits / len(groups)
        
        return {
            'total_groups': len(groups),
            'total_commits': total_commits,
            'single_commits': single_commits,
            'merged_groups': merged_groups,
            'avg_group_size': avg_group_size
        }
    
    def analyze_file_patterns(self, groups: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """分析文件模式.
        
        Args:
            groups: 分组列表
            
        Returns:
            文件模式分析结果
        """
        file_frequency = defaultdict(int)
        file_groups = defaultdict(list)
        
        for group_id, group in enumerate(groups):
            group_files = set()
            for commit in group:
                files = safe_json_loads(commit.get('modified_files', '[]'), [])
                for file_path in files:
                    file_frequency[file_path] += 1
                    group_files.add(file_path)
            
            for file_path in group_files:
                file_groups[file_path].append(group_id)
        
        # 找出最常修改的文件
        most_modified = sorted(file_frequency.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # 找出只在一个分组中出现的文件
        single_group_files = [f for f, groups in file_groups.items() if len(groups) == 1]
        
        return {
            'most_modified_files': most_modified,
            'single_group_files': single_group_files,
            'total_unique_files': len(file_frequency)
        }
    
    def validate_groups(self, groups: List[List[Dict[str, Any]]]) -> List[str]:
        """验证分组的有效性.
        
        Args:
            groups: 分组列表
            
        Returns:
            验证错误列表
        """
        errors = []
        
        for i, group in enumerate(groups):
            # 检查分组大小
            if len(group) > self.max_group_size:
                errors.append(f"分组 {i} 超过最大大小限制: {len(group)} > {self.max_group_size}")
            
            # 检查连续性
            for j in range(1, len(group)):
                if not self._is_continuous(group[j], group[j-1]):
                    errors.append(f"分组 {i} 中的提交不连续: {group[j-1]['hash'][:8]} -> {group[j]['hash'][:8]}")
            
            # 检查相似度
            for j in range(1, len(group)):
                similarity = self._calculate_diff_similarity(
                    group[j]['diff_content'],
                    group[j-1]['diff_content'],
                    group[j].get('modified_files', '[]'),
                    group[j-1].get('modified_files', '[]')
                )
                if similarity <= self.threshold:
                    errors.append(f"分组 {i} 中提交相似度过低: {similarity:.3f} <= {self.threshold}")
        
        return errors
