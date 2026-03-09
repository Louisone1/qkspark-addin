# KNOWN_ISSUES

## 当前已知问题

1. 替换逻辑仍主要依赖 `search(original)`，重复文本场景可能替错位置
2. Office 2019 上原生批注支持不稳定，当前前端已默认切到“修订标记”模式（高亮 + 尾注 / highlight_note），后续仅在能力确认后再开放 native_comment
3. 参考文献核查虽支持 `body_text`，但前端链路尚未完整启用正文引用完整性检查
4. 公式/特殊格式段落定位仍不稳定
5. manifest 与页面版本号需要统一
