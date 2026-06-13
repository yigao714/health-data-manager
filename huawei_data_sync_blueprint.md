# 华为运动健康数据一键同步：获取指南与系统集成设计蓝图

本蓝图文档包含两大部分：
1. **《华为运动健康数据备份下载实操指南》**（面向您或您的客户，手把手指导如何获取原始数据压缩包）；
2. **《系统集成与临床分析设计方案》**（面向开发，设计数据导入路径、AES-256 解密逻辑、增量合并机制及符合最新医学指南的临床评估指标）。

---

# 第一部分：华为运动健康数据备份下载实操指南

华为为了保护用户隐私，其导出的健康数据包采用 **AES-256 强加密** 格式。请严格按照以下步骤操作以获取完整数据：

### 📥 步骤一：在电脑浏览器提交申请
1. 用电脑浏览器访问华为官方个人隐私中心：[https://privacy.consumer.huawei.com](https://privacy.consumer.huawei.com)。
2. 使用需要导出数据的**华为帐号和密码**进行登录。
   * *💡 安全提示：如果是首次在电脑端登录，或帐号开启了双重验证，网页会提示输入发送到使用者手机上的**短信验证码**。*
3. 登录成功后，在主页中点击 **“获取您的数据副本”**。
4. 页面会弹出身份二次验证，再次输入密码或短信验证码确认。
5. 进入数据选择页面，**仅勾选“运动健康”**（这样可以大幅加快华为后台打包的速度），点击“确定”。
6. **设置压缩密码（至关重要）**：
   * 系统会要求您为即将生成的 ZIP 文件设置一个密码。
   * *⚠️ 警告：该密码由您自己设定且华为不会保存，它是后续我们本地系统解密导入的**唯一钥匙**，请务必将其记录下来。*

### ⏳ 步骤二：等待华为打包完成（通常几小时到一天）
* 提交后，华为服务器会在后台汇总该帐号在云端的运动健康历史记录。
* 打包完成后，使用者的手机会收到一条短信通知（或注册邮箱收到邮件），告知数据副本已就绪。

### 💾 步骤三：下载加密 ZIP 包到电脑
1. 收到通知后，重新登录 [华为隐私中心官网](https://privacy.consumer.huawei.com)。
2. 页面上会显示已准备就绪的数据包，直接点击 **“下载”**，将该加密的 `.zip` 压缩包保存到电脑本地。

> ### 📌 补充注意事项（避坑指南）
> * **数据年限限制**：自助申请的数据通常只包含**最近 1 年**的记录。如果您需要更久远的历史数据（例如 3 到 5 年前的记录），请在隐私中心的“问题反馈”中联系客服，申请“延长数据副本年限”。
> * **云同步开关**：请确保使用者的手机运动健康 App 中，**“数据同步到云”的开关已开启**（路径：运动健康App > 我 > 隐私管理 > 数据同步管理 > 开启“同步运动健康数据到云”）。如果云同步未开启，云端将没有历史数据，导出的压缩包将是空的。

---

# 第二部分：系统集成与临床分析设计方案

在单机版健康管理器中，我们需要在后台增加一个 ZIP 文件上传通道，提取并合并其中的 JSON 数据。

## 一、 技术细节与 AES-256 解密规避

### 1. 关键技术问题：Python 内建库的限制
* **问题描述**：Python 标准库的 `zipfile` 模块**仅支持传统的 ZipCrypto 加密格式**，如果直接用 `zipfile.extractall(pwd=...)` 解压华为的 AES-256 加密压缩包，会抛出 `NotImplementedError: That compression method is not supported` 异常。
* **规避解决方案**：
  * **方案 A（无需外部依赖）**：利用 Windows 系统自带的命令行工具（如果用户电脑安装了 7-Zip，可通过 `subprocess` 调用 `7z.exe` 进行解密提取）。
  * **方案 B（推荐，纯 Python 跨平台）**：使用第三方库 `pyzipper`（它是一个完整支持 AES 解密的 zipfile 替代库）。在服务器启动前运行 `pip install pyzipper`。

### 2. 后端数据解密与解析路由设计 (`app.py`)
新增接口：`/api/import-huawei-zip`，支持流式读取，**不向硬盘写入任何密码和明文数据**：

```python
import pyzipper
import io
import json
from flask import request, jsonify

@app.route("/api/import-huawei-zip", methods=["POST"])
def api_import_huawei_zip():
    person_id = request.args.get("person", "").strip()
    password = request.form.get("password", "").strip()
    
    if "file" not in request.files or not password:
        return jsonify({"error": "缺少文件或解压密码"}), 400
        
    file = request.files["file"]
    
    try:
        # 将上传的 ZIP 读入内存
        zip_data = io.BytesIO(file.read())
        
        # 使用 pyzipper 读取加密的 zip
        with pyzipper.AESZipFile(zip_data) as zf:
            zf.setpassword(password.encode('utf-8'))
            
            # 1. 扫描 zip 内的文件列表，定位核心每日汇总和睡眠 JSON
            file_names = zf.namelist()
            summary_file = next((f for f in file_names if "daily_health_summary" in f or "statistics" in f), None)
            sleep_file = next((f for f in file_names if "sleep" in f), None)
            
            if not summary_file:
                return jsonify({"error": "压缩包内未找到运动健康每日汇总数据"}), 400
                
            # 2. 从内存中直接解析 JSON (数据不落地，无隐私泄露)
            daily_data = json.loads(zf.read(summary_file).decode('utf-8'))
            sleep_data = json.loads(zf.read(sleep_file).decode('utf-8')) if sleep_file else []
            
        # 3. 执行增量合并逻辑
        store = load_store(person_id)
        imported_count = merge_huawei_data(store, daily_data, sleep_data)
        
        # 4. 保存数据库并重新生成个人仪表盘
        save_store(store, person_id)
        regenerate_dashboard(store, person_id)
        
        return jsonify({"success": True, "imported_records": imported_count})
        
    except RuntimeError:
        return jsonify({"error": "解压密码错误，无法解密文件"}), 400
    except Exception as e:
        return jsonify({"error": f"导入失败: {str(e)}"}), 500
```

### 3. 数据合并与排重策略 (Merge Strategy)
为了避免重复数据或覆盖用户手动修正的数据，采用 **“增量合并”** 算法：
* 读取导入记录的日期 `date`。
* **规则一（排重）**：如果该日期在本地数据库中尚不存在，则直接追加（Create）。
* **规则二（更新保护）**：如果该日期已存在：
  * 对比关键指标。如果导入的数据与本地数据一致，则跳过。
  * 如果不一致，且本地数据并未被标记为“用户手动修改过”（可在 schema 中为修改过的记录增设一个标签 `edited_by_user: bool`），则用导入的官方数据覆盖更新；否则以用户手动修正的值为准，保护人工编辑成果。

---

## 二、 基于最新指南的临床分析评估模型

导入 15 天或 1 年的数据后，系统需遵循以下临床指南（2020-2025版）对数据进行深度解读与可视化：

### 1. 静息心率稳定性与 $\beta$ 受体阻滞剂控制率 (AHA/ESC 2023)
* **背景指南**：《2023年 ESC 慢性冠脉综合征管理指南》和《2022年 AHA/ACC 冠心病二级预防指南》。
* **评估逻辑**：
  * 若用户档案无基础病：静息心率基线正常范围定义为 **60-80 bpm**。
  * 若用户档案中包含高血压或冠心病且使用 $\beta$ 受体阻滞剂：静息心率控制目标调整为 **55-65 bpm**。
* **展示与分析**：
  * 计算 15 天内静息心率在目标区间内的天数百分比（称为 **“药物控制达标率 (Time in Target Range, TTR)”**）。
  * 若 TTR $< 60\%$（即静息心率频繁 $> 75\text{ bpm}$ 或 $< 50\text{ bpm}$），系统报告中醒目提示：“*该 15 天周期内药物心率控制达标率仅为 X%，建议门诊复查，由医生评估是否需调整 $\beta$ 阻滞剂用量。*”

### 2. 睡眠质量 - 夜间血氧低氧事件交叉模型 (OSAHS 预警, JACC 2022)
* **背景指南**：中华医学会呼吸病学分会《阻塞性睡眠呼吸暂停低通气综合征诊治指南（2020/2023）》及 2022 年 JACC 睡眠呼吸障碍与心血管风险研究。
* **评估逻辑**：
  * 指标一：夜间平均最低血氧 `spo2_min`。
  * 指标二：日内睡眠质量得分（Sleep Score）及深睡比例。
* **分析判定**：
  * **正常**：`spo2_min >= 95%` 且睡眠分数稳定。
  * **轻中度缺氧风险**：`90% <= spo2_min < 95%` 持续 3 天以上。
  * **重度低氧与 OSAHS 高危预警**：连续 15 天内有 3 天以上 `spo2_min < 90%`（例如频繁出现 88%、85% 甚至更低），且同时伴有睡眠分数低于 65 分、中途清醒次数增多。
  * **系统解读**：在仪表盘上弹出黄色/红色警报，并输出临床意见：“*系统检测到您最近 15 天内有多日夜间血氧饱和度降至 X%（低于安全阈值 90%），且伴有睡眠碎片化。这高度提示可能存在阻塞性睡眠呼吸暂停（打鼾、憋气）。夜间低氧会显著增加清晨高血压和夜间卒中风险，强烈建议前往呼吸科或睡眠中心进行多导睡眠图（PSG）检查。*”

### 3. 日间活动代偿率与最大心率安全边界 (Gelish 2020)
* **背景研究**：ACSM（美国运动医学会）《运动测试与处方指南（第十一版）》。
* **评估逻辑**：
  * 计算老年人安全最大心率上限（Gelish公式）：$\text{HR\_max\_limit} = 207 - 0.7 \times \text{年龄}$。
  * 对于 79 岁用户，安全上限为 $151$ bpm。
* **展示与分析**：
  * 监测 15 天内每天的 `heart_rate_max`（最高心率）是否逼近或超过安全上限。
  * 若某天 `heart_rate_max` 超过 $130$ bpm（达到了安全上限的 85%），系统会比对当天的锻炼时长和步数。
  * **报警判定**：若当天运动量为 0，但最高心率依然达到 135 bpm，系统标记为“异常心率升高”，提示可能存在阵发性心动过速、高热应激或情绪剧烈波动；反之，若在有氧运动时心率合理升高，则评估为健康的运动响应。
