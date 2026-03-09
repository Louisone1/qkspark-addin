"""共享 fixtures"""
import json
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# 让 import backend 模块生效
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import main  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(autouse=True)
def stub_llm_chat(monkeypatch):
    """测试中禁用真实 LLM 外呼，返回稳定假响应。"""

    async def fake_chat(messages, model=None, temperature=0.3, max_tokens=4096):
        user_content = messages[-1]["content"] if messages else ""
        system_content = messages[0]["content"] if messages else ""

        if '术语规范' in system_content:
            if 'tensorflow' in user_content.lower() or 'machine learning' in user_content.lower() or ' AI ' in (' ' + user_content + ' '):
                return json.dumps({
                    "issues": [
                        {
                            "original": "tensorflow",
                            "suggestion": "TensorFlow",
                            "reason": "专有名词大小写需规范",
                            "position": "段落中部",
                            "severity": "warning"
                        }
                    ],
                    "summary": "发现 1 处术语规范问题"
                }, ensure_ascii=False)
            return json.dumps({"issues": [], "summary": "整体术语较规范"}, ensure_ascii=False)

        if '语言润色' in system_content:
            source_text = user_content.split('---')[-2].strip() if '---' in user_content else user_content
            return json.dumps({
                "polished": source_text.replace('好很多', '更优').replace('不少', '较为明显'),
                "changes": [
                    {
                        "original": "好很多" if '好很多' in source_text else "不少",
                        "revised": "更优" if '好很多' in source_text else "较为明显",
                        "reason": "学术表达更凝练"
                    }
                ],
                "summary": "已完成润色"
            }, ensure_ascii=False)

        if '语言编校专家' in system_content:
            return json.dumps({"issues": [], "summary": "未发现明显语言编校问题"}, ensure_ascii=False)

        if '参考文献规范核查' in system_content:
            return json.dumps({"issues": [], "summary": "参考文献格式基本规范"}, ensure_ascii=False)

        return json.dumps({}, ensure_ascii=False)

    monkeypatch.setattr(main, 'chat', fake_chat)


@pytest.fixture
def client():
    """异步测试客户端，不需要真正启动服务器"""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")
