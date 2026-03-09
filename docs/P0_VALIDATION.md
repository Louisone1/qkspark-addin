# P0 Validation Notes

日期：2026-03-09

## 已完成改造

### 1. 修订标记兼容层
- UI 文案已从“写入批注”改为“修订标记”
- 默认模式：`highlight_note`
- 兼容模式预留：`native_comment` / `report_only`

### 2. 替换双锚定（前端第一版）
- 在前端对 proofread issue 本地补充：
  - `anchor_prefix`
  - `anchor_suffix`
  - `paragraph_excerpt`
- `acceptIssue()` 改为优先按目标段落 + 锚点评分定位
- `batchAcceptAll()` 对不确定项跳过，不再默认替换第一个命中
- `locateIssue()` 优先按锚点定位，否则退回段落定位

## 已完成静态验证
- `node --check frontend/taskpane.js`
- `node --check taskpane.js`
- `python3 -m py_compile backend/main.py backend/models.py backend/prompts.py`

## 部署入口已收口
- 已将 `frontend/taskpane.html/js/css` 同步到仓库根目录 `taskpane.html/js/css`
- 已将 `manifest/manifest.xml` 同步到根目录 `manifest.xml`
- 目的：让 GitHub Pages 与 Windows sideload 都加载同一份最新前端，而不是旧 root 文件

## 当前宿主验收结论（2026-03-09 15:02）
### 已确认通过
1. 主仓库 P0 改造代码已落地：修订标记兼容层 + 双锚定替换第一版
2. 本地后端回归已通过：`python -m pytest -q` → `8 passed`
3. Windows 测试机已同步最新 `taskpane.html/js/css` 与 `manifest.xml`
4. sideload 脚本已修正为复用现有 manifest，不再重写 localhost 版本
5. GitHub Pages / sideload 指向的根目录部署入口已与 `frontend/` 最新代码一致

### 当前阻塞
- Windows 远端自动化卡在宿主会话层：SSH/COM 可拉起 Word 进程与文档，但 UIAutomation 看不到稳定可交互窗口，导致任务窗格自动注入链路无法完成最终闭环
- 这属于测试机桌面会话问题，不是 add-in 前端 P0 逻辑本身的问题

## 待完成真机验证
在 Windows Word 测试机（192.168.28.106）验证：
1. 连续 20 条“修订标记”写入不崩
2. 同一原文在文中重复出现时，单条采纳不再优先替错第一个命中
3. 批量采纳对不确定项会跳过，而不是误替换
4. `定位` 能优先选中目标段落附近命中
