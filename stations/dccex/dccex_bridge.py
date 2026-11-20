import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from stations.bridge import StationBridge
from stations.dccex import dccex_protocol as p
from stations.dccex.dccex_client import DccexClient


class DccexBridge(StationBridge):
    """DCC-EX over WiFi (TCP).

    use_id=True  : "Turnout ID" mode. The tile's ID is the turnout id defined on the board.
                   <T id state> is answered and broadcast with <H id state>, so the panel
                   follows the board, including changes from other throttles.
    use_id=False : "DCC address" mode. Raw accessory commands <a address state>; the board
                   never answers, so the panel shows what was commanded (no feedback).
    """
    PING_SECONDS = 5        # heartbeat: <JT> is answered on every board and changes nothing
    SILENCE_SECONDS = 15    # no message at all for this long = connection lost
    CONNECT_TIMEOUT = 3     # how long to wait for an answer to <s> after connecting

    def __init__(self, host, port=p.DEFAULT_PORT, use_id=False):
        super().__init__()
        self.host = host.strip()
        self.port = port
        self.use_id = use_id
        self.client = None
        self._token = None                    # identifies the current connection
        self._last_message = time.monotonic()
        self._got_message = threading.Event()
        self._heartbeat_stop = threading.Event()
        self._sender = ThreadPoolExecutor(max_workers=1)

    # ---- hooks (see StationBridge) --------------------------------------

    def _open(self):
        token = object()
        self._token = token
        self._last_message = time.monotonic()
        self._got_message.clear()
        client = DccexClient(
            self.host, self._on_message, lambda: self._client_lost(token), self.port
        )
        # <s> is the whole resync: it answers with the version, the power state and the
        # position of every turnout, all of which arrive through _on_message. It also
        # proves somebody is home, which a bare TCP connection does not.
        try:
            client.send("<s>")
        except OSError:
            self._token = None
            client.close()
            raise
        if not self._got_message.wait(self.CONNECT_TIMEOUT):
            self._token = None
            client.close()
            raise TimeoutError("connected, but the DCC-EX is not answering")
        self.client = client
        self._start_heartbeat(client, token)

    def _close(self):
        self._token = None                    # a late disconnect callback is now ignored
        self._heartbeat_stop.set()
        client, self.client = self.client, None
        if client is not None:
            client.close()

    def _send_turnout(self, address, protocol, diverging):
        if self.client is None:
            raise ConnectionError("not connected")
        if self.use_id:
            command = p.turnout_command(address, diverging)     # ValueError if out of range
        else:
            if protocol != "DCC":
                raise ValueError("DCC-EX can only switch DCC accessories")
            command = p.accessory_command(address, diverging)
        self._sender.submit(
            self._do_send, self.client, self._token, command, address, diverging
        )

    def _send_power(self, on):
        if self.client is None:
            raise ConnectionError("not connected")
        self._sender.submit(self._do_command, self.client, self._token, p.power_command(on))

    # ---- sending (runs on the sender thread, never the UI thread) --------

    def _do_send(self, client, token, command, address, diverging):
        if not self._do_command(client, token, command):
            return
        if not self.use_id:
            # No answer will ever come, so the bridge reports what it just commanded.
            # (Emitted from this thread: delivered later on the main thread, i.e. after
            # the tap that caused it has finished.)
            self.turnout_changed.emit(address, "DCC", diverging)

    def _do_command(self, client, token, command):
        try:
            client.send(command)
        except OSError:
            self._client_lost(token)
            return False
        return True

    # ---- incoming (runs on the client's reader thread) -------------------

    def _on_message(self, body):
        self._last_message = time.monotonic()
        self._got_message.set()
        try:
            parsed = p.parse(body)
            if parsed is None:
                return
            if parsed[0] == "turnout" and self.use_id:
                # In DCC address mode the ids in <H> are not addresses: ignore them.
                self.turnout_changed.emit(parsed[1], "DCC", parsed[2])
            elif parsed[0] == "power":
                self.report_power(parsed[1])
            elif parsed[0] == "refused":
                print("DCC-EX answered <X>: a command was refused"
                      + (" (is that turnout id defined on the board?)" if self.use_id else ""))
        except Exception:
            traceback.print_exc()             # never let a bug kill the reader thread

    def _client_lost(self, token):
        if token is self._token:              # ignore callbacks from old connections
            self.report_lost()

    # ---- heartbeat -------------------------------------------------------

    def _start_heartbeat(self, client, token):
        self._heartbeat_stop = stop = threading.Event()

        def run():
            while not stop.wait(self.PING_SECONDS):
                if time.monotonic() - self._last_message > self.SILENCE_SECONDS:
                    self._client_lost(token)
                    return
                try:
                    client.send("<JT>")
                except OSError:
                    self._client_lost(token)
                    return

        threading.Thread(target=run, daemon=True).start()