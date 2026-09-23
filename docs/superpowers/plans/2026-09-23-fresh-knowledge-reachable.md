# Fresh Knowledge Reachable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Data yang baru dimasukkan lewat `/#/admin/knowledge` — file, teks tempel, maupun URL — langsung bisa ditemukan agent di chatbot, termasuk di sesi yang pernah membawa lampiran.

**Architecture:** Tidak ada perubahan skema atau dependensi. Empat perbaikan kecil di jalur retrieval dan ingest: (1) `rag_search` membuang potongan berisi sama agar duplikat tidak memenuhi `top_k`; (2) pencarian ber-scope sesi ikut membuka korpus bersama bila ada hit korpus yang lebih kuat dari hit sesi terbaik; (3) judul teks/URL ikut disimpan di isi agar ikut ter-embed; (4) `html_to_text` membuang `nav`/`aside`/`footer`.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy, PostgreSQL + pgvector (HNSW, cosine), Ollama `nomic-embed-text`, pytest.

**Spec:** Tidak ada spec terpisah — plan ini berargumen dari temuan debugging di bawah.

## Temuan (root cause, terukur di DB asli, transaksi di-rollback)

| Kasus | Sesi baru (tanpa lampiran) | Sesi yang punya lampiran |
|---|---|---|
| File upload | ✅ #1, skor 0.86 | ❌ tidak pernah dicari |
| Teks tempel, judul hanya di field judul | ❌ di luar 4 besar | ❌ tidak pernah dicari |
| Teks tempel, judul ada di isi | ✅ #1, skor 0.84 | ❌ tidak pernah dicari |
| URL, halaman penuh menu navigasi | ❌ peringkat #11 (0.71, lolos floor 0.6) | ❌ tidak pernah dicari |

1. **Scope sesi mengunci korpus** — `routers/chat.py:95` `_session_document_filenames` mengumpulkan semua lampiran sesi; `agent/registry.py:137` lalu membatasi `rag_search` ke file itu saja; `agent/orchestrator.py:608` `read_scope = attached_documents or scope` membuat tiap pesan lanjutan di sesi itu di-*read-first* dari file sesi. Hit file sesi (0.72) lolos floor, turn dianggap grounded dari sumber yang salah. 14 dari 40 sesi terdampak. Berlaku untuk ketiga jalur ingest karena semuanya berakhir di `_ingest_stored → ingest_file → documents`.
2. **Duplikat memenuhi `top_k`** — 193 dari 263 teks potongan tersimpan di lebih dari satu filename (PDF yang sama diunggah 3×+). Empat slot teratas terisi salinan yang sama; dokumen URL di peringkat #11 tidak pernah sampai.
3. **Judul teks tidak ter-embed** — `store_text_file` memakai judul hanya untuk nama file. Isi pendek ("Setiap Selasa 08.00…") tidak cocok dengan pertanyaan yang menyebut judul ("jadwal KTP").
4. **Chrome halaman ikut tersimpan** — `html_to_text` menyimpan menu/footer; fakta hanya 10% dari potongannya. Komentar `ponytail:` di fungsi itu sendiri menyebut ganti "if retrieval measurably starts citing chrome" — sekarang terukur.

Indeks HNSW dan commit tidak bermasalah: baris baru langsung terbaca begitu tersimpan.

## Global Constraints

