"""Windows reader/writer contention must not corrupt sealed live state."""
import io
import os
import threading
import time
import pytest
from ai4math_agent.storage import read_json, write_json
from ai4math_agent.general.controller import _public_print


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_writer_survives_short_reader_handle(tmp_path):
    path = tmp_path / "state.json"
    write_json(path, {"round": 1})
    handle = path.open("rb")
    timer = threading.Timer(0.08, handle.close)
    timer.start()
    try:
        write_json(path, {"round": 2})
    finally:
        timer.join()
        handle.close()
    assert read_json(path) == {"round": 2}


def test_writer_keeps_persistent_permission_error(tmp_path, monkeypatch):
    calls = []
    def denied(*args):
        calls.append(args)
        raise PermissionError("persistent failure")
    monkeypatch.setattr("ai4math_agent.storage.os.replace", denied)
    monkeypatch.setattr("ai4math_agent.storage.time.sleep", lambda duration: None)
    with pytest.raises(PermissionError):
        write_json(tmp_path / "state.json", {"x": 1})
    assert len(calls) == 8


def test_public_math_characters_do_not_crash_legacy_stream(monkeypatch):
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="gbk")
    monkeypatch.setattr("ai4math_agent.general.controller.sys.stdout", stream)
    _public_print("已证明 n³ 和 Σ 的关系")
    stream.flush()
    assert b"\\xb3" in buffer.getvalue()
