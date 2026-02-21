# SPEC-3: 文档结构解析器

> 优先级：高（Spec-4 状态机的条款级循环依赖结构化数据）
> 前置依赖：Spec-2（ClauseNode、DocumentStructure、DocumentParserConfig 模型）
> 预计新建文件：2 个 | 修改文件：0 个
> 参考：GEN3_GAP_ANALYSIS.md 第 9.1 章

---

## 1. 目标

构建通用的合同文档结构解析器（StructureParser），能够：
- 将合同纯文本解析为条款树（`List[ClauseNode]`）
- 提取定义条款中的专有名词定义表
- 识别条款间的交叉引用关系
- 通过 `DocumentParserConfig` 支持不同合同类型的解析规则

解析器本身是通用的，FIDIC 等特定合同类型只需提供不同的 `DocumentParserConfig`。

## 2. 需要创建的文件

### 2.1 `backend/src/contract_review/structure_parser.py`

核心解析器实现。

```python
"""
文档结构解析器

将合同纯文本解析为结构化的条款树（ClauseNode），
提取定义表和交叉引用关系。

通用实现，通过 DocumentParserConfig 适配不同合同类型。
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from .models import (
    ClauseNode,
    CrossReference,
    DocumentParserConfig,
    DocumentStructure,
    LoadedDocument,
)

logger = logging.getLogger(__name__)

# 默认配置：通用编号条款合同
DEFAULT_PARSER_CONFIG = DocumentParserConfig(
    clause_pattern=r"^(\d+\.)+\d*\s+",
    chapter_pattern=None,
    definitions_section_id=None,
    max_depth=4,
    structure_type="generic_numbered",
)


class StructureParser:
    """
    条款结构解析器

    使用方式:
        parser = StructureParser(config)
        structure = parser.parse(document)
    """

    def __init__(self, config: Optional[DocumentParserConfig] = None):
        self.config = config or DEFAULT_PARSER_CONFIG
        self._clause_re = re.compile(self.config.clause_pattern, re.MULTILINE)
        self._chapter_re = (
            re.compile(self.config.chapter_pattern, re.MULTILINE)
            if self.config.chapter_pattern
            else None
        )

    def parse(self, document: LoadedDocument) -> DocumentStructure:
        """
        解析文档，返回结构化结果

        Args:
            document: 已加载的文档（含纯文本）

        Returns:
            DocumentStructure 包含条款树、定义表、交叉引用
        """
        text = document.text
        document_id = str(document.path) if document.path else "unknown"

        # Step 1: 切分条款
        raw_clauses = self._split_clauses(text)
        logger.info(f"切分出 {len(raw_clauses)} 个原始条款段落")

        # Step 2: 构建条款树
        clause_tree = self._build_tree(raw_clauses)
        total = self._count_clauses(clause_tree)
        logger.info(f"构建条款树完成，共 {total} 个节点")

        # Step 3: 提取定义表
        definitions = {}
        if self.config.definitions_section_id:
            definitions = self._extract_definitions(
                clause_tree, self.config.definitions_section_id
            )
            logger.info(f"提取到 {len(definitions)} 个定义")

        # Step 4: 识别交叉引用
        cross_refs = self._extract_cross_references(clause_tree)
        logger.info(f"识别到 {len(cross_refs)} 个交叉引用")

        return DocumentStructure(
            document_id=document_id,
            structure_type=self.config.structure_type,
            clauses=clause_tree,
            definitions=definitions,
            cross_references=cross_refs,
            total_clauses=total,
        )

    def _split_clauses(self, text: str) -> List[Tuple[str, str, int]]:
        """
        按条款编号切分文本

        Returns:
            List of (clause_id, clause_text, start_offset)
        """
        matches = list(self._clause_re.finditer(text))
        if not matches:
            # 无法识别条款编号，返回整个文档作为单一节点
            return [("0", text, 0)]

        result = []
        for i, match in enumerate(matches):
            clause_id = match.group().strip().rstrip(".")
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            clause_text = text[start:end].strip()
            result.append((clause_id, clause_text, start))

        return result

    def _parse_clause_id_level(self, clause_id: str) -> int:
        """
        根据条款编号推断层级

        "1" → 0, "1.1" → 1, "1.1.1" → 2, "1.1.1.1" → 3
        """
        parts = clause_id.split(".")
        # 过滤空字符串（如 "1." 末尾的点）
        parts = [p for p in parts if p]
        return max(0, len(parts) - 1)

    def _extract_title(self, clause_text: str, clause_id: str) -> str:
        """
        从条款文本中提取标题

        通常标题是条款编号后、第一个换行符前的文本。
        """
        # 移除条款编号前缀
        text = clause_text
        id_pattern = re.escape(clause_id)
        text = re.sub(rf"^{id_pattern}[\.\s]*", "", text).strip()

        # 取第一行作为标题
        first_line = text.split("\n")[0].strip()
        # 如果第一行太长（>100字符），可能不是标题
        if len(first_line) > 100:
            return ""
        return first_line

    def _build_tree(
        self, raw_clauses: List[Tuple[str, str, int]]
    ) -> List[ClauseNode]:
        """
        将扁平的条款列表构建为树形结构

        使用栈来追踪当前的父节点链。
        """
        if not raw_clauses:
            return []

        root_nodes: List[ClauseNode] = []
        # 栈：(level, node) — 追踪当前路径上的祖先节点
        stack: List[Tuple[int, ClauseNode]] = []

        for clause_id, clause_text, start_offset in raw_clauses:
            level = self._parse_clause_id_level(clause_id)
            # 限制最大深度
            level = min(level, self.config.max_depth - 1)

            title = self._extract_title(clause_text, clause_id)

            node = ClauseNode(
                clause_id=clause_id,
                title=title,
                level=level,
                text=clause_text,
                start_offset=start_offset,
                end_offset=start_offset + len(clause_text),
            )

            # 弹出栈中层级 >= 当前层级的节点
            while stack and stack[-1][0] >= level:
                stack.pop()

            if stack:
                # 有父节点，挂到父节点的 children 下
                parent_node = stack[-1][1]
                parent_node.children.append(node)
            else:
                # 无父节点，作为顶级节点
                root_nodes.append(node)

            stack.append((level, node))

        return root_nodes

    def _count_clauses(self, nodes: List[ClauseNode]) -> int:
        """递归统计条款总数"""
        count = 0
        for node in nodes:
            count += 1
            count += self._count_clauses(node.children)
        return count

    def _extract_definitions(
        self, clause_tree: List[ClauseNode], section_id: str
    ) -> Dict[str, str]:
        """
        从定义条款中提取专有名词定义表

        在条款树中查找 clause_id 匹配 section_id 的节点，
        解析其文本中的 "术语" means ... 格式。
        """
        definitions = {}
        target_node = self._find_clause(clause_tree, section_id)
        if not target_node:
            return definitions

        # 合并该节点及其子节点的所有文本
        full_text = self._collect_text(target_node)

        # 匹配常见定义格式:
        # "Term" means ...
        # "Term" 指 ...
        # "Term" shall mean ...
        patterns = [
            r'"([^"]+)"\s+means?\s+(.+?)(?=\n\s*"|$)',
            r'"([^"]+)"\s+shall\s+mean\s+(.+?)(?=\n\s*"|$)',
            r'"([^"]+)"\s*(?:指|是指|系指)\s*(.+?)(?=\n\s*"|$)',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, full_text, re.DOTALL):
                term = match.group(1).strip()
                definition = match.group(2).strip()
                if term and definition:
                    definitions[term] = definition

        return definitions

    def _extract_cross_references(
        self, clause_tree: List[ClauseNode]
    ) -> List[CrossReference]:
        """
        识别条款间的交叉引用

        扫描所有条款文本，查找 "Clause X.Y" 或 "第X.Y条" 格式的引用。
        """
        refs = []
        all_clause_ids = set(self._collect_all_ids(clause_tree))

        patterns = [
            r"[Cc]lause\s+(\d+(?:\.\d+)*)",       # Clause 14.2
            r"[Ss]ub-[Cc]lause\s+(\d+(?:\.\d+)*)", # Sub-Clause 20.1
            r"第\s*(\d+(?:\.\d+)*)\s*条",           # 第14.2条
            r"(?:见|参见|依据|根据)\s*(\d+(?:\.\d+)*)\s*条", # 见14.2条
        ]

        def scan_node(node: ClauseNode):
            for pattern in patterns:
                for match in re.finditer(pattern, node.text):
                    target_id = match.group(1)
                    if target_id != node.clause_id:  # 排除自引用
                        refs.append(CrossReference(
                            source_clause_id=node.clause_id,
                            target_clause_id=target_id,
                            reference_text=match.group(0),
                            is_valid=target_id in all_clause_ids,
                        ))
            for child in node.children:
                scan_node(child)

        for node in clause_tree:
            scan_node(node)

        return refs

    # === 辅助方法 ===

    def _find_clause(
        self, nodes: List[ClauseNode], clause_id: str
    ) -> Optional[ClauseNode]:
        """在条款树中查找指定 ID 的节点"""
        for node in nodes:
            if node.clause_id == clause_id:
                return node
            found = self._find_clause(node.children, clause_id)
            if found:
                return found
        return None

    def _collect_text(self, node: ClauseNode) -> str:
        """收集节点及其所有子节点的文本"""
        texts = [node.text]
        for child in node.children:
            texts.append(self._collect_text(child))
        return "\n".join(texts)

    def _collect_all_ids(self, nodes: List[ClauseNode]) -> List[str]:
        """收集所有条款 ID"""
        ids = []
        for node in nodes:
            ids.append(node.clause_id)
            ids.extend(self._collect_all_ids(node.children))
        return ids

    def get_clause_context(
        self, structure: DocumentStructure, clause_id: str
    ) -> Optional[str]:
        """
        获取指定条款的完整上下文文本

        这是 Skill_Get_Clause_Context 的底层实现。

        Args:
            structure: 已解析的文档结构
            clause_id: 目标条款 ID

        Returns:
            条款全文（含子条款），未找到返回 None
        """
        node = self._find_clause(structure.clauses, clause_id)
        if not node:
            return None
        return self._collect_text(node)
```

