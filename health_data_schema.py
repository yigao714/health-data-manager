"""
华为家庭空间健康数据 — Pydantic V2 模型定义
=============================================

定义从截图中提取的每日健康指标结构，以及用于LLM结构化输出的响应模型。
"""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator
import json
from datetime import datetime


class PersonProfile(BaseModel):
    """个人健康档案 — 用于个体化评估阈值调整"""

    age: Optional[int] = Field(
        default=None,
        description="年龄（整数），影响心率评估(最大心率=220-age)、睡眠需求、运动强度判断"
    )
    sex: Optional[Literal["male", "female"]] = Field(
        default=None,
        description="生理性别: male/female，影响心率正常范围、心血管风险评估"
    )
    height_cm: Optional[float] = Field(
        default=None,
        description="身高（厘米），与体重一起计算BMI"
    )
    weight_kg: Optional[float] = Field(
        default=None,
        description="体重（公斤），用于BMI计算和OSAHS风险评估"
    )
    conditions: List[str] = Field(
        default_factory=list,
        description="基础疾病列表，如: ['高血压','糖尿病','COPD','冠心病','睡眠呼吸暂停']。"
                    "直接影响各指标的评估标准"
    )
    medications: List[str] = Field(
        default_factory=list,
        description="当前用药列表，如: ['美托洛尔','氨氯地平']。"
                    "β受体阻滞剂会人为降低心率，需特殊处理"
    )
    smoking: Optional[bool] = Field(
        default=None,
        description="是否吸烟，影响血氧基线和心血管风险"
    )

    @property
    def bmi(self) -> Optional[float]:
        """计算BMI (kg/m²)"""
        if self.height_cm and self.weight_kg:
            h_m = self.height_cm / 100
            return round(self.weight_kg / (h_m * h_m), 1)
        return None

    @property
    def max_heart_rate(self) -> Optional[int]:
        """预估最大心率 (220 - age)"""
        if self.age:
            return 220 - self.age
        return None

    @property
    def has_beta_blocker(self) -> bool:
        """是否服用β受体阻滞剂（影响心率解读）"""
        beta_blockers = ['美托洛尔', '比索洛尔', '阿替洛尔', '普萘洛尔', '卡维地洛',
                         'metoprolol', 'bisoprolol', 'atenolol', 'propranolol', 'carvedilol']
        return any(med.lower() in [b.lower() for b in beta_blockers]
                   for med in self.medications)

    @property
    def has_copd(self) -> bool:
        """是否有COPD/哮喘（影响血氧基线）— 使用关键词包含匹配"""
        _copd_keywords = ['COPD', '慢阻肺', '阻塞性肺', '哮喘']
        return any(any(kw in c for kw in _copd_keywords) for c in self.conditions)

    def get_thresholds(self) -> dict:
        """根据个人档案返回自适应健康阈值（单一数据源）

        所有阈值集中在此定义，dashboard / report_generator 统一引用。
        血氧阈值参考: BTS/GOLD 指南（COPD）、临床共识（通用）。
        注意: 腕式血氧精度 ±2-3%，判读时应叠加精度容差。
        """
        t = {
            'steps_low': 3000,       # WHO: <5000=久坐, 用3000作为低活动警告
            'steps_goal': 7000,      # Lancet 2022 meta-analysis 最佳获益点
            'spo2_danger': 90,       # 通用人群: <90% 需关注（待临床确认）
            'spo2_warning': 95,      # 通用人群: <95% 留意（待临床确认）
            'spo2_precision': 2,     # 腕式传感器精度容差(%)
            'sleep_low': 6,          # NSF: 成人<6h 睡眠不足
            'sleep_high': 9,         # NSF: 成人>9h 可能过长
            'rhr_low': 50,           # 正常下限(非运动员)
            'rhr_high': 80,          # 持续>80需关注
            'sleep_score_low': 60,
        }
        # COPD/哮喘: 放宽血氧阈值（BTS/GOLD 指南）
        if self.has_copd:
            t['spo2_danger'] = 88    # 待临床确认
            t['spo2_warning'] = 92   # 待临床确认
        # 老年人: 睡眠需求降低
        if self.age and self.age >= 65:
            t['sleep_low'] = 5.5
            t['sleep_high'] = 8
        # β阻滞剂: 心率下限放宽
        if self.has_beta_blocker:
            t['rhr_low'] = 45
        return t


