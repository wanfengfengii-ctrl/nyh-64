from pydantic import BaseModel, field_validator

class WeirCreate(BaseModel):
    name: str
    location: str = ""
    description: str = ""

class WeirUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    description: str | None = None

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
    name: str | None = None
    width: float | None = None
    description: str | None = None

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

class BranchCanalUpdate(BaseModel):
    name: str | None = None
    width: float | None = None
    acreage: float | None = None
    position: int | None = None
    description: str | None = None

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
    name: str | None = None
    opening: int | None = None
    description: str | None = None

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
    records: list[WaterLevelCreate]

class SchemeCreate(BaseModel):
    weir_id: int
    name: str
    rule: str = "equal"

    @field_validator("rule")
    @classmethod
    def rule_must_be_valid(cls, v):
        if v not in ("equal", "downstream_first", "acreage_ratio"):
            raise ValueError("分水规则必须是 equal / downstream_first / acreage_ratio")
        return v