- Interpreter: `../.venv/bin/python` / `../.venv/bin/pytest` dari `backend/` — `python3` polos rusak di mesin ini.
- Tidak ada dependensi baru, tidak ada migrasi skema.
- `rag_min_score` tetap 0.6.
- Kode, nama, komentar, dan pesan commit dalam bahasa Inggris; gaya komentar mengikuti file sekitarnya (menjelaskan *kenapa*, dengan angka terukur bila ada).
- Model tidak pernah memilih nama file — scope tetap diturunkan server.
- Pesan commit diakhiri `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. Pertanyaan samar ("pelajari dokumen ini") di sesi berlampiran yang jatuh ke `first_chunks` → korpus **tidak** boleh ikut masuk (Task 2, `test_dispatch_first_chunks_fallback_does_not_widen`).
2. Turn yang membawa lampiran baru → read-first tetap sempit ke file itu, regresi "dokumen ini dijawab dari struk" tidak boleh kembali (Task 2, `test_read_first_keeps_a_fresh_attachment_narrow`).
3. Salinan korpus berisi sama dengan file sesi → tidak muncul dua kali di hasil (Task 2, `test_dispatch_lets_a_stronger_corpus_hit_into_a_scoped_search`).
4. Teks berjudul yang isinya bersih jadi kosong (`"\x00\x00"`) → tetap 422 dan tidak meninggalkan file yatim; judul tidak boleh "menyelamatkan" isi kosong (Task 3, test lama `test_text_that_cleans_down_to_nothing_takes_its_file_with_it` + `test_titled_leaves_empty_text_empty`).
5. Halaman yang seluruh isinya di dalam `<nav>` → jadi teks kosong dan ditolak 422, bukan tersimpan diam-diam (Task 4, `test_html_to_text_drops_navigation_and_footer` memeriksa hasil kosong).

---

## File Structure

| File | Tanggung jawab | Task |
|---|---|---|
| `backend/tools/rag_tool.py` | dedupe per isi di `rag_search` | 1 |
| `backend/agent/registry.py` | parameter `widen` di `dispatch` | 2 |
| `backend/agent/orchestrator.py` | read-first meneruskan `widen` | 2 |
| `backend/tests/test_orchestrator.py` | 21 fake `dispatch` menerima `**_` | 2 |
| `backend/routers/documents.py` | helper `_titled`, dipakai `/text` dan `/url` | 3 |
| `backend/services/document_service.py` | `_VisibleText.SKIP` + `nav`/`aside`/`footer` | 4 |

Urutan: 1 → 2 → 3 → 4 → 5. Task 1–4 saling independen secara kode; Task 5 verifikasi akhir.

---

### Task 1: Dedupe potongan berisi sama di `rag_search`

**Files:**
- Modify: `backend/tools/rag_tool.py:17-50`
- Test: `backend/tests/test_rag_tool.py`

**Interfaces:**
- Produces: `rag_search(db, query, top_k=4, filenames=None) -> list[RagHit]` — signature tidak berubah; hasil kini unik per `content`.

- [ ] **Step 1: Write the failing test** — tambahkan di akhir `backend/tests/test_rag_tool.py`:

```python
def test_rag_search_returns_one_copy_of_a_chunk_stored_under_two_names(db, monkeypatch):
    """The same PDF uploaded three times filled all four slots with one passage, and a
    fresh URL ingest at rank #11 never reached the model. One copy, then the next
    distinct passage."""
    db.add(Document(filename="ragtest-a.pdf", content="jadwal interviu", embedding=_vector(1.0), doc_metadata={}))
    db.add(Document(filename="ragtest-a-copy.pdf", content="jadwal interviu", embedding=_vector(1.0), doc_metadata={}))
    db.add(Document(filename="ragtest-b.txt", content="tarif retribusi pasar", embedding=_vector2(1.0, 0.5), doc_metadata={}))
    db.flush()
    monkeypatch.setattr(rag_tool, "embed_query", lambda q: _vector(1.0))

    hits = rag_tool.rag_search(db, "apa saja", top_k=2)

    assert [h.content for h in hits] == ["jadwal interviu", "tarif retribusi pasar"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../.venv/bin/pytest tests/test_rag_tool.py::test_rag_search_returns_one_copy_of_a_chunk_stored_under_two_names -v`
Expected: FAIL — `['jadwal interviu', 'jadwal interviu'] != ['jadwal interviu', 'tarif retribusi pasar']`

- [ ] **Step 3: Write minimal implementation** — di `backend/tools/rag_tool.py`, ganti blok dari `# Over-fetch so the score floor ...` sampai `return hits[:top_k]` dengan:

```python
    # Over-fetch so the score floor and the dedupe below cannot silently hand back
    # fewer than the documents that actually clear it.
    # ponytail: 5x, kept under pgvector's default hnsw.ef_search of 40 -- an HNSW
    # scan returns at most that many rows. Raise ef_search with the multiplier if
    # top_k ever grows past 8.
    rows = query_.order_by(distance).limit(top_k * 5).all()

    # One copy per passage: the same file uploaded three times filled every slot
    # with one chunk (193 of 263 distinct chunks sit under more than one name).
    min_score = get_settings().rag_min_score
    hits: list[RagHit] = []
    seen: set[str] = set()
    for filename, content, dist in rows:
        score = round(1.0 - float(dist), 4)
        if score >= min_score and content not in seen:
            seen.add(content)
            hits.append(RagHit(filename=filename, content=content, score=score))
    return hits[:top_k]
```

Catatan: pembandingan floor kini memakai skor yang sudah dibulatkan 4 desimal; selisihnya < 0.00005 dan tidak mengubah test floor yang ada.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/test_rag_tool.py -v`
Expected: semua PASS (termasuk `test_rag_search_respects_top_k`, yang isinya berbeda-beda `isi {i}`).

- [ ] **Step 5: Commit**

```bash
git add backend/tools/rag_tool.py backend/tests/test_rag_tool.py
git commit -m "fix: return one copy of a passage stored under several names"
```

---

### Task 2: Pencarian ber-scope sesi ikut membuka korpus bila korpus lebih kuat

**Files:**
- Modify: `backend/agent/registry.py:118-150` (`dispatch`)
- Modify: `backend/agent/orchestrator.py:467-509` (`_read_attachments`), `:613` (pemanggilnya)
- Modify: 21 fake `dispatch` di `backend/tests/test_orchestrator.py` (fake dengan signature serupa di file test lain adalah fake `run_agent`/`stream_agent`, bukan `dispatch` — jangan disentuh)
- Test: `backend/tests/test_registry.py`, `backend/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `rag_search` dari Task 1 (hasil terurut skor menurun, unik per isi).
- Produces: `registry.dispatch(name, arguments, db, image_paths, document_filenames=None, widen=True) -> ToolOutcome`; `orchestrator._read_attachments(db, message, image_paths, scope, widen) -> list[tuple[str, dict, ToolOutcome]]`.

Aturan: hit file sesi tetap diutamakan. Hit korpus ikut masuk **hanya** bila skornya **lebih tinggi** dari hit sesi terbaik, dan isinya belum ada di hit sesi. Bila hit sesi berasal dari `first_chunks` (pertanyaan samar), korpus tidak dicari sama sekali. Read-first untuk turn yang membawa lampiran baru memakai `widen=False`.

- [ ] **Step 1: Beri semua fake `dispatch` di test parameter `**_`** — agar kwarg `widen` baru tidak memecah 21 fake yang sudah ada (perubahan mekanis, belum ada perilaku baru):

```bash
cd backend && sed -i '' -E 's/image_paths, document_filenames=None([):])/image_paths, document_filenames=None, **_\1/' tests/test_orchestrator.py
grep -c "document_filenames=None, \*\*_" tests/test_orchestrator.py
```

Expected: `21`. Jalankan `../.venv/bin/pytest -q` → hasil sama dengan sebelum perubahan.

- [ ] **Step 2: Write the failing tests** — tambahkan di `backend/tests/test_registry.py` setelah `test_dispatch_rag_search_without_session_documents_stays_global`:

```python
def test_dispatch_lets_a_stronger_corpus_hit_into_a_scoped_search(monkeypatch):
    """A session that once carried a PDF could never reach knowledge added later:
    measured live, the new note scored 0.86 unscoped while the scoped search returned
    six chunks of the old PDF at 0.72 -- above the floor, so the turn looked grounded.
    A corpus hit that beats the best session hit comes in; a weaker one and a second
    copy of a session passage do not."""
    def fake_rag(db, query, top_k=4, filenames=None):
        if filenames:
            return [RagHit(filename="abc-jadwal.pdf", content="jadwal interviu", score=0.72)]
        return [
            RagHit(filename="new-ktp.txt", content="pelayanan KTP hari Selasa", score=0.86),
            RagHit(filename="copy-jadwal.pdf", content="jadwal interviu", score=0.72),
            RagHit(filename="old.txt", content="makanan khas", score=0.65),
        ]

    monkeypatch.setattr(registry, "rag_search", fake_rag)

    outcome = registry.dispatch(
        "rag_search", {"query": "jadwal KTP"}, db=None,
        image_paths=[], document_filenames=["abc-jadwal.pdf"],
    )

    assert [s.filename for s in outcome.sources] == ["new-ktp.txt", "abc-jadwal.pdf"]


def test_dispatch_without_widen_keeps_a_scoped_search_to_its_files(monkeypatch):
    """The turn that attaches a file reads that file only -- see
    test_read_first_reads_what_this_message_attached_not_the_whole_session."""
    calls = []

    def fake_rag(db, query, top_k=4, filenames=None):
        calls.append(filenames)
        return [RagHit(filename="abc-jadwal.pdf", content="jadwal interviu", score=0.72)]

    monkeypatch.setattr(registry, "rag_search", fake_rag)

    registry.dispatch(
        "rag_search", {"query": "jadwal"}, db=None,
        image_paths=[], document_filenames=["abc-jadwal.pdf"], widen=False,
    )

    assert calls == [["abc-jadwal.pdf"]]


def test_dispatch_first_chunks_fallback_does_not_widen(monkeypatch):
    """A vague "pelajari dokumen ini" that clears the floor against nothing anchors to
    the session's opening chunks; the corpus is not searched, so a stray 0.65 chunk
    from another file cannot take the summary over."""
    calls = []

    def fake_rag(db, query, top_k=4, filenames=None):
        calls.append(filenames)
        return []

    monkeypatch.setattr(registry, "rag_search", fake_rag)
    monkeypatch.setattr(
        registry, "first_chunks",
        lambda db, filenames, limit=4: [RagHit(filename="abc-laporan.pdf", content="KEPUTUSAN BUPATI", score=1.0)],
    )

    outcome = registry.dispatch(
        "rag_search", {"query": "pelajari dokumen ini"}, db=None,
        image_paths=[], document_filenames=["abc-laporan.pdf"],
    )

    assert calls == [["abc-laporan.pdf"]]
    assert [s.filename for s in outcome.sources] == ["abc-laporan.pdf"]
```

Dan di `backend/tests/test_orchestrator.py` setelah `test_read_first_falls_back_to_the_session_scope_when_nothing_is_attached`:

```python
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
    only place it can look -- knowledge added after the session began lives outside."""
    seen = []

    def fake_dispatch(name, arguments, db, image_paths, document_filenames=None, widen=True):
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && ../.venv/bin/pytest tests/test_registry.py tests/test_orchestrator.py -k "widen or stronger_corpus or fresh_attachment_narrow or follow_up_also" -v`
Expected: FAIL — `TypeError: dispatch() got an unexpected keyword argument 'widen'`, `['abc-jadwal.pdf'] != ['new-ktp.txt', 'abc-jadwal.pdf']`, dan `seen == [True]`/`[False]` gagal karena `widen` belum diteruskan.

- [ ] **Step 4: Implement `widen` di `registry.dispatch`** — di `backend/agent/registry.py`, ubah signature dan cabang `rag_search`:

```python
def dispatch(
    name: str,
    arguments: dict,
    db: Session | None,
    image_paths: list[str] | None,
    document_filenames: list[str] | None = None,
    widen: bool = True,
) -> ToolOutcome:
    """Run one tool call. Failures come back as text so the model can recover.

    image_paths carries the caller's attached images and document_filenames the
    documents its session references -- both resolved from the authenticated
    request, never names the model chose; the tool schemas deliberately expose
    no file parameter.

    widen lets a scoped search reach the shared corpus when the corpus holds a
    stronger match than any of the session's files. False only for the turn that
    attaches a file, which must read that file on its own.
    """
    if name == "rag_search":
        # With session documents on record, scope retrieval to them and read a
        # little deeper: "pelajari dokumen ini" must anchor to those files, not
        # to whichever chunk of the shared corpus happens to score 0.65. When
        # the model's own query embeds too weakly to clear the floor against
        # those files, fall back to their opening chunks -- the title and
        # subject line a summary needs -- instead of answering "not found".
        query = str(arguments.get("query", ""))
        filenames = document_filenames or None
        hits = rag_search(db, query, top_k=6 if filenames else 4, filenames=filenames)
        if filenames and not hits:
            hits = first_chunks(db, filenames)
        elif filenames and widen:
            # A scope alone locked every session that ever carried a file out of
            # knowledge added later. Measured live: a new note scored 0.86 unscoped
            # while the scope returned an old PDF at 0.72 -- above the floor, so the
            # turn looked grounded and the note was never searched. Only a corpus hit
            # that BEATS the session's best comes in, so a question about the
            # session's own file keeps answering from it.
            best = hits[0].score
            known = {h.content for h in hits}
            hits = [h for h in rag_search(db, query) if h.score > best and h.content not in known] + hits
        if not hits:
```

(Baris setelah `if not hits:` tetap seperti sekarang. `hits` dari `rag_search` sudah terurut menurun, dan semua hit korpus yang masuk > `best`, jadi hasil gabungan tetap terurut tanpa `sort`.)

- [ ] **Step 5: Teruskan `widen` dari read-first** — di `backend/agent/orchestrator.py`:

Signature `_read_attachments`:

```python
def _read_attachments(
    db: Session | None,
    message: str,
    image_paths: list[str] | None,
    scope: list[str],
    widen: bool,
) -> list[tuple[str, dict, registry.ToolOutcome]]:
```

Tambahkan satu paragraf di akhir docstring-nya, sebelum `"""`:

```python
    `widen` is False when `scope` is the files THIS message attached: those are read
    on their own. A follow-up reads the session scope with the corpus open, because
    knowledge added after the session began lives outside it.
```

Panggilan dispatch rag_search di dalamnya:

```python
                registry.dispatch(
                    "rag_search", arguments, db=db, image_paths=[], document_filenames=scope, widen=widen
                ),
```

Pemanggil di `stream_agent` (sekitar baris 613):

```python
        for name, arguments, outcome in _read_attachments(
            db, message, image_paths, read_scope, widen=not attached_documents
        ):
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/test_registry.py tests/test_orchestrator.py tests/test_attachments.py -v`
Expected: semua PASS, termasuk test lama `test_dispatch_scopes_rag_search_to_session_documents`, `test_read_first_reads_what_this_message_attached_not_the_whole_session`, `test_read_first_falls_back_to_the_session_scope_when_nothing_is_attached`.

- [ ] **Step 7: Commit**

```bash
git add backend/agent/registry.py backend/agent/orchestrator.py backend/tests/test_registry.py backend/tests/test_orchestrator.py
git commit -m "fix: let a session-scoped search reach stronger knowledge added later"
```

---

### Task 3: Judul teks tempel dan URL ikut disimpan di isi

**Files:**
- Modify: `backend/routers/documents.py` (helper baru + `ingest_text` + `ingest_url`)
- Test: `backend/tests/test_ingest_sources.py`

**Interfaces:**
- Produces: `routers.documents._titled(title: str | None, text: str) -> str`.

Keputusan: ini **membalik** keputusan lama yang dikunci `test_pasted_text_is_ingested_as_a_document_of_its_own` ("stored as the text it was given, nothing appended"). Alasannya terukur: tanpa judul di isi, catatan pendek tidak masuk 4 besar; dengan judul, #1 di 0.84. Untuk URL hanya `payload.title` yang dipakai — `<title>` halaman sudah terbaca oleh `html_to_text`, dan slug URL hanya menambah noise.

- [ ] **Step 1: Write the failing tests** — di `backend/tests/test_ingest_sources.py`, ganti assertion terakhir `test_pasted_text_is_ingested_as_a_document_of_its_own`:

```python
        row = session.query(Document).filter(Document.filename == body["filename"]).one()
        # The title is embedded with the body: a short note ("cuti tahunan 12 hari")
        # asked about by its title missed the top four until it was.
        assert row.content == f"{name} cuti tahunan 12 hari"
```

Tambahkan di `test_a_url_is_fetched_and_stored_as_text`, setelah `assert "Cuti tahunan 12 hari." in row.content`:

```python
        assert row.content.startswith(name), "the operator's title leads the page text"
```

Dan tambahkan test baru:

```python
def test_titled_leaves_empty_text_empty():
    """A title must not rescue a body that cleans down to nothing -- the empty-text
    refusals downstream have to keep firing."""
    from routers.documents import _titled

    assert _titled("Jadwal KTP", "Selasa 08.00") == "Jadwal KTP\n\nSelasa 08.00"
    assert _titled(None, "Selasa 08.00") == "Selasa 08.00"
    assert _titled("Jadwal KTP", "\x00\x00") == "\x00\x00"
    assert _titled("Jadwal KTP", "   ") == "   "
```

(`row.content` berisi teks setelah `clean_text`, jadi `"\n\n"` menjadi satu spasi — karena itu assertion teks memakai `f"{name} cuti tahunan 12 hari"`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/bin/pytest tests/test_ingest_sources.py -v`
Expected: FAIL — `ImportError: cannot import name '_titled'`, dan dua assertion konten gagal.

- [ ] **Step 3: Write minimal implementation** — di `backend/routers/documents.py`, tambahkan `clean_text` ke import `services.document_service`:

```python
from services.document_service import IngestError, clean_text, fetch_url_text, ingest_file, name_from_url
```

Tambahkan helper setelah `_ingest_stored`:

```python
def _titled(title: str | None, text: str) -> str:
    """The operator's title as the first line of what gets embedded.

    A title that only names the file is invisible to retrieval: measured, a short
    note asked about by its title missed the top four, and with the title leading
    its text it ranked first at 0.84. Text that cleans down to nothing stays as it
    was, so the empty-text refusals downstream still fire.
    """
    return f"{title}\n\n{text}" if title and clean_text(text) else text
```

Di `ingest_text`:

```python
        stored_path = store_text_file(_titled(payload.title, payload.content), payload.title or "catatan")
```

Di `ingest_url`:

```python
        stored_path = store_text_file(_titled(payload.title, text), payload.title or name_from_url(payload.url))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/test_ingest_sources.py -v`
Expected: semua PASS, termasuk `test_text_that_cleans_down_to_nothing_takes_its_file_with_it` (422, tanpa file yatim) dan `test_empty_text_is_refused_at_the_edge`.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/documents.py backend/tests/test_ingest_sources.py
git commit -m "fix: embed a pasted note's or page's title with its text"
```

---

### Task 4: Buang navigasi, sidebar, dan footer dari halaman URL

**Files:**
- Modify: `backend/services/document_service.py:48-83` (`_VisibleText`, docstring `html_to_text`)
- Test: `backend/tests/test_ingest_sources.py`

**Interfaces:**
- Produces: `html_to_text(html: str) -> str` — signature tetap; `nav`, `aside`, `footer` tidak lagi menghasilkan teks.

`header` sengaja tidak dilewati: sering memuat `<h1>` judul halaman.

- [ ] **Step 1: Write the failing test** — tambahkan setelah `test_html_to_text_keeps_the_prose_and_drops_the_chrome`:

```python
def test_html_to_text_drops_navigation_and_footer():
    """Measured: on a menu-heavy page the fact was 10% of its chunk and ranked #11.
    Navigation, sidebars and footers are chrome, not knowledge."""
    menu = "<li><a>Beranda Profil Berita Layanan PPID Kontak</a></li>" * 10
    page = (
        f"<html><body><nav><ul>{menu}</ul></nav><aside>Berita terpopuler</aside>"
        "<main><h1>Retribusi Pasar</h1><p>Tarif Rp 5.000 per lapak per hari.</p></main>"
        f"<footer>{menu} Hak cipta 2026</footer></body></html>"
    )

    text = document_service.clean_text(document_service.html_to_text(page))

    assert text == "Retribusi Pasar Tarif Rp 5.000 per lapak per hari."
    assert document_service.clean_text(document_service.html_to_text(f"<nav>{menu}</nav>")) == "", (
        "a page that is all navigation reads as empty and is refused, not stored"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../.venv/bin/pytest tests/test_ingest_sources.py::test_html_to_text_drops_navigation_and_footer -v`
Expected: FAIL — teks masih memuat "Beranda Profil ..." dan "Hak cipta 2026".

- [ ] **Step 3: Write minimal implementation** — di `backend/services/document_service.py`:

```python
    SKIP = {"script", "style", "noscript", "template", "nav", "aside", "footer"}
```

Perbarui docstring `_VisibleText` baris pertama menjadi `"""Everything a reader came for: no script, style or template bodies, and no navigation, sidebar or footer chrome.` dan ganti catatan `ponytail:` di `html_to_text`:

```python
    ponytail: a tag stripper, not a readability extractor. nav, aside and footer are
    dropped because measured retrieval ranked a fact at #11 behind its own page's
    menus; chrome built from plain divs still survives. Swap in a content extractor
    only if that measurably starts costing answers.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/test_ingest_sources.py -v`
Expected: semua PASS, termasuk `test_html_to_text_keeps_the_prose_and_drops_the_chrome` dan `test_html_with_an_unclosed_head_still_reads`.

- [ ] **Step 5: Commit**

```bash
git add backend/services/document_service.py backend/tests/test_ingest_sources.py
git commit -m "fix: drop navigation, sidebar and footer text from an ingested page"
```

---

### Task 5: Verifikasi menyeluruh dan data lama

**Files:** tidak ada perubahan kode.

- [ ] **Step 1: Full test suite**

Run: `cd backend && ../.venv/bin/pytest -q`
Expected: semua PASS (bandingkan jumlah dengan baseline sebelum Task 1).

- [ ] **Step 2: Restart backend** — uvicorn saat ini berjalan tanpa `--reload`, jadi perubahan belum dimuat:

```bash
pkill -f "uvicorn main:app" ; cd backend && ../.venv/bin/uvicorn main:app --port 8000
```

(jalankan di background / terminal terpisah; pastikan `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health` → `200`).

- [ ] **Step 3: Uji langsung lewat UI di `http://localhost:5173`** (origin lain ditolak CORS) — matriks 3 × 2:

| Sumber (di `/#/admin/knowledge`) | Contoh isi | Sesi baru | Sesi yang punya lampiran |
|---|---|---|---|
| File `.txt` | "Jadwal pelayanan KTP Disdukcapil: Selasa 08.00–12.00 WITA" | ☐ | ☐ |
| Teks tempel, judul "Jadwal Paspor", isi "Setiap Kamis 09.00–11.00" | — | ☐ | ☐ |
| URL halaman berita/pemda dengan menu | fakta dari paragraf utama | ☐ | ☐ |

Lulus bila tiap sel menjawab benar dan chip sumber menunjuk dokumen baru. Tambahan regresi: di sesi berlampiran, lampirkan PDF baru dan kirim "Pelajari dokumen ini lalu ringkas isinya" → ringkasan harus dari PDF itu, bukan dari data umum.

- [ ] **Step 4: Data lama** — 7 dokumen `.txt` (teks/URL) yang di-ingest sebelum Task 3/4 belum membawa judul dan masih memuat chrome. Hapus lalu tambah ulang lewat `/#/admin/knowledge` yang memang dibutuhkan (mis. `pelatahihan_ai_kominfo.txt`, `Kabupaten_Tabalong.txt`, `makanan_khas_kalsel.txt`). Skrip backfill sengaja tidak dibuat — 7 dokumen lebih cepat diulang manual; buat skrip bila jumlahnya ratusan.

- [ ] **Step 5: Hapus duplikat (opsional)** — Task 1 membuat duplikat tidak merusak hasil, tapi salinan PDF "Jadwal Interviu …" (3×) dan "2026kb6306267" (3×) tetap memakan penyimpanan. Hapus salinan lewat tombol hapus di halaman knowledge bila diinginkan. Pencegahan duplikat saat upload (hash) sengaja tidak dibuat; tambahkan bila penyimpanan jadi masalah.

## Di luar scope (sengaja)

- Pencegahan duplikat saat upload (cek hash) — Task 1 sudah menetralkan dampaknya ke retrieval.
- Content extractor (readability) untuk URL — `nav`/`aside`/`footer` sudah menutup kasus terukur.
- Mengubah `rag_min_score` atau model embedding.
- Frontend — tidak ada perubahan; halaman knowledge sudah memanggil endpoint yang benar.
