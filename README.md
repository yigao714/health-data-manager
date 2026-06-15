# 🏥 AI 智能健康数据管理中心 (Health Data Manager)

[![GitHub stars](https://img.shields.io/github/stars/yigao714/health-data-manager.svg?style=social)](https://github.com/yigao714/health-data-manager)
[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

基于 **Qwen-VL 多模态大模型** 的健康截图结构化 OCR 提取系统与多维度数据分析看板。支持**一键云端部署**与**微信/企业微信端完美共享**，专为家庭多成员长周期健康追踪打造。

> **💡 解决的痛点**：  
> 很多长辈使用华为等智能手环/手表，但健康数据零散在“家庭空间”截图里，极难进行长期统计。本项目实现了**“截图发送 → AI 自动提取 → 自动入库归档 → 生成循证医学评估看板 → 一键云部署发回微信”**的闭环。

---

## 🌟 核心功能亮点

### 1. 📸 智能截图识别 (Qwen-VL-max 驱动)
* **秒级提取**：直接拖拽或上传华为/荣耀手机“家庭空间”健康截图，AI 自动提取：**步数、行走距离、锻炼时长、心率范围、静息心率、最低/最高血氧、总睡眠时长、作息起止时间及睡眠分数**。
* **AI 双重验证**：大模型提取后，系统会自动将提取结果与原图发给 AI 进行第二轮双重比对纠错，将大模型“幻觉”率降至最低。
* **跨日一致性预警**：新数据入库时，自动比对历史数据的平均值与标准差，若手环佩戴异常导致指标突变（如心率暴增、睡眠骤降）会提供报警提示。

### 2. 📊 可视化多维健康看板 (ECharts)
* **多维动态图表**：自动绘制活动量、心脏波动、血氧变化、睡眠规律性等四维动态折线图、柱状图及日历热力图。
* **个体化循证阈值**：引入专业医学背景指标校正：
  * **呼吸系统疾病 (COPD/慢阻肺)**：自动下调血氧安全阈值，避免误报。
  * **年龄校正**：根据长辈年龄（如 $\ge 65$ 岁）动态适配睡眠时长与心率评估基准。
  * **药物抗凝 (β阻滞剂)**：自动调整静息心率下限。

### 3. 📤 一键发布云端 & 手机微信完美适配
* 解决手机微信直接发送 `.html` 文件在苹果手机上显示源码、在华为手机上图表空白的痛点。
* 支持一键调用 Netlify 免费云托管 API，生成专属、高私密性的随机域名网址。
* 接收人直接在微信中点击链接即可在内置浏览器内完美运行 full-interactive 动态图表（支持 ECharts 动效、多时间窗口切换与置灰防呆逻辑）。

![微信/Netlify 发布效果预览](doc/wechat_netlify_preview.png)

---

## 🏗️ 架构与技术栈

### ⚙️ 系统工作流与架构 (Mermaid)

```mermaid
graph TD
    A[智能健康设备/手环] -->|健康数据截图| B[微信家庭空间/截图]
    B -->|拖入/上传| C[AI 智能健康数据管理中心]
    
    subgraph 后端服务 (Python Flask)
        C -->|1. OCR 结构化提取| D[通义千问 Qwen-VL-max]
        D -->|提取数据| E[AI 双重验证与纠错]
        E -->|清洗校验 (Pydantic)| F[增量数据合并 & 数据库入库]
        F -->|数据更新| G[生成内联 HTML 仪表盘]
        F -->|报告导出| H[Word 阶段性分析报告]
    end
    
    subgraph 前端展示 & 云端共享
        G -->|一键发布 API| I[Netlify 云端托管]
        I -->|专属随机加密 URL| J[微信/企业微信端完美共享]
        G -->|局域网共享| K[家庭 WiFi 终端访问]
    end
    
    style C fill:#f9f,stroke:#333,stroke-width:2px
    style I fill:#bbf,stroke:#333,stroke-width:2px
    style J fill:#bfb,stroke:#333,stroke-width:2px
```

* **后端服务**：Python + Flask (轻量高效)
* **大模型驱动**：阿里云通义千问 Qwen-VL-max API (零额外本地硬件要求)
* **前端渲染**：Vanilla HTML5 + Modern CSS3 + Javascript (ES6)
* **数据可视化**：Apache ECharts (完全内联化处理，支持完全脱网离线查看)
* **报告导出**：python-docx 自动渲染带表格、图表和医学建议的 Word 版阶段性分析报告

---

## 🚀 快速启动指南

### 1. 安装依赖环境
请确保您的电脑上已安装 Python 3.9 或更高版本，然后在项目目录下运行以下命令：
```bash
pip install flask python-docx matplotlib pydantic pydantic-settings requests
```

### 2. 配置大模型 API 密钥
本系统使用通义千问大模型进行截图 OCR，请在您的系统环境变量中配置您的 DashScope 密钥（[如何获取 API 密钥](https://help.aliyun.com/zh/dashscope/developer-reference/acquisition-and-configuration-of-api-key)）：
* **Windows (CMD / PowerShell)**:
  ```powershell
  $env:DASHSCOPE_API_KEY="您的阿里云API密钥"
  ```

### 3. 启动项目
双击运行目录下的 [`start.bat`](file:///d:/Agent/data%20analysis--JY/start.bat)，或者在命令行中运行：
```bash
python app.py
```
启动后，系统会自动在您的默认浏览器中打开管理中心：
👉 `http://localhost:8080`

---

## 🔒 隐私保护策略 (Safety & Privacy First)

本项目对隐私保护极度重视，在开源设计中采用了多层防御：
1. **数据本地化**：所有成员的健康记录、个人档案以及上传的截图全部物理保存在您本地电脑的 `people/` 和 `data/` 目录中。
2. **Git 强隔离**：项目内置了高强度的 [`.gitignore`](file:///d:/Agent/data%20analysis--JY/.gitignore) 配置文件。您上传到 GitHub 上的版本**绝对不会包含任何家人姓名、截图和本地健康数据库**。
3. **云端安全网址**：发布到 Netlify 的网址包含 8 位以上随机加密后缀，且禁止了搜索引擎抓取，只有拿到您分享的专属链接的人才可访问。

---

## 🤝 贡献与 Star

如果您觉得这个工具对您照顾家人、记录长辈健康有所帮助，欢迎在右上角点一个 **⭐ Star**！

您的点赞是这个项目持续迭代的动力！有任何功能建议或 Bug 反馈，请在 Issue 区提出。

### 📌 参与贡献

- 📖 阅读 [**贡献指南 (CONTRIBUTING.md)**](CONTRIBUTING.md) 了解开发规范与 PR 流程
- 🗺️ 查看 [**功能路线图 (FEATURE_ROADMAP.md)**](FEATURE_ROADMAP.md) 了解未来方向和可认领任务
- 🏷️ 新手推荐从标记有 `good first issue` 的 Issue 开始
