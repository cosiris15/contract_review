# SPEC-5: 领域插件机制

> 优先级：高（FIDIC 场景的基础）
> 前置依赖：Spec-1（SkillRegistration）、Spec-2（ReviewChecklistItem、DocumentParserConfig）
> 预计新建文件：3 个 | 修改文件：0 个
> 参考：GEN3_GAP_ANALYSIS.md 第 8.3-8.4 章、第 9 章

---

## 1. 目标

构建领域插件注册与发现机制，使系统能够：
- 按合同类型（FIDIC、国内采购、M&A 等）注册独立的领域插件
- 每个插件提供：专属 Skills + 审查清单 + 文档解析配置 + 基线文本
- Orchestrator 根据任务的 `domain_id` 自动加载对应插件
- 提供 FIDIC Silver Book 插件骨架作为第一个实现

## 2. 需要创建的文件

### 2.1 `backend/src/contract_review/plugins/__init__.py`

空文件，标记 plugins 为 Python 包。

### 2.2 `backend/src/contract_review/plugins/registry.py`

领域插件注册表 — 插件的注册、发现、查询。

```python
"""
领域插件注册表

管理所有领域插件的注册和发现。
Orchestrator 通过 domain_id 查询可用的 Skills 和审查清单。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ..models import (
    DocumentParserConfig,
    ReviewChecklistItem,
)
from ..skills.schema import SkillRegistration

logger = logging.getLogger(__name__)


class DomainPlugin(BaseModel):
    """
    领域插件注册信息

    每个合同类型对应一个 DomainPlugin 实例。
    包含该领域的专属 Skills、审查清单、解析配置等。
    """
    domain_id: str                          # 全局唯一，如 "fidic", "domestic", "ma"
    name: str                               # 显示名称
    description: str = ""
    supported_subtypes: List[str] = Field(default_factory=list)  # 如 ["silver_book", "yellow_book"]

    # 领域专属 Skills（同样支持双后端）
    domain_skills: List[SkillRegistration] = Field(default_factory=list)

    # 审查主线脚本：定义该领域的条款审查顺序
    review_checklist: List[ReviewChecklistItem] = Field(default_factory=list)

    # 文档预处理规则
    document_parser_config: DocumentParserConfig = Field(
        default_factory=DocumentParserConfig
    )

    # 基线文本（用于偏离分析）
    # clause_id → 标准文本
    baseline_texts: Dict[str, str] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True


# ============================================================
# 全局注册表
# ============================================================

_DOMAIN_PLUGINS: Dict[str, DomainPlugin] = {}


def register_domain_plugin(plugin: DomainPlugin) -> None:
    """
    注册一个领域插件

    Args:
        plugin: DomainPlugin 实例

    Raises:
        ValueError: domain_id 已被注册
    """
    if plugin.domain_id in _DOMAIN_PLUGINS:
        logger.warning(
            f"领域插件 '{plugin.domain_id}' 已存在，将被覆盖"
        )
    _DOMAIN_PLUGINS[plugin.domain_id] = plugin
    logger.info(
        f"领域插件已注册: {plugin.domain_id} ({plugin.name}) "
        f"[Skills: {len(plugin.domain_skills)}, "
        f"Checklist: {len(plugin.review_checklist)} 条]"
    )


def get_domain_plugin(domain_id: str) -> Optional[DomainPlugin]:
    """获取指定领域的插件"""
    return _DOMAIN_PLUGINS.get(domain_id)


def list_domain_plugins() -> List[DomainPlugin]:
    """列出所有已注册的领域插件"""
    return list(_DOMAIN_PLUGINS.values())


def get_domain_ids() -> List[str]:
    """获取所有已注册的领域 ID"""
    return list(_DOMAIN_PLUGINS.keys())


def get_review_checklist(
    domain_id: str, subtype: Optional[str] = None
) -> List[ReviewChecklistItem]:
    """
    获取某个领域的审查清单

    Args:
        domain_id: 领域 ID
        subtype: 可选的子类型（如 "silver_book"），
                 未来可用于过滤 checklist

    Returns:
        审查清单列表，无插件时返回空列表
    """
    plugin = _DOMAIN_PLUGINS.get(domain_id)
    if not plugin:
        return []
    # TODO: 后续可根据 subtype 过滤
    return plugin.review_checklist


def get_all_skills_for_domain(
    domain_id: str,
    generic_skills: Optional[List[SkillRegistration]] = None,
) -> List[SkillRegistration]:
    """
    获取某个领域可用的全部 Skills（通用 + 领域专属）

    Args:
        domain_id: 领域 ID
        generic_skills: 通用 Skills 列表

    Returns:
        合并后的 Skills 列表
    """
    skills = list(generic_skills or [])
    plugin = _DOMAIN_PLUGINS.get(domain_id)
    if plugin:
        skills.extend(plugin.domain_skills)
    return skills


def get_parser_config(domain_id: str) -> DocumentParserConfig:
    """
    获取某个领域的文档解析配置

    无插件时返回默认配置。
    """
    plugin = _DOMAIN_PLUGINS.get(domain_id)
    if plugin:
        return plugin.document_parser_config
    return DocumentParserConfig()


def get_baseline_text(
    domain_id: str, clause_id: str
) -> Optional[str]:
    """获取某个条款的基线文本"""
    plugin = _DOMAIN_PLUGINS.get(domain_id)
    if not plugin:
        return None
    return plugin.baseline_texts.get(clause_id)


def clear_plugins() -> None:
    """清空所有注册的插件（测试用）"""
    _DOMAIN_PLUGINS.clear()
```

