# 🗺️ Feature Roadmap — Health Data Manager

> 本文件作为项目的功能路线图，同时也是 **GitHub Issues 的蓝图**。  
> 每一条均可直接作为一个 Issue 提交到 GitHub，标签（Labels）已预标注。  
> 标记 `good first issue` 🏷️ 的条目适合新贡献者作为入门任务。

---

## 标签说明

| 标签 | 含义 |
|------|------|
| 🏷️ `good first issue` | 适合新贡献者的入门任务 |
| 🟢 `enhancement` | 新功能 |
| 🔧 `fix` | Bug 修复 / 一致性修正 |
| 📄 `documentation` | 文档改进 |
| 🧪 `testing` | 测试相关 |
| 🔴 P0 | 最高优先级 |
| 🟡 P1 | 高优先级 |
| 🔵 P2 | 中低优先级 |
| ⚪ Backlog | 延后项 |

---

## Phase 1：工程基础与质量 🏗️

### Issue #1 — 统一渲染路径，消除双重 HTML 模板 `🔴 P0` `🔧 fix`
- **描述**：`dashboard_template.html` 中存在两条独立的渲染路径（初始加载 vs 时间窗口点击处理器），HTML 模板已发散。切换时间窗口后风险面板版式突变、"血氧标记日"行消失。
- **目标**：抽取统一渲染函数 `renderViews(filtered, label)`，初始加载与时间按钮点击共用同一套模板。
- **验收**：`risk-assessment`、`summary-cards`、`data-table-wrapper` 的 innerHTML 赋值各只有一处来源。
- **关联**：同时解决 F6 / F7 / F9 / F10。

---

### Issue #2 — 个体化血氧阈值传导到摘要卡颜色 `🟡 P1` `🔧 fix`
- **描述**：摘要卡的血氧颜色判定写死 95%，未使用个体化阈值，导致 COPD 患者摘要卡显红但风险面板判"正常"，结论自相矛盾。
- **目标**：摘要卡血氧 `cls` 改用 `effWarningDisplay` 个体化生效阈值。
- **建议**：并入 Issue #1 统一渲染函数中一起修改。

---

### Issue #3 — 移动端时间选择器可见性修复 `🟡 P1` `🔧 fix` `🏷️ good first issue`
- **描述**：`dashboard_template.html` 中 480px 断点将 `.time-selector` 设为 `display: none`，导致手机上核心控件不可用。
- **目标**：改为 `flex-wrap` 换行或横向滚动，按钮可缩小但必须可见可点。
- **验收**：在 360–414px 宽度下所有时间按钮可见、可点击切换。
- **难度**：🟢 低（纯 CSS 修改）

---

### Issue #4 — 三视图血氧风险措辞统一 `🟡 P1` `🔧 fix` `🏷️ good first issue`
- **描述**：同一 danger 档位，徽章叫"需关注"、逐日标记叫"偏低"、日历叫不同措辞。三视图措辞不统一。
- **目标**：统一为 **需关注 / 留意 / 正常** 三档措辞。
- **验收**：徽章、逐日标记、日历 tooltip 三处对同一天给出同一档位词。
- **难度**：🟢 低（字符串替换）

---

### Issue #5 — 哮喘从 COPD 放宽关键词中移除 `🟡 P1` `🔧 fix` `🏷️ good first issue`
- **描述**：`has_copd` 关键词列表包含"哮喘"，导致哮喘患者被错误套用 COPD 的 88–92% 放宽阈值。哮喘 ≠ 高碳酸风险。
- **目标**：在 `health_data_schema.py` 和 `dashboard_template.html` 两处，将"哮喘"从 COPD 关键词集中移出。
- **验收**：仅含"哮喘"的档案使用通用阈值（90/95）。
- **难度**：🟢 低（删除关键词）

---

### Issue #6 — danger 档血氧不再减精度容差 `🔴 P0` `🔧 fix`
- **描述**：根据临床决策 D-1/D-2，danger 档使用指南标称值（COPD 88%、通用 90%），不减 ±2% 容差；容差仅用于留意档。
- **目标**：`dashboard_template.html` 和 `report_generator.py` 三处同步修改 danger 公式。
- **验收**：COPD `<88%` 需关注、`88–90%` 留意；通用 `<90%` 需关注、`90–93%` 留意。

---

### Issue #7 — 临床免责声明合规化 `🟡 P1` `📄 documentation` `🏷️ good first issue`
- **描述**：仪表盘和 Word 报告需加入统一的非诊断临床免责声明，现有提示语需去除"自行调整治疗"暗示。
- **目标**：在 `dashboard_template.html` 页脚和 `report_generator.py` 附录中接入免责声明。
- **验收**：全站无指示用户自行调整治疗的文案。
- **难度**：🟢 低（文案插入）

---

### Issue #8 — FDA 引用措辞修正 `🔵 P2` `📄 documentation` `🏷️ good first issue`
- **描述**：代码中 "FDA 510(k) ±2-3%" 引用不当（消费级腕式多未经 510(k) 清关），需改为 ISO 80601-2-61 标准。
- **目标**：全仓 grep 替换 `FDA 510|AASM参考`，统一为正确措辞。
- **验收**：全仓 0 处残留错误引用。
- **难度**：🟢 低（文本查找替换）

---

### Issue #9 — C5–C7 高风险血氧逻辑专项测试 `🟡 P1` `🧪 testing`
- **描述**：临床依据文档要求对容差/门控逻辑编写专项测试覆盖。
- **目标**：在 `tests/` 下新增测试用例，覆盖 COPD 86–89%、单日 <88%、多天 <92%、缺失值、设备误差模拟等场景。
- **依赖**：Issue #6 先完成。

