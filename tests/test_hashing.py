from payroll_ingest.hashing import sha256_file


def test_sha256_file_matches_known_digest(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"ciao mondo")
    # sha256("ciao mondo") calcolato indipendentemente con hashlib
    assert sha256_file(path) == "6c872dc19c4b6dc990b7158ace7d17b4e8ffb75d08493d9656d226fb64e8ecd2"


def test_sha256_file_same_content_same_hash(tmp_path):
    path_a = tmp_path / "a.txt"
    path_b = tmp_path / "b.txt"
    path_a.write_bytes(b"stesso contenuto")
    path_b.write_bytes(b"stesso contenuto")
    assert sha256_file(path_a) == sha256_file(path_b)


def test_sha256_file_different_content_different_hash(tmp_path):
    path_a = tmp_path / "a.txt"
    path_b = tmp_path / "b.txt"
    path_a.write_bytes(b"contenuto uno")
    path_b.write_bytes(b"contenuto due")
    assert sha256_file(path_a) != sha256_file(path_b)


def test_sha256_file_reads_in_chunks_smaller_than_file(tmp_path):
    # chunk_size minuscolo forza piu' iterazioni del while: verifica che il
    # digest risultante sia comunque corretto e coerente con la lettura intera.
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * 100)
    assert sha256_file(path, chunk_size=7) == sha256_file(path, chunk_size=1024 * 1024)


def test_sha256_file_empty_file(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    import hashlib

    assert sha256_file(path) == hashlib.sha256(b"").hexdigest()
