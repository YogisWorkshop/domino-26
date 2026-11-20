"""Look at what a DCC-EX EX-CommandStation really says over WiFi (TCP).

    python lab/dccex/probe_dccex.py 192.168.1.50
    python lab/dccex/probe_dccex.py 192.168.1.50 --listen 30
    python lab/dccex/probe_dccex.py 192.168.1.50 --throw 3      # also throws turnout id 3, then closes it

It only READS by default: <s> (status), <JT> (list turnouts) and <JT id> for each one.
Then it listens, so flip a turnout / the power from another throttle and see what
gets broadcast. --throw sends <T id 1> then <T id 0> to that one turnout.
Everything received is printed raw (repr), so line endings are visible.
"""
import argparse
import re
import socket
import time


def collect(sock, seconds, label=""):
    """Print everything that arrives for `seconds`, return it as one string."""
    end = time.time() + seconds
    text = ""
    while time.time() < end:
        sock.settimeout(max(0.05, end - time.time()))
        try:
            data = sock.recv(4096)
        except socket.timeout:
            break
        if not data:
            print("   (connection closed by the DCC-EX)")
            break
        chunk = data.decode(errors="replace")
        text += chunk
        print(f"   {time.strftime('%H:%M:%S')} {label}<- {chunk!r}")
    return text


def send(sock, command, wait=1.0):
    print(f"-> {command}")
    sock.sendall(command.encode())
    return collect(sock, wait)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=2560)
    parser.add_argument("--listen", type=int, default=60, help="seconds to listen at the end")
    parser.add_argument("--throw", type=int, help="turnout id to throw and close again")
    args = parser.parse_args()

    print(f"connecting to {args.host}:{args.port} ...")
    sock = socket.create_connection((args.host, args.port), timeout=5)
    print("connected. Anything sent on connect:")
    collect(sock, 1.5)

    send(sock, "<s>", 1.5)                      # version, power, turnout list
    listing = send(sock, "<JT>", 1.5)
    match = re.search(r"<jT([\d ]*)>", listing)
    ids = [int(x) for x in match.group(1).split()] if match else []
    print(f"\nturnout ids: {ids}\n")
    for turnout_id in ids:
        send(sock, f"<JT {turnout_id}>", 0.7)

    if args.throw is not None:
        print("\n--- throwing (T = thrown/diverging, C = closed/straight) ---")
        send(sock, f"<T {args.throw} 1>", 1.5)
        send(sock, f"<T {args.throw} 0>", 1.5)

    print(f"\n--- listening for {args.listen} s: operate something from another throttle ---")
    collect(sock, args.listen, "event ")
    sock.close()


if __name__ == "__main__":
    main()