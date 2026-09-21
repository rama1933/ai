import json
from contextlib import nullcontext

import httpx
import pytest

from agent import orchestrator, registry
from schemas import SourceRef

_dumps = json.dumps


def _reply(content: str = "", tool_calls: list | None = None) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"message": message}


def _mock_ollama(monkeypatch, replies: list[dict]) -> list[dict]:
    """Queue up successive /api/chat responses; returns the list of sent payloads.

    Each queued response is served as one NDJSON line over a fake httpx.stream, so
    the generator's line splitting stays under test. (It patched httpx.post before
    the agent loop became a streaming generator; the transport is the only change.)
    """
    sent: list[dict] = []
    queue = list(replies)

    def fake_stream(method, url, json=None, timeout=None, **kwargs):
        sent.append(json)
        body = (_dumps(queue.pop(0)) + "\n").encode()
        return nullcontext(httpx.Response(200, content=body, request=httpx.Request(method, url)))

    monkeypatch.setattr(orchestrator.httpx, "stream", fake_stream)
    return sent


def _mock_ollama_chunks(monkeypatch, turns: list[list[dict]]) -> list[dict]:
    """Queue streaming turns; each turn is a list of chunk messages sent as NDJSON lines."""
    sent: list[dict] = []
    queue = list(turns)

    def fake_stream(method, url, json=None, timeout=None, **kwargs):
        sent.append(json)
        body = "".join(_dumps({"message": chunk}) + "\n" for chunk in queue.pop(0)).encode()
        return nullcontext(httpx.Response(200, content=body, request=httpx.Request(method, url)))

    monkeypatch.setattr(orchestrator.httpx, "stream", fake_stream)
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
        lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(
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
    assert payload["stream"] is True
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
        registry, "dispatch", lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(text="nothing")
    )

    result = orchestrator.run_agent(db=None, message="loop", history=[])

    assert "tidak dapat" in result.answer.lower() or "could not" in result.answer.lower()
    assert result.tool_used == "rag_search"


def test_tool_call_written_as_content_is_dispatched_not_leaked(monkeypatch):
    """VERIFIER PAYLOAD: llama3.2:3b put the tool call in message.content.

    Observed response body was the raw blob with tool_used null:
    {"answer":"{\\"name\\":\\"sql_query\\",\\"parameters\\":{...}}","tool_used":null,"sources":[]}
    """
    blob = '{"name":"sql_query","parameters":{"query":"SELECT 1"}}'
    _mock_ollama(monkeypatch, [_reply(content=blob), _reply(content="Ada 1 dokumen.")])
    dispatched: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: (
            dispatched.append((name, arguments)) or registry.ToolOutcome(text="[(1,)]")
        ),
    )

    result = orchestrator.run_agent(db=None, message="berapa dokumen ada?", history=[])

    assert dispatched == [("sql_query", {"query": "SELECT 1"})]
    assert result.answer == "Ada 1 dokumen."
    assert '"name"' not in result.answer
    assert result.tool_used == "sql_query"


def test_unknown_tool_blob_in_content_is_not_returned_as_answer(monkeypatch):
    """VERIFIER PAYLOAD: content '{"name":"function","parameters":{}}' returned verbatim."""
    _mock_ollama(
        monkeypatch,
        [_reply(content='{"name":"function","parameters":{}}'), _reply(content="Baik, ini jawaban biasa.")],
    )

    result = orchestrator.run_agent(db=None, message="halo", history=[])

    assert result.answer == "Baik, ini jawaban biasa."
    assert '"name"' not in result.answer
    assert result.tool_used is None


def test_chat_payload_pins_decoding_determinism(monkeypatch):
    sent = _mock_ollama(monkeypatch, [_reply(content="ok")])

    orchestrator.run_agent(db=None, message="halo", history=[])

    options = sent[0]["options"]
    assert options["temperature"] == 0.0
    assert "seed" in options


def test_tool_used_records_the_first_tool_of_a_multi_tool_turn(monkeypatch):
    _mock_ollama(
        monkeypatch,
        [
            _reply(
                tool_calls=[
                    {"function": {"name": "rag_search", "arguments": {"query": "a"}}},
                    {"function": {"name": "sql_query", "arguments": {"query": "SELECT 1"}}},
                ]
            ),
            _reply(content="Selesai."),
        ],
    )
    monkeypatch.setattr(registry, "dispatch", lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(text="ok"))

    result = orchestrator.run_agent(db=None, message="dua tool", history=[])

    assert result.answer == "Selesai."
    assert result.tool_used == "rag_search"


def test_ollama_error_raises_agent_error(monkeypatch):
    def fake_stream(method, url, json=None, timeout=None, **kwargs):
        return nullcontext(httpx.Response(500, text="boom", request=httpx.Request(method, url)))

    monkeypatch.setattr(orchestrator.httpx, "stream", fake_stream)

    with pytest.raises(orchestrator.AgentError):
        orchestrator.run_agent(db=None, message="halo", history=[])


