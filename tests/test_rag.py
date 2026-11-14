from backend.services.rag_service import chunk_text


def test_chunk_text_short_text_is_one_chunk():
    assert chunk_text("hello world", 100, 20) == ["hello world"]
    assert chunk_text("   ", 100, 20) == []


def test_chunk_text_covers_everything_with_overlap():
    words = [f"word{i}" for i in range(300)]
    chunks = chunk_text(" ".join(words), 200, 40)
    assert len(chunks) > 5
    assert all(len(c) <= 200 for c in chunks)
    joined = " ".join(chunks)
    assert all(w in joined for w in words)
    # consecutive chunks share text
    assert chunks[0].split()[-1] in chunks[1]


def test_chunk_text_prefers_paragraph_breaks():
    text = ("a" * 150) + "\n\n" + ("b" * 150)
    assert chunk_text(text, 200, 0) == ["a" * 150, "b" * 150]
