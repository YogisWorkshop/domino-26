"""A pretend ECoS for testing without hardware.  python tools/fake_ecos.py

Everything the app sends is printed, with a note on what it did. The heartbeat
(get(1, status) every few seconds) is hidden unless you turn on verbose (v).

Console: t <addr> r|g [mm|mot] = throw a turnout "on the ECoS itself"
         go / stop = press the ECoS's own power button
         list = show all accessories and the power state
         v = show / hide the heartbeat, h = help
         d = drop all connections (cable pulled), s = go silent / answer again, q = quit
"""
import re
import socket
import sys
import threading
import time

_print_lock = threading.Lock()


def log(text):
    with _print_lock:
        print(f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}  {text}", flush=True)

PORT = 15471

ACCESSORIES = {   # object id -> [name, addr, protocol, state]
    20000: ["T1", 1, "DCC", 0],
    20001: ["T2", 2, "DCC", 0],
    20002: ["T3", 3, "DCC", 1],
    20003: ["T4", 4, "DCC", 0],
    20004: ["T5", 5, "MOT", 0],
    20005: ["T6", 6, "MOT", 1],
}
ROUTE = 30000


class FakeEcos:
    def __init__(self, port=PORT):
        self.silent = False
        self.verbose = False
        self.power = "GO"
        self.clients = []
        self.numbers = {}                      # socket -> "#1", "#2" ... for the log
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
        buffer = b""
        try:
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    log(f"{self.numbers.get(sock, '?')} closed by the app")
                    if sock in self.clients:
                        self.clients.remove(sock)
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self._handle(sock, line.decode().strip())
        except OSError:
            pass

    @staticmethod
    def _reply(command, lines=()):
        body = "".join(f"{line}\r\n" for line in lines)
        return f"<REPLY {command}>\r\n{body}<END 0 (OK)>\r\n".encode()

    @staticmethod
    def _event(obj_id, option):
        return f"<EVENT {obj_id}>\r\n{obj_id} {option}\r\n<END 0 (OK)>\r\n".encode()

    def _handle(self, sock, command):
        who = self.numbers.get(sock, "?")
        quiet = command.startswith("get(1, status)") and not self.verbose
        if self.silent:
            if not quiet:
                log(f"{who} -> {command}   (ignored, fake is silent)")
            return
        if not quiet:
            log(f"{who} -> {command}")
        if command.startswith("queryObjects(11"):
            lines = [f'{i} name1["{n}"] addr[{a}] protocol[{p}]'
                     for i, (n, a, p, _) in ACCESSORIES.items()]
            lines.append(f'{ROUTE} name1["Route"]')
            sock.sendall(self._reply(command, lines))
            log(f"     answered with {len(ACCESSORIES)} accessories (+ 1 route, which the app must skip)")
        elif command.startswith("get(1, status)"):
            sock.sendall(self._reply(command, [f"1 status[{self.power}]"]))
            if not quiet:
                log(f"     power is {self.power}")
        elif m := re.match(r"set\(1, (go|stop)\)", command):
            sock.sendall(self._reply(command))
            log(f"     power -> {m.group(1).upper()}")
            self.set_power(m.group(1).upper())
        elif m := re.match(r"get\((\d+), state\)", command):
            obj_id = int(m.group(1))
            if obj_id in ACCESSORIES:
                sock.sendall(self._reply(command, [f"{obj_id} state[{ACCESSORIES[obj_id][3]}]"]))
                name, address, protocol, state = ACCESSORIES[obj_id]
                log(f"     {name} ({protocol} {address}) is {'r' if state else 'g'}")
            else:
                sock.sendall(self._reply(command))
                log(f"     no accessory with id {obj_id}")
        elif m := re.match(r"set\(11, switch\[(DCC|MOT)(\d+)([rg])\]\)", command):
            protocol, address, port = m.group(1), int(m.group(2)), m.group(3)
            sock.sendall(self._reply(command))
            self.throw(address, protocol, port == "r")
        else:                                  # request(...) and anything else
            sock.sendall(self._reply(command))

    def throw(self, address, protocol, diverging, source="app"):
        """Switch an accessory and tell every client, like a real ECoS."""
        found = False
        for obj_id, item in ACCESSORIES.items():
            if item[1] == address and item[2] == protocol:
                found = True
                before = item[3]
                item[3] = 1 if diverging else 0
                log(f"     {item[0]} ({protocol} {address}) -> {'r' if diverging else 'g'}"
                    f"  (was {'r' if before else 'g'}, set from the {source}); event sent to "
                    f"{len(self.clients)} client(s)")
                for option in ("switching[1]", f"state[{item[3]}]", "switching[0]"):
                    for client in list(self.clients):
                        try:
                            client.sendall(self._event(obj_id, option))
                        except OSError:
                            pass
        if not found:
            log(f"     {protocol} {address} is not in the fake's accessory list: nothing changed, "
                f"no event sent  (use 'list' to see the addresses)")

    def show(self):
        log(f"power {self.power}; {len(self.clients)} client(s); "
            f"{'SILENT' if self.silent else 'answering'}")
        for obj_id, (name, address, protocol, state) in ACCESSORIES.items():
            log(f"     {name:<4} id {obj_id}  {protocol:<3} {address:<3}  {'r' if state else 'g'}")

    def set_power(self, status):
        """GO or STOP, from a command or from the ECoS's own buttons."""
        self.power = status
        log(f"     power is now {status}; event sent to {len(self.clients)} client(s)")
        for client in list(self.clients):
            try:
                client.sendall(self._event(1, f"status[{status}]"))
            except OSError:
                pass

    def drop_all(self):
        log(f"dropping {len(self.clients)} connection(s)")
        for client in self.clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except OSError:
                pass
        self.clients.clear()


HELP = """  t <addr> r|g [mm|mot]   throw a turnout on the ECoS itself (default DCC)
  go / stop           the ECoS's own power button
  list                accessories, power, clients
  v                   show / hide the heartbeat
  d                   drop all connections
  s                   go silent / answer again
  q                   quit"""

if __name__ == "__main__":
    ecos = FakeEcos()
    log(f"Fake ECoS on port {PORT}.  Type h for the commands.")
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        key = parts[0]
        if key in ("go", "stop"):
            log(f"ECoS button: {key.upper()}")
            ecos.set_power(key.upper())
        elif key == "d":
            ecos.drop_all()
        elif key == "s":
            ecos.silent = not ecos.silent
            log("silent" if ecos.silent else "answering")
        elif key == "v":
            ecos.verbose = not ecos.verbose
            log("heartbeat shown" if ecos.verbose else "heartbeat hidden")
        elif key == "list":
            ecos.show()
        elif key in ("h", "help", "?"):
            print(HELP)
        elif key == "t" and len(parts) in (3, 4) and parts[1].isdigit() and parts[2] in ("r", "g"):
            protocol = "MOT" if len(parts) == 4 and parts[3].lower() in ("mm", "mot") else "DCC"
            ecos.throw(int(parts[1]), protocol, parts[2] == "r", source="ECoS")
        elif key == "q":
            break
        else:
            print("?  (h = help)")
