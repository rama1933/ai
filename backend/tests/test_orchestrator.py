import httpx
import pytest

from agent import orchestrator, registry
from schemas import SourceRef


def _reply(content: str = "", tool_calls: list | None = None) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"message": message}


def _mock_ollama(monkeypatch, replies: list[dict]) -> list[dict]:
    """Queue up successive /api/chat responses; returns the list of sent payloads."""
    sent: list[dict] = []
    queue = list(replies)

    def fake_post(url, json, timeout):
        sent.append(json)
        return httpx.Response(200, json=queue.pop(0), request=httpx.Request("POST", url))

    monkeypatch.setattr(orchestrator.httpx, "post", fake_post)
    return sent


def test_direct_answer_without_tool_call(monkeypatch):
    _mock_ollama(monkeypatch, [_reply(content="Halo, ada yang bisa saya bantu?")])

    result = orchestrator.run_agent(db=None, message="halo", history=[])

    assert result.answer == "Halo, ada yang bisa saya bantu?"
    assert result.tool_used is None
    assert result.sources == []


def test_tool_call_result_is_fed_back_and_answer_returned(monkeypatch):
    sent = _mock_ollama(
        monkeypatch,
        [
            _reply(tool_calls=[{"function": {"name": "rag_search", "arguments": {"query": "retensi"}}}]),
            _reply(content="Masa retensi dokumen adalah 5 tahun."),
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_path: registry.ToolOutcome(
            text="[policy.pdf] retensi 5 tahun", sources=[SourceRef(filename="policy.pdf", score=0.9)]
        ),
    )

    result = orchestrator.run_agent(db=None, message="berapa lama masa retensi?", history=[])

    assert result.answer == "Masa retensi dokumen adalah 5 tahun."
    assert result.tool_used == "rag_search"
    assert result.sources[0].filename == "policy.pdf"
    # second request must carry the tool result back to the model
    second_messages = sent[1]["messages"]
    assert second_messages[-1]["role"] == "tool"
    assert "retensi 5 tahun" in second_messages[-1]["content"]


def test_system_prompt_and_tools_are_sent_on_every_request(monkeypatch):
    sent = _mock_ollama(monkeypatch, [_reply(content="ok")])
    orchestrator.run_agent(db=None, message="halo", history=[])

    payload = sent[0]
    assert payload["messages"][0]["role"] == "system"
    assert payload["stream"] is False
    assert {t["function"]["name"] for t in payload["tools"]} == {"rag_search", "image_ocr", "sql_query"}


def test_history_is_included_in_the_prompt(monkeypatch):
    sent = _mock_ollama(monkeypatch, [_reply(content="ok")])
    orchestrator.run_agent(
        db=None, message="lanjutkan", history=[{"role": "user", "content": "halo"}, {"role": "assistant", "content": "hai"}]
    )

    roles = [m["role"] for m in sent[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_iteration_cap_stops_a_tool_call_loop(monkeypatch):
    loop_reply = _reply(tool_calls=[{"function": {"name": "rag_search", "arguments": {"query": "x"}}}])
    _mock_ollama(monkeypatch, [loop_reply] * 10)
    monkeypatch.setattr(
        registry, "dispatch", lambda name, arguments, db, image_path: registry.ToolOutcome(text="nothing")
    )

    result = orchestrator.run_agent(db=None, message="loop", history=[])

    assert "tidak dapat" in result.answer.lower() or "could not" in result.answer.lower()
    assert result.tool_used == "rag_search"


def test_ollama_error_raises_agent_error(monkeypatch):
    def fake_post(url, json, timeout):
        return httpx.Response(500, text="boom", request=httpx.Request("POST", url))

    monkeypatch.setattr(orchestrator.httpx, "post", fake_post)

    with pytest.raises(orchestrator.AgentError):
        orchestrator.run_agent(db=None, message="halo", history=[])
