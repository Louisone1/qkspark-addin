"""QKSPARK Word Plugin MVP - FastAPI 主入口"""
import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import httpx

from config import HOST, PORT, DEFAULT_MODEL, FALLBACK_MODEL
from models import (
    TermCheckRequest, TermCheckResponse, TermIssue,
    PolishRequest, PolishResponse, PolishChange,
    ProofreadRequest, ProofreadResponse, ProofreadIssue, ProofreadStats,
    RefCheckRequest, RefCheckResponse, RefIssueModel,
    HealthResponse,
)
from llm import chat
from prompts import (
    TERMINOLOGY_CHECK_SYSTEM, TERMINOLOGY_CHECK_USER,
    POLISH_SYSTEM, POLISH_USER,
    PROOFREAD_SYSTEM, PROOFREAD_USER,
    REFS_CHECK_SYSTEM, REFS_CHECK_USER,
)
import rag
from refs import check_refs

# 并行编校的最大并发数
PROOFREAD_CONCURRENCY = 4


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"🔥 QKSPARK 后端启动 | 默认模型: {DEFAULT_MODEL} | 备用: {FALLBACK_MODEL}")
    yield
    print("QKSPARK 后端关闭")


app = FastAPI(
    title="QKSPARK Word Plugin API",
    version="0.1.0",
    lifespan=lifespan,
)

AUDIT_LOG_PATH = Path(__file__).parent / "logs" / "audit.log"
AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

PROOFREAD_MAX_BATCH_CHARS = 3000


