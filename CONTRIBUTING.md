# 🤝 贡献指南 (Contributing Guide)

感谢您对 **AI 智能健康数据管理中心** 项目的关注！无论是修复 Bug、改进文档、还是提出新功能，我们都非常欢迎您的参与。

本文档将引导您完成从环境搭建到提交 Pull Request 的完整流程。

---

## 📋 目录

- [行为准则](#-行为准则)
- [快速开始](#-快速开始)
- [开发环境搭建](#-开发环境搭建)
- [项目结构](#-项目结构)
- [开发工作流](#-开发工作流)
- [代码规范](#-代码规范)
- [提交规范](#-提交规范)
- [Pull Request 流程](#-pull-request-流程)
- [Issue 指南](#-issue-指南)
- [新手入门](#-新手入门good-first-issues)
- [隐私与安全](#-隐私与安全)
- [获取帮助](#-获取帮助)

---

## 📜 行为准则

请在参与本项目时保持友善和尊重。我们致力于提供一个开放、包容的协作环境。

- 尊重不同的观点和经验
- 接受建设性的批评
- 关注对社区最有利的事情
- 对其他社区成员表示同理心

---

## ⚡ 快速开始

```bash
# 1. Fork 并克隆仓库
git clone https://github.com/<your-username>/health-data-manager.git
cd health-data-manager

# 2. 安装依赖
pip install flask python-docx matplotlib pydantic pydantic-settings requests pyzipper

# 3. 配置 API 密钥（可选，仅 OCR 功能需要）
# Windows PowerShell:
$env:DASHSCOPE_API_KEY="your_api_key"

# 4. 启动开发服务器
python app.py

# 5. 运行测试
python -m pytest tests/ -v
```

---

## 🛠️ 开发环境搭建

### 前置要求

| 工具 | 版本要求 | 说明 |
|------|---------|------|
| Python | ≥ 3.9 | 核心运行时 |
| pip | 最新版 | 包管理器 |
| Git | ≥ 2.x | 版本控制 |
| 阿里云 DashScope API Key | — | 仅 AI OCR 功能需要，非必须 |

### 安装步骤

1. **Fork 仓库**：点击 GitHub 页面右上角的 `Fork` 按钮，将项目复制到您的账户下。

2. **克隆到本地**：
   ```bash
   git clone https://github.com/<your-username>/health-data-manager.git
   cd health-data-manager
   ```

3. **添加上游仓库**：
   ```bash
   git remote add upstream https://github.com/yigao714/health-data-manager.git
   ```

4. **安装 Python 依赖**：
   ```bash
   pip install flask python-docx matplotlib pydantic pydantic-settings requests pyzipper
   ```

5. **验证安装**：
   ```bash
   python -m pytest tests/ -v
   ```
   所有测试应通过。

---

## 📁 项目结构

```
health-data-manager/
├── app.py                      # Flask 后端主程序（API 端点与路由）
├── extract_health_data.py      # AI 截图 OCR 提取与验证逻辑
├── health_data_schema.py       # Pydantic 数据模型与临床阈值定义
├── dashboard_template.html     # 可视化仪表盘 HTML 模板（ECharts）
├── report_generator.py         # Word 阶段性分析报告生成器
├── run_analysis.py             # 独立运行的数据分析脚本
├── start.bat                   # Windows 一键启动脚本
├── echarts.min.js              # ECharts 库（内联化，支持离线）
├── publish_config.json         # Netlify 发布配置（⚠️ 已在 .gitignore 中）
├── tests/                      # 自动化测试套件
│   ├── test_schemas.py         # 数据模型测试
│   ├── test_validators.py      # 校验器测试
│   └── test_clinical_logic.py  # 临床逻辑测试
├── doc/                        # 文档与参考资料
├── people/                     # 成员数据目录（⚠️ 已在 .gitignore 中，不会上传）
├── CHANGELOG.md                # 版本更新日志
├── CONTRIBUTING.md             # 本文件 — 贡献指南
├── FEATURE_ROADMAP.md          # 功能路线图与 Issue 蓝图
└── README.md                   # 项目说明
```

### 核心文件说明

| 文件 | 职责 | 修改注意事项 |
|------|------|-------------|
| `app.py` | 全部 API 路由、文件上传、数据管理 | 不改变用户交互流程 |
| `health_data_schema.py` | Pydantic 数据模型、`get_thresholds()` 阈值 | 阈值修改需临床确认 |
| `dashboard_template.html` | 前端图表、评估逻辑、JS `getThresholds()` | 确保与 schema 阈值同步 |
| `report_generator.py` | Word 报告的评分/免责声明 | 确保与仪表盘逻辑一致 |
| `extract_health_data.py` | Qwen-VL API 调用、OCR 提取 | 修改需同步测试 |

---

## 🔄 开发工作流

### 1. 同步上游代码

```bash
git checkout main
git fetch upstream
git merge upstream/main
```

### 2. 创建功能分支

分支命名规范：
```bash
# 功能开发
git checkout -b feature/描述性名称

# Bug 修复
git checkout -b fix/问题简述

# 文档更新
git checkout -b docs/文档主题
```

**示例**：
```bash
git checkout -b fix/mobile-time-selector
git checkout -b feature/csv-export
git checkout -b docs/api-documentation
```

### 3. 开发与测试

```bash
# 开发中随时运行测试
python -m pytest tests/ -v

# 启动本地服务器查看效果
python app.py
# 访问 http://localhost:8080
```

### 4. 提交与推送

```bash
git add .
git commit -m "fix: 修复移动端时间选择器被隐藏的问题"
git push origin fix/mobile-time-selector
```

### 5. 发起 Pull Request

在 GitHub 上从您的分支向 `upstream/main` 发起 PR。

---

## 📝 代码规范

### Python

- **风格**：遵循 [PEP 8](https://peps.python.org/pep-0008/)
- **类型标注**：新增函数请使用 Python type hints
- **文档字符串**：公共函数需有中文 docstring
- **命名**：
  - 函数和变量：`snake_case`
  - 类名：`PascalCase`
  - 常量：`UPPER_SNAKE_CASE`

```python
# ✅ 好的示例
def calculate_spo2_score(spo2_min: float, thresholds: dict) -> str:
    """
    计算血氧评分等级。

    Args:
        spo2_min: 最低血氧饱和度（%）
        thresholds: 个体化阈值字典

    Returns:
        评分等级字符串：'需关注' / '留意' / '正常'
    """
    if spo2_min < thresholds['spo2_danger']:
        return '需关注'
    elif spo2_min < thresholds['spo2_warning'] - thresholds['spo2_precision']:
        return '留意'
    return '正常'
```

### JavaScript / HTML

- **缩进**：4 空格
- **变量声明**：优先使用 `const`，必要时使用 `let`，禁止 `var`
- **模板字符串**：使用反引号 `` ` `` 拼接 HTML
- **中文常量**：直接写 UTF-8 中文，不使用 `\uXXXX` 转义

### CSS

- **单位**：响应式布局使用 `rem`、`%`、`vw/vh`
- **移动适配**：确保所有交互元素在 360px 宽度下可用
- **暗色主题**：使用 CSS 变量管理颜色值

### 关键原则：阈值单一数据源

项目中临床阈值有 **两处同步定义**，修改时必须同步：

1. **Python 端**：`health_data_schema.py` → `get_thresholds()`
2. **JavaScript 端**：`dashboard_template.html` → `getThresholds()`

> ⚠️ **警告**：两处阈值不同步将导致仪表盘和 Word 报告评估结论矛盾。每次修改后请交叉检查。

---

## 💬 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
<type>(<scope>): <description>

[可选正文]

[可选脚注]
```

### Type 类型

| Type | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat(dashboard): 新增暗/亮主题切换` |
| `fix` | Bug 修复 | `fix(schema): 移除哮喘从 COPD 关键词列表` |
| `docs` | 文档更新 | `docs: 补充 API 接口文档` |
| `style` | 代码格式（不影响逻辑） | `style: 统一缩进为 4 空格` |
| `refactor` | 重构（不新增功能/修复 Bug） | `refactor(dashboard): 统一渲染路径` |
| `test` | 增加/修改测试 | `test: 新增 C5-C7 血氧逻辑专项测试` |
| `chore` | 构建/工具/依赖变更 | `chore: 添加 GitHub Actions CI` |

### 示例

```bash
# 好的提交信息
git commit -m "fix(dashboard): 修复移动端时间选择器被 display:none 隐藏的问题

将 480px 断点下的 .time-selector 从 display:none 改为 flex-wrap，
确保手机端可见可点击。

Closes #3"

# 不好的提交信息
git commit -m "修了个 bug"
git commit -m "update"
```

---

## 🚀 Pull Request 流程

### PR 模板

请在 PR 描述中包含以下信息：

```markdown
## 变更内容
简要描述本次改动。

## 关联 Issue
Closes #<issue-number>

## 变更类型
- [ ] Bug 修复
- [ ] 新功能
- [ ] 文档更新
- [ ] 重构
- [ ] 测试

## 测试说明
描述你做了哪些测试来验证改动。

## 截图（如涉及 UI 变更）
附上改动前后的截图对比。

## 检查清单
- [ ] 代码已自测通过
- [ ] 所有测试用例通过 (`python -m pytest tests/ -v`)
- [ ] 若修改了阈值：已同步 Python `get_thresholds()` 和 JS `getThresholds()`
- [ ] 若涉及 UI：已在 PC 和 360px 手机模式下验证
- [ ] 未引入新的隐私数据泄露风险
```

### 审查标准

PR 将根据以下标准审查：

1. **功能正确性**：改动是否实现了预期效果
2. **测试覆盖**：是否有对应测试（尤其是临床逻辑相关改动）
3. **阈值同步**：Python 和 JS 端的阈值是否一致
4. **移动端兼容**：UI 改动在手机端是否正常
5. **隐私安全**：是否会意外暴露用户健康数据
6. **最小改动原则**：只改必须改的，不做额外"顺便优化"

---

## 📌 Issue 指南

### 报告 Bug

请使用以下格式提交 Bug Issue：

```markdown
**Bug 描述**
简明扼要地描述问题。

**复现步骤**
1. 打开 '...'
2. 点击 '...'
3. 滚动到 '...'
4. 看到错误

**预期行为**
描述你期望看到的行为。

**实际行为**
描述实际发生了什么。

**截图**
如适用，附上截图。

**环境**
- OS: [e.g. Windows 11]
- Python 版本: [e.g. 3.11]
- 浏览器: [e.g. Chrome 120]
```

### 提出新功能

```markdown
**功能描述**
清楚简洁地描述您希望增加的功能。

**使用场景**
描述这个功能解决什么问题。

**建议方案**
如有想法，描述您建议的实现方式。
```

---

## 🌱 新手入门（Good First Issues）

如果您是第一次参与开源项目或本项目，以下步骤可以帮助您快速上手：

1. **阅读 README**：了解项目用途和功能
2. **浏览 `FEATURE_ROADMAP.md`**：查看所有带 🏷️ `good first issue` 标记的任务
3. **选择一个 Issue**：在 GitHub Issues 中认领一个 `good first issue`
4. **搭建开发环境**：按照上方指南搭建环境
5. **提交 PR**：完成开发后提交 Pull Request

### 推荐入门任务

以下任务特别适合新贡献者：

| 任务 | 难度 | 类型 | 涉及文件 |
|------|------|------|---------|
| 移动端时间选择器修复 | 🟢 低 | CSS | `dashboard_template.html` |
| 三视图措辞统一 | 🟢 低 | 文本 | `dashboard_template.html` |
| 哮喘关键词移除 | 🟢 低 | Python + JS | `health_data_schema.py` + `dashboard_template.html` |
| 清理 `movingAvg()` 死代码 | 🟢 低 | JS + 文档 | `dashboard_template.html` |
| 临床免责声明插入 | 🟢 低 | HTML + Python | `dashboard_template.html` + `report_generator.py` |
| FDA 引用措辞修正 | 🟢 低 | 文本 | 全仓 grep 替换 |
| Docker 部署配置 | 🟢 低 | DevOps | 新建 `Dockerfile` |
| GitHub Actions CI | 🟢 低 | CI/CD | 新建 `.github/workflows/ci.yml` |
| API 文档编写 | 🟢 低 | 文档 | 新建 `doc/API.md` |
| 使用截图/GIF 补充 | 🟢 低 | 文档 | `doc/` + `README.md` |

---

## 🔒 隐私与安全

本项目处理敏感的个人健康数据，贡献时请**严格遵守**以下规则：

### ⛔ 绝对禁止

- **提交真实健康数据**：`people/`、`data/`、`health_data.json` 等目录/文件已在 `.gitignore` 中，绝不可手动添加到 Git
- **提交 API 密钥**：`publish_config.json`、`.env` 等配置文件绝不可提交
- **在 Issue/PR 中粘贴真实数据**：讨论问题时请使用**脱敏或虚构**的示例数据
- **引入外部数据上报**：不得添加任何将用户数据发送到外部服务器的功能

### ✅ 正确做法

- 测试数据使用虚构的姓名和数值
- 提交前运行 `git diff --cached` 确认未包含敏感文件
- 新增文件时检查是否需要加入 `.gitignore`

---

## ❓ 获取帮助

- **GitHub Issues**：在 [Issue 区](https://github.com/yigao714/health-data-manager/issues) 提问或讨论
- **讨论区**：对于开放性话题，欢迎使用 GitHub Discussions

感谢您的贡献！每一个 Star ⭐、Issue 和 PR 都是这个项目持续迭代的动力。