### 2.3 `backend/src/contract_review/plugins/fidic.py`

FIDIC Silver Book 插件骨架 — 第一个领域插件实现。

```python
"""
FIDIC 国际工程合同领域插件

提供 FIDIC Silver Book 的：
- 专属 Skills（GC+PC 合并、时效计算、ER 语义检索）
- 审查清单（关键条款及审查要点）
- 文档解析配置（FIDIC 编号规则）
- 基线文本（Silver Book 标准条款，后续录入）
"""

from __future__ import annotations

from ..models import (
    DocumentParserConfig,
    ReviewChecklistItem,
)
from ..skills.schema import SkillBackend, SkillRegistration
from .registry import DomainPlugin

# ============================================================
# FIDIC 文档解析配置
# ============================================================

FIDIC_PARSER_CONFIG = DocumentParserConfig(
    # FIDIC 条款编号格式: "1.1", "14.2", "20.1.1"
    clause_pattern=r"^(\d+\.)+\d*\s+",
    # 顶级章节: "Clause 1", "Clause 2" 等（部分 FIDIC 版本使用）
    chapter_pattern=r"^[Cc]lause\s+\d+\b",
    # 定义条款
    definitions_section_id="1.1",
    max_depth=4,
    structure_type="fidic_gc",
)


# ============================================================
# FIDIC 专属 Skills
# ============================================================

# 注意：此处只定义 SkillRegistration（元数据），
# 实际 handler 实现在后续开发阶段完成。
# 当前使用占位 handler 路径。

FIDIC_DOMAIN_SKILLS: list[SkillRegistration] = [
    # GC+PC 合并 — 本地实现（纯文档拼接逻辑）
    SkillRegistration(
        skill_id="fidic_merge_gc_pc",
        name="GC+PC 合并",
        description="将 FIDIC 通用条件(GC)与专用条件(PC)按条款合并，PC 覆盖 GC",
        input_schema=None,   # TODO: 定义 MergeGcPcInput
        output_schema=None,  # TODO: 定义 MergeGcPcOutput
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.fidic.merge_gc_pc.merge",
    ),
    # 索赔时效计算 — 本地实现（确定性 datetime 逻辑）
    SkillRegistration(
        skill_id="fidic_calculate_time_bar",
        name="索赔时效计算",
        description="根据 FIDIC 条款计算索赔/通知时效期限",
        input_schema=None,   # TODO: 定义 TimeBarInput
        output_schema=None,  # TODO: 定义 TimeBarOutput
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.fidic.time_bar.calculate",
    ),
    # ER 语义检索 — Refly 实现（需要 embedding + RAG）
    SkillRegistration(
        skill_id="fidic_search_er",
        name="ER 语义检索",
        description="在业主方要求(Employer's Requirements)中做语义检索",
        input_schema=None,   # TODO: 定义 SearchErInput
        output_schema=None,  # TODO: 定义 SearchErOutput
        backend=SkillBackend.REFLY,
        refly_workflow_id="refly_wf_fidic_search_er",  # 后续在 Refly 平台创建
    ),
]


# ============================================================
# FIDIC Silver Book 审查清单
# ============================================================

FIDIC_SILVER_BOOK_CHECKLIST: list[ReviewChecklistItem] = [
    ReviewChecklistItem(
        clause_id="1.1",
        clause_name="定义与解释",
        priority="high",
        required_skills=["get_clause_context", "resolve_definition"],
        description="核实所有关键定义是否被 PC 修改，特别关注 Employer/Contractor/Engineer 的定义变更",
    ),
    ReviewChecklistItem(
        clause_id="1.5",
        clause_name="文件优先顺序",
        priority="high",
        required_skills=["get_clause_context", "fidic_merge_gc_pc"],
        description="确认合同文件优先顺序，PC 是否修改了默认优先级",
    ),
    ReviewChecklistItem(
        clause_id="4.1",
        clause_name="承包商的一般义务",
        priority="critical",
        required_skills=[
            "get_clause_context", "fidic_merge_gc_pc",
            "compare_with_baseline", "cross_reference_check",
        ],
        description="检查义务范围是否被不合理扩大，设计责任是否清晰",
    ),
    ReviewChecklistItem(
        clause_id="4.12",
        clause_name="不可预见的物质条件",
        priority="high",
        required_skills=["get_clause_context", "compare_with_baseline"],
        description="Silver Book 中此条通常被删除或大幅修改，需重点关注风险转移",
    ),
    ReviewChecklistItem(
        clause_id="8.2",
        clause_name="竣工时间",
        priority="high",
        required_skills=[
            "get_clause_context", "fidic_calculate_time_bar",
            "extract_financial_terms",
        ],
        description="核查工期延误的赔偿机制和延期条件",
    ),
    ReviewChecklistItem(
        clause_id="14.1",
        clause_name="合同价格",
        priority="critical",
        required_skills=[
            "get_clause_context", "extract_financial_terms",
            "compare_with_baseline",
        ],
        description="核查价格调整机制、汇率风险分担",
    ),
    ReviewChecklistItem(
        clause_id="14.2",
        clause_name="预付款",
        priority="high",
        required_skills=[
            "get_clause_context", "fidic_merge_gc_pc",
            "extract_financial_terms",
        ],
        description="核查预付款退还机制、保函期限、扣回比例",
    ),
    ReviewChecklistItem(
        clause_id="14.7",
        clause_name="期中付款",
        priority="high",
        required_skills=["get_clause_context", "extract_financial_terms"],
        description="核查付款周期、付款条件、扣留金比例",
    ),
    ReviewChecklistItem(
        clause_id="17.6",
        clause_name="责任限制",
        priority="critical",
        required_skills=[
            "get_clause_context", "extract_financial_terms",
            "compare_with_baseline",
        ],
        description="核查赔偿上限、间接损失排除、保险覆盖范围",
    ),
    ReviewChecklistItem(
        clause_id="18.1",
        clause_name="保险要求",
        priority="high",
        required_skills=["get_clause_context", "extract_financial_terms"],
        description="核查保险类型、保额、免赔额、投保义务方",
    ),
    ReviewChecklistItem(
        clause_id="20.1",
        clause_name="承包商索赔",
        priority="critical",
        required_skills=[
            "get_clause_context", "fidic_calculate_time_bar",
            "cross_reference_check",
        ],
        description="核查索赔时效(28天通知)、通知义务、时效丧失后果",
    ),
    ReviewChecklistItem(
        clause_id="20.2",
        clause_name="争议裁决",
        priority="high",
        required_skills=["get_clause_context", "compare_with_baseline"],
        description="核查 DAB/DAAB 机制是否被修改、仲裁条款",
    ),
]


# ============================================================
# 组装 FIDIC 插件
# ============================================================

FIDIC_PLUGIN = DomainPlugin(
    domain_id="fidic",
    name="FIDIC 国际工程合同",
    description="基于 FIDIC Silver/Yellow/Red Book 的国际工程合同审查",
    supported_subtypes=["silver_book", "yellow_book", "red_book"],
    domain_skills=FIDIC_DOMAIN_SKILLS,
    review_checklist=FIDIC_SILVER_BOOK_CHECKLIST,
    document_parser_config=FIDIC_PARSER_CONFIG,
    baseline_texts={
        # TODO: 后续录入 Silver Book 标准条款文本
        # "14.2": "The Employer shall make an advance payment...",
        # "17.6": "The Contractor's total liability...",
    },
)


def register_fidic_plugin() -> None:
    """注册 FIDIC 插件到全局注册表"""
    from .registry import register_domain_plugin
    register_domain_plugin(FIDIC_PLUGIN)
```

