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


def test_system_prompt_and_tools_are_sent_for_a_knowledge_question(monkeypatch):
    sent = _mock_ollama(
        monkeypatch,
        [
            _reply(tool_calls=[{"function": {"name": "rag_search", "arguments": {"query": "retensi"}}}]),
            _reply(content="ok"),
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(text="retensi 5 tahun"),
    )

    orchestrator.run_agent(db=None, message="berapa retensi?", history=[])

    payload = sent[0]
    assert payload["messages"][0]["role"] == "system"
    assert payload["stream"] is True
    assert {t["function"]["name"] for t in payload["tools"]} == {"rag_search", "image_ocr", "sql_query"}


def test_no_tools_are_offered_for_small_talk(monkeypatch):
    """This is what makes the spec matrix's "a greeting answers with tool_used None"
    deterministic. Offering the schemas was not enough: llama3.2:3b called rag_search on
    "Halo, perkenalkan dirimu dalam satu kalimat." anyway and answered out of the chunks,
    which failed test_e2e_matrix.py::test_agent_001 on the live model."""
    sent = _mock_ollama(monkeypatch, [_reply(content="Halo, ada yang bisa saya bantu?")])

    orchestrator.run_agent(db=None, message="Halo, perkenalkan dirimu dalam satu kalimat.", history=[])

    assert "tools" not in sent[0]


def test_history_is_included_in_the_prompt(monkeypatch):
    """The message is a greeting only because the grounding gate refuses, and retries,
    an ungrounded reply to a knowledge question -- this test is about the layout of the
    window, and one request is all it needs to assert it."""
    sent = _mock_ollama(monkeypatch, [_reply(content="ok")])
    orchestrator.run_agent(
        db=None, message="halo", history=[{"role": "user", "content": "halo"}, {"role": "assistant", "content": "hai"}]
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
                    {"function": {"name": "rag_search", "arguments": {"query": "retensi"}}},
                    {"function": {"name": "sql_query", "arguments": {"query": "SELECT 1"}}},
                ]
            ),
            # The answer traces to what rag_search returned, because a turn that read
            # retrieved prose is checked against it -- a bare "Selesai." is refused.
            _reply(content="retensi dokumen adalah 5 tahun"),
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(
            text="[policy.txt] retensi dokumen adalah 5 tahun"
        ),
    )

    result = orchestrator.run_agent(db=None, message="dua tool", history=[])

    assert result.answer == "retensi dokumen adalah 5 tahun"
    assert result.tool_used == "rag_search"


def test_ollama_error_raises_agent_error(monkeypatch):
    def fake_stream(method, url, json=None, timeout=None, **kwargs):
        return nullcontext(httpx.Response(500, text="boom", request=httpx.Request(method, url)))

    monkeypatch.setattr(orchestrator.httpx, "stream", fake_stream)

    with pytest.raises(orchestrator.AgentError):
        orchestrator.run_agent(db=None, message="halo", history=[])


def test_stream_small_talk_yields_deltas_then_done(monkeypatch):
    """Small talk is the only lane whose text streams as it is written. Every other turn
    has to be whole before anything is drawn, because the answer is checked as a whole
    (see test_a_grounded_answer_is_released_only_by_done). This is also the lane that
    still exercises _accumulate's holding buffer end to end."""
    _mock_ollama_chunks(
        monkeypatch,
        [[{"role": "assistant", "content": "Halo"}, {"role": "assistant", "content": ", ada yang bisa saya bantu?"}]],
    )

    events = list(orchestrator.stream_agent(db=None, message="halo", history=[]))

    deltas = [e["text"] for e in events if e["type"] == "delta"]
    assert "".join(deltas) == "Halo, ada yang bisa saya bantu?"
    assert events[-1] == {
        "type": "done",
        "answer": "Halo, ada yang bisa saya bantu?",
        "tool_used": None,
        "sources": [],
    }


