"""API 数据模型"""
from typing import Literal

from pydantic import BaseModel, Field


class TermCheckRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=50000, description="待检查的文本")
    model: str | None = Field(None, description="指定模型，留空用默认")


class TermIssue(BaseModel):
    original: str
    suggestion: str
    reason: str
    position: str
    severity: str  # error | warning | info


class TermCheckResponse(BaseModel):
    issues: list[TermIssue]
    summary: str
    model_used: str


class PolishRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=50000, description="待润色的文本")
    mode: str = Field("conservative", pattern="^(conservative|enhanced)$")
    model: str | None = Field(None, description="指定模型，留空用默认")


class PolishChange(BaseModel):
    original: str
    revised: str
    reason: str


class PolishResponse(BaseModel):
    polished: str
    changes: list[PolishChange]
    summary: str
    model_used: str


class ProofreadParagraph(BaseModel):
    index: int = Field(..., ge=0, description="段落索引")
    text: str = Field(..., min_length=1, description="段落文本")


class ProofreadRequest(BaseModel):
    paragraphs: list[ProofreadParagraph] = Field(..., min_length=1, description="待编校段落列表")
    model: str | None = Field(None, description="指定模型，留空用默认")


class ProofreadIssue(BaseModel):
    paragraph_index: int = Field(..., ge=0)
    category: Literal["spelling", "grammar", "punctuation", "terminology", "consistency", "expression"]
    severity: Literal["error", "warning", "info"]
    original: str
    suggestion: str
    reason: str
    position: str


class ProofreadStats(BaseModel):
    error: int = 0
    warning: int = 0
    info: int = 0


class ProofreadResponse(BaseModel):
    issues: list[ProofreadIssue]
    summary: str
    stats: ProofreadStats
    model_used: str


class RefCheckRequest(BaseModel):
    refs_text: str = Field(..., min_length=1, description="参考文献列表文本")
    body_text: str = Field("", description="正文文本（用于引用完整性检查，可选）")
    verify_dois: bool = Field(True, description="是否联网验证 DOI")


class RefIssueModel(BaseModel):
    ref_index: int
    raw: str
    severity: str
    category: str
    message: str
    suggestion: str = ""


class RefCheckResponse(BaseModel):
    refs_count: int
    issues: list[RefIssueModel]
    summary: str
    stats: dict


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