class ExerciseRecord(BaseModel):
    """单次运动记录"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    start_time: Optional[str] = Field(default=None, description="开始时间 HH:MM")
    end_time: Optional[str] = Field(default=None, description="结束时间 HH:MM")
    sport_type: Optional[str] = Field(default=None, description="运动类型: 步行/跑步/骑行/游泳等")
    duration_min: Optional[float] = Field(default=None, description="运动时长（分钟）")
    distance_km: Optional[float] = Field(default=None, description="运动距离（公里）")
    calories: Optional[float] = Field(default=None, description="消耗热量（千卡）")
    avg_heart_rate: Optional[int] = Field(default=None, description="运动平均心率")
    max_heart_rate: Optional[int] = Field(default=None, description="运动最大心率")
    hr_recovery_1min: Optional[int] = Field(default=None, description="运动后1分钟心率恢复值（下降bpm数）")


class DailyHealthData(BaseModel):
    """每日健康数据结构"""

    date: str = Field(
        ...,
        description="日期，格式 YYYY-MM-DD，例如 2026-06-04"
    )

    # ── 活动数据 ──
    steps: Optional[int] = Field(
        default=None,
        description="步数（整数），例如 1976"
    )
    distance_km: Optional[float] = Field(
        default=None,
        description="距离（公里），例如 1.48"
    )
    exercise_minutes: Optional[int] = Field(
        default=None,
        description="锻炼时长（分钟），例如 0 或 30"
    )
    exercise_type: Optional[str] = Field(
        default=None,
        description="主要运动类型，如 步行/跑步/骑行"
    )
    calories: Optional[float] = Field(
        default=None,
        description="当日消耗热量（千卡）"
    )

    # ── 心血管数据 ──
    heart_rate_min: Optional[int] = Field(
        default=None,
        description="当日心率最低值（次/分钟），例如 54"
    )
    heart_rate_max: Optional[int] = Field(
        default=None,
        description="当日心率最高值（次/分钟），例如 132"
    )
    resting_heart_rate: Optional[int] = Field(
        default=None,
        description="静息心率（次/分钟），例如 62"
    )
    avg_heart_rate: Optional[int] = Field(
        default=None,
        description="全天平均心率（次/分钟）"
    )
    hr_recovery_1min: Optional[int] = Field(
        default=None,
        description="运动后1分钟心率恢复值（下降bpm数），≤12为异常"
    )

    # ── 血氧数据 ──
    spo2_min: Optional[int] = Field(
        default=None,
        description="血氧饱和度最低值（%），例如 95"
    )
    spo2_max: Optional[int] = Field(
        default=None,
        description="血氧饱和度最高值（%），例如 99"
    )
    spo2_avg: Optional[float] = Field(
        default=None,
        description="夜间平均血氧饱和度（%）"
    )
    odi: Optional[float] = Field(
        default=None,
        description="氧减指数 ODI（事件/小时），用于 OSAHS 筛查"
    )

    # ── 睡眠基础数据 ──
    sleep_hours: Optional[float] = Field(
        default=None,
        description="总睡眠时长（小时，精确到小数），例如 7.27 代表 7小时16分钟"
    )
    sleep_start: Optional[str] = Field(
        default=None,
        description="入睡时间，格式 HH:MM，例如 21:28"
    )
    sleep_end: Optional[str] = Field(
        default=None,
        description="醒来时间，格式 HH:MM，例如 05:26"
    )
    sleep_score: Optional[int] = Field(
        default=None,
        description="睡眠分数（0-100），例如 81"
    )

    # ── 睡眠结构（TruSleep 分期）──
    deep_sleep_min: Optional[float] = Field(
        default=None,
        description="深睡时长（分钟），正常占总睡眠15-25%"
    )
    light_sleep_min: Optional[float] = Field(
        default=None,
        description="浅睡时长（分钟）"
    )
    rem_sleep_min: Optional[float] = Field(
        default=None,
        description="REM快速眼动睡眠时长（分钟），正常占20-25%"
    )
    awake_min: Optional[float] = Field(
        default=None,
        description="睡眠期间觉醒时长（分钟）"
    )
    sleep_cycles: Optional[int] = Field(
        default=None,
        description="完整睡眠周期数，正常4-6个"
    )
    sleep_fragmentation: Optional[float] = Field(
        default=None,
        description="睡眠碎片化指数（觉醒次数/小时），>10为高碎片化"
    )

    # ── 压力与呼吸 ──
    stress_avg: Optional[int] = Field(
        default=None,
        description="日平均压力指数（0-100）"
    )
    stress_max: Optional[int] = Field(
        default=None,
        description="日最高压力指数"
    )
    breath_rate_avg: Optional[float] = Field(
        default=None,
        description="平均呼吸频率（次/分钟），正常12-20"
    )

    @field_validator(
        'steps', 'distance_km', 'exercise_minutes', 'exercise_type', 'calories',
        'heart_rate_min', 'heart_rate_max', 'resting_heart_rate', 'avg_heart_rate',
        'hr_recovery_1min', 'spo2_min', 'spo2_max', 'spo2_avg', 'odi',
        'sleep_hours', 'sleep_score', 'sleep_start', 'sleep_end',
        'deep_sleep_min', 'light_sleep_min', 'rem_sleep_min', 'awake_min',
        'sleep_cycles', 'sleep_fragmentation',
        'stress_avg', 'stress_max', 'breath_rate_avg',
        mode='before'
    )
    @classmethod
    def clean_none_strings(cls, v):
        """将大模型输出的 'None' 或 'null' 字符串（可能带单位如 'None%'）自动转为真正的 None 对象"""
        if isinstance(v, str):
            val = v.strip().lower()
            # 移除常见的后缀或单位
            val_clean = val.replace('%', '').replace('bpm', '').replace('km', '').replace('min', '').replace('h', '').replace('次/分', '').strip()
            if val_clean in ('none', 'null', 'nan', '', 'undefined', '-', '--', '无', '暂无') or any(val_clean.startswith(x) for x in ('none', 'null', 'nan')):
                return None
        return v

    @field_validator('date')
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """确保日期格式正确"""
        try:
            datetime.strptime(v, '%Y-%m-%d')
        except ValueError:
            raise ValueError(f"日期格式必须为 YYYY-MM-DD，收到: {v}")
        return v

    @field_validator('steps')
    @classmethod
    def validate_steps(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 0 or v > 200000):
            raise ValueError(f"步数异常: {v}，应在 0-200000 之间")
        return v

    @field_validator('resting_heart_rate')
    @classmethod
    def validate_resting_hr(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 30 or v > 150):
            raise ValueError(f"静息心率异常: {v}，应在 30-150 之间")
        return v

    @field_validator('sleep_score')
    @classmethod
    def validate_sleep_score(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 0 or v > 100):
            raise ValueError(f"睡眠分数异常: {v}，应在 0-100 之间")
        return v


class HealthScreenshotExtraction(BaseModel):
    """
    LLM 结构化输出的完整响应模型。
    用于 Qwen-VL 对华为家庭空间截图进行结构化提取。
    """
    data: DailyHealthData = Field(
        ...,
        description="从截图中提取的当日健康数据"
    )
    extraction_notes: Optional[str] = Field(
        default=None,
        description="AI在识别过程中遇到的任何问题或不确定之处的备注"
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0, le=1.0,
        description="整体提取置信度，0.0=极不确定，1.0=完全肯定"
    )


class HealthDataStore(BaseModel):
    """完整的数据存储结构"""
    person_name: str = Field(
        default="",
        description="数据主人姓名/称呼，可后期填写"
    )
    profile: PersonProfile = Field(
        default_factory=PersonProfile,
        description="个人健康档案，填写后可启用个体化评估"
    )
    data_source: str = Field(
        default="华为家庭空间",
        description="数据来源应用名称"
    )
    last_updated: str = Field(
        default="",
        description="最后更新时间 ISO格式"
    )
    records: List[DailyHealthData] = Field(
        default_factory=list,
        description="按日期排序的健康数据记录列表"
    )
    exercise_records: List[ExerciseRecord] = Field(
        default_factory=list,
        description="按时间排序的运动记录列表"
    )
    processed_files: List[str] = Field(
        default_factory=list,
        description="已处理过的截图文件名列表（避免重复OCR）"
    )

    def add_record(self, record: DailyHealthData, filename: str = "") -> bool:
        """
        添加或更新一条记录。
        如果相同日期已存在，则替换；否则追加。
        返回是否为新增记录。
        """
        # 查找是否已有同日数据
        for i, existing in enumerate(self.records):
            if existing.date == record.date:
                self.records[i] = record
                if filename and filename not in self.processed_files:
                    self.processed_files.append(filename)
                self.last_updated = datetime.now().isoformat()
                return False  # 更新已有

        self.records.append(record)
        if filename and filename not in self.processed_files:
            self.processed_files.append(filename)
        self.last_updated = datetime.now().isoformat()
        # 按日期排序
        self.records.sort(key=lambda r: r.date)
        return True  # 新增

    def save(self, filepath: str):
        """保存到JSON文件"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.model_dump(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, filepath: str) -> 'HealthDataStore':
        """从JSON文件加载"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.model_validate(data)