### 2.2 `backend/src/contract_review/skills/local/__init__.py`

空文件，标记 local skills 包。后续各 Skill 的本地实现放在此目录下。

### 2.3 `backend/src/contract_review/skills/local/clause_context.py`

第一个本地 Skill 实现：条款上下文获取。基于 StructureParser 提供的能力。

```python
"""
本地 Skill: 条款上下文获取

基于 StructureParser 的 get_clause_context 方法，
获取指定条款的完整上下文文本（含子条款）。
"""

from __future__ import annotations

from pydantic import BaseModel
from typing import Optional

from ...structure_parser import StructureParser
from ...models import DocumentStructure


class ClauseContextInput(BaseModel):
    """条款上下文获取 — 输入"""
    clause_id: str
    document_structure: DocumentStructure


class ClauseContextOutput(BaseModel):
    """条款上下文获取 — 输出"""
    clause_id: str
    found: bool = False
    context_text: str = ""
    title: str = ""


async def get_clause_context(input_data: ClauseContextInput) -> ClauseContextOutput:
    """
    获取指定条款的完整上下文

    这是一个本地 Skill handler，签名符合 LocalSkillExecutor 的要求。
    """
    parser = StructureParser()
    text = parser.get_clause_context(input_data.document_structure, input_data.clause_id)

    if text is None:
        return ClauseContextOutput(clause_id=input_data.clause_id, found=False)

    # 尝试从结构中获取标题
    node = parser._find_clause(
        input_data.document_structure.clauses, input_data.clause_id
    )
    title = node.title if node else ""

    return ClauseContextOutput(
        clause_id=input_data.clause_id,
        found=True,
        context_text=text,
        title=title,
    )
```