def test_stream_plain_answer_yields_deltas_then_done(monkeypatch):
    _mock_ollama_chunks(
        monkeypatch,
        [[{"role": "assistant", "content": "Berdasar"}, {"role": "assistant", "content": " dokumen: 5 tahun."}]],
    )

    events = list(orchestrator.stream_agent(db=None, message="berapa retensi?", history=[]))

    deltas = [e["text"] for e in events if e["type"] == "delta"]
    assert "".join(deltas) == "Berdasar dokumen: 5 tahun."
    assert events[-1] == {
        "type": "done",
        "answer": "Berdasar dokumen: 5 tahun.",
        "tool_used": None,
        "sources": [],
    }


def test_stream_tool_turn_yields_tool_sources_then_deltas(monkeypatch):
    _mock_ollama_chunks(
        monkeypatch,
        [
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "rag_search", "arguments": {"query": "retensi"}}}],
                }
            ],
            [{"role": "assistant", "content": "Masa retensi"}, {"role": "assistant", "content": " 5 tahun."}],
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(
            text="[policy.pdf] retensi 5 tahun", sources=[SourceRef(filename="policy.pdf", score=0.9)]
        ),
    )

    events = list(orchestrator.stream_agent(db=None, message="berapa lama masa retensi?", history=[]))

    types = [e["type"] for e in events]
    assert types[0] == "tool"
    assert types.index("tool") < types.index("sources") < types.index("delta")
    assert events[1]["sources"][0].filename == "policy.pdf"
    done = events[-1]
    assert done["type"] == "done"
    assert done["answer"] == "Masa retensi 5 tahun."
    assert done["tool_used"] == "rag_search"
    assert done["sources"][0].filename == "policy.pdf"


def test_stream_tool_call_blob_is_never_streamed_as_text(monkeypatch):
    """The JSON-leak guard: a tool call written as prose must not flash as deltas."""
    blob = '{"name":"sql_query","parameters":{"query":"SELECT 1"}}'
    _mock_ollama_chunks(
        monkeypatch,
        [
            [{"role": "assistant", "content": blob[:6]}, {"role": "assistant", "content": blob[6:]}],
            [{"role": "assistant", "content": "Ada 1 dokumen."}],
        ],
    )
    dispatched: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: (
            dispatched.append((name, arguments)) or registry.ToolOutcome(text="[(1,)]")
        ),
    )

    events = list(orchestrator.stream_agent(db=None, message="berapa dokumen ada?", history=[]))

    deltas = "".join(e["text"] for e in events if e["type"] == "delta")
    assert deltas == "Ada 1 dokumen."  # not one character of the blob leaked
    assert dispatched == [("sql_query", {"query": "SELECT 1"})]
    assert events[-1]["answer"] == "Ada 1 dokumen."
    assert events[-1]["tool_used"] == "sql_query"


def test_stream_legitimate_json_answer_is_still_delivered(monkeypatch):
    """An answer that starts with '{' but is not a tool call must still reach the user."""
    _mock_ollama_chunks(monkeypatch, [[{"role": "assistant", "content": '{"hasil": "12 dokumen"}'}]])

    events = list(orchestrator.stream_agent(db=None, message="berapa?", history=[]))

    deltas = "".join(e["text"] for e in events if e["type"] == "delta")
    assert deltas == '{"hasil": "12 dokumen"}'
    assert events[-1]["answer"] == '{"hasil": "12 dokumen"}'
    assert events[-1]["tool_used"] is None


def test_stream_exhausted_loop_yields_give_up_done(monkeypatch):
    loop = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "rag_search", "arguments": {"query": "x"}}}],
        }
    ]
    _mock_ollama_chunks(monkeypatch, [loop] * 10)
    monkeypatch.setattr(
        registry, "dispatch", lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(text="nothing")
    )

    events = list(orchestrator.stream_agent(db=None, message="loop", history=[]))

    done = events[-1]
    assert done["type"] == "done"
    assert "tidak dapat" in done["answer"].lower() or "could not" in done["answer"].lower()
    assert done["tool_used"] == "rag_search"


def test_stream_agent_threads_document_filenames_to_dispatch(monkeypatch):
    tool_turn = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "rag_search", "arguments": {"query": "retensi"}}}],
        }
    ]
    answer_turn = [{"role": "assistant", "content": "selesai."}]
    _mock_ollama_chunks(monkeypatch, [tool_turn, answer_turn])
    captured = {}

    def capture_dispatch(name, arguments, db, image_paths, document_filenames=None):
        captured["document_filenames"] = document_filenames
        return registry.ToolOutcome(text="ok")

    monkeypatch.setattr(registry, "dispatch", capture_dispatch)

    list(orchestrator.stream_agent(db=None, message="tanya", history=[], document_filenames=["abc-laporan.pdf"]))

    assert captured["document_filenames"] == ["abc-laporan.pdf"]


def test_system_prompt_pins_the_context_only_guardrail():
    """The anti-off-context instruction is load-bearing against hallucinated
    summaries; if someone trims it, this fails instead of the users."""
    assert "HANYA berdasarkan isi blok UNTRUSTED_DATA" in orchestrator.SYSTEM_PROMPT
    assert "jangan membuat ringkasan umum" in orchestrator.SYSTEM_PROMPT
