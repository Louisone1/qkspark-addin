"""
参考文献规则引擎（前置过滤层）
用 rapidfuzz + 正则做确定性检查，减少 LLM 调用
"""
import re
from typing import List, Dict, Any
from rapidfuzz import fuzz

def check_format_rules(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    规则引擎：格式检查
    返回问题列表，格式与 LLM 输出一致
    """
    issues = []
    
    for ref in refs:
        ref_num = ref.get('ref_num', '?')
        text = ref.get('text', '')
        
        # 规则 1：缺少必要字段（作者、标题、年份）
        if not re.search(r'[\u4e00-\u9fa5a-zA-Z]{2,}', text):  # 没有作者名
            issues.append({
                'ref_num': ref_num,
                'severity': 'error',
                'category': 'format',
                'message': '缺少作者信息',
                'suggestion': '请补充作者姓名'
            })
        
        if not re.search(r'\d{4}', text):  # 没有年份
            issues.append({
                'ref_num': ref_num,
                'severity': 'error',
                'category': 'format',
                'message': '缺少出版年份',
                'suggestion': '请补充年份（如 2020）'
            })
        
        # 规则 2：标点符号错误（中文文献用中文标点，英文用英文标点）
        has_chinese = bool(re.search(r'[\u4e00-\u9fa5]', text))
        if has_chinese:
            # 中文文献应该用中文标点
            if re.search(r'[,;:](?![0-9])', text):  # 英文标点后不是数字
                issues.append({
                    'ref_num': ref_num,
                    'severity': 'warning',
                    'category': 'format',
                    'message': '中文文献应使用中文标点符号',
                    'suggestion': '将英文逗号、分号改为中文标点'
                })
        
        # 规则 3：页码格式（应为 123-456 或 123）
        page_match = re.search(r'[:：]\s*(\d+[-~]\d+|\d+)\s*[\.。]?\s*$', text)
        if page_match:
            pages = page_match.group(1)
            if '~' in pages:
                issues.append({
                    'ref_num': ref_num,
                    'severity': 'warning',
                    'category': 'format',
                    'message': '页码分隔符应使用短横线',
                    'suggestion': f'将 {pages} 改为 {pages.replace("~", "-")}'
                })
        
        # 规则 4：期刊标识符检查
        if '[J]' in text or '[M]' in text or '[C]' in text:
            # 检查标识符前是否有句号
            if not re.search(r'\.\s*\[J\]|\.\s*\[M\]|\.\s*\[C\]', text):
                issues.append({
                    'ref_num': ref_num,
                    'severity': 'warning',
                    'category': 'format',
                    'message': '文献类型标识符前应有句号',
                    'suggestion': '在 [J]/[M]/[C] 前加句号'
                })
    
    return issues


def check_duplicate_rules(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    规则引擎：去重检查（基于 rapidfuzz）
    """
    issues = []
    n = len(refs)
    
    for i in range(n):
        for j in range(i + 1, n):
            ref_i = refs[i]
            ref_j = refs[j]
            
            text_i = ref_i.get('text', '')
            text_j = ref_j.get('text', '')
            
            # 提取标题（简化版：取第一个句号前的内容）
            title_i = text_i.split('.')[0] if '.' in text_i else text_i[:50]
            title_j = text_j.split('.')[0] if '.' in text_j else text_j[:50]
            
            # 标题相似度
            title_sim = fuzz.token_sort_ratio(title_i, title_j)
            
            # 提取作者（简化版：取前 20 字符）
            author_i = text_i[:20]
            author_j = text_j[:20]
            author_sim = fuzz.ratio(author_i, author_j)
            
            # 综合相似度（标题 70% + 作者 30%）
            combined_sim = title_sim * 0.7 + author_sim * 0.3
            
            if combined_sim >= 85:
                issues.append({
                    'ref_num': f"{ref_i.get('ref_num', '?')} & {ref_j.get('ref_num', '?')}",
                    'severity': 'warning',
                    'category': 'duplicate',
                    'message': f'疑似重复文献（相似度 {combined_sim:.0f}%）',
                    'suggestion': '请检查是否为同一文献的不同版本'
                })
    
    return issues


def check_year_rules(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    规则引擎：年份检查
    """
    issues = []
    current_year = 2026  # 可以从系统获取
    
    for ref in refs:
        text = ref.get('text', '')
        ref_num = ref.get('ref_num', '?')
        
        # 提取年份
        year_match = re.search(r'\b(19|20)\d{2}\b', text)
        if year_match:
            year = int(year_match.group(0))
            
            # 年份过旧（超过 15 年）
            if current_year - year > 15:
                issues.append({
                    'ref_num': ref_num,
                    'severity': 'info',
                    'category': 'metadata',
                    'message': f'文献年份较旧（{year}）',
                    'suggestion': '建议引用更新的文献'
                })
            
            # 年份未来
            if year > current_year:
                issues.append({
                    'ref_num': ref_num,
                    'severity': 'error',
                    'category': 'metadata',
                    'message': f'年份异常（{year}）',
                    'suggestion': '请检查年份是否正确'
                })
    
    return issues


def run_rule_engine(refs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    运行完整规则引擎
    返回：{
        'issues': [...],
        'stats': {'total_checks': N, 'issues_found': M}
    }
    """
    all_issues = []
    
    # 格式检查
    all_issues.extend(check_format_rules(refs))
    
    # 去重检查
    all_issues.extend(check_duplicate_rules(refs))
    
    # 年份检查
    all_issues.extend(check_year_rules(refs))
    
    return {
        'issues': all_issues,
        'stats': {
            'total_checks': len(refs),
            'issues_found': len(all_issues)
        }
    }
