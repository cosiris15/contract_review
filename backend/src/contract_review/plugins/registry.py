"""Domain plugin registry."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ..models import DocumentParserConfig, ReviewChecklistItem
from ..skills.schema import SkillRegistration

logger = logging.getLogger(__name__)


class DomainPlugin(BaseModel):
    domain_id: str
    name: str
    description: str = ""
    supported_subtypes: List[str] = Field(default_factory=list)
    domain_skills: List[SkillRegistration] = Field(default_factory=list)
    review_checklist: List[ReviewChecklistItem] = Field(default_factory=list)
    document_parser_config: DocumentParserConfig = Field(default_factory=DocumentParserConfig)
    baseline_texts: Dict[str, str] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True


_DOMAIN_PLUGINS: Dict[str, DomainPlugin] = {}


def register_domain_plugin(plugin: DomainPlugin) -> None:
    if plugin.domain_id in _DOMAIN_PLUGINS:
        logger.warning("领域插件 '%s' 已存在，将被覆盖", plugin.domain_id)
    _DOMAIN_PLUGINS[plugin.domain_id] = plugin
    logger.info("领域插件已注册: %s (%s)", plugin.domain_id, plugin.name)


def get_domain_plugin(domain_id: str) -> Optional[DomainPlugin]:
    return _DOMAIN_PLUGINS.get(domain_id)


def list_domain_plugins() -> List[DomainPlugin]:
    return list(_DOMAIN_PLUGINS.values())


def get_domain_ids() -> List[str]:
    return list(_DOMAIN_PLUGINS.keys())


def get_review_checklist(domain_id: str, subtype: Optional[str] = None) -> List[ReviewChecklistItem]:
    _ = subtype
    plugin = _DOMAIN_PLUGINS.get(domain_id)
    if not plugin:
        return []
    return plugin.review_checklist


def get_all_skills_for_domain(
    domain_id: str, generic_skills: Optional[List[SkillRegistration]] = None
) -> List[SkillRegistration]:
    skills = list(generic_skills or [])
    plugin = _DOMAIN_PLUGINS.get(domain_id)
    if plugin:
        skills.extend(plugin.domain_skills)
    return skills


def get_parser_config(domain_id: str) -> DocumentParserConfig:
    plugin = _DOMAIN_PLUGINS.get(domain_id)
    if plugin:
        return plugin.document_parser_config
    return DocumentParserConfig()


def get_baseline_text(domain_id: str, clause_id: str) -> Optional[str]:
    plugin = _DOMAIN_PLUGINS.get(domain_id)
    if not plugin:
        return None
    return plugin.baseline_texts.get(clause_id)


def clear_plugins() -> None:
    _DOMAIN_PLUGINS.clear()
