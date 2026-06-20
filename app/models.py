from typing import Optional, List
from pydantic import BaseModel, field_validator

FARM_TYPES = ["general", "paddy", "dryland", "vegetable", "orchard"]
FARM_TYPE_LABELS = {
    "general": "通用",
    "paddy": "水田",
    "dryland": "旱地",
    "vegetable": "菜地",
    "orchard": "果园",
}
FARM_IRRIGATION_NEEDS = {
    "general": 1.0,
    "paddy": 1.8,
    "dryland": 0.6,
    "vegetable": 1.4,
    "orchard": 0.9,
}

class WeirCreate(BaseModel):
    name: str
    location: str = ""
    description: str = ""

class WeirUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None

class MainCanalCreate(BaseModel):
    weir_id: int
    name: str
    width: float = 1.0
    description: str = ""

    @field_validator("width")
    @classmethod
    def width_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError("渠宽不能为负数")
        return v

class MainCanalUpdate(BaseModel):
    name: Optional[str] = None
    width: Optional[float] = None
    description: Optional[str] = None

    @field_validator("width")
    @classmethod
    def width_must_be_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("渠宽不能为负数")
        return v

class BranchCanalCreate(BaseModel):
    main_canal_id: int
    name: str
    width: float = 0.5
    acreage: float = 0.0
    farm_type: str = "general"
    position: int = 0
    description: str = ""

    @field_validator("width")
    @classmethod
    def width_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError("支渠宽度不能为负数")
        return v

    @field_validator("acreage")
    @classmethod
    def acreage_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError("田亩数不能为负数")
        return v

    @field_validator("farm_type")
    @classmethod
    def farm_type_valid(cls, v):
        if v not in FARM_TYPES:
            raise ValueError("农田类型必须是 " + ", ".join(FARM_TYPES) + " 之一")
        return v

class BranchCanalUpdate(BaseModel):
    name: Optional[str] = None
    width: Optional[float] = None
    acreage: Optional[float] = None
    farm_type: Optional[str] = None
    position: Optional[int] = None
    description: Optional[str] = None

    @field_validator("width")
    @classmethod
    def width_must_be_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("支渠宽度不能为负数")
        return v

    @field_validator("acreage")
    @classmethod
    def acreage_must_be_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("田亩数不能为负数")
        return v

    @field_validator("farm_type")
    @classmethod
    def farm_type_valid(cls, v):
        if v is not None and v not in FARM_TYPES:
            raise ValueError("农田类型必须是 " + ", ".join(FARM_TYPES) + " 之一")
        return v

class GateCreate(BaseModel):
    branch_canal_id: int
    name: str
    opening: int = 100
    description: str = ""

    @field_validator("opening")
    @classmethod
    def opening_range(cls, v):
        if v < 0 or v > 100:
            raise ValueError("闸口开度必须在0-100之间")
        return v

class GateUpdate(BaseModel):
    name: Optional[str] = None
    opening: Optional[int] = None
    description: Optional[str] = None

    @field_validator("opening")
    @classmethod
    def opening_range(cls, v):
        if v is not None and (v < 0 or v > 100):
            raise ValueError("闸口开度必须在0-100之间")
        return v

class WaterLevelCreate(BaseModel):
    weir_id: int
    date: str
    level: float
    is_simulated: bool = False

    @field_validator("level")
    @classmethod
    def level_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError("水位不能为负数")
        return v

class WaterLevelBatchCreate(BaseModel):
    weir_id: int
    records: List[WaterLevelCreate]

class SchemeCreate(BaseModel):
    weir_id: int
    name: str
    rule: str = "equal"
    change_note: str = ""

    @field_validator("rule")
    @classmethod
    def rule_must_be_valid(cls, v):
        if v not in ("equal", "downstream_first", "acreage_ratio"):
            raise ValueError("分水规则必须是 equal / downstream_first / acreage_ratio")
        return v

class SeasonalRuleCreate(BaseModel):
    weir_id: int
    name: str
    description: str = ""
    start_month: int = 1
    end_month: int = 12
    rule: str = "equal"
    priority_farm_type: str = ""
    priority_ratio: float = 1.0
    water_level_threshold: float = 0

    @field_validator("start_month", "end_month")
    @classmethod
    def month_range(cls, v):
        if v < 1 or v > 12:
            raise ValueError("月份必须在1-12之间")
        return v

    @field_validator("rule")
    @classmethod
    def rule_must_be_valid(cls, v):
        if v not in ("equal", "downstream_first", "acreage_ratio"):
            raise ValueError("分水规则必须是 equal / downstream_first / acreage_ratio")
        return v

    @field_validator("priority_ratio")
    @classmethod
    def ratio_positive(cls, v):
        if v <= 0:
            raise ValueError("优先级系数必须大于0")
        return v

class SeasonalRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    start_month: Optional[int] = None
    end_month: Optional[int] = None
    rule: Optional[str] = None
    priority_farm_type: Optional[str] = None
    priority_ratio: Optional[float] = None
    water_level_threshold: Optional[float] = None

    @field_validator("start_month", "end_month")
    @classmethod
    def month_range(cls, v):
        if v is not None and (v < 1 or v > 12):
            raise ValueError("月份必须在1-12之间")
        return v

    @field_validator("rule")
    @classmethod
    def rule_must_be_valid(cls, v):
        if v is not None and v not in ("equal", "downstream_first", "acreage_ratio"):
            raise ValueError("分水规则必须是 equal / downstream_first / acreage_ratio")
        return v

class ScenarioCreate(BaseModel):
    weir_id: int
    name: str
    description: str = ""
    main_canal_id: Optional[int] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    scenario_type: str = "historical"
    seasonal_rule_ids: List[int] = []

class MissingDateFix(BaseModel):
    weir_id: int
    date: str
    level: float
    method: str = "interpolate"

class GateChangeCreate(BaseModel):
    gate_id: Optional[int] = None
    branch_canal_id: int
    branch_canal_name: str
    gate_name: str
    opening_before: int
    opening_after: int
    flow_before: float = 0.0
    flow_after: float = 0.0
    coverage_before: float = 0.0
    coverage_after: float = 0.0

class ScheduleLogCreate(BaseModel):
    weir_id: int
    scheme_id: Optional[int] = None
    operator: str = "系统管理员"
    adjust_reason: str
    water_level: float = 0.0
    water_level_date: Optional[str] = None
    rule_before: Optional[str] = None
    rule_after: Optional[str] = None
    total_flow_before: float = 0.0
    total_flow_after: float = 0.0
    avg_coverage_before: float = 0.0
    avg_coverage_after: float = 0.0
    notes: Optional[str] = ""
    gate_changes: List[GateChangeCreate] = []

class ScheduleLogQuery(BaseModel):
    weir_id: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    operator: Optional[str] = None