## 3. 目录结构（完成后）

```
backend/src/contract_review/
├── structure_parser.py              # 新建：通用条款结构解析器
├── skills/
│   ├── __init__.py                  # Spec-1 已创建
│   ├── schema.py                    # Spec-1 已创建
│   ├── dispatcher.py                # Spec-1 已创建
│   ├── refly_client.py              # Spec-1 已创建
│   └── local/
│       ├── __init__.py              # 新建：本地 Skills 包
│       └── clause_context.py        # 新建：条款上下文获取 Skill
└── ... (其他文件不动)
```

## 4. 验收标准

1. `StructureParser` 能解析包含编号条款的合同文本，生成正确的 `DocumentStructure`
2. 条款树层级正确：`"1"` → level 0，`"1.1"` → level 1，`"1.1.1"` → level 2
3. 子条款正确嵌套在父条款的 `children` 中
4. 定义提取能识别 `"Term" means ...` 格式
5. 交叉引用能识别 `Clause X.Y` 和 `第X.Y条` 格式，并标记 `is_valid`
6. `get_clause_context()` 能返回指定条款及其子条款的完整文本
7. `clause_context.py` 的 `get_clause_context` handler 可被 `LocalSkillExecutor` 调用
8. 所有新代码通过 `python -m py_compile` 语法检查

## 5. 验证用测试代码

