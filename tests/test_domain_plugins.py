from contract_review.plugins.fidic import (
    FIDIC_PLUGIN,
    FIDIC_SILVER_BOOK_CHECKLIST,
    register_fidic_plugin,
)
from contract_review.plugins.registry import (
    clear_plugins,
    get_domain_ids,
    get_domain_plugin,
    get_parser_config,
    get_review_checklist,
    list_domain_plugins,
    register_domain_plugin,
)


class TestPluginRegistry:
    def setup_method(self):
        clear_plugins()

    def test_register_and_get(self):
        register_domain_plugin(FIDIC_PLUGIN)
        plugin = get_domain_plugin("fidic")
        assert plugin is not None
        assert plugin.name == "FIDIC 国际工程合同"

    def test_list_plugins(self):
        register_domain_plugin(FIDIC_PLUGIN)
        plugins = list_domain_plugins()
        assert len(plugins) == 1

    def test_get_nonexistent(self):
        assert get_domain_plugin("nonexistent") is None

    def test_get_review_checklist(self):
        register_domain_plugin(FIDIC_PLUGIN)
        checklist = get_review_checklist("fidic")
        assert len(checklist) >= 12
        clause_ids = [item.clause_id for item in checklist]
        assert "4.1" in clause_ids
        assert "14.2" in clause_ids
        assert "17.6" in clause_ids
        assert "20.1" in clause_ids

    def test_get_review_checklist_empty(self):
        assert get_review_checklist("nonexistent") == []

    def test_parser_config(self):
        register_domain_plugin(FIDIC_PLUGIN)
        config = get_parser_config("fidic")
        assert config.structure_type == "fidic_gc"
        assert config.definitions_section_id == "1.1"

    def test_parser_config_default(self):
        config = get_parser_config("nonexistent")
        assert config.structure_type == "generic_numbered"

    def test_clear_plugins(self):
        register_domain_plugin(FIDIC_PLUGIN)
        assert len(get_domain_ids()) == 1
        clear_plugins()
        assert len(get_domain_ids()) == 0


class TestFidicPlugin:
    def test_plugin_structure(self):
        assert FIDIC_PLUGIN.domain_id == "fidic"
        assert "silver_book" in FIDIC_PLUGIN.supported_subtypes

    def test_checklist_priorities(self):
        critical = [c for c in FIDIC_SILVER_BOOK_CHECKLIST if c.priority == "critical"]
        high = [c for c in FIDIC_SILVER_BOOK_CHECKLIST if c.priority == "high"]
        assert len(critical) >= 4
        assert len(high) >= 5

    def test_register_convenience(self):
        clear_plugins()
        register_fidic_plugin()
        assert get_domain_plugin("fidic") is not None
