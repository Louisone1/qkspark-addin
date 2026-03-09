"""RAG 知识库模块 - 纯 SQLite + BM25 文本检索（无外部依赖）"""
import hashlib
import math
import re
import sqlite3
from pathlib import Path
from typing import Optional

# 数据目录
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "knowledge.db"

_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                chunk_index INTEGER,
                text TEXT NOT NULL
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON chunks(source)")
        _conn.commit()
    return _conn


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """按字符数切分文本，带重叠"""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return [c.strip() for c in chunks if c.strip()]


def _doc_id(source: str, idx: int) -> str:
    h = hashlib.md5(source.encode()).hexdigest()[:8]
    return f"{h}-{idx}"


def _tokenize(text: str) -> list[str]:
    """简单中文分词：按标点和空格切分，再按2-gram切中文"""
    # 先提取英文单词
    words = re.findall(r'[a-zA-Z]+', text.lower())
    # 中文字符 2-gram
    cn_chars = re.findall(r'[\u4e00-\u9fff]', text)
    for i in range(len(cn_chars) - 1):
        words.append(cn_chars[i] + cn_chars[i + 1])
    # 单个中文字也加入
    words.extend(cn_chars)
    return words


def ingest_text(text: str, source: str, metadata: Optional[dict] = None) -> int:
    """导入一段文本到知识库，返回 chunk 数"""
    conn = _get_conn()
    chunks = _chunk_text(text)
    if not chunks:
        return 0

    # 先删除同 source 的旧数据
    conn.execute("DELETE FROM chunks WHERE source = ?", (source,))

    for i, chunk in enumerate(chunks):
        doc_id = _doc_id(source, i)
        conn.execute(
            "INSERT OR REPLACE INTO chunks (id, source, chunk_index, text) VALUES (?, ?, ?, ?)",
            (doc_id, source, i, chunk),
        )
    conn.commit()
    return len(chunks)


def query(text: str, n_results: int = 5) -> list[dict]:
    """BM25 检索与 text 最相关的知识片段"""
    conn = _get_conn()
    rows = conn.execute("SELECT id, source, text FROM chunks").fetchall()
    if not rows:
        return []

    query_tokens = _tokenize(text)
    if not query_tokens:
        return []

    # 计算 BM25 分数
    k1, b = 1.5, 0.75
    N = len(rows)

    # 文档频率
    df = {}
    doc_tokens = []
    doc_lens = []
    for row in rows:
        tokens = _tokenize(row["text"])
        doc_tokens.append(tokens)
        doc_lens.append(len(tokens))
        seen = set(tokens)
        for t in seen:
            df[t] = df.get(t, 0) + 1

    avg_dl = sum(doc_lens) / N if N > 0 else 1

    scores = []
    for i, row in enumerate(rows):
        score = 0.0
        tokens = doc_tokens[i]
        dl = doc_lens[i]
        tf_map = {}
        for t in tokens:
            tf_map[t] = tf_map.get(t, 0) + 1

        for qt in query_tokens:
            if qt not in df:
                continue
            idf = math.log((N - df[qt] + 0.5) / (df[qt] + 0.5) + 1)
            tf = tf_map.get(qt, 0)
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))

        scores.append((score, row))

    scores.sort(key=lambda x: -x[0])
    results = []
    for score, row in scores[:n_results]:
        if score > 0:
            results.append({
                "text": row["text"],
                "source": row["source"],
                "score": round(score, 3),
            })
    return results


def list_sources() -> list[dict]:
    """列出知识库中所有来源"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT source, COUNT(*) as chunks FROM chunks GROUP BY source"
    ).fetchall()
    return [{"source": r["source"], "chunks": r["chunks"]} for r in rows]


def delete_source(source: str) -> int:
    """删除指定来源的所有文档，返回删除数"""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM chunks WHERE source = ?", (source,))
    conn.commit()
    return cursor.rowcount


def count() -> int:
    """知识库总 chunk 数"""
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) as cnt FROM chunks").fetchone()
    return row["cnt"]
