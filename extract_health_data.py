"""
华为家庭空间截图 OCR 结构化提取器
==================================

复用 llm_medical_extractor 的 QwenProvider 核心能力（Base64图片编码 + Pydantic校验），
为华为家庭空间的健康截图定制了专用的 Prompt 和 Schema。

用法:
    # 提取 data/ 目录中所有未处理的截图
    python extract_health_data.py

    # 测试单张图片
    python extract_health_data.py --test-single data/xxxx.jpg

    # 强制重新提取所有图片（忽略已处理标记）
    python extract_health_data.py --force
"""

import os
import sys
import io
import json
import base64
import mimetypes
import requests
from pathlib import Path
from typing import Optional, Union
from datetime import datetime

# 修复 Windows GBK 终端无法输出 emoji 的问题
if sys.stdout and hasattr(sys.stdout, 'buffer') and not getattr(sys.stdout, '_utf8_wrapped', False):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stdout._utf8_wrapped = True
if sys.stderr and hasattr(sys.stderr, 'buffer') and not getattr(sys.stderr, '_utf8_wrapped', False):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    sys.stderr._utf8_wrapped = True

# 将项目根目录加入路径
PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

from health_data_schema import (
    DailyHealthData,
    HealthScreenshotExtraction,
    HealthDataStore,
)

# ──────────────────────────────────────────────
# 华为家庭空间截图专用提取 Prompt
# ──────────────────────────────────────────────

PROMPT_HUAWEI_HEALTH = """你是一个专业的健康数据结构化提取系统。请仔细分析这张华为/荣耀手机"家庭空间"应用的健康数据截图。

【你的任务】
从截图中精确提取以下每日健康指标数据：

1. **日期**：截图中显示的日期（如"2026年06月04日"），请转换为 YYYY-MM-DD 格式
2. **活动数据**：
   - 步数（整数）
   - 距离（公里，保留小数）
   - 锻炼时长（分钟，整数）
3. **心血管数据**：
   - 心率范围（最低-最高，如"54-132 次/分钟"）→ 提取为 heart_rate_min 和 heart_rate_max
   - 静息心率（次/分钟）
4. **血氧数据**：
   - 血氧饱和度范围（如"95%-99%"）→ 提取为 spo2_min 和 spo2_max（只取数字）
5. **睡眠数据**：
   - 总睡眠时长（如"7小时16分钟"）→ 转换为小时制小数，如 7.27
   - 入睡时间（如"21:28"）
   - 醒来时间（如"05:26"）
   - 睡眠分数（整数）

【严格规则 — 必须遵守】
1. 忠实原图：只能从截图中提取可见的数据，禁止猜测或编造任何数值
2. 精确数字：步数不要遗漏逗号分隔的数位（如 1,976 应提取为 1976）
3. 睡眠时长转换：X小时Y分钟 → X + Y/60，保留两位小数
4. 日期转换：YYYY年MM月DD日 → YYYY-MM-DD
5. 如果某项数据在截图中不可见或被遮挡，对应字段必须为 null
6. 血氧范围中的百分号要去掉，只保留数字
7. 注意心率范围格式是 "最低-最高"，例如 "54-132" → min=54, max=132

【输出格式】
严格按照指定的 JSON Schema 输出，不要输出任何额外文字。
"""