def write_audit(event: str, endpoint: str, request_id: str, payload: dict | None = None, result: dict | None = None, error: str | None = None):
    """追加审计日志（JSONL）"""
    record = {
        "ts": datetime.now().isoformat(),
        "event": event,
        "endpoint": endpoint,
        "request_id": request_id,
    }
    if payload is not None:
        record["payload"] = payload
    if result is not None:
        record["result"] = result
    if error is not None:
        record["error"] = error

    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# CORS - Word Add-in 需要跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发阶段放开，生产收紧
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_json(text: str) -> dict:
    """从 LLM 返回中提取 JSON，兼容 markdown 代码块包裹"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 去掉 ```json ... ```
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)


def _split_proofread_batches(paragraphs: list[dict], max_chars: int = PROOFREAD_MAX_BATCH_CHARS) -> list[list[dict]]:
    """按总字符数分批，单批不超过 max_chars（段落过长时单段独立成批）。"""
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_chars = 0

    for para in paragraphs:
        text = para.get("text", "")
        para_chars = len(text)

        # 当前批次非空且加入后会超长 -> 先落盘当前批次
        if current_batch and (current_chars + para_chars > max_chars):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(para)
        current_chars += para_chars

        # 单段本身超长，单独作为一个批次
        if current_chars >= max_chars:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

    if current_batch:
        batches.append(current_batch)

    return batches


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse()


@app.post("/api/check-terms", response_model=TermCheckResponse)
async def check_terms(req: TermCheckRequest, request: Request):
    """术语规范检查"""
    request_id = request.headers.get("x-request-id", "") or f"terms-{int(datetime.now().timestamp() * 1000)}"
    payload = {
        "text_len": len(req.text),
        "model": req.model or DEFAULT_MODEL,
    }

    messages = [
        {"role": "system", "content": TERMINOLOGY_CHECK_SYSTEM},
        {"role": "user", "content": TERMINOLOGY_CHECK_USER.format(text=req.text)},
    ]
    model = req.model or DEFAULT_MODEL
    try:
        raw = await chat(messages, model=model)
        data = _parse_json(raw)
        issues = [TermIssue(**item) for item in data.get("issues", [])]
        resp = TermCheckResponse(
            issues=issues,
            summary=data.get("summary", ""),
            model_used=model,
        )
        write_audit(
            event="check_terms.success",
            endpoint="/api/check-terms",
            request_id=request_id,
            payload=payload,
            result={"issues_count": len(issues), "model_used": model},
        )
        return resp
    except json.JSONDecodeError:
        write_audit(
            event="check_terms.error",
            endpoint="/api/check-terms",
            request_id=request_id,
            payload=payload,
            error="JSONDecodeError: 模型返回格式异常",
        )
        raise HTTPException(status_code=502, detail="模型返回格式异常，请重试")
    except Exception as e:
        write_audit(
            event="check_terms.error",
            endpoint="/api/check-terms",
            request_id=request_id,
            payload=payload,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/polish", response_model=PolishResponse)
async def polish(req: PolishRequest, request: Request):
    """段落级学术润色"""
    request_id = request.headers.get("x-request-id", "") or f"polish-{int(datetime.now().timestamp() * 1000)}"
    payload = {
        "text_len": len(req.text),
        "mode": req.mode,
        "model": req.model or DEFAULT_MODEL,
    }

    messages = [
        {"role": "system", "content": POLISH_SYSTEM},
        {"role": "user", "content": POLISH_USER.format(text=req.text, mode=req.mode)},
    ]
    model = req.model or DEFAULT_MODEL
    try:
        raw = await chat(messages, model=model)
        data = _parse_json(raw)
        changes = [PolishChange(**item) for item in data.get("changes", [])]
        resp = PolishResponse(
            polished=data.get("polished", ""),
            changes=changes,
            summary=data.get("summary", ""),
            model_used=model,
        )
        write_audit(
            event="polish.success",
            endpoint="/api/polish",
            request_id=request_id,
            payload=payload,
            result={"changes_count": len(changes), "model_used": model},
        )
        return resp
    except json.JSONDecodeError:
        write_audit(
            event="polish.error",
            endpoint="/api/polish",
            request_id=request_id,
            payload=payload,
            error="JSONDecodeError: 模型返回格式异常",
        )
        raise HTTPException(status_code=502, detail="模型返回格式异常，请重试")
    except Exception as e:
        write_audit(
            event="polish.error",
            endpoint="/api/polish",
            request_id=request_id,
            payload=payload,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/proofread", response_model=ProofreadResponse)
async def proofread(req: ProofreadRequest, request: Request):
    """全文语言编校（Layer 1）— 支持 RAG 知识库增强 + 并行批次"""
    request_id = request.headers.get("x-request-id", "") or f"proofread-{int(datetime.now().timestamp() * 1000)}"
    model = req.model or DEFAULT_MODEL

    paragraph_dicts = [{"index": p.index, "text": p.text} for p in req.paragraphs]
    batches = _split_proofread_batches(paragraph_dicts)

    # RAG 检索：用前几段文本作为 query，检索相关规范
    sample_text = " ".join(p["text"][:200] for p in paragraph_dicts[:5])
    rag_results = rag.query(sample_text, n_results=5)
    rag_context = ""
    if rag_results:
        rag_snippets = [f"[{r['source']}] {r['text']}" for r in rag_results]
        rag_context = "\n\n【参考规范】\n" + "\n---\n".join(rag_snippets) + "\n\n请结合以上规范进行编校。如果规范中有明确要求，请在 reason 中引用。\n"

    payload = {
        "paragraph_count": len(paragraph_dicts),
        "batch_count": len(batches),
        "total_chars": sum(len(p["text"]) for p in paragraph_dicts),
        "model": model,
        "rag_chunks": len(rag_results),
    }

    all_issues: list[ProofreadIssue] = []
    batch_summaries: list[str] = []

    async def _run_batch(batch):
        """单批次编校"""
        system_prompt = PROOFREAD_SYSTEM + rag_context
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": PROOFREAD_USER.format(
                    paragraphs_json=json.dumps(batch, ensure_ascii=False)
                ),
            },
        ]
        raw = await chat(messages, model=model)
        data = _parse_json(raw)
        issues_data = data.get("issues", [])
        issues = [ProofreadIssue(**item) for item in issues_data]
        summary = (data.get("summary") or "").strip()
        return issues, summary

    try:
        # 并行执行，限制并发数
        semaphore = asyncio.Semaphore(PROOFREAD_CONCURRENCY)

        async def _limited_batch(batch):
            async with semaphore:
                return await _run_batch(batch)

        results = await asyncio.gather(*[_limited_batch(b) for b in batches], return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                raise r
            issues, summary = r
            all_issues.extend(issues)
            if summary:
                batch_summaries.append(summary)

        stats = ProofreadStats(
            error=sum(1 for i in all_issues if i.severity == "error"),
            warning=sum(1 for i in all_issues if i.severity == "warning"),
            info=sum(1 for i in all_issues if i.severity == "info"),
        )

        summary = "；".join(batch_summaries) if batch_summaries else "未发现明显语言编校问题。"

        resp = ProofreadResponse(
            issues=all_issues,
            summary=summary,
            stats=stats,
            model_used=model,
        )

        write_audit(
            event="proofread.success",
            endpoint="/api/proofread",
            request_id=request_id,
            payload=payload,
            result={
                "issues_count": len(all_issues),
                "stats": stats.model_dump(),
                "model_used": model,
            },
        )
        return resp
    except json.JSONDecodeError:
        write_audit(
            event="proofread.error",
            endpoint="/api/proofread",
            request_id=request_id,
            payload=payload,
            error="JSONDecodeError: 模型返回格式异常",
        )
        raise HTTPException(status_code=502, detail="模型返回格式异常，请重试")
    except Exception as e:
        write_audit(
            event="proofread.error",
            endpoint="/api/proofread",
            request_id=request_id,
            payload=payload,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


# ========== 参考文献核查 ==========

async def _fetch_doi_metadata(doi: str) -> dict | None:
    """查询 CrossRef 获取 DOI 元数据"""
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(
                f"https://api.crossref.org/works/{doi}",
                headers={"User-Agent": "QKSPARK-Editor/1.0"}
            )
            if resp.status_code == 200:
                msg = resp.json().get("message", {})
                year = None
                for f in ["published-print", "published-online", "issued"]:
                    dp = msg.get(f, {}).get("date-parts", [[]])
                    if dp and dp[0]:
                        year = str(dp[0][0])
                        break
                return {
                    "found": True,
                    "title": (msg.get("title") or [""])[0][:100],
                    "year": year,
                    "journal": (msg.get("container-title") or [""])[0][:60],
                }
            elif resp.status_code == 404:
                return {"found": False}
    except Exception:
        pass
    return None


@app.post("/api/check-refs", response_model=RefCheckResponse)
async def check_refs_api(req: RefCheckRequest, request: Request):
    """参考文献核查：规则引擎前置 + LLM 补刀 + CrossRef DOI 验证"""
    request_id = request.headers.get("x-request-id", "") or f"refs-{int(datetime.now().timestamp() * 1000)}"

    try:
        from refs import parse_refs
        from refs_rule_engine import run_rule_engine

        # 1. 解析参考文献
        refs = parse_refs(req.refs_text)
        refs_count = len(refs)

        # 2. 规则引擎前置检查（< 1 秒，零成本）
        refs_dict = [{'ref_num': r.index, 'text': r.raw} for r in refs]
        rule_result = run_rule_engine(refs_dict)
        rule_issues = rule_result['issues']

        # 智能分流：问题太多时跳过 LLM，让用户先修正格式
        # 阈值：平均每条文献 > 2.5 个问题（说明格式问题严重）
        skip_llm = refs_count > 0 and len(rule_issues) > refs_count * 2.5

        # 3. 并行验证 DOI（如果开启）
        doi_context = ""
        if req.verify_dois:
            dois = [(r.index, r.doi) for r in refs if r.doi]
            if dois:
                sem = asyncio.Semaphore(5)

                async def _check_doi(idx, doi):
                    async with sem:
                        result = await _fetch_doi_metadata(doi)
                        return idx, doi, result

                doi_results = await asyncio.gather(*[_check_doi(i, d) for i, d in dois])
                doi_lines = []
                for idx, doi, meta in doi_results:
                    if meta is None:
                        doi_lines.append(f"[{idx}] DOI={doi} → 查询超时/失败")
                    elif not meta["found"]:
                        doi_lines.append(f"[{idx}] DOI={doi} → ❌ CrossRef 未找到该 DOI")
                    else:
                        doi_lines.append(
                            f"[{idx}] DOI={doi} → ✅ 找到 | 年份:{meta['year']} | 标题:{meta['title'][:50]}"
                        )
                if doi_lines:
                    doi_context = "【CrossRef DOI 验证结果】\n" + "\n".join(doi_lines)

        # 4. LLM 深度检查（仅在规则引擎问题不多时启用）
        llm_issues = []
        summaries = []

        if not skip_llm:
            ref_lines = [line for line in req.refs_text.split('\n') if line.strip()]
            ref_entries = []
            current = []
            for line in ref_lines:
                if re.match(r'\s*\[\d+\]', line) and current:
                    ref_entries.append('\n'.join(current))
                    current = [line]
                else:
                    current.append(line)
            if current:
                ref_entries.append('\n'.join(current))

            if len(ref_entries) <= 1 and refs_count > 1:
                ref_entries = [f"[{r.index}] {r.raw}" for r in refs]

            batch_size = 20
            batches = [ref_entries[i:i + batch_size] for i in range(0, len(ref_entries), batch_size)]

            async def _check_batch(batch_refs, batch_doi_ctx):
                refs_text_batch = '\n'.join(batch_refs)
                messages = [
                    {"role": "system", "content": REFS_CHECK_SYSTEM},
                    {"role": "user", "content": REFS_CHECK_USER.format(
                        refs_text=refs_text_batch,
                        doi_context=batch_doi_ctx,
                    )},
                ]
                raw = await chat(messages, model=DEFAULT_MODEL, temperature=0.1)
                return _parse_json(raw)

            llm_sem = asyncio.Semaphore(3)

            async def _limited(batch):
                async with llm_sem:
                    return await _check_batch(batch, doi_context)

            try:
                results = await asyncio.gather(*[_limited(b) for b in batches], return_exceptions=True)
                for r in results:
                    if isinstance(r, Exception):
                        continue
                    for iss in r.get("issues", []):
                        llm_issues.append(RefIssueModel(
                            ref_index=iss.get("ref_index", 0),
                            raw="",
                            severity=iss.get("severity", "info"),
                            category=iss.get("category", "format"),
                            message=iss.get("message", ""),
                            suggestion=iss.get("suggestion", ""),
                        ))
                    s = r.get("summary", "").strip()
                    if s:
                        summaries.append(s)
            except Exception:
                pass  # LLM 失败不影响规则引擎结果

        # 5. 合并结果：规则引擎 + LLM
        all_issues = []

        for rule_iss in rule_issues:
            ref_num_str = str(rule_iss.get('ref_num', '0'))
            if '&' in ref_num_str:
                ref_index = int(ref_num_str.split('&')[0].strip())
            else:
                ref_index = int(ref_num_str) if ref_num_str.isdigit() else 0
            all_issues.append(RefIssueModel(
                ref_index=ref_index,
                raw="",
                severity=rule_iss.get("severity", "info"),
                category=rule_iss.get("category", "format"),
                message=f"[规则] {rule_iss.get('message', '')}",
                suggestion=rule_iss.get("suggestion", ""),
            ))

        all_issues.extend(llm_issues)

        errors = sum(1 for i in all_issues if i.severity == "error")
        warnings = sum(1 for i in all_issues if i.severity == "warning")
        infos = sum(1 for i in all_issues if i.severity == "info")
        mode_note = "（快速模式，已跳过 AI 深度检查）" if skip_llm else ""
        summary = f"共 {refs_count} 条文献，发现 {errors} 个错误、{warnings} 个警告、{infos} 条建议{mode_note}"

        resp = RefCheckResponse(
            refs_count=refs_count,
            issues=all_issues,
            summary=summary,
            stats={"error": errors, "warning": warnings, "info": infos},
        )
        write_audit(
            event="check_refs.success", endpoint="/api/check-refs",
            request_id=request_id,
            payload={"refs_count": refs_count, "verify_dois": req.verify_dois, "skip_llm": skip_llm},
            result={"issues_count": len(all_issues)},
        )
        return resp

    except Exception as e:
        write_audit(event="check_refs.error", endpoint="/api/check-refs",
                    request_id=request_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ========== 知识库管理 API ==========

@app.get("/api/knowledge")
async def knowledge_list():
    """列出知识库所有来源"""
    sources = rag.list_sources()
    return {"sources": sources, "total_chunks": rag.count()}


@app.post("/api/knowledge/upload")
async def knowledge_upload(file: UploadFile = File(...), source: str = Form(None)):
    """上传规范文档到知识库（支持 txt/md/json）"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".txt", ".md", ".json"):
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}，仅支持 txt/md/json")

    content = await file.read()
    text = content.decode("utf-8")

    if ext == ".json":
        try:
            data = json.loads(text)
            if isinstance(data, list):
                text = "\n\n".join(str(item) for item in data)
            elif isinstance(data, dict):
                text = "\n\n".join(f"{k}: {v}" for k, v in data.items())
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="JSON 格式错误")

    src_name = source or file.filename
    chunks = rag.ingest_text(text, source=src_name)
    return {"source": src_name, "chunks": chunks, "total_chunks": rag.count()}


@app.delete("/api/knowledge/{source}")
async def knowledge_delete(source: str):
    """删除指定来源的知识"""
    deleted = rag.delete_source(source)
    return {"source": source, "deleted": deleted, "total_chunks": rag.count()}


@app.post("/api/refs-stats")
async def refs_statistics(req: RefCheckRequest):
    """参考文献统计分析"""
    from refs import analyze_refs_statistics
    
    if not req.refs_text or not req.refs_text.strip():
        raise HTTPException(status_code=400, detail="参考文献文本为空")
    
    stats = analyze_refs_statistics(req.refs_text)
    return stats


# 静态文件 - 前端 taskpane（避免 HTTPS→HTTP mixed content 问题）
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=int(PORT), reload=True)
