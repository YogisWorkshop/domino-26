"""A pretend CS3 for testing without hardware.  python -m tools.fake_cs3

Everything the app sends is printed in readable form, with a note on how the fake
answered. The ping (every 5 s) is hidden unless you turn on verbose (v).

Console: t <addr> r|g [mm] = throw a turnout "on the CS3 screen"
         go / stop = press the CS3 screen's power button
         list = show the turnouts the fake knows about and the power state
         v = show / hide the ping, h = help
         d = drop all connections, s = go silent / answer again, q = quit
"""
import socket
import sys
import threading
import time

from stations.cs3 import cs3_protocol as p

PORT = p.CS3_PORT
_print_lock = threading.Lock()


def log(text):
    with _print_lock:
        print(f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}  {text}", flush=True)


GUI_HASH = 0xB326            # what the CS3 screen uses as sender
TRACK_HASH = 0x8B3F          # the track processor, which confirms every command


class FakeCs3:
    def __init__(self, port=PORT):
        self.silent = False
        self.verbose = False
        self.numbers = {}
        self.power = None
        self.clients = []
        self.positions = {}                    # (protocol, address) -> 0 / 1
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", port))
        self.server.listen()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                sock, _ = self.server.accept()
            except OSError:
                return
            self.clients.append(sock)
            self.numbers[sock] = f"#{len(self.numbers) + 1}"
            log(f"{self.numbers[sock]} connected ({len(self.clients)} client(s))")
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _serve(self, sock):
        framer = p.Framer()
        who = self.numbers.get(sock, "?")
        try:
            while True:
                data = sock.recv(1024)
                if not data:
                    log(f"{who} closed by the app")
                    if sock in self.clients:
                        self.clients.remove(sock)
                    return
                for frame in framer.feed(data):
                    self._handle(frame, who)
        except OSError:
            pass

    def broadcast(self, frame):
        for client in list(self.clients):
            try:
                client.sendall(frame.to_bytes())
            except OSError:
                pass

    def _handle(self, frame, who="?"):
        if frame.response:
            return                             # the fake only listens to commands
        decoded = p.decode(frame)
        is_ping = frame.command == p.CMD_PING
        if decoded is not None:
            text = str(decoded)
        else:
            name = p.COMMAND_NAMES.get(frame.command, f"command 0x{frame.command:02x}")
            text = f"{name}  data {frame.data.hex(' ')}"
        if not (is_ping and not self.verbose):
            log(f"{who} -> {text}{'   (ignored, fake is silent)' if self.silent else ''}")
        if self.silent:
            return
        if is_ping:
            reply = bytes.fromhex("6373f555") + bytes([2, 5]) + (0xFFFF).to_bytes(2, "big")
            self.broadcast(p.Frame(p.CMD_PING, True, GUI_HASH, reply))
            if self.verbose:
                log("     ping answered")
        elif frame.command == p.CMD_ACCESSORY:
            self._confirm(frame)
        elif frame.command == p.CMD_SYSTEM and len(frame.data) >= 5:
            self._confirm_power(frame)
        elif not is_ping:
            log("     not answered (the fake only knows ping, accessory, GO and STOP)")

    def _confirm_power(self, frame):
        """Only GO and STOP are answered. Like the real CS3: confirmed twice."""
        if frame.data[4] not in (p.SUB_GO, p.SUB_STOP):
            return
        self.power = frame.data[4] == p.SUB_GO
        log(f"     power is now {'GO' if self.power else 'STOP'}; confirmed twice to "
            f"{len(self.clients)} client(s)")
        self.broadcast(p.Frame(p.CMD_SYSTEM, True, TRACK_HASH, frame.data))
        self.broadcast(p.Frame(p.CMD_SYSTEM, True, TRACK_HASH, frame.data))

    def screen_power(self, go):
        """The GO/STOP button on the CS3 screen."""
        frame = p.system_frame(p.SUB_GO if go else p.SUB_STOP)
        frame.hash_code = GUI_HASH
        self.broadcast(frame)
        self._confirm_power(frame)

    def _confirm(self, frame):
        decoded = p.decode(frame)
        self.positions[(decoded.protocol, decoded.address)] = decoded.position
        if decoded.current:
            log(f"     {decoded.protocol} {decoded.address} -> {'r' if decoded.position == 0 else 'g'}"
                f"; confirmation sent to {len(self.clients)} client(s)")
        self.broadcast(p.Frame(frame.command, True, TRACK_HASH, frame.data))
        if decoded.switch_time:                # the CS3 reports the OFF itself
            off = frame.data[:4] + bytes([decoded.position, 0])
            threading.Timer(0.1, self.broadcast,
                            [p.Frame(frame.command, True, TRACK_HASH, off)]).start()

    def screen_throw(self, address, protocol, position):
        """A throw from the CS3 screen: ON + OFF, each confirmed."""
        on = p.accessory_frame(address, position, 1, protocol)
        off = p.accessory_frame(address, position, 0, protocol)
        for frame in (on, off):
            frame.hash_code = GUI_HASH
            self.broadcast(frame)
            self._confirm(frame)

    def show(self):
        power = {None: "unknown", True: "GO", False: "STOP"}[self.power]
        log(f"power {power}; {len(self.clients)} client(s); "
            f"{'SILENT' if self.silent else 'answering'}")
        if not self.positions:
            log("     no turnout has been switched yet")
        for (protocol, address), position in sorted(self.positions.items()):
            log(f"     {protocol:<3} {address:<4}  {'r' if position == 0 else 'g'}")

    def drop_all(self):
        log(f"dropping {len(self.clients)} connection(s)")
        for client in self.clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except OSError:
                pass
        self.clients.clear()


HELP = """  t <addr> r|g [mm]   throw a turnout on the CS3 screen (default DCC)
  go / stop           the CS3 screen's power button
  list                turnouts switched so far, power, clients
  v                   show / hide the ping
  d                   drop all connections
  s                   go silent / answer again
  q                   quit"""

if __name__ == "__main__":
    cs3 = FakeCs3()
    log(f"Fake CS3 on port {PORT}.  Type h for the commands.")
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        if parts[0] in ("go", "stop"):
            log(f"CS3 screen: {parts[0].upper()}")
            cs3.screen_power(parts[0] == "go")
        elif parts[0] == "d":
            cs3.drop_all()
        elif parts[0] == "s":
            cs3.silent = not cs3.silent
            log("silent" if cs3.silent else "answering")
        elif parts[0] == "v":
            cs3.verbose = not cs3.verbose
            log("ping shown" if cs3.verbose else "ping hidden")
        elif parts[0] == "list":
            cs3.show()
        elif parts[0] in ("h", "help", "?"):
            print(HELP)
        elif parts[0] == "t" and len(parts) in (3, 4) and parts[1].isdigit() and parts[2] in ("r", "g"):
            protocol = "MM" if len(parts) == 4 and parts[3].lower() == "mm" else "DCC"
            log(f"CS3 screen: {protocol} {parts[1]} {parts[2]}")
            cs3.screen_throw(int(parts[1]), protocol, 0 if parts[2] == "r" else 1)
        elif parts[0] == "q":
            break
        else:
            print("?  (h = help)")