def test_a_grounded_answer_is_released_only_by_done(monkeypatch):
    """The cost of the support check, pinned so it is a decision and not an accident.

    The answer is correct and is delivered -- but it arrives in `done` rather than as
    deltas, because the check that keeps a fabricated answer off the screen needs the
    whole answer to run. Streaming it first would mean the client had already painted
    text we might have to disown, and the abort path would have persisted it.
    """
    _mock_ollama_chunks(
        monkeypatch,
        [
            [{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "rag_search", "arguments": {"query": "retensi"}}}]}],
            [{"role": "assistant", "content": "retensi dokumen"}, {"role": "assistant", "content": " adalah 5 tahun."}],
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(
            text="[policy.txt] retensi dokumen adalah 5 tahun", sources=[SourceRef(filename="policy.txt", score=0.9)]
        ),
    )

    events = list(orchestrator.stream_agent(db=None, message="berapa retensi?", history=[]))

    assert [e["type"] for e in events] == ["tool", "sources", "done"]
    assert events[-1]["answer"] == "retensi dokumen adalah 5 tahun."
    assert events[-1]["tool_used"] == "rag_search"
    assert events[-1]["sources"][0].filename == "policy.txt"


def test_stream_tool_call_blob_is_never_streamed_as_text(monkeypatch):
    """The JSON-leak guard: a tool call written as prose must not flash as deltas.

    Driven on the small-talk lane, which is the lane that actually streams -- on any
    other turn the text is withheld until the answer is approved, so the guard would
    hold the blob for a reason that had nothing to do with blob detection.
    """
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

    events = list(orchestrator.stream_agent(db=None, message="halo", history=[]))

    deltas = "".join(e["text"] for e in events if e["type"] == "delta")
    assert deltas == "Ada 1 dokumen."  # not one character of the blob leaked
    assert dispatched == [("sql_query", {"query": "SELECT 1"})]
    assert events[-1]["answer"] == "Ada 1 dokumen."
    assert events[-1]["tool_used"] == "sql_query"


def test_stream_legitimate_json_answer_is_still_delivered(monkeypatch):
    """An answer that starts with '{' but is not a tool call must still reach the user.

    The point is that the JSON-leak guard, which holds anything starting with '{' until
    it is sure, releases it again when it turns out to be prose rather than a tool-call
    blob -- the `unsent` flush. Driven on the small-talk lane so the flush is actually
    exercised: on any other turn the text would be withheld for the gate's own reasons
    and the assertion would pass without testing the guard at all.
    """
    _mock_ollama_chunks(monkeypatch, [[{"role": "assistant", "content": '{"hasil": "12 dokumen"}'}]])

    events = list(orchestrator.stream_agent(db=None, message="halo", history=[]))

    deltas = "".join(e["text"] for e in events if e["type"] == "delta")
    assert deltas == '{"hasil": "12 dokumen"}'
    assert events[-1]["answer"] == '{"hasil": "12 dokumen"}'


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
    assert "jangan meringkas" in orchestrator.SYSTEM_PROMPT and "tidak ditemukan" in orchestrator.SYSTEM_PROMPT


def test_system_prompt_requires_a_retrieval_for_general_questions():
    """The old prompt said to use a tool ONLY when the question mentioned a document,
    data, an image or a file -- which is exactly what told llama3.2:3b to answer
    "Apa ibu kota Kanada?" out of its weights."""
    # Whitespace-collapsed and lowercased before matching: the guard is about the words,
    # not the case or where the source happens to wrap. Two earlier drafts of this
    # assertion failed on exactly that -- a capital "Jangan" and then a newline inside
    # the phrase, neither of which is the thing being protected.
    prompt = " ".join(orchestrator.SYSTEM_PROMPT.lower().split())
    assert "jangan pernah menjawab dari pengetahuanmu" in prompt
    assert "hanya jika pertanyaan user menyebut dokumen" not in prompt


# --- the grounding gate -------------------------------------------------------------
#
# Every case below was reproduced live against llama3.2:3b before the gate existed.
# The fast suite could not see any of them: the router tests replace stream_agent and
# the orchestrator tests only fed it synthetic turns, so 171 tests stayed green while
# the agent invented answers. These assert the absence of an answer, which nothing did.


def test_answer_from_the_models_own_weights_is_refused_not_delivered(monkeypatch):
    """Reproduced live: "Apa ibu kota Kanada?" -> "Ibu kota Kanada adalah Ottawa."
    with tool_used=rag_search and no sources at all -- nothing was ever read."""
    fabricated = "Ibu kota Kanada adalah Ottawa."
    _mock_ollama(monkeypatch, [_reply(content=fabricated), _reply(content=fabricated)])

    result = orchestrator.run_agent(db=None, message="Apa ibu kota Kanada?", history=[])

    assert "Ottawa" not in result.answer
    assert "tidak ditemukan" in result.answer.lower()
    assert result.tool_used is None
    assert result.sources == []


