"""Socket interface between the Python xApps and the E2 connector (xapp-sm-connector).

The connector forwards every decoded KPM indication as a length-prefixed message holding a serialised string map
({key: value}), and accepts handover controls as the text "<imsi>,<target cell>".
"""
import socket
import struct


def open_control_socket(port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("", port))
    server.listen(10)
    print(f"Waiting for the E2 connector on port {port}", flush=True)
    conn, addr = server.accept()
    print(f"E2 connector connected: {addr[0]}:{addr[1]}", flush=True)
    return conn


def receive(conn):
    """One message: 4-byte big-endian length followed by the payload."""
    size = struct.unpack("!I", conn.recv(4))[0]
    return conn.recv(size)


def send_control(conn, imsi, target_cell):
    conn.send(f"{imsi},{target_cell}".encode("utf-8"))


def deserialize_map(data):
    """uint32 n, then n times (uint32 key length, key, uint32 value length, value), big-endian, UTF-8."""
    out = {}
    if not data or len(data) < 4:
        return out
    off, total = 4, len(data)
    for _ in range(struct.unpack(">I", data[:4])[0]):
        if off + 4 > total:
            break
        n = struct.unpack(">I", data[off:off + 4])[0]; off += 4
        if off + n > total:
            break
        key = data[off:off + n].decode("utf-8"); off += n
        if off + 4 > total:
            break
        n = struct.unpack(">I", data[off:off + 4])[0]; off += 4
        if off + n > total:
            break
        out[key] = data[off:off + n].decode("utf-8"); off += n
    return out
