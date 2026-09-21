import uuid

import pytest
from sqlalchemy import text

from database import SessionLocal
from models import ChatHistory, ChatSession, Document, User


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


def test_can_insert_and_read_chat_history(db):
    owner = User(username=f"model-{uuid.uuid4().hex[:8]}", password_hash="x", role="USER")
    db.add(owner)
    db.flush()
    db.add(ChatSession(id="test-session", user_id=owner.id))
    db.flush()
    db.add(ChatHistory(session_id="test-session", role="user", message="halo"))
    db.flush()
    row = db.query(ChatHistory).filter_by(session_id="test-session").one()
    assert row.message == "halo"
    assert row.created_at is not None


def test_document_embedding_roundtrips_as_768_floats(db):
    vector = [0.01] * 768
    doc = Document(filename="a.txt", content="isi dokumen", embedding=vector, doc_metadata={"chunk": 0})
    db.add(doc)
    db.flush()
    stored = db.query(Document).filter_by(filename="a.txt").one()
    assert len(stored.embedding) == 768
    assert stored.doc_metadata["chunk"] == 0


def test_readonly_engine_cannot_write(db):
    from database import get_readonly_engine

    with get_readonly_engine().connect() as conn:
        with pytest.raises(Exception):
            conn.execute(text("INSERT INTO chat_history (session_id, role, message) VALUES ('x','user','y')"))
            conn.commit()
