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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(
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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(text="retensi 5 tahun"),
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
        registry, "dispatch", lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(text="nothing")
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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: (
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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(
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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(
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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: (
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
        registry, "dispatch", lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(text="nothing")
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

    def capture_dispatch(name, arguments, db, image_paths, document_filenames=None, **_):
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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(
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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(text="[{'count': 12}]"),
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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(text="[]", grounded=False),
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
    tabalong = (
        "[Kabupaten_Tabalong.txt] Kabupaten Tabalong memiliki luas 3.767 km2 dan berpenduduk "
        "218.954 jiwa menurut sensus 2010."
    )
    receipt = "[receipt.png] TOKO MAJU JAYA Kopi Susu 25000 Roti Bakar 18000 TOTAL 43000"

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
        # MEASURED LIVE on Kabupaten_Tabalong.txt: the evidence spells its figures with
        # Indonesian separators and the model restated one with a decimal tail. The check
        # compared the answer's digits ("376700") against the raw evidence ("3.767"), so
        # it could never match, and a correct answer to "berikan gambaran tentang
        # kabupaten tabalong" was refused and replaced by "tidak ditemukan".
        (
            "Kabupaten Tabalong memiliki luas 3.767,00 km² dan berpenduduk 218.954 jiwa.",
            tabalong,
            "berikan gambaran tentang kabupaten tabalong",
            True,
        ),
        # The same answer with a figure nobody wrote is still a fabrication: every word
        # traces, so only the numeral can catch it, and it does.
        (
            "Kabupaten Tabalong memiliki luas 3.767,00 km² dan berpenduduk 999.999 jiwa.",
            tabalong,
            "berikan gambaran tentang kabupaten tabalong",
            False,
        ),
        # The figure nobody wrote, one digit away from one somebody did: reading a token
        # in both of its spellings glues "1.500.000,00" into "150000000" and lets this
        # through, which is why there is one spelling per token and not two.
        (
            "Harga tanah adalah Rp 150.000.000,00 per meter persegi.",
            "[harga.txt] Harga tanah adalah Rp 1.500.000,00 per meter persegi.",
            "berapa harga tanah?",
            False,
        ),
        # The corpus mixes conventions: the Wikipedia dumps carry English-style figures,
        # where the comma groups and the dot is not a grouping separator at all.
        (
            "Kabupaten Tabalong memiliki luas 3.767 km2 (1,454 sq mi) dan kepadatan 72/km2.",
            "[Kabupaten_Tabalong.txt] Luas 3.767 km2 (1,454 sq mi) dan kepadatan 72/km2.",
            "gambaran kabupaten tabalong",
            True,
        ),
        # MEASURED LIVE on an attached receipt (TOKO MAJU JAYA / TOTAL 43000). Both of
        # these are what the model actually wrote about the image it had just been
        # handed, and both were refused: the first counted "transaksi" as news the answer
        # had invented, though the question had supplied it as "transaksinya"; the second
        # counted a reporting verb that introduces the name rather than being one.
        (
            "Total transaksi adalah 43.000.",
            receipt,
            "Menurut dokumen ini, berapa total transaksinya?",
            True,
        ),
        ("Toko tersebut bernama Maju Jaya.", receipt, "Apa nama toko pada struk itu?", True),
        ("Toko yang tertera pada struk itu adalah Toko Maju Jaya.", receipt, "Apa nama toko pada struk itu?", True),
        # A reporting verb does not launder a fabrication: the name itself still has to
        # be in the passage, and it is not.
        ("Toko tersebut bernama Toko Sumber Rejeki.", receipt, "Apa nama toko pada struk itu?", False),
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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(
            text="[2026kb6306267.pdf] Peraturan Pemerintah Nomor 24 Tahun 1997 tentang Pendaftaran Tanah "
            "(Lembaran Negara Republik Indonesia Tahun 1997 Nomor 59). Presiden Republik Indonesia menetapkan.",
            sources=[SourceRef(filename="2026kb6306267.pdf", score=0.724)],
        ),
    )

    events = list(orchestrator.stream_agent(db=None, message="Siapa presiden pertama Indonesia?", history=[]))
    done = events[-1]

    assert "Soekarno" not in done["answer"]
    # The model answered; the answer just did not come from the decree. Saying the knowledge
    # base has nothing would send the user looking for a document that is not missing.
    assert done["answer"] == orchestrator.UNSUPPORTED_ANSWER
    assert "tidak ditemukan di knowledge base" not in done["answer"]
    assert done["sources"] == [], "chips beside a refusal read as corroboration"
    assert "Soekarno" not in "".join(e["text"] for e in events if e["type"] == "delta")


def test_a_widened_scoped_turn_does_not_license_a_fabricated_answer(monkeypatch):
    """Widening hands the model more evidence than the session's own file carried, and the
    support check is the only thing between that evidence and an answer about something
    else. Every other gate test runs unscoped, so none of them exercised the shape the
    widen change creates; this one does, and the answer must still be refused."""
    _mock_ollama(
        monkeypatch,
        [
            _reply(tool_calls=[{"function": {"name": "rag_search", "arguments": {"query": "presiden"}}}]),
            _reply(content="Ir. Soekarno adalah presiden pertama Indonesia."),
        ],
    )
    monkeypatch.setattr(
        registry, "dispatch",
        lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(
            text="[new-ktp.txt] pelayanan KTP hari Selasa di loket 3.\n\n"
            "[abc-laporan.pdf] KEPUTUSAN BUPATI tentang redistribusi tanah pertanian.",
            sources=[
                SourceRef(filename="new-ktp.txt", score=0.86),
                SourceRef(filename="abc-laporan.pdf", score=0.72),
            ],
        ),
    )

    events = list(
        orchestrator.stream_agent(
            db=None,
            message="Siapa presiden pertama Indonesia?",
            history=[],
            document_filenames=["abc-laporan.pdf"],
        )
    )
    done = events[-1]

    assert done["answer"] == orchestrator.UNSUPPORTED_ANSWER
    assert done["sources"] == [], "chips beside a refusal read as corroboration"


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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: (
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
    assert done["answer"] == orchestrator.UNSUPPORTED_ANSWER


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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(
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
        lambda name, arguments, db, image_paths, document_filenames=None, **_: registry.ToolOutcome(
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


def test_an_attached_image_is_read_before_the_model_is_asked(monkeypatch):
    """The file the caller handed over is not something to leave to the model's choice.

    Measured live: with a receipt attached, "Menurut dokumen ini, berapa total
    transaksinya?" went to sql_query, read nothing, and was answered "tidak ditemukan"
    while the image sat there unread. The server reads it now, and the turn opens with
    the same tool/sources pair the loop emits for a tool the model chose itself.
    """
    seen = []

    def fake_dispatch(name, arguments, db, image_paths, document_filenames=None, **_):
        seen.append((name, tuple(image_paths or ())))
        return registry.ToolOutcome(
            text="TOKO MAJU JAYA TOTAL 43000", sources=[SourceRef(filename="receipt.png")]
        )

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    _mock_ollama_chunks(monkeypatch, [[{"role": "assistant", "content": "Totalnya 43.000."}]])

    events = list(
        orchestrator.stream_agent(
            db=None, message="Berapa total transaksi pada struk ini?", history=[], image_paths=["/u/abc-receipt.png"]
        )
    )

    assert seen == [("image_ocr", ("/u/abc-receipt.png",))]
    assert [e["type"] for e in events] == ["tool", "sources", "done"]
    assert events[-1]["tool_used"] == "image_ocr"
    assert events[-1]["answer"] == "Totalnya 43.000."


def test_an_unreadable_attachment_does_not_license_the_answer(monkeypatch):
    """An image with no readable text reads nothing, so the turn is still ungrounded --
    the read counts only when it produced something."""
    monkeypatch.setattr(
        registry, "dispatch", lambda *a, **k: registry.ToolOutcome(text="no readable text", grounded=False)
    )
    _mock_ollama(
        monkeypatch,
        [_reply(content="Ibu kota Kanada adalah Ottawa."), _reply(content="Ibu kota Kanada adalah Ottawa.")],
    )

    events = list(
        orchestrator.stream_agent(db=None, message="Apa ibu kota Kanada?", history=[], image_paths=["/u/abc.png"])
    )

    assert [e["type"] for e in events] == ["done"]
    assert "Ottawa" not in events[-1]["answer"]


def test_an_attached_document_is_searched_before_the_model_is_asked(monkeypatch):
    """Same read-first rule for a PDF: measured live, a follow-up question about an
    attached report went to sql_query and was refused while a scoped rag_search held the
    answer at 0.6368."""
    seen = []

    def fake_dispatch(name, arguments, db, image_paths, document_filenames=None, **_):
        seen.append((name, arguments.get("query"), tuple(document_filenames or ())))
        return registry.ToolOutcome(
            text="[abc-laporan.pdf] Total anggaran Rp 987.654.321.",
            sources=[SourceRef(filename="abc-laporan.pdf", score=0.9)],
        )

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    _mock_ollama_chunks(monkeypatch, [[{"role": "assistant", "content": "Total anggarannya Rp 987.654.321."}]])

    events = list(
        orchestrator.stream_agent(
            db=None,
            message="Berapa total anggarannya?",
            history=[],
            document_filenames=["abc-laporan.pdf"],
        )
    )

    assert seen == [("rag_search", "Berapa total anggarannya?", ("abc-laporan.pdf",))]
    assert events[-1]["tool_used"] == "rag_search"
    assert events[-1]["answer"] == "Total anggarannya Rp 987.654.321."


def test_an_image_is_not_searched_again_as_a_document(monkeypatch):
    """The OCR branch has just written the extract into the corpus under the image's own
    stored name, so searching for it would put the same text in the transcript twice.

    Both searches are asserted, and that is the point: the read-first block and the loop
    narrowing the scope differently is exactly how the duplicate gets back in, because
    the model's own rag_search would reach around the read-first block's narrowing.
    """
    seen = []

    def fake_dispatch(name, arguments, db, image_paths, document_filenames=None, **_):
        seen.append((name, tuple(document_filenames or ())))
        return registry.ToolOutcome(text="kept", sources=[SourceRef(filename="receipt.png")])

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    _mock_ollama_chunks(
        monkeypatch,
        [
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "rag_search", "arguments": {"query": "lagi"}}}],
                }
            ],
            [{"role": "assistant", "content": "Baik."}],
        ],
    )

    list(
        orchestrator.stream_agent(
            db=None,
            message="Berapa totalnya?",
            history=[],
            image_paths=["/u/abc-receipt.png"],
            document_filenames=["abc-receipt.png", "xyz-laporan.pdf"],
        )
    )

    assert seen == [
        ("image_ocr", ()),
        ("rag_search", ("xyz-laporan.pdf",)),  # read-first
        ("rag_search", ("xyz-laporan.pdf",)),  # the model's own, same scope
    ]


def test_a_greeting_with_an_attachment_reads_nothing(monkeypatch):
    """The spec matrix's "a greeting answers with tool_used None" has to survive a file
    riding along with the greeting."""
    monkeypatch.setattr(
        registry, "dispatch", lambda *a, **k: pytest.fail("a greeting must not read the attachment")
    )
    _mock_ollama(monkeypatch, [_reply(content="Halo, ada yang bisa saya bantu?")])

    result = orchestrator.run_agent(db=None, message="halo", history=[], image_paths=["/u/abc.png"])

    assert result.tool_used is None
    assert result.answer == "Halo, ada yang bisa saya bantu?"


def _receipt_turn(monkeypatch, history):
    monkeypatch.setattr(
        registry,
        "dispatch",
        lambda *a, **k: registry.ToolOutcome(
            text="TOKO MAJU JAYA TOTAL 43000", sources=[SourceRef(filename="receipt.png")]
        ),
    )
    _mock_ollama_chunks(
        monkeypatch, [[{"role": "assistant", "content": "Total transaksi pada struk tersebut adalah Rp 43.000."}]]
    )
    return list(
        orchestrator.stream_agent(
            db=None,
            message="Sebutkan lagi totalnya berapa?",
            history=history,
            document_filenames=["abc-receipt.png"],
        )
    )


def test_a_word_from_an_earlier_turn_is_not_an_invention(monkeypatch):
    """The history is in the prompt the model was handed, so an answer reusing a word from
    an earlier turn of THIS conversation is not something it made up.

    Measured on an attached receipt: the extract reads "TOKO MAJU JAYA ... TOTAL 43000",
    so "transaksi" and "struk" appear in it nowhere, and the correct answer above was
    refused with them counted as invented. Turn 1's near-identical wording only passed
    because its question happened to supply "transaksi" -- an answer must not depend on
    that coincidence.
    """
    history = [
        {"role": "user", "content": "Berapa total transaksi pada struk ini?"},
        {"role": "assistant", "content": "Total transaksi pada struk ini adalah Rp 43.000."},
    ]

    assert _receipt_turn(monkeypatch, history)[-1]["answer"].startswith("Total transaksi pada struk tersebut")


def test_without_that_history_the_same_answer_is_still_refused(monkeypatch):
    """The other side of the same rule, so the evidence cannot be widened into a licence:
    with nothing earlier in the conversation to have supplied them, those two words come
    from nowhere and the answer goes."""
    events = _receipt_turn(monkeypatch, [])

    assert events[-1]["answer"] == orchestrator.UNSUPPORTED_ANSWER


def test_the_conversation_is_never_the_evidence(monkeypatch):
    """`carried` excuses a word the answer reuses; it must never count AS evidence.

    Measured on the real helper: with an unrelated decree as the tool output and
    "Siapa presiden pertama Indonesia?" earlier in the conversation, folding the
    history into the context instead scored this fabrication 3/4 -- exactly at the
    0.75 bar -- and shipped it, because `asked` only ever looked at the current
    message.
    """
    decree = "[2026kb6306267.pdf] Peraturan Pemerintah Nomor 24 Tahun 1997 tentang Pendaftaran Tanah."
    carried = "Siapa presiden pertama Indonesia?\nMaaf, informasi tersebut tidak ditemukan di knowledge base."

    refused = orchestrator._supported_by(
        "Presiden pertama Indonesia adalah Sukarno.", decree, question="Sebutkan lagi.", carried=carried
    )
    assert refused is False

    # The exemption itself still works: an answer about the attached receipt passes,
    # because the words it reuses came from the earlier turn rather than from the image.
    excused = orchestrator._supported_by(
        "Total transaksi pada struk tersebut adalah Rp 43.000.",
        "[receipt.png] TOKO MAJU JAYA TOTAL 43000",
        question="Sebutkan lagi totalnya berapa?",
        carried="Berapa total transaksi pada struk ini?",
    )
    assert excused is True


def test_read_first_reads_what_this_message_attached_not_the_whole_session(monkeypatch):
    """A session's older files are searchable by the model, but they must not crowd out
    the file the user just handed over.

    Measured live through the UI, before this: a session holding a receipt and a freshly
    attached PDF answered "Pelajari dokumen ini lalu ringkas isinya." out of the RECEIPT
    -- that chunk cleared the 0.6 floor and the PDF's did not, and the first_chunks
    fallback only fires when NOTHING hits. The newly attached file was never read.
    """
    seen = []

    def fake_dispatch(name, arguments, db, image_paths, document_filenames=None, **_):
        seen.append(tuple(document_filenames or ()))
        return registry.ToolOutcome(text="kept", sources=[SourceRef(filename="laporan.pdf")])

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    _mock_ollama_chunks(monkeypatch, [[{"role": "assistant", "content": "Baik."}]])

    list(
        orchestrator.stream_agent(
            db=None,
            message="Pelajari dokumen ini.",
            history=[],
            document_filenames=["abc-laporan.pdf", "xyz-struk.png"],
            attached_documents=["abc-laporan.pdf"],
        )
    )

    assert seen == [("abc-laporan.pdf",)]


def test_read_first_falls_back_to_the_session_scope_when_nothing_is_attached(monkeypatch):
    """A follow-up carries no attachment of its own, and that is exactly the turn the
    session scope exists for."""
    seen = []

    def fake_dispatch(name, arguments, db, image_paths, document_filenames=None, **_):
        seen.append(tuple(document_filenames or ()))
        return registry.ToolOutcome(text="kept", sources=[SourceRef(filename="abc-laporan.pdf")])

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    _mock_ollama_chunks(monkeypatch, [[{"role": "assistant", "content": "Baik."}]])

    list(
        orchestrator.stream_agent(
            db=None,
            message="Siapa penanggung jawabnya?",
            history=[],
            document_filenames=["abc-laporan.pdf"],
        )
    )

    assert seen == [("abc-laporan.pdf",)]


def test_read_first_keeps_a_fresh_attachment_narrow(monkeypatch):
    """The file this message brought is read on its own: widening here is how a
    receipt's chunk answered a question about a freshly attached PDF."""
    seen = []

    def fake_dispatch(name, arguments, db, image_paths, document_filenames=None, widen=True):
        seen.append(widen)
        return registry.ToolOutcome(text="kept", sources=[SourceRef(filename="laporan.pdf")])

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    _mock_ollama_chunks(monkeypatch, [[{"role": "assistant", "content": "Baik."}]])

    list(
        orchestrator.stream_agent(
            db=None,
            message="Pelajari dokumen ini.",
            history=[],
            document_filenames=["abc-laporan.pdf", "xyz-struk.png"],
            attached_documents=["abc-laporan.pdf"],
        )
    )

    assert seen == [False]


def test_read_first_on_a_follow_up_also_searches_the_corpus(monkeypatch):
    """A follow-up carries no file of its own, so the session's files must not be the
    only place it can look -- knowledge added after the session began lives outside.

    The fake defaults `widen` to None, not True: a default of True would pass whether
    or not the orchestrator forwarded the argument at all, which is the thing under test.
    """
    seen = []

    def fake_dispatch(name, arguments, db, image_paths, document_filenames=None, widen=None):
        seen.append(widen)
        return registry.ToolOutcome(text="kept", sources=[SourceRef(filename="abc-laporan.pdf")])

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    _mock_ollama_chunks(monkeypatch, [[{"role": "assistant", "content": "Baik."}]])

    list(
        orchestrator.stream_agent(
            db=None,
            message="Kapan jadwal pelayanan KTP?",
            history=[],
            document_filenames=["abc-laporan.pdf"],
        )
    )

    assert seen == [True]


def test_a_read_attachment_tells_the_model_what_to_do_with_it(monkeypatch):
    """Measured on a 45-chunk decree: asked to READ a file -- "baca isi file ini", "ringkas
    file ini", "pelajari dokumen ini" -- this model answers "Tidak ditemukan." with the
    file's own text sitting in the transcript, while the same evidence asked as a question
    is answered correctly. The refusal is about the shape of the request. A rule added to
    SYSTEM_PROMPT (do not answer not-found while the tool result holds the file) changed
    nothing; this note does.
    """
    monkeypatch.setattr(
        registry,
        "dispatch",
        lambda *a, **k: registry.ToolOutcome(text="isi file", sources=[SourceRef(filename="laporan.pdf")]),
    )
    sent = _mock_ollama_chunks(monkeypatch, [[{"role": "assistant", "content": "Baik."}]])

    list(
        orchestrator.stream_agent(
            db=None,
            message="baca isi file ini",
            history=[],
            document_filenames=["abc-laporan.pdf"],
            attached_documents=["abc-laporan.pdf"],
        )
    )

    # The user turn, not messages[-1]: by the time the note is added, the read-first block
    # has appended its assistant tool-call and tool result after it.
    user_turn = sent[0]["messages"][1]
    assert user_turn["role"] == "user"
    assert user_turn["content"].endswith(orchestrator.ATTACHMENT_READ_NOTE)
    assert sent[0]["messages"][-1]["role"] == "tool"


def test_a_turn_that_read_nothing_carries_no_note(monkeypatch):
    """A greeting reads nothing, and neither does an attachment whose read came back
    empty -- telling the model to relay a result that is not there is worse than saying
    nothing."""
    monkeypatch.setattr(
        registry, "dispatch", lambda *a, **k: registry.ToolOutcome(text="nothing", grounded=False)
    )
    sent = _mock_ollama(monkeypatch, [_reply(content="Baik."), _reply(content="Baik.")])

    list(
        orchestrator.stream_agent(
            db=None,
            message="baca isi file ini",
            history=[],
            document_filenames=["abc-laporan.pdf"],
            attached_documents=["abc-laporan.pdf"],
        )
    )
    assert orchestrator.ATTACHMENT_READ_NOTE not in sent[0]["messages"][1]["content"]

    greeting = _mock_ollama(monkeypatch, [_reply(content="Halo!")])
    orchestrator.run_agent(db=None, message="halo", history=[])
    assert orchestrator.ATTACHMENT_READ_NOTE not in greeting[0]["messages"][-1]["content"]


def test_the_notes_own_words_do_not_count_against_the_answer():
    """The answer may echo the note ("Isi file yang dibaca adalah ..."), and a word the
    model was handed is not an invention -- the same reason the conversation's words are
    excluded."""
    echoed = "Isi file yang dilampirkan dan sudah dibaca adalah TOKO MAJU JAYA."

    assert (
        orchestrator._supported_by(
            echoed,
            "[receipt.png] TOKO MAJU JAYA TOTAL 43000",
            question="baca isi file ini",
            carried=orchestrator.ATTACHMENT_READ_NOTE,
        )
        is True
    )
    # Without that exclusion the echo alone sinks a correct answer: 3 of 6 counted words
    # trace, well under the bar.
    assert (
        orchestrator._supported_by(echoed, "[receipt.png] TOKO MAJU JAYA TOTAL 43000", question="baca isi file ini")
        is False
    )


def test_a_model_that_reports_nothing_found_is_told_apart_from_a_model_that_invented(monkeypatch):
    """Both land on the same branch and are not the same thing to the user.

    A model that answers "tidak ditemukan" itself is reporting the corpus empty, and the
    e2e matrix's not-found signal is the honest sentence for it. Anything else is a real
    answer this check could not hold to the evidence -- the file holds it, the model could
    not be held to it -- which is a limit of the model and now says so.
    """
    monkeypatch.setattr(
        registry,
        "dispatch",
        lambda *a, **k: registry.ToolOutcome(
            text="[receipt.png] TOKO MAJU JAYA TOTAL 43000", sources=[SourceRef(filename="receipt.png")]
        ),
    )

    reported_empty = _mock_ollama_chunks(monkeypatch, [[{"role": "assistant", "content": "Tidak ditemukan."}]])
    done = list(
        orchestrator.stream_agent(
            db=None,
            message="Berapa total transaksinya?",
            history=[],
            document_filenames=["abc-receipt.png"],
        )
    )[-1]
    assert done["answer"] == orchestrator.NOT_IN_KNOWLEDGE_ANSWER
    assert reported_empty  # the payload was sent; the wording is what this test is about

    invented = _mock_ollama_chunks(
        monkeypatch, [[{"role": "assistant", "content": "Toko itu bernama Toko Sumber Rejeki."}]]
    )
    done = list(
        orchestrator.stream_agent(
            db=None,
            message="Apa nama tokonya?",
            history=[],
            document_filenames=["abc-receipt.png"],
        )
    )[-1]
    assert done["answer"] == orchestrator.UNSUPPORTED_ANSWER
    assert invented


def test_a_turn_that_read_nothing_keeps_the_corpus_wording(monkeypatch):
    """Nothing was read at all, so the corpus is exactly the thing that has nothing --
    and this is the sentence the e2e matrix pins."""
    sent = _mock_ollama(monkeypatch, [_reply(content="Ibu kota Kanada adalah Ottawa."), _reply(content="Ibu kota Kanada adalah Ottawa.")])

    result = orchestrator.run_agent(db=None, message="Apa ibu kota Kanada?", history=[])

    assert result.answer == orchestrator.NOT_IN_KNOWLEDGE_ANSWER
    assert sent
