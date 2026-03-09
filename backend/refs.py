"""参考文献核查模块 - 解析 + CrossRef 验证 + GB/T 7714 格式检查"""
import asyncio
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx
from rapidfuzz import fuzz

CROSSREF_API = "https://api.crossref.org/works/{doi}"
CROSSREF_SEARCH = "https://api.crossref.org/works"
CROSSREF_TIMEOUT = 8  # 秒


@dataclass
class ParsedRef:
    """解析后的单条参考文献"""
    raw: str                          # 原始文本
    index: int                        # 序号（1-based）
    authors: list[str] = field(default_factory=list)
    title: str = ""
    journal: str = ""
    year: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    ref_type: str = "journal"         # journal / book / other
    is_chinese: bool = False


@dataclass
class RefIssue:
    """单条文献的核查问题"""
    ref_index: int
    raw: str
    severity: str                     # error / warning / info
    category: str                     # format / doi / metadata / citation
    message: str
    suggestion: str = ""


def parse_refs(text: str) -> list[ParsedRef]:
    """从文本中提取并解析参考文献列表"""
    refs = []

    # 先把文本里所有 [数字] 开头的文献条目切分出来
    # 支持同一行多条（如 [40]...[41]...）
    # 用前瞻断言在每个 [数字] 前切分
    entries = re.split(r'(?=\[\d+\])', text)

    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue

        # 提取序号
        idx_m = re.match(r'\[(\d+)\]\s*', entry)
        if not idx_m:
            continue

        idx = int(idx_m.group(1))
        raw = entry[idx_m.end():].strip()
        raw = re.sub(r'\s+', ' ', raw)
        if not raw:
            continue

        ref = ParsedRef(raw=raw, index=idx)
        ref.is_chinese = bool(re.search(r'[\u4e00-\u9fff]', raw))

        # 提取 DOI
        doi_m = re.search(r'(?:doi[:\s]*|https?://doi\.org/)([^\s,，。\]]+)', raw, re.I)
        if doi_m:
            ref.doi = doi_m.group(1).strip().rstrip('.')

        # 提取年份
        year_m = re.search(r'\b(19|20)\d{2}\b', raw)
        if year_m:
            ref.year = year_m.group(0)

        # 判断类型
        if re.search(r'\[M\]|\[M/OL\]', raw):
            ref.ref_type = "book"
        elif re.search(r'\[R\]|\[R/OL\]', raw):
            ref.ref_type = "report"
        elif re.search(r'\[D\]', raw):
            ref.ref_type = "thesis"
        elif re.search(r'\[C\]|\[A\]', raw):
            ref.ref_type = "conference"
        else:
            ref.ref_type = "journal"

        # 提取作者
        author_part = raw.split('.')[0] if '.' in raw else raw[:50]
        ref.authors = [a.strip() for a in re.split(r'[,，;；]', author_part) if a.strip()][:5]

        refs.append(ref)

    return sorted(refs, key=lambda r: r.index)


def check_format(ref: ParsedRef) -> list[RefIssue]:
    """GB/T 7714 格式检查"""
    issues = []

    # 检查文献类型标识（支持全角空格、各种空白前的标识，以及 N/OL 等）
    if not re.search(r'[\s\u3000]*\[(J|M|C|D|R|S|N|EB|OL|J/OL|M/OL|EB/OL|N/OL|C/OL)\]', ref.raw):
        issues.append(RefIssue(
            ref_index=ref.index,
            raw=ref.raw,
            severity="warning",
            category="format",
            message="缺少文献类型标识",
            suggestion="期刊论文应标注[J]，图书标注[M]，学位论文标注[D]"
        ))

    # 检查年份
    if not ref.year:
        issues.append(RefIssue(
            ref_index=ref.index,
            raw=ref.raw,
            severity="error",
            category="format",
            message="未找到出版年份",
        ))

    # 期刊论文检查卷期页码（只对期刊类型，且非中文文献）
    if ref.ref_type == "journal" and not ref.is_chinese:
        if not re.search(r'\d+\s*[(:（]\s*\d+', ref.raw):
            issues.append(RefIssue(
                ref_index=ref.index,
                raw=ref.raw,
                severity="info",
                category="format",
                message="未找到卷(期)信息",
            ))

    # 检查 DOI 格式
    if ref.doi and not re.match(r'^10\.\d{4,}/', ref.doi):
        issues.append(RefIssue(
            ref_index=ref.index,
            raw=ref.raw,
            severity="warning",
            category="doi",
            message=f"DOI 格式异常: {ref.doi}",
            suggestion="DOI 应以 10. 开头，如 10.1000/xyz123"
        ))

    return issues


