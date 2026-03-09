# TESTING

## 当前测试分层

### 1. 后端 API 测试
- 位置：`tests/`
- 当前已验证：基础 API 测试可通过（health / check-terms / polish）

### 2. Word 真机测试
- 测试机：`192.168.28.106`
- 用途：
  - sideload manifest
  - 验证 taskpane 加载
  - 验证文档读写
  - 验证批注/替换/导出报告实际行为

## 下一步应补的测试
1. proofread 返回结构测试
2. check-refs 基础解析测试
3. body_text 引用完整性测试
4. knowledge 上传/删除测试
5. DOI mock 测试

## 2026-03-09 当前进展
- 主仓库后端测试已完成本地隔离回归：`python -m pytest -q` → `8 passed`
- Windows 测试机已同步到最新前端/manifest
- 发现旧问题：测试机 sideload 脚本仍会重写 localhost manifest，需要收口为复用现有 GitHub Pages manifest
