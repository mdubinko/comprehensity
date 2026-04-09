"""Tests for lsp_client.py — framing and subprocess lifecycle."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch, call

import pytest

from lsp_client import LspClient, LspError, encode_message, read_message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frame(msg: dict) -> bytes:
    """Build a Content-Length-framed LSP message (same as encode_message)."""
    body = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def _stream(*messages: dict) -> bytes:
    """Raw bytes for one or more framed LSP messages."""
    return b"".join(_frame(m) for m in messages)


def _mock_proc(stdout_bytes: bytes) -> MagicMock:
    """Return a mock Popen-like object with controllable stdout."""
    proc = MagicMock()
    proc.stdout = io.BytesIO(stdout_bytes)
    proc.stdin = MagicMock()
    proc.wait.return_value = 0
    return proc


def _init_response(req_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": {"capabilities": {}}}


def _shutdown_response(req_id: int) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": None}


# ---------------------------------------------------------------------------
# encode_message
# ---------------------------------------------------------------------------

class TestEncodeMessage:
    def test_has_content_length_header(self):
        raw = encode_message({"jsonrpc": "2.0", "method": "ping"})
        assert raw.startswith(b"Content-Length:")

    def test_content_length_matches_body(self):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        raw = encode_message(msg)
        header, _, body = raw.partition(b"\r\n\r\n")
        declared = int(header.split(b":")[1].strip())
        assert declared == len(body)

    def test_body_is_valid_json(self):
        msg = {"jsonrpc": "2.0", "method": "test", "params": {"x": 1}}
        raw = encode_message(msg)
        _, _, body = raw.partition(b"\r\n\r\n")
        parsed = json.loads(body)
        assert parsed["params"]["x"] == 1

    def test_crlf_separator(self):
        raw = encode_message({"method": "x"})
        assert b"\r\n\r\n" in raw


# ---------------------------------------------------------------------------
# read_message
# ---------------------------------------------------------------------------

class TestReadMessage:
    def test_round_trip(self):
        msg = {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}
        stream = io.BytesIO(encode_message(msg))
        result = read_message(stream)
        assert result["id"] == 7
        assert result["result"]["ok"] is True

    def test_multiple_messages_sequential(self):
        m1 = {"jsonrpc": "2.0", "id": 1, "result": "first"}
        m2 = {"jsonrpc": "2.0", "id": 2, "result": "second"}
        stream = io.BytesIO(encode_message(m1) + encode_message(m2))
        assert read_message(stream)["result"] == "first"
        assert read_message(stream)["result"] == "second"

    def test_extra_header_ignored(self):
        """Content-Type header alongside Content-Length is valid LSP."""
        body = json.dumps({"id": 1}).encode("utf-8")
        raw = (
            f"Content-Length: {len(body)}\r\n"
            f"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n"
            f"\r\n"
        ).encode("ascii") + body
        result = read_message(io.BytesIO(raw))
        assert result["id"] == 1

    def test_empty_stream_raises(self):
        with pytest.raises(LspError, match="closed"):
            read_message(io.BytesIO(b""))

    def test_missing_content_length_raises(self):
        raw = b"Content-Type: application/json\r\n\r\n{}"
        with pytest.raises(LspError, match="Content-Length"):
            read_message(io.BytesIO(raw))

    def test_short_body_raises(self):
        body = b'{"id":1}'
        # Lie about body length
        raw = f"Content-Length: {len(body) + 10}\r\n\r\n".encode("ascii") + body
        with pytest.raises(LspError, match="Short read"):
            read_message(io.BytesIO(raw))


# ---------------------------------------------------------------------------
# LspClient lifecycle (subprocess mocked)
# ---------------------------------------------------------------------------

class TestLspClientLifecycle:
    def _make_client(self, stdout_bytes: bytes) -> tuple[LspClient, MagicMock]:
        proc = _mock_proc(stdout_bytes)
        client = LspClient(["dummy-lsp", "--stdio"], root_uri="file:///repo")
        client._proc = proc
        client._next_id = 1
        client._start_reader()
        return client, proc

    def test_initialize_sends_request(self):
        stdout = _stream(_init_response(1))
        client, proc = self._make_client(stdout)
        client._initialize()
        # stdin.write called twice: initialize request + initialized notification
        assert proc.stdin.write.call_count == 2

    def test_initialize_sends_correct_method(self):
        stdout = _stream(_init_response(1))
        client, proc = self._make_client(stdout)
        client._initialize()
        first_call_bytes = proc.stdin.write.call_args_list[0][0][0]
        _, _, body = first_call_bytes.partition(b"\r\n\r\n")
        msg = json.loads(body)
        assert msg["method"] == "initialize"

    def test_initialized_notification_sent_after_response(self):
        stdout = _stream(_init_response(1))
        client, proc = self._make_client(stdout)
        client._initialize()
        second_call_bytes = proc.stdin.write.call_args_list[1][0][0]
        _, _, body = second_call_bytes.partition(b"\r\n\r\n")
        msg = json.loads(body)
        assert msg["method"] == "initialized"
        assert "id" not in msg  # notifications have no id

    def test_stop_sends_shutdown_then_exit(self):
        # id=1 for shutdown (next_id starts at 1 after init used it)
        stdout = _stream(_shutdown_response(1))
        client, proc = self._make_client(stdout)
        client._next_id = 1  # reset as if init already done
        client.stop()
        written = [
            json.loads(c[0][0].partition(b"\r\n\r\n")[2])
            for c in proc.stdin.write.call_args_list
        ]
        methods = [m["method"] for m in written]
        assert methods == ["shutdown", "exit"]

    def test_stop_clears_proc(self):
        stdout = _stream(_shutdown_response(1))
        client, proc = self._make_client(stdout)
        client._next_id = 1
        client.stop()
        assert client._proc is None

    def test_stop_when_already_stopped_is_noop(self):
        client = LspClient(["dummy"], root_uri="file:///repo")
        client.stop()  # should not raise

    def test_notifications_buffered_during_wait(self):
        notif = {"jsonrpc": "2.0", "method": "window/logMessage",
                 "params": {"type": 3, "message": "loading"}}
        response = _init_response(1)
        stdout = _stream(notif, response)
        client, _ = self._make_client(stdout)
        client._initialize()
        assert len(client.notifications) == 1
        assert client.notifications[0]["method"] == "window/logMessage"

    def test_server_error_response_raises(self):
        err_response = {
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        }
        stdout = _stream(err_response)
        client, _ = self._make_client(stdout)
        with pytest.raises(LspError, match="error"):
            client._request("unsupported/method")

    def test_context_manager_calls_start_and_stop(self):
        init_resp = _init_response(1)
        shutdown_resp = _shutdown_response(2)
        proc = _mock_proc(_stream(init_resp, shutdown_resp))

        with patch("subprocess.Popen", return_value=proc):
            with LspClient(["dummy"], root_uri="file:///repo") as client:
                assert client._proc is proc
        assert client._proc is None

    def test_start_sends_initialize_to_real_proc_shape(self):
        """start() calls Popen with the given cmd and pipe flags."""
        init_resp = _init_response(1)
        proc = _mock_proc(_stream(init_resp))

        with patch("subprocess.Popen", return_value=proc) as mock_popen:
            client = LspClient(["pyright", "--stdio"], root_uri="file:///x")
            client.start()
            client._proc = None  # skip stop()

        mock_popen.assert_called_once()
        kwargs = mock_popen.call_args
        assert kwargs[0][0] == ["pyright", "--stdio"]


# ---------------------------------------------------------------------------
# did_open / did_close / collect_diagnostics / open_files
# ---------------------------------------------------------------------------

def _diag_notif(uri: str, diagnostics: list) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {"uri": uri, "diagnostics": diagnostics},
    }


def _doc_symbol_response(req_id: int) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": []}


class TestDidOpen:
    def _make_client(self, stdout_bytes: bytes) -> tuple[LspClient, MagicMock]:
        proc = _mock_proc(stdout_bytes)
        client = LspClient(["dummy-lsp", "--stdio"], root_uri="file:///repo")
        client._proc = proc
        client._next_id = 1
        client._start_reader()
        return client, proc

    def _sent_messages(self, proc: MagicMock) -> list[dict]:
        result = []
        for c in proc.stdin.write.call_args_list:
            _, _, body = c[0][0].partition(b"\r\n\r\n")
            result.append(json.loads(body))
        return result

    # -- did_open --

    def test_did_open_sends_notification(self):
        client, proc = self._make_client(b"")
        client.did_open("file:///repo/main.py", "x = 1\n", "python")
        assert proc.stdin.write.call_count == 1
        msg = self._sent_messages(proc)[0]
        assert msg["method"] == "textDocument/didOpen"
        assert "id" not in msg
        td = msg["params"]["textDocument"]
        assert td["uri"] == "file:///repo/main.py"
        assert td["languageId"] == "python"
        assert td["text"] == "x = 1\n"
        assert td["version"] == 1

    def test_did_open_different_language_ids(self):
        for lang in ("typescript", "java", "go"):
            client, proc = self._make_client(b"")
            client.did_open("file:///repo/f", "x", lang)
            msg = self._sent_messages(proc)[0]
            assert msg["params"]["textDocument"]["languageId"] == lang

    # -- did_close --

    def test_did_close_sends_notification(self):
        client, proc = self._make_client(b"")
        client.did_close("file:///repo/main.py")
        msg = self._sent_messages(proc)[0]
        assert msg["method"] == "textDocument/didClose"
        assert "id" not in msg
        assert msg["params"]["textDocument"]["uri"] == "file:///repo/main.py"

    # -- collect_diagnostics --

    def test_collect_diagnostics_extracts_publish_diagnostics(self):
        client, _ = self._make_client(b"")
        client.notifications = [
            _diag_notif("file:///repo/a.py", [{"message": "undefined name"}])
        ]
        result = client.collect_diagnostics()
        assert "file:///repo/a.py" in result
        assert result["file:///repo/a.py"][0]["message"] == "undefined name"

    def test_collect_diagnostics_removes_diagnostic_notifications_by_default(self):
        client, _ = self._make_client(b"")
        client.notifications = [
            _diag_notif("file:///a.py", []),
            {"jsonrpc": "2.0", "method": "window/logMessage",
             "params": {"type": 3, "message": "log"}},
        ]
        client.collect_diagnostics(clear=True)
        assert len(client.notifications) == 1
        assert client.notifications[0]["method"] == "window/logMessage"

    def test_collect_diagnostics_no_clear_leaves_notifications(self):
        client, _ = self._make_client(b"")
        client.notifications = [_diag_notif("file:///a.py", [])]
        client.collect_diagnostics(clear=False)
        assert len(client.notifications) == 1

    def test_collect_diagnostics_empty_notifications_returns_empty(self):
        client, _ = self._make_client(b"")
        assert client.collect_diagnostics() == {}

    def test_collect_diagnostics_multiple_files(self):
        client, _ = self._make_client(b"")
        client.notifications = [
            _diag_notif("file:///a.py", [{"message": "err1"}]),
            _diag_notif("file:///b.py", [{"message": "err2"}]),
        ]
        result = client.collect_diagnostics()
        assert len(result) == 2
        assert result["file:///a.py"][0]["message"] == "err1"
        assert result["file:///b.py"][0]["message"] == "err2"

    # -- open_files --

    def test_open_files_empty_returns_empty(self):
        client, _ = self._make_client(b"")
        assert client.open_files([]) == {}

    def test_open_files_sends_did_open_for_each_file(self):
        client, proc = self._make_client(_stream(_doc_symbol_response(1)))
        files = [
            ("file:///repo/a.py", "a = 1", "python"),
            ("file:///repo/b.py", "b = 2", "python"),
        ]
        client.open_files(files)
        msgs = self._sent_messages(proc)
        # 2 didOpen notifications + 1 documentSymbol request
        assert len(msgs) == 3
        assert msgs[0]["method"] == "textDocument/didOpen"
        assert msgs[1]["method"] == "textDocument/didOpen"
        assert msgs[2]["method"] == "textDocument/documentSymbol"

    def test_open_files_doc_symbol_targets_last_file(self):
        client, proc = self._make_client(_stream(_doc_symbol_response(1)))
        files = [
            ("file:///repo/a.py", "a=1", "python"),
            ("file:///repo/b.py", "b=2", "python"),
        ]
        client.open_files(files)
        msgs = self._sent_messages(proc)
        ds_params = msgs[2]["params"]
        assert ds_params["textDocument"]["uri"] == "file:///repo/b.py"

    def test_open_files_collects_push_diagnostics(self):
        diag = _diag_notif(
            "file:///repo/main.py",
            [{"message": "type error", "severity": 1}],
        )
        client, _ = self._make_client(_stream(diag, _doc_symbol_response(1)))
        result = client.open_files([("file:///repo/main.py", "x: int = 'bad'", "python")])
        assert "file:///repo/main.py" in result
        assert result["file:///repo/main.py"][0]["message"] == "type error"

    def test_open_files_no_diagnostics_returns_empty_dict(self):
        client, _ = self._make_client(_stream(_doc_symbol_response(1)))
        result = client.open_files([("file:///repo/ok.py", "x = 1", "python")])
        assert result == {}

    def test_open_files_tolerates_doc_symbol_error(self):
        """If documentSymbol returns an error, open_files still returns diagnostics."""
        diag = _diag_notif("file:///repo/x.py", [])
        err_resp = {
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        }
        client, _ = self._make_client(_stream(diag, err_resp))
        result = client.open_files([("file:///repo/x.py", "x=1", "python")])
        assert "file:///repo/x.py" in result


# ---------------------------------------------------------------------------
# Call hierarchy: prepareCallHierarchy / incomingCalls / get_incoming_calls
# ---------------------------------------------------------------------------

def _call_hierarchy_item(name: str = "do_thing", uri: str = "file:///repo/a.py") -> dict:
    return {
        "name": name,
        "kind": 12,  # Function
        "uri": uri,
        "range": {"start": {"line": 4, "character": 0}, "end": {"line": 6, "character": 0}},
        "selectionRange": {"start": {"line": 4, "character": 4}, "end": {"line": 4, "character": 12}},
    }


def _prepare_response(req_id: int, items) -> dict:
    """items may be None or a list of CallHierarchyItem dicts."""
    return {"jsonrpc": "2.0", "id": req_id, "result": items}


def _incoming_response(req_id: int, calls) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": calls}


class TestCallHierarchy:
    def _make_client(self, stdout_bytes: bytes) -> tuple[LspClient, MagicMock]:
        proc = _mock_proc(stdout_bytes)
        client = LspClient(["dummy-lsp", "--stdio"], root_uri="file:///repo")
        client._proc = proc
        client._next_id = 1
        client._start_reader()
        return client, proc

    def _sent_messages(self, proc: MagicMock) -> list[dict]:
        result = []
        for c in proc.stdin.write.call_args_list:
            _, _, body = c[0][0].partition(b"\r\n\r\n")
            result.append(json.loads(body))
        return result

    # -- prepare_call_hierarchy --

    def test_prepare_sends_correct_method_and_params(self):
        client, proc = self._make_client(_stream(_prepare_response(1, None)))
        client.prepare_call_hierarchy("file:///repo/a.py", line=4, character=6)
        msg = self._sent_messages(proc)[0]
        assert msg["method"] == "textDocument/prepareCallHierarchy"
        assert msg["params"]["textDocument"]["uri"] == "file:///repo/a.py"
        assert msg["params"]["position"] == {"line": 4, "character": 6}

    def test_prepare_returns_none_when_server_returns_null(self):
        client, _ = self._make_client(_stream(_prepare_response(1, None)))
        result = client.prepare_call_hierarchy("file:///repo/a.py", 0, 0)
        assert result is None

    def test_prepare_returns_empty_list(self):
        client, _ = self._make_client(_stream(_prepare_response(1, [])))
        result = client.prepare_call_hierarchy("file:///repo/a.py", 0, 0)
        assert result == []

    def test_prepare_returns_items(self):
        item = _call_hierarchy_item("my_func")
        client, _ = self._make_client(_stream(_prepare_response(1, [item])))
        result = client.prepare_call_hierarchy("file:///repo/a.py", 4, 6)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "my_func"

    # -- incoming_calls --

    def test_incoming_calls_sends_item_in_params(self):
        item = _call_hierarchy_item("do_thing")
        client, proc = self._make_client(_stream(_incoming_response(1, [])))
        client.incoming_calls(item)
        msg = self._sent_messages(proc)[0]
        assert msg["method"] == "callHierarchy/incomingCalls"
        assert msg["params"]["item"]["name"] == "do_thing"

    def test_incoming_calls_returns_empty_when_null(self):
        item = _call_hierarchy_item()
        client, _ = self._make_client(_stream(_incoming_response(1, None)))
        assert client.incoming_calls(item) == []

    def test_incoming_calls_returns_list(self):
        item = _call_hierarchy_item("do_thing")
        caller_item = _call_hierarchy_item("caller", uri="file:///repo/b.py")
        call = {
            "from": caller_item,
            "fromRanges": [{"start": {"line": 10, "character": 4}, "end": {"line": 10, "character": 12}}],
        }
        client, _ = self._make_client(_stream(_incoming_response(1, [call])))
        result = client.incoming_calls(item)
        assert len(result) == 1
        assert result[0]["from"]["name"] == "caller"
        assert result[0]["from"]["uri"] == "file:///repo/b.py"

    # -- get_incoming_calls --

    def test_get_incoming_calls_returns_empty_when_prepare_returns_none(self):
        client, _ = self._make_client(_stream(_prepare_response(1, None)))
        result = client.get_incoming_calls("file:///repo/a.py", 4, 6)
        assert result == []

    def test_get_incoming_calls_returns_empty_when_prepare_returns_empty_list(self):
        client, _ = self._make_client(_stream(_prepare_response(1, [])))
        result = client.get_incoming_calls("file:///repo/a.py", 4, 6)
        assert result == []

    def test_get_incoming_calls_uses_first_item_from_prepare(self):
        item1 = _call_hierarchy_item("func_a")
        item2 = _call_hierarchy_item("func_b")
        caller_item = _call_hierarchy_item("caller", uri="file:///repo/b.py")
        incoming = [{"from": caller_item, "fromRanges": []}]
        client, proc = self._make_client(
            _stream(_prepare_response(1, [item1, item2]), _incoming_response(2, incoming))
        )
        result = client.get_incoming_calls("file:///repo/a.py", 4, 6)
        # The incomingCalls request should carry item1 (not item2)
        msgs = self._sent_messages(proc)
        assert msgs[1]["params"]["item"]["name"] == "func_a"
        assert len(result) == 1

    def test_get_incoming_calls_end_to_end(self):
        item = _call_hierarchy_item("validate")
        caller = _call_hierarchy_item("process", uri="file:///repo/processor.py")
        incoming = [{"from": caller, "fromRanges": []}]
        client, _ = self._make_client(
            _stream(_prepare_response(1, [item]), _incoming_response(2, incoming))
        )
        result = client.get_incoming_calls("file:///repo/a.py", 10, 4)
        assert len(result) == 1
        assert result[0]["from"]["name"] == "process"


# ---------------------------------------------------------------------------
# references (textDocument/references — fallback for non-callable symbols)
# ---------------------------------------------------------------------------

def _references_response(req_id: int, locations) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": locations}


def _location(uri: str = "file:///repo/a.py", line: int = 5) -> dict:
    return {
        "uri": uri,
        "range": {
            "start": {"line": line, "character": 4},
            "end": {"line": line, "character": 12},
        },
    }


class TestReferences:
    def _make_client(self, stdout_bytes: bytes) -> tuple[LspClient, MagicMock]:
        proc = _mock_proc(stdout_bytes)
        client = LspClient(["dummy-lsp", "--stdio"], root_uri="file:///repo")
        client._proc = proc
        client._next_id = 1
        client._start_reader()
        return client, proc

    def _sent_messages(self, proc: MagicMock) -> list[dict]:
        result = []
        for c in proc.stdin.write.call_args_list:
            _, _, body = c[0][0].partition(b"\r\n\r\n")
            result.append(json.loads(body))
        return result

    def test_sends_correct_method(self):
        client, proc = self._make_client(_stream(_references_response(1, [])))
        client.references("file:///repo/a.py", line=3, character=8)
        msg = self._sent_messages(proc)[0]
        assert msg["method"] == "textDocument/references"

    def test_sends_correct_params(self):
        client, proc = self._make_client(_stream(_references_response(1, [])))
        client.references("file:///repo/a.py", line=3, character=8)
        msg = self._sent_messages(proc)[0]
        assert msg["params"]["textDocument"]["uri"] == "file:///repo/a.py"
        assert msg["params"]["position"] == {"line": 3, "character": 8}

    def test_default_include_declaration_is_false(self):
        client, proc = self._make_client(_stream(_references_response(1, [])))
        client.references("file:///repo/a.py", 0, 0)
        msg = self._sent_messages(proc)[0]
        assert msg["params"]["context"]["includeDeclaration"] is False

    def test_include_declaration_true_passes_through(self):
        client, proc = self._make_client(_stream(_references_response(1, [])))
        client.references("file:///repo/a.py", 0, 0, include_declaration=True)
        msg = self._sent_messages(proc)[0]
        assert msg["params"]["context"]["includeDeclaration"] is True

    def test_returns_empty_when_null(self):
        client, _ = self._make_client(_stream(_references_response(1, None)))
        assert client.references("file:///repo/a.py", 0, 0) == []

    def test_returns_empty_when_empty_list(self):
        client, _ = self._make_client(_stream(_references_response(1, [])))
        assert client.references("file:///repo/a.py", 0, 0) == []

    def test_returns_locations(self):
        locs = [_location("file:///repo/b.py", 10), _location("file:///repo/c.py", 20)]
        client, _ = self._make_client(_stream(_references_response(1, locs)))
        result = client.references("file:///repo/a.py", 5, 4)
        assert len(result) == 2
        assert result[0]["uri"] == "file:///repo/b.py"
        assert result[1]["range"]["start"]["line"] == 20

    def test_location_shape(self):
        """Each location has uri and range with start/end positions."""
        loc = _location("file:///repo/x.py", 7)
        client, _ = self._make_client(_stream(_references_response(1, [loc])))
        result = client.references("file:///repo/a.py", 0, 0)
        assert "uri" in result[0]
        assert "range" in result[0]
        assert "start" in result[0]["range"]
        assert "end" in result[0]["range"]