async def verify_doi(ref: ParsedRef) -> list[RefIssue]:
    """通过 CrossRef API 验证 DOI 并比对元数据"""
    if not ref.doi:
        return []

    issues = []
    try:
        async with httpx.AsyncClient(timeout=CROSSREF_TIMEOUT) as client:
            url = CROSSREF_API.format(doi=ref.doi)
            resp = await client.get(url, headers={"User-Agent": "QKSPARK-Editor/1.0"})

            if resp.status_code == 404:
                issues.append(RefIssue(
                    ref_index=ref.index,
                    raw=ref.raw,
                    severity="error",
                    category="doi",
                    message=f"DOI 无效或不存在: {ref.doi}",
                    suggestion="请核实 DOI 是否正确"
                ))
                return issues

            if resp.status_code != 200:
                return issues  # API 异常，跳过

            data = resp.json().get("message", {})

            # 比对年份
            cr_year = None
            for date_field in ["published-print", "published-online", "issued"]:
                dp = data.get(date_field, {}).get("date-parts", [[]])
                if dp and dp[0]:
                    cr_year = str(dp[0][0])
                    break

            if cr_year and ref.year and cr_year != ref.year:
                issues.append(RefIssue(
                    ref_index=ref.index,
                    raw=ref.raw,
                    severity="warning",
                    category="metadata",
                    message=f"年份不一致：文中写 {ref.year}，CrossRef 记录为 {cr_year}",
                    suggestion=f"建议核实，正确年份可能是 {cr_year}"
                ))

            # 比对标题（使用 rapidfuzz 模糊匹配）
            cr_titles = data.get("title", [])
            if cr_titles and ref.title:
                cr_title = cr_titles[0].strip()
                ref_title = ref.title.strip()
                # token_sort_ratio: 忽略词序，容忍拼写差异
                similarity = fuzz.token_sort_ratio(cr_title, ref_title)
                if similarity < 60:  # 阈值 60%
                    issues.append(RefIssue(
                        ref_index=ref.index,
                        raw=ref.raw,
                        severity="warning",
                        category="metadata",
                        message=f"标题与 CrossRef 记录差异较大（相似度 {similarity}%）",
                        suggestion=f"CrossRef 标题: {cr_titles[0][:80]}"
                    ))

    except (httpx.TimeoutException, httpx.ConnectError):
        # 网络超时，跳过 DOI 验证
        pass
    except Exception:
        pass

    return issues


def check_citation_completeness(ref_list: list[ParsedRef], body_text: str) -> list[RefIssue]:
    """检查正文引用与文献列表的完整性"""
    issues = []

    cited_nums = set()

    # 优先解析前端注入的上标引用标记
    sup_match = re.search(r'\[SUPERSCRIPT_CITATIONS:([\d,]+)\]', body_text)
    if sup_match:
        for n in sup_match.group(1).split(','):
            if n.strip():
                cited_nums.add(int(n.strip()))
    else:
        # 普通方括号引用：[1] [1,2] [1-3]
        for m in re.finditer(r'\[(\d+(?:[,，\s\-–—]*\d+)*)\]', body_text):
            nums_str = m.group(1)
            range_m = re.match(r'(\d+)\s*[-–—]\s*(\d+)', nums_str)
            if range_m:
                for n in range(int(range_m.group(1)), int(range_m.group(2)) + 1):
                    cited_nums.add(n)
            else:
                for n in re.findall(r'\d+', nums_str):
                    cited_nums.add(int(n))

        # 圆圈数字
        circle_map = {'①':1,'②':2,'③':3,'④':4,'⑤':5,'⑥':6,'⑦':7,'⑧':8,'⑨':9,'⑩':10}
        for ch, n in circle_map.items():
            if ch in body_text:
                cited_nums.add(n)

    ref_nums = {r.index for r in ref_list}

    # 没提取到任何引用，跳过
    if not cited_nums:
        return []

    # 正文引用了但文献列表没有
    for n in sorted(cited_nums - ref_nums):
        issues.append(RefIssue(
            ref_index=n,
            raw="",
            severity="error",
            category="citation",
            message=f"正文引用了 [{n}]，但参考文献列表中不存在该编号",
        ))

    # 文献列表有但正文未引用（最多显示10条）
    unreferenced = sorted(ref_nums - cited_nums)
    for n in unreferenced[:10]:
        ref = next((r for r in ref_list if r.index == n), None)
        raw_preview = (ref.raw[:50] + "...") if ref else ""
        issues.append(RefIssue(
            ref_index=n,
            raw=raw_preview,
            severity="info",
            category="citation",
            message=f"参考文献 [{n}] 在正文中未被引用",
        ))
    if len(unreferenced) > 10:
        issues.append(RefIssue(
            ref_index=0,
            raw="",
            severity="info",
            category="citation",
            message=f"另有 {len(unreferenced) - 10} 条文献未被引用（已省略）",
        ))

    return issues


