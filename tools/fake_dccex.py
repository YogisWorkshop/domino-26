"""A pretend DCC-EX EX-CommandStation for testing without hardware.  python tools/fake_dccex.py

It answers like the real board did in lab/dccex/probe_dccex.py. Everything the app sends is
printed, with a note on what it did. The heartbeat (<JT> every few seconds) is hidden unless
you turn on verbose (v).

Console: t <id> r|g   = throw (r) / close (g) a turnout "from another throttle"
         go / stop    = track power from another throttle
         list         = show the turnouts, the raw accessory commands received, and power
         v            = show / hide the heartbeat, h = help
         d            = drop all connections, s = go silent / answer again, q = quit
"""
import socket
import sys
import threading
import time

PORT = 2560
VERSION = "<iDCC-EX V-5.6.6 / MEGA / STANDARD_MOTOR_SHIELD G-fake>"

TURNOUTS = {1: 0, 2: 1, 3: 0, 4: 0, 5: 0}      # id -> 0 closed (straight) / 1 thrown (diverging)

_print_lock = threading.Lock()


def log(text):
    with _print_lock:
        print(f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}  {text}", flush=True)


class FakeDccex:
    def __init__(self, port=PORT):
        self.silent = False
        self.verbose = False
        self.power = True
        self.turnouts = dict(TURNOUTS)
        self.accessories = {}                  # raw <a> commands: linear address -> 0 / 1
        self.clients = []
        self.numbers = {}
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
        buffer = ""
        who = self.numbers.get(sock, "?")
        try:
            while True:
                data = sock.recv(1024)
                if not data:
                    log(f"{who} closed by the app")
                    if sock in self.clients:
                        self.clients.remove(sock)
                    return
                buffer += data.decode(errors="replace")
                while "<" in buffer and ">" in buffer[buffer.index("<"):]:
                    start = buffer.index("<")
                    end = buffer.index(">", start)
                    self._handle(sock, who, buffer[start + 1:end])
                    buffer = buffer[end + 1:]
        except OSError:
            pass

    # ---- sending ----------------------------------------------------------

    @staticmethod
    def _bytes(lines):
        return "".join(f"{line}\n" for line in lines).encode()

    def _send(self, sock, lines):
        try:
            sock.sendall(self._bytes(lines))
        except OSError:
            pass

    def _broadcast(self, lines):
        for client in list(self.clients):
            self._send(client, lines)

    def _power_lines(self):
        if self.power:
            return ["<p1 A>", "<p1 B>", "<p1>", "<p1 MAIN>", "<p1 PROG>"]
        return ["<p0 A>", "<p0 B>", "<p0>"]

    # ---- commands -----------------------------------------------------------

    def _handle(self, sock, who, body):
        parts = body.split()
        if not parts:
            return
        quiet = parts == ["JT"] and not self.verbose
        if self.silent:
            if not quiet:
                log(f"{who} -> <{body}>   (ignored, fake is silent)")
            return
        if not quiet:
            log(f"{who} -> <{body}>")
        command = parts[0]

        if command == "s":
            lines = [VERSION] + self._power_lines()
            lines += [f"<H {i} {s}>" for i, s in self.turnouts.items()]
            self._send(sock, lines)
            log("     answered with version, power and every turnout state")
        elif command == "JT" and len(parts) == 1:
            self._send(sock, ["<jT " + " ".join(str(i) for i in self.turnouts) + ">"])
        elif command == "JT" and len(parts) == 2 and parts[1].isdigit():
            turnout_id = int(parts[1])
            if turnout_id in self.turnouts:
                self._send(sock, [f'<jT {turnout_id} {"T" if self.turnouts[turnout_id] else "C"} "">'])
            else:
                self._send(sock, [f"<jT {turnout_id} X>"])
        elif command == "T" and len(parts) == 3 and parts[1].isdigit() and parts[2] in ("0", "1"):
            self.throw(int(parts[1]), parts[2] == "1", sock=sock)
        elif command in ("1", "0") and len(parts) == 1:
            self.set_power(command == "1")
        elif command == "a" and len(parts) in (3, 4) and all(x.isdigit() for x in parts[1:]):
            numbers = [int(x) for x in parts[1:]]
            if len(numbers) == 2:
                linear, active = numbers
            else:
                linear, active = (numbers[0] - 1) * 4 + numbers[1] + 1, numbers[2]
            self.accessories[linear] = active
            log(f"     raw accessory {linear} -> {'thrown' if active else 'closed'}"
                f"  (the real board sends no answer to this, and neither does the fake)")
        else:
            log("     not understood: <X> sent")
            self._send(sock, ["<X>"])

    def throw(self, turnout_id, thrown, sock=None, source="app"):
        """Set a turnout and tell every client with <H>, like the board."""
        if turnout_id not in self.turnouts:
            log(f"     turnout {turnout_id} is not defined: <X> sent  (use 'list' to see the ids)")
            if sock is not None:
                self._send(sock, ["<X>"])
            return
        before = self.turnouts[turnout_id]
        self.turnouts[turnout_id] = 1 if thrown else 0
        log(f"     turnout {turnout_id} -> {'thrown' if thrown else 'closed'}"
            f"  (was {'thrown' if before else 'closed'}, set from the {source}); "
            f"<H> sent to {len(self.clients)} client(s)")
        self._broadcast([f"<H {turnout_id} {self.turnouts[turnout_id]}>"])

    def set_power(self, on, source="app"):
        self.power = on
        log(f"     power -> {'ON' if on else 'OFF'} (from the {source}); sent to {len(self.clients)} client(s)")
        self._broadcast(self._power_lines())

    def show(self):
        log(f"power {'ON' if self.power else 'OFF'}; {len(self.clients)} client(s); "
            f"{'SILENT' if self.silent else 'answering'}")
        for turnout_id, state in self.turnouts.items():
            log(f"     turnout {turnout_id:<3} {'thrown' if state else 'closed'}")
        for linear, state in sorted(self.accessories.items()):
            log(f"     raw accessory {linear:<4} {'thrown' if state else 'closed'}")

    def drop_all(self):
        log(f"dropping {len(self.clients)} connection(s)")
        for client in self.clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except OSError:
                pass
        self.clients.clear()


HELP = """  t <id> r|g          throw (r) or close (g) a turnout from "another throttle"
  go / stop           track power from another throttle
  list                turnouts, raw accessory commands, power, clients
  v                   show / hide the heartbeat
  d                   drop all connections
  s                   go silent / answer again
  q                   quit"""

if __name__ == "__main__":
    dccex = FakeDccex()
    log(f"Fake DCC-EX on port {PORT}.  Type h for the commands.")
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        key = parts[0]
        if key in ("go", "stop"):
            log(f"another throttle: power {key.upper()}")
            dccex.set_power(key == "go", source="throttle")
        elif key == "d":
            dccex.drop_all()
        elif key == "s":
            dccex.silent = not dccex.silent
            log("silent" if dccex.silent else "answering")
        elif key == "v":
            dccex.verbose = not dccex.verbose
            log("heartbeat shown" if dccex.verbose else "heartbeat hidden")
        elif key == "list":
            dccex.show()
        elif key in ("h", "help", "?"):
            print(HELP)
        elif key == "t" and len(parts) == 3 and parts[1].isdigit() and parts[2] in ("r", "g"):
            dccex.throw(int(parts[1]), parts[2] == "r", source="throttle")
        elif key == "q":
            break
        else:
            print("?  (h = help)")