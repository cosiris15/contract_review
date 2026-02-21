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


class GeminiSettings(BaseModel):
    """Gemini API 配置（用于标准生成）"""
    api_key: Optional[str] = None
    model: str = Field(default="gemini-2.0-flash")
    timeout: int = Field(default=120)


class ReflySettings(BaseModel):
    """Refly API 配置"""

    enabled: bool = False
    base_url: str = "https://api.refly.ai"
    api_key: str = ""
    timeout: int = 120
    poll_interval: int = 2
    max_poll_attempts: int = 60


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
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    refly: ReflySettings = Field(default_factory=ReflySettings)
    use_react_agent: bool = False
    react_max_iterations: int = 5
    react_temperature: float = 0.1
    use_orchestrator: bool = False


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

    # 允许通过环境变量配置 Gemini API Key
    gemini_cfg = data.get("gemini", {})
    gemini_api_key = os.getenv("GEMINI_API_KEY", gemini_cfg.get("api_key"))
    if gemini_api_key:
        gemini_cfg["api_key"] = gemini_api_key
    data["gemini"] = gemini_cfg

    refly_cfg = data.get("refly", {})
    refly_enabled = os.getenv("REFLY_ENABLED", None)
    if refly_enabled is not None:
        refly_cfg["enabled"] = str(refly_enabled).strip().lower() in {"1", "true", "yes", "on"}
    refly_api_key = os.getenv("REFLY_API_KEY", refly_cfg.get("api_key", ""))
    if refly_api_key:
        refly_cfg["api_key"] = refly_api_key
    refly_base_url = os.getenv("REFLY_BASE_URL", refly_cfg.get("base_url", ""))
    if refly_base_url:
        refly_cfg["base_url"] = refly_base_url
    data["refly"] = refly_cfg

    react_enabled = os.getenv("USE_REACT_AGENT", None)
    if react_enabled is not None:
        data["use_react_agent"] = str(react_enabled).strip().lower() in {"1", "true", "yes", "on"}
    react_iters = os.getenv("REACT_MAX_ITERATIONS", None)
    if react_iters is not None:
        try:
            data["react_max_iterations"] = int(react_iters)
        except ValueError:
            pass
    react_temp = os.getenv("REACT_TEMPERATURE", None)
    if react_temp is not None:
        try:
            data["react_temperature"] = float(react_temp)
        except ValueError:
            pass
    orchestrator_enabled = os.getenv("USE_ORCHESTRATOR", None)
    if orchestrator_enabled is not None:
        data["use_orchestrator"] = str(orchestrator_enabled).strip().lower() in {"1", "true", "yes", "on"}

    settings = Settings(**data)

    # 解析相对路径
    base_dir = config_path.parent.parent if config_path.parent.name == "config" else config_path.parent
    resolved_review = settings.review.resolve_paths(base_dir)

    return Settings(
        llm=settings.llm,
        review=resolved_review,
        gemini=settings.gemini,
        refly=settings.refly,
        use_react_agent=settings.use_react_agent,
        react_max_iterations=settings.react_max_iterations,
        react_temperature=settings.react_temperature,
        use_orchestrator=settings.use_orchestrator,
    )


# 全局配置实例（延迟加载）
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取全局配置实例"""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings
