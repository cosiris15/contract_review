"""Document structure parser."""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from .definition_patterns import extract_by_patterns
from .models import ClauseNode, CrossReference, DocumentParserConfig, DocumentStructure, LoadedDocument

logger = logging.getLogger(__name__)

DEFAULT_PARSER_CONFIG = DocumentParserConfig(
    clause_pattern=r"^\d+(?:\.\d+)*\s+",
    chapter_pattern=None,
    definitions_section_id=None,
    max_depth=4,
    structure_type="generic_numbered",
)


class StructureParser:
    """Parse contract text into clause tree and references."""

    def __init__(self, config: Optional[DocumentParserConfig] = None):
        self.config = config or DEFAULT_PARSER_CONFIG
        self._clause_re = re.compile(self.config.clause_pattern, re.MULTILINE)
        self._chapter_re = (
            re.compile(self.config.chapter_pattern, re.MULTILINE)
            if self.config.chapter_pattern
            else None
        )

    def parse(self, document: LoadedDocument) -> DocumentStructure:
        text = document.text
        document_id = str(document.path) if document.path else "unknown"

        raw_clauses = self._split_clauses(text)
        clause_tree = self._build_tree(raw_clauses)
        total = self._count_clauses(clause_tree)

        definitions = {}
        if self.config.definitions_section_id:
            definitions = self._extract_definitions_v2(clause_tree, self.config.definitions_section_id)

        cross_refs = self._extract_cross_references(clause_tree)

        return DocumentStructure(
            document_id=document_id,
            structure_type=self.config.structure_type,
            clauses=clause_tree,
            definitions=definitions,
            cross_references=cross_refs,
            total_clauses=total,
        )

    def _split_clauses(self, text: str) -> List[Tuple[str, str, int]]:
        matches = list(self._clause_re.finditer(text))
        if not matches:
            return [("0", text, 0)]

        result: List[Tuple[str, str, int]] = []
        for i, match in enumerate(matches):
            clause_id = match.group().strip().rstrip(".")
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            clause_text = text[start:end].strip()
            result.append((clause_id, clause_text, start))
        return result

    def _parse_clause_id_level(self, clause_id: str) -> int:
        parts = [p for p in clause_id.split(".") if p]
        return max(0, len(parts) - 1)

    def _extract_title(self, clause_text: str, clause_id: str) -> str:
        text = re.sub(rf"^{re.escape(clause_id)}[\.\s]*", "", clause_text).strip()
        first_line = text.split("\n")[0].strip()
        return "" if len(first_line) > 100 else first_line

    def _build_tree(self, raw_clauses: List[Tuple[str, str, int]]) -> List[ClauseNode]:
        if not raw_clauses:
            return []

        root_nodes: List[ClauseNode] = []
        stack: List[Tuple[int, ClauseNode]] = []

        for clause_id, clause_text, start_offset in raw_clauses:
            level = min(self._parse_clause_id_level(clause_id), self.config.max_depth - 1)
            node = ClauseNode(
                clause_id=clause_id,
                title=self._extract_title(clause_text, clause_id),
                level=level,
                text=clause_text,
                start_offset=start_offset,
                end_offset=start_offset + len(clause_text),
            )

            while stack and stack[-1][0] >= level:
                stack.pop()

            if stack:
                stack[-1][1].children.append(node)
            else:
                root_nodes.append(node)

            stack.append((level, node))

        return root_nodes

    def _count_clauses(self, nodes: List[ClauseNode]) -> int:
        count = 0
        for node in nodes:
            count += 1
            count += self._count_clauses(node.children)
        return count

    def _extract_definitions_legacy(self, clause_tree: List[ClauseNode], section_id: str) -> Dict[str, str]:
        definitions: Dict[str, str] = {}
        target_node = self._find_clause(clause_tree, section_id)
        if not target_node:
            return definitions

        full_text = self._collect_text(target_node)
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

    def _extract_definitions_v2(self, clause_tree: List[ClauseNode], section_id: str) -> Dict[str, str]:
        """Extract definitions with expanded pattern set (sync path)."""
        definitions: Dict[str, str] = {}
        target_node = self._find_clause(clause_tree, section_id)
        if not target_node:
            return definitions
        full_text = self._collect_text(target_node)
        for term, definition, _pattern in extract_by_patterns(full_text):
            if term not in definitions:
                definitions[term] = definition
        return definitions

    def _extract_cross_references(self, clause_tree: List[ClauseNode]) -> List[CrossReference]:
        refs: List[CrossReference] = []
        all_clause_ids = set(self._collect_all_ids(clause_tree))
        patterns = [
            r"[Cc]lause\s+(\d+(?:\.\d+)*)",
            r"[Ss]ub-[Cc]lause\s+(\d+(?:\.\d+)*)",
            r"第\s*(\d+(?:\.\d+)*)\s*条",
            r"(?:见|参见|依据|根据)\s*(\d+(?:\.\d+)*)\s*条",
        ]

        def scan_node(node: ClauseNode):
            for pattern in patterns:
                for match in re.finditer(pattern, node.text):
                    target_id = match.group(1)
                    if target_id != node.clause_id:
                        refs.append(
                            CrossReference(
                                source_clause_id=node.clause_id,
                                target_clause_id=target_id,
                                reference_text=match.group(0),
                                is_valid=target_id in all_clause_ids,
                            )
                        )
            for child in node.children:
                scan_node(child)

        for node in clause_tree:
            scan_node(node)
        return refs

    def _find_clause(self, nodes: List[ClauseNode], clause_id: str) -> Optional[ClauseNode]:
        for node in nodes:
            if node.clause_id == clause_id:
                return node
            found = self._find_clause(node.children, clause_id)
            if found:
                return found
        return None

    def _collect_text(self, node: ClauseNode) -> str:
        texts = [node.text]
        for child in node.children:
            texts.append(self._collect_text(child))
        return "\n".join(texts)

    def _collect_all_ids(self, nodes: List[ClauseNode]) -> List[str]:
        ids: List[str] = []
        for node in nodes:
            ids.append(node.clause_id)
            ids.extend(self._collect_all_ids(node.children))
        return ids

    def get_clause_context(self, structure: DocumentStructure, clause_id: str) -> Optional[str]:
        node = self._find_clause(structure.clauses, clause_id)
        if not node:
            return None
        return self._collect_text(node)
