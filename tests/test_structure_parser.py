from pathlib import Path

from contract_review.models import DocumentParserConfig, LoadedDocument
from contract_review.structure_parser import StructureParser

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
        structure = self.parser.parse(self.doc)
        assert structure.total_clauses > 0
        assert len(structure.clauses) > 0

    def test_clause_levels(self):
        structure = self.parser.parse(self.doc)
        for node in structure.clauses:
            assert node.level == 0

    def test_nested_children(self):
        structure = self.parser.parse(self.doc)
        node_3_1 = self.parser._find_clause(structure.clauses, "3.1")
        if node_3_1:
            child_ids = [c.clause_id for c in node_3_1.children]
            assert "3.1.1" in child_ids or "3.1.2" in child_ids

    def test_cross_references(self):
        structure = self.parser.parse(self.doc)
        assert len([r.target_clause_id for r in structure.cross_references]) > 0

    def test_get_clause_context(self):
        structure = self.parser.parse(self.doc)
        context = self.parser.get_clause_context(structure, "1.1")
        assert context is not None
        assert "Definitions" in context or "definitions" in context.lower()

    def test_get_nonexistent_clause(self):
        structure = self.parser.parse(self.doc)
        assert self.parser.get_clause_context(structure, "99.99") is None

    def test_definitions_extraction(self):
        config = DocumentParserConfig(
            clause_pattern=r"^(\d+\.)+\d*\s+",
            definitions_section_id="1.1",
            structure_type="generic_numbered",
        )
        parser = StructureParser(config)
        structure = parser.parse(self.doc)
        assert len(structure.definitions) > 0

    def test_custom_config(self):
        config = DocumentParserConfig(
            clause_pattern=r"^(\d+\.)+\d*\s+",
            max_depth=2,
            structure_type="custom_test",
        )
        parser = StructureParser(config)
        structure = parser.parse(self.doc)
        assert structure.structure_type == "custom_test"

        def check_depth(nodes, max_level=1):
            for n in nodes:
                assert n.level <= max_level
                check_depth(n.children, max_level)

        check_depth(structure.clauses)