def find_duplicate_refs(ref_list: list[ParsedRef]) -> list[RefIssue]:
    """检测重复文献（基于 rapidfuzz 模糊匹配）"""
    issues = []
    checked_pairs = set()
    
    for i in range(len(ref_list)):
        for j in range(i + 1, len(ref_list)):
            if (i, j) in checked_pairs:
                continue
            
            ref_i = ref_list[i]
            ref_j = ref_list[j]
            
            # 标题相似度（token_sort_ratio 忽略词序）
            title_score = 0
            if ref_i.title and ref_j.title:
                title_score = fuzz.token_sort_ratio(ref_i.title, ref_j.title)
            
            # 作者相似度
            author_score = 0
            if ref_i.authors and ref_j.authors:
                authors_i = ', '.join(ref_i.authors[:3])
                authors_j = ', '.join(ref_j.authors[:3])
                author_score = fuzz.token_sort_ratio(authors_i, authors_j)
            
            # 综合得分：标题权重 70%，作者权重 30%
            combined_score = title_score * 0.7 + author_score * 0.3
            
            # 阈值 85% 认为是重复
            if combined_score > 85:
                checked_pairs.add((i, j))
                issues.append(RefIssue(
                    ref_index=ref_j.index,
                    raw=ref_j.raw[:80] + "..." if len(ref_j.raw) > 80 else ref_j.raw,
                    severity="warning",
                    category="duplicate",
                    message=f"疑似与文献 [{ref_i.index}] 重复（相似度 {int(combined_score)}%）",
                    suggestion=f"请核实是否为同一文献"
                ))
    
    return issues


async def check_refs(refs_text: str, body_text: str = "", verify_dois: bool = True) -> dict:
    """主入口：解析 + 格式检查 + DOI 验证 + 引用完整性"""
    refs = parse_refs(refs_text)
    if not refs:
        return {"refs_count": 0, "issues": [], "summary": "未找到参考文献列表"}

    all_issues: list[RefIssue] = []

    # 格式检查（同步）
    for ref in refs:
        all_issues.extend(check_format(ref))

    # DOI 验证（并行，最多 5 路）
    if verify_dois:
        refs_with_doi = [r for r in refs if r.doi]
        if refs_with_doi:
            sem = asyncio.Semaphore(5)
            async def _verify(ref):
                async with sem:
                    return await verify_doi(ref)
            doi_results = await asyncio.gather(*[_verify(r) for r in refs_with_doi])
            for result in doi_results:
                all_issues.extend(result)

    # 引用完整性检查
    if body_text:
        all_issues.extend(check_citation_completeness(refs, body_text))

    # 文献去重检测
    all_issues.extend(find_duplicate_refs(refs))

    # 统计
    errors = sum(1 for i in all_issues if i.severity == "error")
    warnings = sum(1 for i in all_issues if i.severity == "warning")
    infos = sum(1 for i in all_issues if i.severity == "info")

    summary = f"共 {len(refs)} 条文献，发现 {errors} 个错误、{warnings} 个警告、{infos} 条建议"

    return {
        "refs_count": len(refs),
        "issues": [
            {
                "ref_index": i.ref_index,
                "raw": i.raw,
                "severity": i.severity,
                "category": i.category,
                "message": i.message,
                "suggestion": i.suggestion,
            }
            for i in sorted(all_issues, key=lambda x: (x.ref_index, x.severity))
        ],
        "summary": summary,
        "stats": {"error": errors, "warning": warnings, "info": infos},
    }


def analyze_refs_statistics(refs_text: str) -> dict:
    """参考文献统计分析"""
    refs = parse_refs(refs_text)
    if not refs:
        return {"total": 0}
    
    # 基础统计
    total = len(refs)
    with_doi = sum(1 for r in refs if r.doi)
    
    # 年份分布
    year_dist = {}
    for ref in refs:
        if ref.year:
            year_dist[ref.year] = year_dist.get(ref.year, 0) + 1
    
    # 类型分布
    type_dist = {}
    for ref in refs:
        ref_type = ref.ref_type or "未知"
        type_dist[ref_type] = type_dist.get(ref_type, 0) + 1
    
    # 中英文文献统计（简单判断：含中文字符）
    chinese_count = sum(1 for r in refs if re.search(r'[\u4e00-\u9fa5]', r.raw))
    
    # 期刊分布 TOP 5（从原始文本粗提取期刊名）
    journal_dist = {}
    for ref in refs:
        # 尝试提取期刊名（[J]. 后到逗号之间）
        m = re.search(r'\[J\]\.?\s*(.+?),', ref.raw)
        if m:
            journal = m.group(1).strip()[:50]  # 限制长度
            journal_dist[journal] = journal_dist.get(journal, 0) + 1
    
    journal_top5 = sorted(journal_dist.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # 年份警告（超过 30% 文献 > 10 年）
    import datetime
    current_year = datetime.datetime.now().year
    old_refs = sum(1 for r in refs if r.year and (current_year - int(r.year)) > 10)
    year_warning = None
    if old_refs / total > 0.3:
        year_warning = f"有 {old_refs} 条文献（{old_refs/total*100:.1f}%）发表于 10 年前，建议补充近期文献"
    
    return {
        "total": total,
        "with_doi": with_doi,
        "chinese": chinese_count,
        "english": total - chinese_count,
        "year_dist": dict(sorted(year_dist.items())),
        "type_dist": type_dist,
        "journal_top5": [{"journal": j, "count": c} for j, c in journal_top5],
        "year_warning": year_warning,
    }