```python
# tests/test_structure_parser.py
import pytest
from pathlib import Path
from contract_review.models import (
    LoadedDocument, DocumentParserConfig, ClauseNode, DocumentStructure,
)
from contract_review.structure_parser import StructureParser, DEFAULT_PARSER_CONFIG


# 测试用合同文本
SAMPLE_CONTRACT = """
1 General Provisions

1.1 Definitions
In this Contract, the following words and expressions shall have the meanings stated:
"Employer" means the person named as employer in the Contract Data.
"Contractor" means the person named as contractor in the Contract Data.
"Engineer" means the person appointed by the Employer to act as the Engineer.

1.2 Interpretation
Words importing the singular also include the plural and vice versa.

2 The Employer

2.1 Right of Access to the Site
The Employer shall give the Contractor right of access to the Site.

2.2 Permits, Licences or Approvals
The Employer shall provide reasonable assistance to the Contractor. See Clause 1.1 for definitions.

3 The Contractor

3.1 General Obligations
The Contractor shall design, execute and complete the Works in accordance with Clause 2.1.

3.1.1 Sub-obligation A
Details of sub-obligation A as per Sub-Clause 3.1.

3.1.2 Sub-obligation B
Details of sub-obligation B.
""".strip()


class TestStructureParser:
    def setup_method(self):
        self.doc = LoadedDocument(path=Path("test.txt"), text=SAMPLE_CONTRACT)
        self.parser = StructureParser()

    def test_parse_basic(self):
        """测试基本解析"""
        structure = self.parser.parse(self.doc)
        assert structure.total_clauses > 0
        assert len(structure.clauses) > 0  # 顶级节点

    def test_clause_levels(self):
        """测试条款层级"""
        structure = self.parser.parse(self.doc)
        # 顶级节点应该是 level 0
        for node in structure.clauses:
            assert node.level == 0

    def test_nested_children(self):
        """测试子条款嵌套"""
        structure = self.parser.parse(self.doc)
        # 找到 clause "3.1"，它应该有子条款 3.1.1 和 3.1.2
        node_3_1 = self.parser._find_clause(structure.clauses, "3.1")
        if node_3_1:
            child_ids = [c.clause_id for c in node_3_1.children]
            assert "3.1.1" in child_ids or "3.1.2" in child_ids

    def test_cross_references(self):
        """测试交叉引用识别"""
        structure = self.parser.parse(self.doc)
        # "See Clause 1.1" 和 "in accordance with Clause 2.1" 应被识别
        ref_targets = [r.target_clause_id for r in structure.cross_references]
        assert len(ref_targets) > 0

    def test_get_clause_context(self):
        """测试获取条款上下文"""
        structure = self.parser.parse(self.doc)
        context = self.parser.get_clause_context(structure, "1.1")
        assert context is not None
        assert "Definitions" in context or "definitions" in context.lower()

    def test_get_nonexistent_clause(self):
        """测试获取不存在的条款"""
        structure = self.parser.parse(self.doc)
        context = self.parser.get_clause_context(structure, "99.99")
        assert context is None

    def test_definitions_extraction(self):
        """测试定义提取"""
        config = DocumentParserConfig(
            clause_pattern=r"^(\d+\.)+\d*\s+",
            definitions_section_id="1.1",
            structure_type="generic_numbered",
        )
        parser = StructureParser(config)
        structure = parser.parse(self.doc)
        # 应该提取到 "Employer", "Contractor", "Engineer"
        assert len(structure.definitions) > 0

    def test_custom_config(self):
        """测试自定义解析配置"""
        config = DocumentParserConfig(
            clause_pattern=r"^(\d+\.)+\d*\s+",
            max_depth=2,
            structure_type="custom_test",
        )
        parser = StructureParser(config)
        structure = parser.parse(self.doc)
        assert structure.structure_type == "custom_test"
        # max_depth=2 时，level 不应超过 1
        def check_depth(nodes, max_level=1):
            for n in nodes:
                assert n.level <= max_level
                check_depth(n.children, max_level)
        check_depth(structure.clauses)
```

## 6. 注意事项

- `StructureParser` 是纯 CPU 操作，不涉及 LLM 调用，适合本地执行
- 正则模式 `clause_pattern` 需要能处理中英文合同的常见编号格式
- `_build_tree` 使用栈算法，时间复杂度 O(n)，适合大文档
- 定义提取的正则模式覆盖了英文 `"Term" means` 和中文 `"术语" 指` 两种格式
- 交叉引用检测同时支持英文 `Clause X.Y` 和中文 `第X.Y条` 格式
- `clause_context.py` 是第一个本地 Skill 实现，验证了 Spec-1 中 `LocalSkillExecutor` 的可行性
- 不要修改现有的 `document_preprocessor.py`，两者职责不同（预处理器做甲乙方提取，结构解析器做条款树）
