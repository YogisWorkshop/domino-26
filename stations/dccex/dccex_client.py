"""DCC-EX client: a background thread reads messages, the main program sends."""

import socket
import threading

from stations.dccex import dccex_protocol


class DccexClient:
    def __init__(self, host, on_message, on_disconnect, port=dccex_protocol.DEFAULT_PORT):
        self.on_message = on_message
        self.on_disconnect = on_disconnect
        self._send_lock = threading.Lock()
        self.sock = socket.create_connection((host, port), timeout=3)
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self):
        buffer = ""
        try:
            while True:
                try:
                    data = self.sock.recv(1024)
                except socket.timeout:
                    continue
                if not data:
                    break                       # the board closed the connection
                buffer += data.decode(errors="replace")
                messages, buffer = dccex_protocol.split_messages(buffer)
                for body in messages:
                    self.on_message(body)
        except OSError:
            pass
        self.on_disconnect()

    def send(self, text):
        with self._send_lock:
            self.sock.sendall(text.encode())

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
        self.reader.join(timeout=1)