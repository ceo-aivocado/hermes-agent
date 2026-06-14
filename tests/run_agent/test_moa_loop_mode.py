from types import SimpleNamespace
from unittest.mock import MagicMock

from run_agent import AIAgent


def _response(content="done", *, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice], usage=None, model="fake-model")


def test_moa_mode_aggregates_reference_models_before_each_agent_iteration(monkeypatch):
    agent = AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        model="anthropic/claude-opus-4.8",
        provider="openrouter",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        enabled_toolsets=[],
        max_iterations=1,
    )
    agent.client = MagicMock()
    agent.client.chat.completions.create.return_value = _response("final")

    aggregate = MagicMock(return_value="reference synthesis")
    monkeypatch.setattr("agent.moa_loop.aggregate_moa_context", aggregate)

    result = agent.run_conversation(
        "solve this",
        moa_config={
            "reference_models": [
                {"provider": "openai-codex", "model": "gpt-5.5"},
                {"provider": "openrouter", "model": "deepseek/deepseek-v4-pro"},
            ],
            "aggregator": {"provider": "openrouter", "model": "anthropic/claude-opus-4.8"},
        },
    )

    assert result["final_response"] == "final"
    aggregate.assert_called_once()
    kwargs = aggregate.call_args.kwargs
    assert kwargs["user_prompt"] == "solve this"
    assert [m["model"] for m in kwargs["reference_models"]] == [
        "gpt-5.5",
        "deepseek/deepseek-v4-pro",
    ]
    sent_messages = agent.client.chat.completions.create.call_args.kwargs["messages"]
    sent_text = "\n".join(str(m.get("content", "")) for m in sent_messages)
    assert "reference synthesis" in sent_text