---

### Issue #10 — 清理 `movingAvg()` 死代码及文档残留 `🔵 P2` `🔧 fix` `🏷️ good first issue`
- **描述**：7日滑动均值线已按需求删除，但 `movingAvg()` 函数定义和 walkthrough 文档中仍有残留。
- **目标**：删除 `dashboard_template.html` 中 `movingAvg()` 函数、清除相关空行、更新文档。
- **验收**：全文件 grep `movingAvg` 为 0 处。
- **难度**：🟢 低（删除死代码）

---

## Phase 2：数据能力增强 📊

### Issue #11 — 周/月聚合粒度切换 `🔵 P2` `🟢 enhancement`
- **描述**：当前长跨度仍逐日画点，没有按周/月取均值降密度。随数据增长，图表点过密、手机渲染慢。
- **目标**：支持在时间窗口选择器旁增加 **日 / 周 / 月** 聚合粒度切换。
- **触发时机**：当记录数 > 180 天时明显需要。

---

### Issue #12 — 服务端预聚合 + API 取数 `⚪ Backlog` `🟢 enhancement`
- **描述**：当前为全量 JSON 内联进 HTML，数据增长后 HTML 膨胀、手机变慢。
- **目标**：后端提供 `/api/data` 接口按时间范围返回数据，前端改为 AJAX 按需取数。
- **触发时机**：数据量 > 365 天或 HTML > 1MB。

---

### Issue #13 — 日历热力图多年横向溢出修复 `⚪ Backlog` `🟢 enhancement`
- **描述**：日历 `orient:'horizontal'` 在多年数据下横向溢出，手机需横滚。
- **目标**：改为按年分行或垂直堆叠。
- **触发时机**：记录跨越 2 个自然年。

---

### Issue #14 — 支持更多智能穿戴设备数据导入 `⚪ Backlog` `🟢 enhancement`
- **描述**：当前仅支持华为/荣耀设备截图和备份导入。扩展支持小米手环、Apple Health 导出 XML 等。
- **目标**：在 `extract_health_data.py` 中新增数据适配器，解析不同厂商格式。

---

## Phase 3：用户体验优化 ✨

### Issue #15 — 暗色/亮色主题切换 `⚪ Backlog` `🟢 enhancement` `🏷️ good first issue`
- **描述**：当前仪表盘仅有暗色主题。部分用户（尤其长辈）在强光环境下需要亮色模式。
- **目标**：增加主题切换按钮，支持暗色/亮色双主题。
- **难度**：🟢 中（CSS 变量 + JS 切换）

---

### Issue #16 — 数据导出为 CSV/Excel `🔵 P2` `🟢 enhancement` `🏷️ good first issue`
- **描述**：用户可能需要将健康数据导出为 CSV 或 Excel 供医生参考或自行分析。
- **目标**：在管理中心增加"导出数据"按钮，支持 CSV 和 Excel 格式。
- **难度**：🟢 中

---

### Issue #17 — 多语言 i18n 支持 `⚪ Backlog` `🟢 enhancement`
- **描述**：当前仅支持中文。增加英文界面支持可扩大项目受众。
- **目标**：前端文案提取为语言包，支持中/英切换。

---

### Issue #18 — Docker 一键部署 `🔵 P2` `🟢 enhancement` `🏷️ good first issue`
- **描述**：提供 `Dockerfile` 和 `docker-compose.yml`，让用户无需手动安装 Python 依赖。
- **目标**：`docker-compose up` 即可启动完整服务。
- **难度**：🟢 低

---

## Phase 4：文档与社区 📚

### Issue #19 — 完善 API 接口文档 `🔵 P2` `📄 documentation` `🏷️ good first issue`
- **描述**：`app.py` 中定义了多个 API 端点（上传截图、导入备份、发布等），但缺少独立的 API 文档。
- **目标**：在 `doc/` 目录下创建 `API.md`，列出所有端点的请求/响应格式和示例。
- **难度**：🟢 低

---

### Issue #20 — 截图示例与使用教程 `🔵 P2` `📄 documentation` `🏷️ good first issue`
- **描述**：README 中缺少实际使用的截图/GIF 动画演示。新用户难以直观了解产品效果。
- **目标**：在 `doc/` 中添加截图和 GIF，README 中嵌入使用流程动画。
- **难度**：🟢 低

---

### Issue #21 — 增加 GitHub Actions CI `🔵 P2` `🧪 testing` `🏷️ good first issue`
- **描述**：项目已有 `tests/` 测试套件但缺少 CI 集成。每次 PR 应自动运行测试。
- **目标**：添加 `.github/workflows/ci.yml`，在 push/PR 时自动运行 `python -m pytest tests/`。
- **难度**：🟢 低

---

## 提交 Issue 指引

将本文档中的条目提交为 GitHub Issue 时，请：

1. **Title**：使用 `[Phase X] Issue 标题` 格式
2. **Labels**：按上方标注添加 GitHub Labels（如 `good first issue`、`enhancement`、`P0` 等）
3. **Body**：复制对应条目的描述、目标、验收标准
4. **Milestone**：按 Phase 归属到对应 Milestone

> 💡 **新贡献者**：请优先认领标有 🏷️ `good first issue` 的条目！这些任务范围明确、难度适中，是了解项目代码的最佳起点。
