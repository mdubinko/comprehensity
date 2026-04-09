"""
lsp_client.py — minimal synchronous LSP client over stdio

JSON-RPC 2.0 transport over subprocess stdin/stdout. No asyncio — one thread,
synchronous request/response with interleaved notification buffering.

A background reader thread drains the server's stdout into a queue so that
``_wait_for`` can apply a per-request timeout without blocking the main thread
forever.  The default timeout is 120 s per request; pass ``request_timeout_s``
to ``__init__`` to override.

Usage::

    with LspClient(["pyright", "--stdio"], root_uri="file:///path/to/repo") as client:
        # client is initialized; ready for file-level requests
        ...
    # shutdown/exit sent automatically on context exit
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class LspError(Exception):
    """Raised for LSP-level errors (server error responses, framing failures)."""


# ---------------------------------------------------------------------------
# Framing helpers (module-level so tests can call them without a live process)
# ---------------------------------------------------------------------------

def encode_message(msg: Dict) -> bytes:
    """Encode a JSON-RPC message with Content-Length framing."""
    body = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def read_message(stream) -> Dict:
    """Read one Content-Length-framed JSON-RPC message from *stream*.

    *stream* must support ``readline()`` and ``read(n)`` returning ``bytes``.
    Raises ``LspError`` on framing errors or if the stream closes.
    """
    content_length: Optional[int] = None

    while True:
        raw = stream.readline()
        if not raw:
            raise LspError("Server closed connection unexpectedly")
        line = raw.decode("ascii").rstrip("\r\n")
        if line == "":
            break  # blank line signals end of headers
        key, _, value = line.partition(":")
        if key.lower() == "content-length":
            content_length = int(value.strip())

    if content_length is None:
        raise LspError("LSP message missing Content-Length header")

    body = stream.read(content_length)
    if len(body) < content_length:
        raise LspError(
            f"Short read: expected {content_length} bytes, got {len(body)}"
        )
    return json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class LspClient:
    """Synchronous LSP client for one language server subprocess.

    Lifecycle::

        client = LspClient(cmd, root_uri)
        client.start()          # launches subprocess, runs initialize handshake
        ...                     # issue requests here (added in later bites)
        client.stop()           # sends shutdown/exit, waits for process to end

    Or use as a context manager (preferred).

    Attributes:
        notifications: list of push notifications buffered while waiting for
                       synchronous responses (e.g. publishDiagnostics).
    """

    #: Default per-request read timeout in seconds.
    DEFAULT_REQUEST_TIMEOUT_S: float = 120.0

    def __init__(
        self,
        cmd: List[str],
        root_uri: str,
        initialization_options: Optional[Dict] = None,
        request_timeout_s: Optional[float] = None,
    ) -> None:
        self._cmd = cmd
        self._root_uri = root_uri
        self._initialization_options = initialization_options
        self._request_timeout = (
            request_timeout_s
            if request_timeout_s is not None
            else self.DEFAULT_REQUEST_TIMEOUT_S
        )
        self._next_id: int = 1
        self._proc: Optional[subprocess.Popen] = None
        self.notifications: List[Dict] = []
        # Background reader thread drains stdout → queue so _wait_for can timeout.
        self._msg_queue: queue.Queue = queue.Queue()
        self._reader_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Low-level send / receive
    # ------------------------------------------------------------------

    def _send(self, msg: Dict) -> None:
        assert self._proc is not None
        self._proc.stdin.write(encode_message(msg))
        self._proc.stdin.flush()

    def _notify(self, method: str, params: Any = None) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        msg: Dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    def _request(self, method: str, params: Any = None) -> Any:
        """Send a request and block until the matching response arrives.

        Interleaved notifications are appended to ``self.notifications``.
        Raises ``LspError`` if the server returns an error object.
        """
        req_id = self._next_id
        self._next_id += 1
        msg: Dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)
        return self._wait_for(req_id)

    def _wait_for(self, req_id: int) -> Any:
        """Read messages until response matching *req_id* arrives.

        Raises ``LspError`` if no matching response arrives within
        ``self._request_timeout`` seconds.
        """
        deadline = time.monotonic() + self._request_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LspError(
                    f"Timed out after {self._request_timeout:.0f}s waiting "
                    f"for response to request {req_id}"
                )
            try:
                msg = self._msg_queue.get(timeout=remaining)
            except queue.Empty:
                raise LspError(
                    f"Timed out after {self._request_timeout:.0f}s waiting "
                    f"for response to request {req_id}"
                )
            if isinstance(msg, Exception):
                raise LspError(f"Reader thread error: {msg}") from msg
            if "id" in msg and msg["id"] == req_id:
                if "error" in msg:
                    raise LspError(f"Server returned error: {msg['error']}")
                return msg.get("result")
            # notification or mismatched response — buffer it
            self.notifications.append(msg)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _start_reader(self) -> None:
        """Spawn the background thread that drains server stdout into the queue."""
        def _reader_loop() -> None:
            try:
                while True:
                    msg = read_message(self._proc.stdout)  # type: ignore[union-attr]
                    self._msg_queue.put(msg)
            except Exception as exc:  # noqa: BLE001
                self._msg_queue.put(exc)

        self._reader_thread = threading.Thread(
            target=_reader_loop, daemon=True, name="lsp-reader"
        )
        self._reader_thread.start()

    def start(self) -> None:
        """Launch the server subprocess and run the initialize handshake."""
        self._proc = subprocess.Popen(
            self._cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._start_reader()
        self._initialize()

    def _initialize(self) -> None:
        self._request("initialize", {
            "processId": os.getpid(),
            "rootUri": self._root_uri,
            "capabilities": {},
            "initializationOptions": self._initialization_options or {},
        })
        self._notify("initialized", {})

    def stop(self) -> None:
        """Send shutdown/exit and wait for the process to terminate."""
        if self._proc is None:
            return
        try:
            self._request("shutdown")
            self._notify("exit")
            self._proc.stdin.close()
            self._proc.wait(timeout=10)
        except Exception:
            self._proc.kill()
            self._proc.wait()
        finally:
            self._proc = None

    # ------------------------------------------------------------------
    # Document management
    # ------------------------------------------------------------------

    def did_open(self, uri: str, text: str, language_id: str) -> None:
        """Send textDocument/didOpen notification.

        Must be called before any per-file request. Triggers
        textDocument/publishDiagnostics push notifications from the server.
        """
        self._notify("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": language_id,
                "version": 1,
                "text": text,
            }
        })

    def did_close(self, uri: str) -> None:
        """Send textDocument/didClose notification."""
        self._notify("textDocument/didClose", {
            "textDocument": {"uri": uri}
        })

    def collect_diagnostics(self, clear: bool = True) -> Dict[str, List[Dict]]:
        """Extract publishDiagnostics from buffered notifications.

        Returns a dict mapping file URI to list of diagnostic dicts.
        With *clear=True* (default), processed diagnostic notifications are
        removed from ``self.notifications``; other notifications are retained.
        """
        result: Dict[str, List[Dict]] = {}
        remaining = []
        for msg in self.notifications:
            if msg.get("method") == "textDocument/publishDiagnostics":
                params = msg.get("params", {})
                uri = params.get("uri", "")
                result[uri] = params.get("diagnostics", [])
            else:
                remaining.append(msg)
        if clear:
            self.notifications = remaining
        return result

    def open_files(
        self, files: List[Tuple[str, str, str]]
    ) -> Dict[str, List[Dict]]:
        """Open *files* and return push diagnostics keyed by URI.

        Sends textDocument/didOpen for every file, then issues a
        textDocument/documentSymbol request on the last file as a sync point
        so that publishDiagnostics notifications emitted before the response
        are captured.

        Args:
            files: sequence of (uri, text, language_id) tuples.

        Returns:
            dict mapping file URI → list of diagnostic dicts (may be empty).
        """
        if not files:
            return {}
        for uri, text, lang_id in files:
            self.did_open(uri, text, lang_id)
        last_uri = files[-1][0]
        try:
            self._request("textDocument/documentSymbol", {
                "textDocument": {"uri": last_uri}
            })
        except LspError:
            pass  # server may not support documentSymbol; diagnostics still buffered
        return self.collect_diagnostics()

    # ------------------------------------------------------------------
    # Call hierarchy
    # ------------------------------------------------------------------

    def prepare_call_hierarchy(
        self, uri: str, line: int, character: int
    ) -> Optional[List[Dict]]:
        """Send textDocument/prepareCallHierarchy.

        Returns a (possibly empty) list of ``CallHierarchyItem`` dicts, or
        ``None`` if the server returned null (symbol not found or not supported).
        """
        return self._request("textDocument/prepareCallHierarchy", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })

    def incoming_calls(self, item: Dict) -> List[Dict]:
        """Send callHierarchy/incomingCalls for a ``CallHierarchyItem``.

        Returns a list of ``CallHierarchyIncomingCall`` dicts, or ``[]`` if
        the server returned null.
        """
        result = self._request("callHierarchy/incomingCalls", {"item": item})
        return result or []

    def get_incoming_calls(
        self, uri: str, line: int, character: int
    ) -> List[Dict]:
        """Prepare call hierarchy and return incoming calls for the symbol.

        Combines :meth:`prepare_call_hierarchy` and :meth:`incoming_calls` into
        one operation. Returns ``[]`` if no symbol is found at the given
        position or the server does not support call hierarchy.
        """
        items = self.prepare_call_hierarchy(uri, line, character)
        if not items:
            return []
        return self.incoming_calls(items[0])

    # ------------------------------------------------------------------
    # References (fallback for non-callable symbols)
    # ------------------------------------------------------------------

    def references(
        self,
        uri: str,
        line: int,
        character: int,
        include_declaration: bool = False,
    ) -> List[Dict]:
        """Send textDocument/references.

        Returns a list of ``Location`` dicts (each with ``uri`` and ``range``),
        or ``[]`` if the server returned null or found nothing.

        Use as a fallback when :meth:`prepare_call_hierarchy` returns None
        (e.g. for class definitions, variables, or servers that don't support
        call hierarchy).

        Args:
            include_declaration: whether to include the symbol's own definition
                site in the results. Defaults to ``False``.
        """
        result = self._request("textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": include_declaration},
        })
        return result or []

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> LspClient:
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()
