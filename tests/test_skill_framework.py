import pytest
from pydantic import BaseModel

from contract_review.skills.dispatcher import LocalSkillExecutor, SkillDispatcher
from contract_review.skills.schema import SkillBackend, SkillRegistration


class EchoInput(BaseModel):
    message: str


class EchoOutput(BaseModel):
    echo: str


async def echo_handler(input_data: EchoInput) -> EchoOutput:
    return EchoOutput(echo=f"ECHO: {input_data.message}")


class TestSkillDispatcher:
    def test_register_local_skill(self):
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
        assert "echo" in dispatcher.skill_ids

    @pytest.mark.asyncio
    async def test_call_local_skill(self):
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
        dispatcher = SkillDispatcher()
        with pytest.raises(ValueError, match="未注册"):
            await dispatcher.call("nonexistent", EchoInput(message="test"))

    def test_register_refly_without_client(self):
        dispatcher = SkillDispatcher()
        with pytest.raises(ValueError, match="refly_client"):
            dispatcher.register(
                SkillRegistration(
                    skill_id="test_refly",
                    name="Test",
                    input_schema=EchoInput,
                    output_schema=EchoOutput,
                    backend=SkillBackend.REFLY,
                    refly_workflow_id="wf_123",
                )
            )

    def test_register_local_without_handler(self):
        dispatcher = SkillDispatcher()
        with pytest.raises(ValueError, match="local_handler"):
            dispatcher.register(
                SkillRegistration(
                    skill_id="test_local",
                    name="Test",
                    input_schema=EchoInput,
                    output_schema=EchoOutput,
                    backend=SkillBackend.LOCAL,
                )
            )