class QwenVLExtractor:
    """
    基于通义千问 Qwen-VL 的华为健康截图提取器。
    核心逻辑参考 llm_medical_extractor.providers.qwen.QwenProvider，
    但简化了依赖，可独立运行。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "qwen-vl-max",
    ):
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or os.getenv("DASHSCOPE_API_KEY_BJ")
        if not self.api_key:
            raise RuntimeError(
                "缺少 DASHSCOPE_API_KEY 环境变量。\n"
                "请设置: set DASHSCOPE_API_KEY=sk-xxxxxx"
            )
        self.model_name = model_name
        self.api_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

    @staticmethod
    def _encode_image(image_path: Union[str, Path]) -> str:
        """将本地图片转为 Base64 字符串"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @staticmethod
    def _clean_json_response(text: str) -> str:
        """剥离 Markdown 代码块标记，提取纯 JSON"""
        text = text.strip()
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.rfind("```")
            if end > start:
                return text[start:end].strip()
        if "```" in text:
            start = text.find("```") + 3
            end = text.rfind("```")
            if end > start:
                return text[start:end].strip()
        # 兜底：寻找最外层花括号
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return text[start:end + 1]
        return text

    def extract_from_image(self, image_path: Union[str, Path]) -> HealthScreenshotExtraction:
        """
        对单张截图进行结构化提取。

        Args:
            image_path: 截图文件路径

        Returns:
            HealthScreenshotExtraction: 包含提取数据和置信度的完整结果
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"图片不存在: {image_path}")

        # 编码图片
        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        b64 = self._encode_image(image_path)

        # 构造 JSON Schema 注入
        schema_json = HealthScreenshotExtraction.model_json_schema()
        schema_str = json.dumps(schema_json, ensure_ascii=False)

        full_instruction = (
            f"{PROMPT_HUAWEI_HEALTH}\n\n"
            f"【强制输出格式】\n"
            f"你必须严格遵循以下 JSON Schema 输出你的结果，不要输出任何 Markdown 标记或说明性文字：\n"
            f"{schema_str}"
        )

        # 构造请求
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": full_instruction},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64}"
                            },
                        },
                    ],
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        print(f"  ⏳ 正在调用 Qwen-VL ({self.model_name}) 识别...")
        try:
            resp = requests.post(
                self.api_url, json=payload, headers=headers, timeout=120
            )
            resp.raise_for_status()
            result_data = resp.json()
        except requests.exceptions.RequestException as e:
            err_msg = str(e)
            if hasattr(e, "response") and e.response is not None:
                err_msg += f" Response: {e.response.text}"
            raise RuntimeError(f"Qwen API 请求失败: {err_msg}")

        # 提取文本
        try:
            raw_content = result_data["choices"][0]["message"]["content"]
            clean_json_str = self._clean_json_response(raw_content)
        except (KeyError, IndexError):
            raise RuntimeError(f"Qwen 响应格式异常: {json.dumps(result_data, ensure_ascii=False)}")

        # Pydantic 校验
        try:
            result = HealthScreenshotExtraction.model_validate_json(clean_json_str)
        except Exception as e:
            raise ValueError(
                f"数据格式校验失败:\n"
                f"错误: {str(e)}\n\n"
                f"原始大模型输出:\n{clean_json_str}"
            )

        return result

    def validate_extraction(self, data: DailyHealthData) -> list[str]:
        """
        对提取结果进行合理性校验，返回警告列表。
        """
        warnings = []

        if data.steps is not None and data.steps > 50000:
            warnings.append(f"⚠️ 步数异常偏高: {data.steps}")

        if data.resting_heart_rate is not None:
            if data.resting_heart_rate < 40 or data.resting_heart_rate > 100:
                warnings.append(f"⚠️ 静息心率异常: {data.resting_heart_rate}")

        if data.heart_rate_min is not None and data.heart_rate_max is not None:
            if data.heart_rate_min >= data.heart_rate_max:
                warnings.append(f"⚠️ 心率范围异常: {data.heart_rate_min}-{data.heart_rate_max}")

        if data.spo2_min is not None:
            if data.spo2_min < 70 or data.spo2_min > 100:
                warnings.append(f"⚠️ 血氧下限异常: {data.spo2_min}%")

        if data.sleep_hours is not None:
            if data.sleep_hours < 0 or data.sleep_hours > 24:
                warnings.append(f"⚠️ 睡眠时长异常: {data.sleep_hours}小时")

        if data.sleep_score is not None:
            if data.sleep_score < 0 or data.sleep_score > 100:
                warnings.append(f"⚠️ 睡眠分数异常: {data.sleep_score}")

        return warnings

    def verify_with_ai(
        self, image_path: Union[str, Path], extracted: DailyHealthData
    ) -> dict:
        """
        AI 双重验证：将提取结果 + 原图再次发给 LLM，逐字段核对。

        返回:
            {
                "verified": True/False,
                "field_results": { "steps": True, "heart_rate_min": False, ... },
                "corrections": { "heart_rate_min": 56 },  # 如果有修正建议
                "notes": "..."
            }
        """
        image_path = Path(image_path)
        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        b64 = self._encode_image(image_path)

        # 构造验证数据摘要
        data_summary = (
            f"日期: {extracted.date}\n"
            f"步数: {extracted.steps}\n"
            f"距离: {extracted.distance_km} km\n"
            f"锻炼时长: {extracted.exercise_minutes} 分钟\n"
            f"心率范围: {extracted.heart_rate_min}-{extracted.heart_rate_max} 次/分钟\n"
            f"静息心率: {extracted.resting_heart_rate} 次/分钟\n"
            f"血氧范围: {extracted.spo2_min}%-{extracted.spo2_max}%\n"
            f"睡眠时长: {extracted.sleep_hours} 小时\n"
            f"入睡时间: {extracted.sleep_start}\n"
            f"醒来时间: {extracted.sleep_end}\n"
            f"睡眠分数: {extracted.sleep_score}"
        )

        verify_prompt = f"""你是一个数据验证专家。请对比这张华为家庭空间健康截图和以下已提取的数据，逐字段核对是否正确。

