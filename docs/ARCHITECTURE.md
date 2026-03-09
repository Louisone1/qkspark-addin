# ARCHITECTURE

## 当前架构

### 前端
- Word Taskpane 前端托管于 GitHub Pages
- 通过 Office.js 与 Word 交互
- 当前主入口：`frontend/taskpane.html`

### 宿主
- Windows Word（测试机：192.168.28.106）
- 通过 sideload manifest 加载 Add-in

### 后端
- 当前后端能力来源于历史 MVP：`word-plugin-mvp/backend`
- 后续将逐步迁入本主仓库 `backend/`

## 当前已识别问题
1. 前后端历史分叉，需收口到本仓库
2. 替换逻辑锚定不足
3. Office 2019 批注兼容性不足
4. 文献核查正文引用完整性链路未完全打通
