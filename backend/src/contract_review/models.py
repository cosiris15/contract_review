"""
数据模型定义

包含审核标准、风险点、修改建议、行动建议、审阅结果等核心模型。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ==================== 基础类型定义 ====================

MaterialType = Literal["contract", "marketing"]
RiskLevel = Literal["high", "medium", "low"]
ModificationPriority = Literal["must", "should", "may"]
ActionUrgency = Literal["immediate", "soon", "normal"]
TaskStatus = Literal["created", "uploading", "reviewing", "completed", "failed"]

# 支持的语言（简化为两种：中文-中国法律体系，英文-普通法体系）
Language = Literal["zh-CN", "en"]

# 业务背景分类
BusinessContextCategory = Literal[
    "core_focus",            # 核心关注点
    "typical_risks",         # 典型风险
    "compliance",            # 合规要求
    "business_practices",    # 业务惯例
    "negotiation_priorities" # 谈判要点
]


def generate_id() -> str:
    """生成短 UUID"""
    return uuid4().hex[:8]


# ==================== 文档相关模型 ====================

class LoadedDocument(BaseModel):
    """加载的文档"""
    path: Path
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ==================== 审核标准模型 ====================

class ReviewStandard(BaseModel):
    """单条审核标准（风险点）"""
    id: str = Field(default_factory=generate_id)
    category: str  # 审核分类：主体资格、权利义务、费用条款、期限条款、责任条款等
    item: str  # 审核要点
    description: str  # 详细说明
    risk_level: RiskLevel = "medium"  # 风险等级
    applicable_to: List[MaterialType] = Field(default_factory=lambda: ["contract", "marketing"])

    # 标准库扩展字段
    collection_id: Optional[str] = None  # 所属标准集ID（必填，用于一对一关联）
    usage_instruction: Optional[str] = None  # 适用说明（LLM生成或手动填写）
    tags: List[str] = Field(default_factory=list)  # 标签，用于搜索和分类
    created_at: Optional[datetime] = None  # 创建时间（入库时设置）
    updated_at: Optional[datetime] = None  # 更新时间

    class Config:
        json_encoders = {Path: str}


class ReviewStandardSet(BaseModel):
    """审核标准集合"""
    name: str  # 标准集名称
    version: str = "1.0"  # 版本
    standards: List[ReviewStandard]
    created_at: datetime = Field(default_factory=datetime.now)
    source_file: Optional[str] = None  # 来源文件名

    @property
    def count(self) -> int:
        return len(self.standards)

    def filter_by_material_type(self, material_type: MaterialType) -> List[ReviewStandard]:
        """按材料类型过滤审核标准"""
        return [s for s in self.standards if material_type in s.applicable_to]


# ==================== 标准库模型 ====================

class StandardCollection(BaseModel):
    """标准集（一套完整的审阅标准）"""
    id: str = Field(default_factory=generate_id)
    name: str  # 集合名称，如"电商平台合作协议审核标准"
    description: str = ""  # 适用场景说明
    usage_instruction: Optional[str] = None  # 适用说明（用于智能推荐）
    material_type: str = "both"  # contract/marketing/both
    is_preset: bool = False  # 是否为系统预设（预设集合不可删除）
    language: Language = "zh-CN"  # 标准集的语言
    # 注意：不再存储 standard_ids，改为通过 ReviewStandard.collection_id 关联
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class StandardLibrary(BaseModel):
    """全局审核标准库"""
    standards: List[ReviewStandard] = Field(default_factory=list)
    collections: List[StandardCollection] = Field(default_factory=list)  # 标准集合
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def count(self) -> int:
        return len(self.standards)

    def get_by_id(self, standard_id: str) -> Optional[ReviewStandard]:
        """根据 ID 获取标准"""
        for s in self.standards:
            if s.id == standard_id:
                return s
        return None

    def filter_by_category(self, category: str) -> List[ReviewStandard]:
        """按分类过滤标准"""
        return [s for s in self.standards if s.category == category]

    def filter_by_material_type(self, material_type: MaterialType) -> List[ReviewStandard]:
        """按材料类型过滤标准"""
        return [s for s in self.standards if material_type in s.applicable_to]

    def search(self, keyword: str) -> List[ReviewStandard]:
        """搜索标准（匹配分类、要点、说明、标签）"""
        keyword = keyword.lower()
        results = []
        for s in self.standards:
            if (keyword in s.category.lower() or
                keyword in s.item.lower() or
                keyword in s.description.lower() or
                any(keyword in tag.lower() for tag in s.tags)):
                results.append(s)
        return results

    def get_categories(self) -> List[str]:
        """获取所有分类"""
        categories = set(s.category for s in self.standards)
        return sorted(categories)

    # ====== 集合相关方法 ======

    def get_collection_by_id(self, collection_id: str) -> Optional[StandardCollection]:
        """根据 ID 获取集合"""
        for c in self.collections:
            if c.id == collection_id:
                return c
        return None

    def get_collection_standards(self, collection_id: str) -> List[ReviewStandard]:
        """获取集合中的所有标准（通过 collection_id 关联）"""
        return [s for s in self.standards if s.collection_id == collection_id]

    def get_collection_standard_count(self, collection_id: str) -> int:
        """获取集合中的标准数量"""
        return len([s for s in self.standards if s.collection_id == collection_id])


class StandardRecommendation(BaseModel):
    """标准推荐结果"""
    standard_id: str
    relevance_score: float  # 0-1 相关性评分
    match_reason: str  # 匹配原因


# ==================== 业务条线模型 ====================

class BusinessContext(BaseModel):
    """业务背景信息条目"""
    id: str = Field(default_factory=generate_id)
    business_line_id: Optional[str] = None  # 所属业务条线ID
    category: BusinessContextCategory  # 分类
    item: str  # 要点名称
    description: str  # 详细说明
    priority: RiskLevel = "medium"  # 重要程度: high/medium/low
    tags: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BusinessLine(BaseModel):
    """业务条线"""
    id: str = Field(default_factory=generate_id)
    user_id: Optional[str] = None  # 所属用户ID，NULL表示系统预设
    name: str  # 业务线名称
    description: str = ""  # 业务线描述
    industry: str = ""  # 所属行业
    is_preset: bool = False  # 是否为系统预设
    language: Language = "zh-CN"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class BusinessLineWithContexts(BusinessLine):
    """带背景信息的业务条线（用于API响应）"""
    contexts: List[BusinessContext] = Field(default_factory=list)
    context_count: int = 0

    def get_contexts_by_category(self, category: BusinessContextCategory) -> List[BusinessContext]:
        """按分类获取背景信息"""
        return [c for c in self.contexts if c.category == category]


class BusinessLineRecommendation(BaseModel):
    """业务条线推荐结果"""
    business_line_id: str
    relevance_score: float  # 0-1 相关性评分
    match_reason: str  # 推荐理由


# ==================== 风险点模型 ====================

class TextLocation(BaseModel):
    """文本位置标记"""
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    original_text: str  # 原文摘录


class RiskPoint(BaseModel):
    """识别出的风险点"""
    id: str = Field(default_factory=generate_id)
    standard_id: Optional[str] = None  # 关联的审核标准 ID
    risk_level: RiskLevel
    risk_type: str  # 风险类型（对应审核分类）
    description: str  # 风险描述
    reason: str  # 判定理由
    location: Optional[TextLocation] = None  # 原文位置
    raw_llm_response: Optional[str] = None  # LLM 原始响应（调试用）


# ==================== 修改建议模型 ====================

class ModificationSuggestion(BaseModel):
    """修改建议"""
    id: str = Field(default_factory=generate_id)
    risk_id: str  # 关联的风险点 ID
    original_text: str  # 当前文本
    suggested_text: str  # 建议修改为
    modification_reason: str  # 修改理由
    priority: ModificationPriority = "should"  # 优先级：必须/应该/可以
    user_confirmed: bool = False  # 用户是否确认
    user_modified_text: Optional[str] = None  # 用户修改后的文本


# ==================== 行动建议模型 ====================

class ActionRecommendation(BaseModel):
    """行动建议（除文本修改外的措施）"""
    id: str = Field(default_factory=generate_id)
    related_risk_ids: List[str]  # 关联的风险点 ID 列表
    action_type: str  # 行动类型：沟通协商、补充材料、法务确认、内部审批等
    description: str  # 具体行动描述
    urgency: ActionUrgency = "normal"  # 紧急程度
    responsible_party: str = ""  # 建议负责方
    deadline_suggestion: Optional[str] = None  # 建议完成时限
    user_confirmed: bool = False


# ==================== 审阅结果模型 ====================

class ReviewSummary(BaseModel):
    """审阅结果摘要"""
    total_risks: int = 0
    high_risks: int = 0
    medium_risks: int = 0
    low_risks: int = 0
    total_modifications: int = 0
    must_modify: int = 0
    should_modify: int = 0
    may_modify: int = 0
    total_actions: int = 0
    immediate_actions: int = 0


class ReviewResult(BaseModel):
    """完整审阅结果"""
    task_id: str
    document_name: str
    document_path: Optional[str] = None
    material_type: MaterialType
    our_party: str  # 我方身份
    review_standards_used: str  # 使用的标准集名称
    language: Language = "zh-CN"  # 审阅语言

    # 业务条线信息（可选）
    business_line_id: Optional[str] = None  # 使用的业务条线ID
    business_line_name: Optional[str] = None  # 使用的业务条线名称

    # 审阅产出
    risks: List[RiskPoint] = Field(default_factory=list)
    modifications: List[ModificationSuggestion] = Field(default_factory=list)
    actions: List[ActionRecommendation] = Field(default_factory=list)

    # 统计摘要
    summary: ReviewSummary = Field(default_factory=ReviewSummary)

    # 元数据
    reviewed_at: datetime = Field(default_factory=datetime.now)
    llm_model: str = ""
    prompt_version: str = "1.0"

    def calculate_summary(self) -> None:
        """根据审阅结果计算摘要统计"""
        self.summary = ReviewSummary(
            total_risks=len(self.risks),
            high_risks=sum(1 for r in self.risks if r.risk_level == "high"),
            medium_risks=sum(1 for r in self.risks if r.risk_level == "medium"),
            low_risks=sum(1 for r in self.risks if r.risk_level == "low"),
            total_modifications=len(self.modifications),
            must_modify=sum(1 for m in self.modifications if m.priority == "must"),
            should_modify=sum(1 for m in self.modifications if m.priority == "should"),
            may_modify=sum(1 for m in self.modifications if m.priority == "may"),
            total_actions=len(self.actions),
            immediate_actions=sum(1 for a in self.actions if a.urgency == "immediate"),
        )


# ==================== 任务模型 ====================

class ReviewTaskProgress(BaseModel):
    """审阅任务进度"""
    stage: str = "idle"  # idle/uploading/analyzing/generating/completed/failed
    percentage: int = 0
    message: str = ""


class ReviewTask(BaseModel):
    """审阅任务"""
    id: str = Field(default_factory=generate_id)
    name: str  # 任务名称
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    status: TaskStatus = "created"
    message: Optional[str] = None  # 状态消息
    progress: ReviewTaskProgress = Field(default_factory=ReviewTaskProgress)

    # 输入配置
    our_party: str  # 我方身份
    material_type: MaterialType = "contract"
    language: Language = "zh-CN"  # 审阅语言

    # 文件路径
    document_filename: Optional[str] = None  # 上传的文档文件名（原始名，用于显示）
    document_storage_name: Optional[str] = None  # 文档存储名（安全名，用于 Storage）
    standard_filename: Optional[str] = None  # 上传的审核标准文件名（原始名，用于显示）
    standard_storage_name: Optional[str] = None  # 标准存储名（安全名，用于 Storage）
    standard_template: Optional[str] = None  # 使用的默认模板名称

    # 业务条线（可选）
    business_line_id: Optional[str] = None  # 关联的业务条线ID

    # 结果
    result: Optional[ReviewResult] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            Path: str,
        }

    def update_status(self, status: TaskStatus, message: Optional[str] = None) -> None:
        """更新任务状态"""
        self.status = status
        self.message = message
        self.updated_at = datetime.now()

    def update_progress(self, stage: str, percentage: int, message: str = "") -> None:
        """更新进度"""
        self.progress = ReviewTaskProgress(
            stage=stage,
            percentage=percentage,
            message=message,
        )
        self.updated_at = datetime.now()
