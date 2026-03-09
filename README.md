# qkspark-addin

智编编辑助手（Word Office Add-in）主仓库。

## 当前定位
- **唯一主仓库**：前端、manifest、文档、后续后端迁移均以此处为准
- Windows 真机测试：`192.168.28.106`（PC-KJCY）
- 当前推荐部署：GitHub Pages + sideload manifest

## 当前目录
- `frontend/`：taskpane 前端源码
- `manifest/`：Word Add-in manifest 源文件
- 根目录 `taskpane.html/js/css` + `manifest.xml`：GitHub Pages / sideload 实际部署入口
- `backend/`：后续迁入的 FastAPI 后端能力
- `tests/`：后续统一测试
- `docs/`：部署、测试、已知问题、架构说明

## 当前阶段
项目已完成主链路验证，但仍处于“可演示、待收口、待稳态化”阶段。

优先级：
1. 仓库收口
2. 替换锚定稳定性修复
3. 修订标记兼容层修复（默认 highlight_note，兼容 native_comment / report_only）
4. 文献核查链路补齐
