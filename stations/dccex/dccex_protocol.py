"""DCC-EX native protocol: text messages in < > brackets.

What the board sends (seen on a real EX-CommandStation 5.6.6):
    <H id state>     turnout id changed (1 = thrown, 0 = closed), also all of them after <s>
    <p1> / <p0>      track power on / off, as a whole (per-track lines like <p1 A> are ignored)
    <jT ...>         answer to <JT>, we use it as a heartbeat
    <X>              a command was refused (e.g. an undefined turnout id)
    <l ...>, <i ...> loco and version chatter: ignored
"""

DEFAULT_PORT = 2560
MAX_TURNOUT_ID = 32767
MAX_LINEAR_ADDRESS = 2044        # DCC accessory outputs 1..2044


def split_messages(buffer):
    """Take every complete <...> message off the front of buffer.

    Returns (list of message bodies without the brackets, what is left over).
    """
    messages = []
    while True:
        start = buffer.find("<")
        if start < 0:
            return messages, ""
        end = buffer.find(">", start)
        if end < 0:
            return messages, buffer[start:]      # incomplete, wait for more
        messages.append(buffer[start + 1:end])
        buffer = buffer[end + 1:]


def parse(body):
    """One message body -> ("turnout", id, thrown) / ("power", on) / ("refused",) / None."""
    parts = body.split()
    if not parts:
        return None
    kind = parts[0]
    if kind == "H" and len(parts) == 3 and parts[1].isdigit():
        if parts[2] in ("0", "C"):
            return ("turnout", int(parts[1]), False)
        if parts[2] in ("1", "T"):
            return ("turnout", int(parts[1]), True)
    if kind in ("p0", "p1") and len(parts) == 1:      # only the overall line, not "p1 A"
        return ("power", kind == "p1")
    if kind == "X" and len(parts) == 1:
        return ("refused",)
    return None


def turnout_command(turnout_id, thrown):
    if not 1 <= turnout_id <= MAX_TURNOUT_ID:
        raise ValueError(f"DCC-EX turnout id out of range: {turnout_id}")
    return f"<T {turnout_id} {1 if thrown else 0}>"


def accessory_command(address, thrown):
    """Raw DCC accessory by its single (linear) address; the board never answers this."""
    if not 1 <= address <= MAX_LINEAR_ADDRESS:
        raise ValueError(f"DCC accessory address out of range: {address}")
    return f"<a {address} {1 if thrown else 0}>"


def power_command(on):
    return "<1>" if on else "<0>"