【已提取的数据】
{data_summary}

【你的任务】
1. 仔细查看截图中的每个数值
2. 与上述已提取的数据逐一对比
3. 严格按以下 JSON 格式输出验证结果：

{{
    "verified": true或false（全部正确为true），
    "field_results": {{
        "date": true或false,
        "steps": true或false,
        "distance_km": true或false,
        "exercise_minutes": true或false,
        "heart_rate_min": true或false,
        "heart_rate_max": true或false,
        "resting_heart_rate": true或false,
        "spo2_min": true或false,
        "spo2_max": true或false,
        "sleep_hours": true或false,
        "sleep_start": true或false,
        "sleep_end": true或false,
        "sleep_score": true或false
    }},
    "corrections": {{}} 或 {{"字段名": 正确值}},
    "notes": "验证备注"
}}

【规则】
- 如果截图中看不到某个数据，对应字段标记为 true（无法验证视为通过）
- 睡眠时长允许 ±0.05 小时的舍入误差
- 只输出 JSON，不要输出其它文字
"""

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": verify_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64}"
                            },
                        },
                    ],
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        print(f"  🔍 AI 复核验证中...")
        try:
            resp = requests.post(
                self.api_url, json=payload, headers=headers, timeout=120
            )
            resp.raise_for_status()
            result_data = resp.json()
            raw_content = result_data["choices"][0]["message"]["content"]
            clean_json = self._clean_json_response(raw_content)
            verification = json.loads(clean_json)
        except Exception as e:
            print(f"  ⚠️ AI 复核调用失败: {str(e)}")
            return {
                "verified": None,
                "field_results": {},
                "corrections": {},
                "notes": f"复核失败: {str(e)}",
            }

        return verification

    def extract_and_verify(
        self, image_path: Union[str, Path]
    ) -> tuple:
        """
        完整的提取+验证流程。

        返回:
            (extraction_result, validation_warnings, verification_result)
        """
        # 第一步：提取
        result = self.extract_from_image(image_path)

        # 第二步：合理性校验
        warnings = self.validate_extraction(result.data)

        # 第三步：AI 复核
        verification = self.verify_with_ai(image_path, result.data)

        # 如果 AI 复核发现错误且提供了修正
        if verification.get("corrections"):
            corrections = verification["corrections"]
            data_dict = result.data.model_dump()
            corrected = False
            for field, value in corrections.items():
                if field in data_dict and data_dict[field] != value:
                    print(f"  🔧 AI 修正: {field} = {data_dict[field]} → {value}")
                    data_dict[field] = value
                    corrected = True
            if corrected:
                result.data = DailyHealthData.model_validate(data_dict)

        return result, warnings, verification


def check_cross_day_consistency(
    new_data: DailyHealthData,
    existing_records: list,
) -> list[str]:
    """
    跨日一致性检查：与历史数据对比，检测突变。

    Args:
        new_data: 新提取的数据
        existing_records: 已有的历史记录列表

    Returns:
        突变警告列表
    """
    if not existing_records:
        return []

    warnings = []

    # 计算历史均值和标准差
    def hist_stats(field):
        values = [getattr(r, field) for r in existing_records
                  if getattr(r, field) is not None]
        if len(values) < 3:
            return None, None
        mean = sum(values) / len(values)
        std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
        return mean, std

    # 定义检查项: (字段名, 显示名, 允许的标准差倍数)
    checks = [
        ("steps", "步数", 3.0),
        ("resting_heart_rate", "静息心率", 3.0),
        ("spo2_min", "血氧下限", 3.0),
        ("sleep_hours", "睡眠时长", 2.5),
    ]

    for field, display_name, threshold in checks:
        new_val = getattr(new_data, field)
        if new_val is None:
            continue

        mean, std = hist_stats(field)
        if mean is None or std is None or std == 0:
            continue

        deviation = abs(new_val - mean) / std
        if deviation > threshold:
            warnings.append(
                f"⚠️ {display_name}突变: {new_val} "
                f"(历史均值 {mean:.1f} ± {std:.1f}, 偏差 {deviation:.1f}σ)"
            )

    return warnings


def scan_and_extract(
    data_dir: str = "data",
    json_path: str = "health_data.json",
    force: bool = False,
):
    """
    扫描截图目录，对未处理的图片进行OCR提取，更新JSON数据。

    Args:
        data_dir: 截图目录路径
        json_path: JSON数据文件路径
        force: 是否强制重新提取所有图片
    """
    data_dir = Path(PROJECT_DIR) / data_dir
    json_path = Path(PROJECT_DIR) / json_path

    # 加载或创建数据存储
    if json_path.exists() and not force:
        store = HealthDataStore.load(str(json_path))
        print(f"📂 已加载 {len(store.records)} 条现有记录")
    else:
        store = HealthDataStore()
        print("📂 创建新的数据存储")

    # 扫描图片
    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    images = sorted([
        f for f in data_dir.iterdir()
        if f.suffix.lower() in image_exts
    ])

    if not images:
        print(f"❌ 在 {data_dir} 中未找到图片文件")
        return

    # 筛选未处理的图片
    if force:
        pending = images
        print(f"🔄 强制模式：将重新提取所有 {len(images)} 张图片")
    else:
        pending = [
            img for img in images
            if img.name not in store.processed_files
        ]
        print(f"📸 发现 {len(images)} 张图片，其中 {len(pending)} 张待处理")

    if not pending:
        print("✅ 所有图片均已处理，无需提取")
        return

    # 初始化提取器
    extractor = QwenVLExtractor()

    success_count = 0
    fail_count = 0

    for i, img_path in enumerate(pending, 1):
        print(f"\n{'='*50}")
        print(f"📷 [{i}/{len(pending)}] 正在处理: {img_path.name}")

        try:
            result = extractor.extract_from_image(img_path)

            # 合理性校验
            warnings = extractor.validate_extraction(result.data)
            if warnings:
                print(f"  ⚠️ 数据校验警告:")
                for w in warnings:
                    print(f"    {w}")

            # 存入数据
            is_new = store.add_record(result.data, img_path.name)
            status = "新增" if is_new else "更新"

            print(f"  ✅ 提取成功 ({status})")
            print(f"     日期: {result.data.date}")
            print(f"     步数: {result.data.steps}")
            print(f"     心率: {result.data.heart_rate_min}-{result.data.heart_rate_max}")
            print(f"     睡眠: {result.data.sleep_hours}h, 分数: {result.data.sleep_score}")
            if result.confidence is not None:
                print(f"     置信度: {result.confidence:.1%}")
            if result.extraction_notes:
                print(f"     备注: {result.extraction_notes}")

            success_count += 1

        except Exception as e:
            print(f"  ❌ 提取失败: {str(e)}")
            fail_count += 1

    # 保存结果
    store.save(str(json_path))
    print(f"\n{'='*50}")
    print(f"📊 提取完成: 成功 {success_count} 张, 失败 {fail_count} 张")
    print(f"💾 数据已保存至: {json_path}")
    print(f"📝 共 {len(store.records)} 条记录")


def test_single(image_path: str):
    """测试单张图片的提取"""
    print(f"🧪 测试模式: 提取单张图片")
    print(f"   图片: {image_path}")

    extractor = QwenVLExtractor()
    result = extractor.extract_from_image(image_path)

    print(f"\n📋 提取结果:")
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))

    warnings = extractor.validate_extraction(result.data)
    if warnings:
        print(f"\n⚠️ 校验警告:")
        for w in warnings:
            print(f"  {w}")
    else:
        print(f"\n✅ 数据校验通过")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="华为家庭空间截图OCR提取器")
    parser.add_argument(
        "--test-single",
        type=str,
        help="测试单张图片的提取",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新提取所有图片（忽略已处理标记）",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="截图目录路径（默认: data）",
    )
    parser.add_argument(
        "--json-path",
        type=str,
        default="health_data.json",
        help="JSON数据文件路径（默认: health_data.json）",
    )

    args = parser.parse_args()

    if args.test_single:
        test_single(args.test_single)
    else:
        scan_and_extract(
            data_dir=args.data_dir,
            json_path=args.json_path,
            force=args.force,
        )