def test_the_fabricated_text_is_never_streamed_as_a_delta(monkeypatch):
    """A retraction at `done` would be too late: the client paints deltas as they
    arrive and the abort path persists them."""
    fabricated = "Ibu kota Kanada adalah Ottawa."
    _mock_ollama_chunks(
        monkeypatch,
        [
            [{"role": "assistant", "content": "Ibu kota Kanada"}],
            [{"role": "assistant", "content": fabricated}],
        ],
    )

    events = list(orchestrator.stream_agent(db=None, message="Apa ibu kota Kanada?", history=[]))

    deltas = "".join(e["text"] for e in events if e["type"] == "delta")
    assert "Ottawa" not in deltas, f"ungrounded text reached the client: {deltas!r}"
    assert events[-1]["answer"] == orchestrator.NOT_IN_KNOWLEDGE_ANSWER


def test_an_empty_retrieval_does_not_license_a_fabricated_answer(monkeypatch):
    """Reproduced live: the model DID call rag_search, got nothing back, and wrote
    "Presiden pertama Indonesia adalah Sukarno." anyway -- tool_used was set and the
    answer was still invented. So `tool_used is not None` cannot be the gate."""
    _mock_ollama(
        monkeypatch,
        [
            _reply(tool_calls=[{"function": {"name": "rag_search", "arguments": {"query": "presiden"}}}]),
            _reply(content="Presiden pertama Indonesia adalah Sukarno."),
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(
            text="No matching document found in the knowledge base. (tidak ditemukan)", grounded=False
        ),
    )

    events = list(orchestrator.stream_agent(db=None, message="Siapa presiden pertama Indonesia?", history=[]))
    done = events[-1]

    assert "Sukarno" not in done["answer"]
    assert "tidak ditemukan" in done["answer"].lower()
    assert done["tool_used"] == "rag_search"  # a refusal still reports what was tried
    assert done["sources"] == []  # and never shows chips beside it


def test_a_source_less_tool_result_still_licenses_the_answer(monkeypatch):
    """The other direction, and the reason the gate reads ToolOutcome.grounded instead
    of `sources`: sql_query never sets a source, and a statistics answer is real."""
    _mock_ollama(
        monkeypatch,
        [
            _reply(tool_calls=[{"function": {"name": "sql_query", "arguments": {"query": "SELECT 1"}}}]),
            _reply(content="Ada 12 dokumen."),
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(text="[{'count': 12}]"),
    )

    result = orchestrator.run_agent(db=None, message="Berapa jumlah baris pada tabel documents?", history=[])

    assert result.answer == "Ada 12 dokumen."
    assert result.tool_used == "sql_query"
    assert result.sources == []


def test_an_empty_sql_result_is_not_data(monkeypatch):
    """repr([]) is a success-shaped "[]"; without grounded=False the model narrates a
    figure it never read. The turn also shows the nudge in sequence: the first refusal
    to answer was ungrounded and rag_search had not been tried, so the model gets the
    search prompt before the refusal is final."""
    _mock_ollama(
        monkeypatch,
        [
            _reply(tool_calls=[{"function": {"name": "sql_query", "arguments": {"query": "SELECT 1"}}}]),
            _reply(content="Ada 99 dokumen."),
            _reply(tool_calls=[{"function": {"name": "rag_search", "arguments": {"query": "dokumen"}}}]),
            _reply(content="Ada 99 dokumen."),
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(text="[]", grounded=False),
    )

    result = orchestrator.run_agent(db=None, message="Berapa dokumen yang cocok?", history=[])

    assert "99" not in result.answer
    assert "tidak ditemukan" in result.answer.lower()
    assert result.tool_used == "sql_query"  # the first tool tried is still what is reported


@pytest.mark.parametrize(
    "message",
    [
        "halo",
        "Halo, perkenalkan dirimu dalam satu kalimat.",  # the e2e matrix's fixture
        "terima kasih",
        "siapa kamu?",
        "apa yang bisa kamu lakukan",
    ],
)
def test_small_talk_is_answered_without_a_retrieval(message):
    assert orchestrator._is_small_talk(message) is True


def test_a_supported_answer_is_told_apart_from_an_echo_of_the_question():
    """The case table behind SUPPORT_RATIO, because a fixture is not a calibration.

    The first version of this check counted every word of the answer against the
    passages, and the first version of the test below used a ONE-LINE title as the
    context. Both were wrong in the same direction: against a real decree paragraph --
    one that says "Republik Indonesia", as they all do -- the fabricated answer traced
    presiden/pertama/indonesia straight back into the boilerplate and scored 0.50,
    exactly on the bar, and shipped. Dropping the words the QUESTION already supplied
    is what removes that echo: the fabrication's one informing word is "soekarno", and
    it traces nowhere.
    """
    real_decree = (
        "[2026kb6306267.pdf] ... Peraturan Pemerintah Nomor 24 Tahun 1997 tentang Pendaftaran "
        "Tanah (Lembaran Negara Republik Indonesia Tahun 1997 Nomor 59). Presiden Republik "
        "Indonesia menetapkan peraturan ini."
    )
    policy = "[policy.txt] Seluruh dokumen keuangan disimpan selama 5 (lima) tahun sejak tanggal penerbitan."

    # (answer, context, question, expected)
    table = [
        ("Ir. Soekarno adalah presiden pertama Indonesia.", real_decree, "Siapa presiden pertama Indonesia?", False),
        ("Presiden pertama Indonesia adalah Ir. Soekarno.", real_decree, "Siapa presiden pertama Indonesia?", False),
        (
            "Presiden pertama Indonesia adalah Ir. Soekarno, presiden Republik Indonesia.",
            real_decree,
            "Siapa presiden pertama Indonesia?",
            False,
        ),
        ("Masa retensi dokumen keuangan adalah 5 (lima) tahun sejak tanggal penerbitan.", policy, "Berapa lama masa retensi dokumen keuangan?", True),
        # Framing words must not count against a correct answer.
        ("Berikut jawabannya: masa retensi dokumen keuangan adalah 5 (lima) tahun sejak tanggal penerbitan.", policy, "Berapa lama masa retensi dokumen keuangan?", True),
        ("12 hari.", policy, "Berapa hari cuti tahunan?", True),
        ("Ya.", policy, "Apakah dokumen ini berlaku?", True),
    ]

    for answer, context, question, expected in table:
        assert orchestrator._supported_by(answer, context, question=question) is expected, answer


def test_an_answer_retrieval_did_not_supply_is_refused(monkeypatch):
    """The case the gate alone cannot see, and the reason layer 2 exists.

    Reproduced live: this question retrieves four chunks of an unrelated decree at
    0.70-0.72 -- above the 0.6 floor, so a "did a tool return content?" gate licenses
    the turn -- and llama3.2:3b then answered "Ir. Soekarno adalah presiden pertama
    Indonesia." off its own weights, with the decree rendered as citation chips. The
    context here is a full decree paragraph rather than a title, so the answer's echo
    of the question has somewhere to land and the check is actually exercised.
    """
    _mock_ollama(
        monkeypatch,
        [
            _reply(tool_calls=[{"function": {"name": "rag_search", "arguments": {"query": "presiden"}}}]),
            _reply(content="Ir. Soekarno adalah presiden pertama Indonesia."),
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(
            text="[2026kb6306267.pdf] Peraturan Pemerintah Nomor 24 Tahun 1997 tentang Pendaftaran Tanah "
            "(Lembaran Negara Republik Indonesia Tahun 1997 Nomor 59). Presiden Republik Indonesia menetapkan.",
            sources=[SourceRef(filename="2026kb6306267.pdf", score=0.724)],
        ),
    )

    events = list(orchestrator.stream_agent(db=None, message="Siapa presiden pertama Indonesia?", history=[]))
    done = events[-1]

    assert "Soekarno" not in done["answer"]
    assert "tidak ditemukan" in done["answer"].lower()
    assert done["sources"] == [], "chips beside a refusal read as corroboration"
    assert "Soekarno" not in "".join(e["text"] for e in events if e["type"] == "delta")


def test_a_second_grounded_tool_does_not_disable_the_support_check(monkeypatch):
    """One grounded sql_query used to switch the check off for the whole turn, so a
    turn that ran both tools was waved through on the strength of the rows -- while the
    prose standing behind the answer was still the retrieval's. Measured live, this
    model misroutes document questions to sql_query often enough for that to matter."""
    _mock_ollama(
        monkeypatch,
        [
            _reply(
                tool_calls=[
                    {"function": {"name": "sql_query", "arguments": {"query": "SELECT 1"}}},
                    {"function": {"name": "rag_search", "arguments": {"query": "presiden"}}},
                ]
            ),
            _reply(content="Ir. Soekarno adalah presiden pertama Indonesia."),
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: (
            registry.ToolOutcome(text="[{'count': 617}]")
            if name == "sql_query"
            else registry.ToolOutcome(
                text="[2026kb6306267.pdf] Lembaran Negara Republik Indonesia Tahun 1997 Nomor 59.",
                sources=[SourceRef(filename="2026kb6306267.pdf", score=0.72)],
            )
        ),
    )

    done = list(orchestrator.stream_agent(db=None, message="Siapa presiden pertama Indonesia?", history=[]))[-1]

    assert "Soekarno" not in done["answer"]
    assert "tidak ditemukan" in done["answer"].lower()


def test_an_ocr_with_no_attached_image_is_not_grounding(monkeypatch):
    """The seventh grounded site. Its outcome text reads like a helpful sentence, so
    without grounded=False the turn counted as read and the answer went out."""
    _mock_ollama(
        monkeypatch,
        [
            _reply(tool_calls=[{"function": {"name": "image_ocr", "arguments": {}}}]),
            _reply(content="Ibu kota Kanada adalah Ottawa."),
            _reply(content="Ibu kota Kanada adalah Ottawa."),  # after the nudge
        ],
    )

    done = list(orchestrator.stream_agent(db=None, message="Apa ibu kota Kanada?", history=[]))[-1]

    assert "Ottawa" not in done["answer"]
    assert "tidak ditemukan" in done["answer"].lower()


def test_a_follow_up_that_reads_nothing_is_refused(monkeypatch):
    """A deliberate trade-off, pinned rather than left in prose.

    "lanjutkan" is not small talk and reads nothing, so it is nudged and then refused.
    Answering it from the conversation would mean trusting assistant rows in the history
    that this gate never approved; the cost is that a bare follow-up has to re-retrieve,
    which the nudge asks it to do and which succeeds whenever the corpus has anything.
    """
    _mock_ollama(monkeypatch, [_reply(content="Baik, lanjut."), _reply(content="Baik, lanjut.")])

    result = orchestrator.run_agent(db=None, message="lanjutkan", history=[])

    assert result.answer == orchestrator.NOT_IN_KNOWLEDGE_ANSWER


def test_an_answer_the_retrieval_did_supply_is_released(monkeypatch):
    """The other side of the same check, so it cannot be satisfied by refusing."""
    _mock_ollama(
        monkeypatch,
        [
            _reply(tool_calls=[{"function": {"name": "rag_search", "arguments": {"query": "retensi"}}}]),
            _reply(content="Masa retensi dokumen keuangan adalah 5 tahun sejak tanggal penerbitan."),
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(
            text="[policy.txt] Seluruh dokumen keuangan disimpan selama 5 (lima) tahun sejak tanggal penerbitan.",
            sources=[SourceRef(filename="policy.txt", score=0.73)],
        ),
    )

    events = list(orchestrator.stream_agent(db=None, message="Berapa lama masa retensi dokumen keuangan?", history=[]))

    assert "5 tahun" in events[-1]["answer"]


def test_a_short_answer_with_nothing_to_trace_is_not_refused(monkeypatch):
    """"12 hari" has one traceable word; a check that demanded a minimum word count
    would refuse a correct answer for being short."""
    _mock_ollama(
        monkeypatch,
        [
            _reply(tool_calls=[{"function": {"name": "rag_search", "arguments": {"query": "cuti"}}}]),
            _reply(content="12 hari."),
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None: registry.ToolOutcome(
            text="[policy.txt] Setiap karyawan tetap berhak atas cuti tahunan sebanyak 12 (dua belas) hari kerja."
        ),
    )

    result = orchestrator.run_agent(db=None, message="Berapa hari cuti tahunan?", history=[])

    assert result.answer == "12 hari."


@pytest.mark.parametrize(
    "message",
    [
        "Berapa lama masa retensi dokumen?",  # no greeting at all
        "halo, berapa lama masa retensi dokumen keuangan?",  # a greeting must not launder it
        "Apa ibu kota Kanada?",
        "halo 2026 apa kabar",  # a digit makes it a question, not a greeting
        "Jelaskan apa itu fotosintesis.",
        # A greeting phrase with a subject hanging off it is a question about the
        # subject. This used to pass on a leftover-word count and, because the lane is
        # also sent no tool schemas, was answered with no retrieval at all.
        "Apa kabar dokumen saya?",
        "apa kabar proyek kita?",
    ],
)
def test_a_knowledge_question_is_never_small_talk(message):
    assert orchestrator._is_small_talk(message) is False
