"""
配置管理模块

处理 YAML 配置文件加载、环境变量覆盖等。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field


class LLMSettings(BaseModel):
    """LLM API 配置"""
    provider: str = Field(default="deepseek")
    api_key: str
    base_url: str = Field(default="https://api.deepseek.com")
    model: str = Field(default="deepseek-chat")
    temperature: float = Field(default=0.1)
    top_p: float = Field(default=0.9)
    max_output_tokens: int = Field(default=4000)  # 审阅结果可能较长，增加 token 限制
    request_timeout: int = Field(default=120)  # 审阅可能耗时较长


class ReviewSettings(BaseModel):
    """审阅任务配置"""
    tasks_dir: Path = Field(default=Path("tasks"))
    templates_dir: Path = Field(default=Path("templates"))
    max_document_chars: int = Field(default=50000)  # 最大文档字符数

    def resolve_paths(self, base: Path) -> "ReviewSettings":
        """解析相对路径为绝对路径"""
        return ReviewSettings(
            tasks_dir=(base / self.tasks_dir).resolve(),
            templates_dir=(base / self.templates_dir).resolve(),
            max_document_chars=self.max_document_chars,
        )


class Settings(BaseModel):
    """全局配置"""
    llm: LLMSettings
    review: ReviewSettings = Field(default_factory=ReviewSettings)


def load_settings(config_path: Optional[Path] = None) -> Settings:
    """
    加载配置文件

    优先级：环境变量 > 配置文件 > 默认值

    Args:
        config_path: 配置文件路径，None 时使用默认路径

    Returns:
        Settings 对象
    """
    if config_path is None:
        # 默认配置文件路径
        config_path = Path(__file__).parent.parent.parent / "config" / "deepseek_config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {config_path}\n"
            "请复制 config/deepseek_config.example.yaml 到 config/deepseek_config.yaml 并填入配置值。"
        )

    with config_path.open("r", encoding="utf-8") as f:
        data: Dict[str, Any] = yaml.safe_load(f) or {}

    # 允许通过环境变量覆盖 API Key
    llm_cfg = data.get("llm", {})
    llm_cfg["api_key"] = os.getenv("DEEPSEEK_API_KEY", llm_cfg.get("api_key"))
    data["llm"] = llm_cfg

    settings = Settings(**data)

    # 解析相对路径
    base_dir = config_path.parent.parent if config_path.parent.name == "config" else config_path.parent
    resolved_review = settings.review.resolve_paths(base_dir)

    return Settings(llm=settings.llm, review=resolved_review)


# 全局配置实例（延迟加载）
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取全局配置实例"""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings
