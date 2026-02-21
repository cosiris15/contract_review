# SPEC-1: Skill 基础框架

> 优先级：最高（其他 Spec 依赖此框架）
> 预计新建文件：3 个 | 修改文件：1 个
> 参考：GEN3_GAP_ANALYSIS.md 第 8 章

---

## 1. 目标

构建 Skill 统一调度框架，支持双后端（Refly 远程 / 本地 Python），使 Orchestrator 通过单一接口调用任意 Skill，无需关心底层实现。

## 2. 需要创建的文件

### 2.1 `backend/src/contract_review/skills/__init__.py`

空文件，标记 skills 为 Python 包。

### 2.2 `backend/src/contract_review/skills/schema.py`

Skill 注册与调度的核心类型定义。

```python
"""
Skill 框架核心类型定义

定义 SkillBackend、SkillRegistration、SkillExecutor 等基础类型，
为双后端（Refly / Local）调度提供统一抽象。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Type

from pydantic import BaseModel, Field


class SkillBackend(str, Enum):
    """Skill 执行后端"""
    REFLY = "refly"     # 远程 Refly Workflow
    LOCAL = "local"     # 本地 Python 函数


class SkillRegistration(BaseModel):
    """
    Skill 注册信息（与执行后端无关）

    每个 Skill 通过此模型注册到 SkillDispatcher。
    Orchestrator 只需知道 skill_id 即可调用。
    """
    skill_id: str                           # 全局唯一标识，如 "get_clause_context"
    name: str                               # 显示名称，如 "条款上下文获取"
    description: str = ""                   # 功能描述
    input_schema: Type[BaseModel]           # 输入 Pydantic 模型类
    output_schema: Type[BaseModel]          # 输出 Pydantic 模型类
    backend: SkillBackend                   # 执行后端

    # Refly 后端专用（backend=REFLY 时必填）
    refly_workflow_id: Optional[str] = None

    # 本地后端专用（backend=LOCAL 时必填）
    # 格式: "module.path.function_name"，如 "skills.local.clause_context.get_clause_context"
    local_handler: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True


class SkillExecutor(ABC):
    """
    Skill 执行器抽象基类

    所有执行器（Refly / Local）必须实现此接口。
    """
    @abstractmethod
    async def execute(self, input_data: BaseModel) -> BaseModel:
        """执行 Skill，返回结构化结果"""
        ...


class SkillResult(BaseModel):
    """Skill 执行结果的通用包装"""
    skill_id: str
    success: bool = True
    data: Optional[Any] = None              # 实际结果（Pydantic 模型序列化后）
    error: Optional[str] = None             # 错误信息
    execution_time_ms: Optional[int] = None # 执行耗时（毫秒）
```

### 2.3 `backend/src/contract_review/skills/dispatcher.py`

Skill 统一调度器 — Orchestrator 的唯一调用入口。

```python
"""
Skill 统一调度器

SkillDispatcher 是 Orchestrator 调用 Skill 的唯一入口。
它根据 SkillRegistration 的 backend 字段自动选择执行器。
"""

from __future__ import annotations

import importlib
import logging
import time
from typing import Dict, List, Optional

from pydantic import BaseModel

from .schema import (
    SkillBackend,
    SkillExecutor,
    SkillRegistration,
    SkillResult,
)

logger = logging.getLogger(__name__)


class LocalSkillExecutor(SkillExecutor):
    """
    本地 Python 执行器

    通过动态导入调用本地 Python 异步函数。
    handler_fn 签名: async def handler(input_data: SomeInput) -> SomeOutput
    """

    def __init__(self, handler_fn):
        self.handler_fn = handler_fn

    async def execute(self, input_data: BaseModel) -> BaseModel:
        return await self.handler_fn(input_data)


class ReflySkillExecutor(SkillExecutor):
    """
    远程 Refly 执行器

    通过 ReflyClient 发起异步 HTTP 调用，轮询结果。
    依赖 ReflyClient 实例（在 Spec-1 中先用 stub，后续对接真实 API）。
    """

    def __init__(self, refly_client, workflow_id: str):
        self.refly_client = refly_client
        self.workflow_id = workflow_id

    async def execute(self, input_data: BaseModel) -> BaseModel:
        task_id = await self.refly_client.call_workflow(
            self.workflow_id, input_data.model_dump()
        )
        return await self.refly_client.poll_result(task_id)


def _import_handler(handler_path: str):
    """
    动态导入本地 handler 函数

    Args:
        handler_path: 点分路径，如 "contract_review.skills.local.clause_context.get_clause_context"

    Returns:
        可调用的异步函数
    """
    module_path, func_name = handler_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    handler = getattr(module, func_name)
    if not callable(handler):
        raise TypeError(f"{handler_path} 不是可调用对象")
    return handler


class SkillDispatcher:
    """
    Skill 统一调度器

    使用方式:
        dispatcher = SkillDispatcher()
        dispatcher.register(some_skill_registration)
        result = await dispatcher.call("skill_id", input_data)

    Orchestrator 不需要知道后端是 Refly 还是本地。
    """

    def __init__(self, refly_client=None):
        """
        Args:
            refly_client: 可选的 Refly API 客户端实例。
                          注册 Refly 类型 Skill 时必须提供。
        """
        self.refly_client = refly_client
        self._executors: Dict[str, SkillExecutor] = {}
        self._registrations: Dict[str, SkillRegistration] = {}

    def register(self, skill: SkillRegistration) -> None:
        """
        注册一个 Skill

        根据 backend 类型创建对应的执行器并缓存。

        Raises:
            AssertionError: 缺少必要的配置字段
        """
        if skill.backend == SkillBackend.REFLY:
            if not skill.refly_workflow_id:
                raise ValueError(
                    f"Refly Skill '{skill.skill_id}' 缺少 refly_workflow_id"
                )
            if not self.refly_client:
                raise ValueError(
                    f"注册 Refly Skill '{skill.skill_id}' 时 refly_client 未提供"
                )
            self._executors[skill.skill_id] = ReflySkillExecutor(
                self.refly_client, skill.refly_workflow_id
            )

        elif skill.backend == SkillBackend.LOCAL:
            if not skill.local_handler:
                raise ValueError(
                    f"Local Skill '{skill.skill_id}' 缺少 local_handler"
                )
            handler = _import_handler(skill.local_handler)
            self._executors[skill.skill_id] = LocalSkillExecutor(handler)

        self._registrations[skill.skill_id] = skill
        logger.info(
            f"Skill 已注册: {skill.skill_id} ({skill.name}) "
            f"[backend={skill.backend.value}]"
        )

    def register_batch(self, skills: List[SkillRegistration]) -> None:
        """批量注册 Skills"""
        for skill in skills:
            self.register(skill)

    async def call(self, skill_id: str, input_data: BaseModel) -> SkillResult:
        """
        统一调用接口

        Args:
            skill_id: 已注册的 Skill ID
            input_data: 符合该 Skill input_schema 的 Pydantic 模型实例

        Returns:
            SkillResult 包装的执行结果

        Raises:
            ValueError: skill_id 未注册
        """
        executor = self._executors.get(skill_id)
        if not executor:
            raise ValueError(f"Skill '{skill_id}' 未注册")

        start = time.monotonic()
        try:
            result = await executor.execute(input_data)
            elapsed = int((time.monotonic() - start) * 1000)
            logger.info(f"Skill '{skill_id}' 执行成功 ({elapsed}ms)")
            return SkillResult(
                skill_id=skill_id,
                success=True,
                data=result.model_dump() if isinstance(result, BaseModel) else result,
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.error(f"Skill '{skill_id}' 执行失败 ({elapsed}ms): {e}")
            return SkillResult(
                skill_id=skill_id,
                success=False,
                error=str(e),
                execution_time_ms=elapsed,
            )

    def get_registration(self, skill_id: str) -> Optional[SkillRegistration]:
        """获取 Skill 注册信息"""
        return self._registrations.get(skill_id)

    def list_skills(self) -> List[SkillRegistration]:
        """列出所有已注册的 Skills"""
        return list(self._registrations.values())

    @property
    def skill_ids(self) -> List[str]:
        """所有已注册的 Skill ID"""
        return list(self._registrations.keys())
```

### 2.4 `backend/src/contract_review/skills/refly_client.py`

Refly API 客户端（初始版本为 stub，后续对接真实 API）。

```python
"""
Refly API 客户端

封装与 Refly.ai 平台的 HTTP 通信：发起 Workflow、轮询结果、解析响应。
初始版本为 stub 实现，后续根据 Refly API 文档替换为真实调用。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ReflyClientConfig(BaseModel):
    """Refly 客户端配置"""
    base_url: str = "https://api.refly.ai"
    api_key: str = ""
    timeout: int = 120          # 单次请求超时（秒）
    poll_interval: int = 2      # 轮询间隔（秒）
    max_poll_attempts: int = 60 # 最大轮询次数


class ReflyClient:
    """
    Refly API 客户端

    当前为 stub 实现。真实实现需要:
    1. call_workflow(): POST /api/workflows/{id}/run
    2. poll_result(): GET /api/tasks/{task_id}/status
    3. 处理认证、超时、重试
    """

    def __init__(self, config: ReflyClientConfig):
        self.config = config
        self._session = None  # 后续用 httpx.AsyncClient

    async def call_workflow(
        self, workflow_id: str, input_data: Dict[str, Any]
    ) -> str:
        """
        发起 Workflow 异步调用

        Args:
            workflow_id: Refly Workflow ID
            input_data: 输入数据（已序列化为 dict）

        Returns:
            task_id: 异步任务 ID，用于后续轮询
        """
        # TODO: 替换为真实 HTTP 调用
        # POST {base_url}/api/workflows/{workflow_id}/run
        # Headers: Authorization: Bearer {api_key}
        # Body: {"input": input_data}
        # Response: {"task_id": "xxx"}
        logger.warning(
            f"[STUB] ReflyClient.call_workflow({workflow_id}) — "
            f"返回模拟 task_id"
        )
        return f"stub_task_{workflow_id}"

    async def poll_result(
        self, task_id: str, timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        轮询任务结果

        Args:
            task_id: 异步任务 ID
            timeout: 超时秒数，None 使用默认配置

        Returns:
            任务结果数据（dict）

        Raises:
            TimeoutError: 超过最大轮询次数
        """
        # TODO: 替换为真实轮询逻辑
        # GET {base_url}/api/tasks/{task_id}/status
        # 循环直到 status == "completed" 或 "failed"
        logger.warning(
            f"[STUB] ReflyClient.poll_result({task_id}) — "
            f"返回空结果"
        )
        return {"status": "completed", "result": {}}

    async def close(self):
        """关闭 HTTP 连接"""
        if self._session:
            await self._session.aclose()
            self._session = None
```

## 3. 需要修改的文件

### 3.1 `backend/src/contract_review/config.py`

在 `Settings` 中新增 Refly 配置段。

```python
# === 新增内容 ===

class ReflySettings(BaseModel):
    """Refly API 配置"""
    base_url: str = "https://api.refly.ai"
    api_key: str = ""
    timeout: int = 120
    poll_interval: int = 2
    max_poll_attempts: int = 60


# === 修改 Settings 类 ===

class Settings(BaseModel):
    """全局配置"""
    llm: LLMSettings
    review: ReviewSettings = Field(default_factory=ReviewSettings)
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    refly: ReflySettings = Field(default_factory=ReflySettings)  # 新增


# === 修改 load_settings() ===
# 在 Gemini 环境变量处理之后，新增:

    refly_cfg = data.get("refly", {})
    refly_api_key = os.getenv("REFLY_API_KEY", refly_cfg.get("api_key", ""))
    if refly_api_key:
        refly_cfg["api_key"] = refly_api_key
    refly_base_url = os.getenv("REFLY_BASE_URL", refly_cfg.get("base_url", ""))
    if refly_base_url:
        refly_cfg["base_url"] = refly_base_url
    data["refly"] = refly_cfg
```

## 4. 目录结构（完成后）

```
backend/src/contract_review/
├── skills/
│   ├── __init__.py              # 新建：包标记
│   ├── schema.py                # 新建：核心类型
│   ├── dispatcher.py            # 新建：统一调度器
│   └── refly_client.py          # 新建：Refly API 客户端 (stub)
├── config.py                    # 修改：新增 ReflySettings
└── ... (其他文件不动)
```

## 5. 验收标准

1. `SkillDispatcher` 可以注册一个 `backend=LOCAL` 的 Skill，调用后返回 `SkillResult(success=True)`
2. `SkillDispatcher` 可以注册一个 `backend=REFLY` 的 Skill（使用 stub ReflyClient），调用后返回 `SkillResult(success=True)`
3. 注册时缺少必要字段（如 LOCAL 缺 handler、REFLY 缺 workflow_id）抛出 `ValueError`
4. `_import_handler()` 能正确动态导入本地函数
5. `config.py` 中 `Settings` 能正确加载 `refly` 配置段，支持环境变量覆盖
6. 所有新代码通过 `python -m py_compile` 语法检查

## 6. 验证用测试代码

```python
# tests/test_skill_framework.py
import asyncio
import pytest
from pydantic import BaseModel
from contract_review.skills.schema import (
    SkillBackend, SkillRegistration, SkillResult
)
from contract_review.skills.dispatcher import SkillDispatcher, LocalSkillExecutor


# 测试用 Skill 输入输出
class EchoInput(BaseModel):
    message: str

class EchoOutput(BaseModel):
    echo: str

# 测试用本地 handler
async def echo_handler(input_data: EchoInput) -> EchoOutput:
    return EchoOutput(echo=f"ECHO: {input_data.message}")


class TestSkillDispatcher:
    def test_register_local_skill(self):
        """测试注册本地 Skill"""
        dispatcher = SkillDispatcher()
        # 直接注入 handler 而非动态导入（测试用）
        executor = LocalSkillExecutor(echo_handler)
        dispatcher._executors["echo"] = executor
        dispatcher._registrations["echo"] = SkillRegistration(
            skill_id="echo",
            name="Echo",
            input_schema=EchoInput,
            output_schema=EchoOutput,
            backend=SkillBackend.LOCAL,
            local_handler="dummy.path",
        )
        assert "echo" in dispatcher.skill_ids

    @pytest.mark.asyncio
    async def test_call_local_skill(self):
        """测试调用本地 Skill 并获取结果"""
        dispatcher = SkillDispatcher()
        executor = LocalSkillExecutor(echo_handler)
        dispatcher._executors["echo"] = executor
        dispatcher._registrations["echo"] = SkillRegistration(
            skill_id="echo",
            name="Echo",
            input_schema=EchoInput,
            output_schema=EchoOutput,
            backend=SkillBackend.LOCAL,
            local_handler="dummy.path",
        )

        result = await dispatcher.call("echo", EchoInput(message="hello"))
        assert result.success is True
        assert result.data["echo"] == "ECHO: hello"
        assert result.execution_time_ms is not None

    @pytest.mark.asyncio
    async def test_call_unregistered_skill(self):
        """测试调用未注册的 Skill 抛出 ValueError"""
        dispatcher = SkillDispatcher()
        with pytest.raises(ValueError, match="未注册"):
            await dispatcher.call("nonexistent", EchoInput(message="test"))

    def test_register_refly_without_client(self):
        """测试注册 Refly Skill 但未提供 client 时报错"""
        dispatcher = SkillDispatcher()  # 无 refly_client
        with pytest.raises(ValueError, match="refly_client"):
            dispatcher.register(SkillRegistration(
                skill_id="test_refly",
                name="Test",
                input_schema=EchoInput,
                output_schema=EchoOutput,
                backend=SkillBackend.REFLY,
                refly_workflow_id="wf_123",
            ))

    def test_register_local_without_handler(self):
        """测试注册 Local Skill 但未提供 handler 时报错"""
        dispatcher = SkillDispatcher()
        with pytest.raises(ValueError, match="local_handler"):
            dispatcher.register(SkillRegistration(
                skill_id="test_local",
                name="Test",
                input_schema=EchoInput,
                output_schema=EchoOutput,
                backend=SkillBackend.LOCAL,
                # 缺少 local_handler
            ))
```

## 7. 注意事项

- `SkillRegistration.input_schema` 和 `output_schema` 存储的是 Pydantic 模型**类**（`Type[BaseModel]`），不是实例。需要 `arbitrary_types_allowed = True`
- `ReflyClient` 当前是 stub，不要在此阶段尝试对接真实 API
- `_import_handler` 的路径是相对于 Python 包的点分路径，不是文件系统路径
- 不要修改任何现有的 `review_engine.py` 或 `interactive_engine.py`，本 Spec 只建基础设施