## 3. 目录结构（完成后）

```
backend/src/contract_review/
├── plugins/
│   ├── __init__.py              # 新建：包标记
│   ├── registry.py              # 新建：插件注册表
│   └── fidic.py                 # 新建：FIDIC 插件骨架
└── ... (其他文件不动)
```

## 4. 验收标准

1. `register_domain_plugin(FIDIC_PLUGIN)` 成功注册，`get_domain_plugin("fidic")` 返回正确插件
2. `get_review_checklist("fidic")` 返回 12+ 条 FIDIC 审查清单
3. `get_all_skills_for_domain("fidic", generic_skills)` 返回通用 + FIDIC 专属 Skills
4. `get_parser_config("fidic")` 返回 FIDIC 特定的解析配置
5. `get_baseline_text("fidic", "14.2")` 在基线文本录入后能返回标准条款
6. 不存在的 domain_id 查询返回 None 或空列表（不报错）
7. `clear_plugins()` 能清空注册表（测试隔离）
8. FIDIC 插件的 `domain_skills` 中 Skill 的 `input_schema`/`output_schema` 当前为 None（占位），不影响注册
9. 所有新代码通过 `python -m py_compile` 语法检查

## 5. 验证用测试代码

```python
# tests/test_domain_plugins.py
import pytest
from contract_review.plugins.registry import (
    DomainPlugin,
    register_domain_plugin,
    get_domain_plugin,
    list_domain_plugins,
    get_domain_ids,
    get_review_checklist,
    get_all_skills_for_domain,
    get_parser_config,
    get_baseline_text,
    clear_plugins,
)
from contract_review.plugins.fidic import (
    FIDIC_PLUGIN,
    FIDIC_SILVER_BOOK_CHECKLIST,
    FIDIC_PARSER_CONFIG,
    register_fidic_plugin,
)
from contract_review.models import ReviewChecklistItem, DocumentParserConfig


class TestPluginRegistry:
    def setup_method(self):
        """每个测试前清空注册表"""
        clear_plugins()

    def test_register_and_get(self):
        """测试注册和获取插件"""
        register_domain_plugin(FIDIC_PLUGIN)
        plugin = get_domain_plugin("fidic")
        assert plugin is not None
        assert plugin.name == "FIDIC 国际工程合同"

    def test_list_plugins(self):
        """测试列出所有插件"""
        register_domain_plugin(FIDIC_PLUGIN)
        plugins = list_domain_plugins()
        assert len(plugins) == 1
        assert plugins[0].domain_id == "fidic"

    def test_get_nonexistent(self):
        """测试获取不存在的插件"""
        plugin = get_domain_plugin("nonexistent")
        assert plugin is None

    def test_get_review_checklist(self):
        """测试获取审查清单"""
        register_domain_plugin(FIDIC_PLUGIN)
        checklist = get_review_checklist("fidic")
        assert len(checklist) >= 12
        # 验证关键条款存在
        clause_ids = [item.clause_id for item in checklist]
        assert "4.1" in clause_ids
        assert "14.2" in clause_ids
        assert "17.6" in clause_ids
        assert "20.1" in clause_ids

    def test_get_review_checklist_empty(self):
        """测试无插件时返回空清单"""
        checklist = get_review_checklist("nonexistent")
        assert checklist == []

    def test_get_all_skills(self):
        """测试获取合并后的 Skills 列表"""
        register_domain_plugin(FIDIC_PLUGIN)
        from contract_review.skills.schema import SkillRegistration, SkillBackend

        generic = [
            SkillRegistration(
                skill_id="get_clause_context",
                name="条款上下文获取",
                input_schema=None,
                output_schema=None,
                backend=SkillBackend.LOCAL,
                local_handler="dummy",
            )
        ]
        all_skills = get_all_skills_for_domain("fidic", generic)
        skill_ids = [s.skill_id for s in all_skills]
        assert "get_clause_context" in skill_ids       # 通用
        assert "fidic_merge_gc_pc" in skill_ids        # FIDIC 专属

    def test_parser_config(self):
        """测试获取解析配置"""
        register_domain_plugin(FIDIC_PLUGIN)
        config = get_parser_config("fidic")
        assert config.structure_type == "fidic_gc"
        assert config.definitions_section_id == "1.1"

    def test_parser_config_default(self):
        """测试无插件时返回默认配置"""
        config = get_parser_config("nonexistent")
        assert config.structure_type == "generic_numbered"

    def test_clear_plugins(self):
        """测试清空注册表"""
        register_domain_plugin(FIDIC_PLUGIN)
        assert len(get_domain_ids()) == 1
        clear_plugins()
        assert len(get_domain_ids()) == 0


class TestFidicPlugin:
    def test_plugin_structure(self):
        """测试 FIDIC 插件结构完整性"""
        assert FIDIC_PLUGIN.domain_id == "fidic"
        assert len(FIDIC_PLUGIN.supported_subtypes) >= 3
        assert "silver_book" in FIDIC_PLUGIN.supported_subtypes

    def test_checklist_priorities(self):
        """测试审查清单优先级分布"""
        critical = [c for c in FIDIC_SILVER_BOOK_CHECKLIST if c.priority == "critical"]
        high = [c for c in FIDIC_SILVER_BOOK_CHECKLIST if c.priority == "high"]
        assert len(critical) >= 4  # 至少 4 个 critical 条款
        assert len(high) >= 5     # 至少 5 个 high 条款

    def test_checklist_skills_reference(self):
        """测试审查清单引用的 Skills 合理性"""
        for item in FIDIC_SILVER_BOOK_CHECKLIST:
            # 每个条款至少需要 get_clause_context
            assert len(item.required_skills) >= 1

    def test_register_convenience(self):
        """测试便捷注册函数"""
        clear_plugins()
        register_fidic_plugin()
        assert get_domain_plugin("fidic") is not None
```

## 6. 注意事项

- FIDIC 插件的 `domain_skills` 中 `input_schema`/`output_schema` 当前为 `None`，这是因为具体的 IO 模型将在 FIDIC Skills 实际开发时定义。`SkillRegistration` 需要在 Spec-1 中确保 `Config` 设置了 `arbitrary_types_allowed = True` 以允许 None
- `baseline_texts` 当前为空 dict，Silver Book 标准条款文本需要后续人工录入
- `FIDIC_DOMAIN_SKILLS` 中的 `local_handler` 路径指向尚未创建的模块，这是预期行为——实际 handler 在后续 FIDIC 开发阶段实现
- `register_fidic_plugin()` 是便捷函数，应在应用启动时调用
- 插件注册表使用模块级全局变量 `_DOMAIN_PLUGINS`，测试时通过 `clear_plugins()` 隔离
- 后续新增领域插件（如国内采购合同）只需创建类似 `fidic.py` 的文件，定义 `DomainPlugin` 并注册
