"""后端 API 测试"""
import pytest


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_check_terms_empty_text(client):
    """空文本应返回 422"""
    resp = await client.post("/api/check-terms", json={"text": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_check_terms_success(client):
    """含术语问题的文本应返回 issues"""
    resp = await client.post(
        "/api/check-terms",
        json={"text": "本研究使用 AI 和 machine learning 方法，基于tensorflow框架。"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "issues" in data
    assert "summary" in data
    assert "model_used" in data
    # 这段文本至少应检出 1 个问题
    assert len(data["issues"]) >= 1
    # 每个 issue 结构完整
    for issue in data["issues"]:
        assert all(k in issue for k in ("original", "suggestion", "reason", "severity"))


@pytest.mark.asyncio
async def test_check_terms_clean_text(client):
    """相对规范的文本，issues 可以为空或很少"""
    resp = await client.post(
        "/api/check-terms",
        json={"text": "本研究采用深度学习方法对遥感影像进行分类。"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["issues"], list)


@pytest.mark.asyncio
async def test_polish_empty_text(client):
    """空文本应返回 422"""
    resp = await client.post("/api/polish", json={"text": "", "mode": "conservative"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_polish_invalid_mode(client):
    """非法 mode 应返回 422"""
    resp = await client.post(
        "/api/polish",
        json={"text": "测试文本", "mode": "aggressive"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_polish_conservative(client):
    """保守润色应返回润色结果"""
    resp = await client.post(
        "/api/polish",
        json={
            "text": "我们做了一个实验，发现这个方法比之前的好很多。",
            "mode": "conservative",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["polished"]  # 非空
    assert isinstance(data["changes"], list)
    assert data["model_used"]


@pytest.mark.asyncio
async def test_polish_enhanced(client):
    """增强润色应返回润色结果"""
    resp = await client.post(
        "/api/polish",
        json={
            "text": "数据表明效果提升了不少，说明我们的方案是可行的。",
            "mode": "enhanced",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["polished"]
    assert "summary" in data
