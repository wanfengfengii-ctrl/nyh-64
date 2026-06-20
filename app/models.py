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

STRUCTURE_TYPES = ["screw", "roller", "hydraulic", "pneumatic", "basket"]
STRUCTURE_TYPE_LABELS = {
    "screw": "螺旋压榨",
    "roller": "辊式压榨",
    "hydraulic": "液压压榨",
    "pneumatic": "气动压榨",
    "basket": "篮式压榨",
}

OPTIMIZATION_ALGORITHMS = ["genetic", "particle_swarm", "grid_search", "random_search", "nsga2"]
OPTIMIZATION_ALGORITHM_LABELS = {
    "genetic": "遗传算法",
    "particle_swarm": "粒子群优化",
    "grid_search": "网格搜索",
    "random_search": "随机搜索",
    "nsga2": "NSGA-II多目标优化",
}

RANKING_METHODS = ["topsis", "ahp", "electre", "weighted_sum", "viikor"]
RANKING_METHOD_LABELS = {
    "topsis": "TOPSIS优劣解距离法",
    "ahp": "层次分析法",
    "electre": "ELECTRE消去选择法",
    "weighted_sum": "加权求和法",
    "viikor": "VIKOR妥协排序法",
}

class PressStructureCreate(BaseModel):
    weir_id: int
    name: str
    structure_type: str = "screw"
    screw_diameter: float = 0.0
    screw_pitch: float = 0.0
    screw_lead: float = 0.0
    cone_angle: float = 0.0
    gap_size: float = 0.0
    compression_ratio: float = 0.0
    rotation_speed: float = 0.0
    feed_rate: float = 0.0
    material_type: str = ""
    moisture_content: float = 0.0
    description: str = ""

    @field_validator("structure_type")
    @classmethod
    def structure_type_valid(cls, v):
        if v not in STRUCTURE_TYPES:
            raise ValueError("结构类型必须是 " + ", ".join(STRUCTURE_TYPES) + " 之一")
        return v

class PressStructureUpdate(BaseModel):
    name: Optional[str] = None
    structure_type: Optional[str] = None
    screw_diameter: Optional[float] = None
    screw_pitch: Optional[float] = None
    screw_lead: Optional[float] = None
    cone_angle: Optional[float] = None
    gap_size: Optional[float] = None
    compression_ratio: Optional[float] = None
    rotation_speed: Optional[float] = None
    feed_rate: Optional[float] = None
    material_type: Optional[str] = None
    moisture_content: Optional[float] = None
    description: Optional[str] = None

class PressExperimentCreate(BaseModel):
    weir_id: int
    structure_id: Optional[int] = None
    name: str
    status: str = "draft"
    juice_yield: float = 0.0
    peak_pressure: float = 0.0
    residue_moisture: float = 0.0
    steady_juice_time: float = 0.0
    energy_consumption: float = 0.0
    throughput: float = 0.0
    experiment_date: Optional[str] = None
    operator: str = ""
    notes: str = ""

class OptimizationTaskCreate(BaseModel):
    weir_id: int
    name: str
    algorithm: str = "genetic"
    target_juice_yield_weight: float = 0.3
    target_peak_pressure_weight: float = 0.25
    target_residue_moisture_weight: float = 0.25
    target_steady_time_weight: float = 0.2
    param_ranges: str = ""
    population_size: int = 50
    max_iterations: int = 100
    mutation_rate: float = 0.1
    crossover_rate: float = 0.8

    @field_validator("algorithm")
    @classmethod
    def algorithm_valid(cls, v):
        if v not in OPTIMIZATION_ALGORITHMS:
            raise ValueError("优化算法必须是 " + ", ".join(OPTIMIZATION_ALGORITHMS) + " 之一")
        return v

    @field_validator("population_size", "max_iterations")
    @classmethod
    def positive_integer(cls, v):
        if v <= 0:
            raise ValueError("必须为正整数")
        return v

    @field_validator("mutation_rate", "crossover_rate")
    @classmethod
    def ratio_range(cls, v):
        if v < 0 or v > 1:
            raise ValueError("比率必须在0-1之间")
        return v

class SchemeRankingCreate(BaseModel):
    weir_id: int
    name: str
    ranking_method: str = "topsis"
    juice_yield_weight: float = 0.3
    peak_pressure_weight: float = 0.25
    residue_moisture_weight: float = 0.25
    steady_time_weight: float = 0.2
    scheme_ids: str = ""

    @field_validator("ranking_method")
    @classmethod
    def method_valid(cls, v):
        if v not in RANKING_METHODS:
            raise ValueError("排序方法必须是 " + ", ".join(RANKING_METHODS) + " 之一")
        return v

class StructureChangeCreate(BaseModel):
    structure_id: int
    change_type: str
    param_name: str
    value_before: Optional[float] = None
    value_after: Optional[float] = None
    effect_description: str = ""
    operator: str = ""
    change_reason: str = ""

class ReportComparisonCreate(BaseModel):
    weir_id: int
    name: str
    experiment_ids: str = ""
    comparison_type: str = "side_by_side"
    include_metrics: str = ""

class ExperimentReviewCreate(BaseModel):
    weir_id: int
    name: str
    experiment_ids: str = ""
    review_type: str = "full"
    success_summary: str = ""
    issue_summary: str = ""
    lesson_learned: str = ""
    improvement_suggestions: str = ""
    key_findings: str = ""
    reviewer: str = ""

class GapFixSuggestionAlternative(BaseModel):
    method: str
    method_label: str
    suggested_level: float
    confidence: str
    basis: str

class GapFixSuggestion(BaseModel):
    date: str
    gap_segment: str
    gap_days: int
    before_date: str
    before_level: Optional[float] = None
    after_date: str
    after_level: Optional[float] = None
    recommended_method: str
    recommended_method_label: str
    recommended_level: float
    recommended_confidence: str
    recommended_basis: str
    alternatives: List[GapFixSuggestionAlternative] = []

class GapFixRecordCreate(BaseModel):
    weir_id: int
    date: str
    fixed_level: float
    method: str = "linear_interpolate"
    confidence_level: str = "medium"
    basis: str = ""
    operator: str = "系统管理员"
    notes: str = ""

class GapFixConfirm(BaseModel):
    record_id: int
    confirmed_by: str = "审核员"
    notes: str = ""

class GapFixBatchApply(BaseModel):
    weir_id: int
    suggestions: List[GapFixRecordCreate] = []
    operator: str = "系统管理员"
