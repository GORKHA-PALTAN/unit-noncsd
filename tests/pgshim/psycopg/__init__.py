"""TEST-ONLY stand-in for psycopg 3, used to run the test-suite against a real PostgreSQL server in an
environment where the real driver cannot be installed. Speaks the PostgreSQL wire protocol (simple query,
trust auth) and interpolates parameters client-side. Production uses the real `psycopg[binary]` package."""
import socket
import struct
from decimal import Decimal
from urllib.parse import urlparse


class Error(Exception):
    pass


class OperationalError(Error):
    pass


class DatabaseError(Error):
    pass


def _lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "'\\x" + bytes(v).hex() + "'::bytea"
    return "'" + str(v).replace("'", "''") + "'"


def _interp(sql, params):
    out, i, pi = [], 0, 0
    params = list(params or [])
    while i < len(sql):
        if sql.startswith("%%", i):
            out.append("%"); i += 2
        elif sql.startswith("%s", i):
            out.append(_lit(params[pi])); pi += 1; i += 2
        else:
            out.append(sql[i]); i += 1
    if pi != len(params):
        raise Error(f"parameter count mismatch ({pi} used, {len(params)} given)")
    return "".join(out)


def _conv(oid, raw):
    if raw is None:
        return None
    s = raw.decode()
    if oid in (20, 21, 23, 26):
        return int(s)
    if oid in (700, 701):
        return float(s)
    if oid == 1700:
        return Decimal(s)
    if oid == 16:
        return s == "t"
    if oid == 17:
        return bytes.fromhex(s[2:])
    return s


class Cursor:
    def __init__(self, conn):
        self.conn, self.description, self.rowcount, self._rows = conn, None, -1, []

    def execute(self, sql, params=()):
        q = _interp(sql, params) if params else sql.replace("%%", "%")
        cols, rows, tag = self.conn._query(q)
        self.description = [(c[0],) for c in cols] if cols is not None else None
        self._rows = [tuple(_conv(c[1], v) for c, v in zip(cols, r)) for r in rows] if cols else []
        parts = (tag or "").split()
        self.rowcount = int(parts[-1]) if parts and parts[-1].isdigit() else len(self._rows)
        return self

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        r, self._rows = self._rows, []
        return r


class Connection:
    def __init__(self, url):
        u = urlparse(url)
        self.sock = socket.create_connection((u.hostname or "127.0.0.1", u.port or 5432))
        self.closed, self.broken = False, False
        params = f"user\0{u.username or 'postgres'}\0database\0{u.path.lstrip('/')}\0\0".encode()
        self.sock.sendall(struct.pack("!ii", 8 + len(params), 196608) + params)
        while True:
            t, body = self._read()
            if t == b"R" and struct.unpack("!i", body[:4])[0] != 0:
                raise OperationalError("only trust auth is supported by the test shim")
            if t == b"E":
                raise OperationalError(self._err(body))
            if t == b"Z":
                break

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                self.closed = self.broken = True
                raise OperationalError("server closed the connection")
            buf += chunk
        return buf

    def _read(self):
        h = self._recv(5)
        return h[:1], self._recv(struct.unpack("!i", h[1:])[0] - 4)

    @staticmethod
    def _err(body):
        fields = {}
        for part in body.split(b"\0"):
            if part:
                fields[part[:1]] = part[1:].decode(errors="replace")
        return fields.get(b"M", "error")

    def _query(self, q):
        data = q.encode() + b"\0"
        self.sock.sendall(b"Q" + struct.pack("!i", len(data) + 4) + data)
        cols, rows, tag, err = None, [], None, None
        while True:
            t, body = self._read()
            if t == b"T":
                n = struct.unpack("!h", body[:2])[0]; p = 2; cols = []
                for _ in range(n):
                    e = body.index(b"\0", p); name = body[p:e].decode(); p = e + 1
                    oid = struct.unpack("!i", body[p + 6:p + 10])[0]; p += 18
                    cols.append((name, oid))
            elif t == b"D":
                n = struct.unpack("!h", body[:2])[0]; p = 2; r = []
                for _ in range(n):
                    ln = struct.unpack("!i", body[p:p + 4])[0]; p += 4
                    if ln < 0:
                        r.append(None)
                    else:
                        r.append(body[p:p + ln]); p += ln
                rows.append(r)
            elif t == b"C":
                tag = body[:-1].decode()
            elif t == b"E":
                err = self._err(body)
            elif t == b"Z":
                break
        if err:
            raise DatabaseError(err)
        return cols, rows, tag

    def cursor(self):
        return Cursor(self)

    def close(self):
        self.closed = True
        self.sock.close()


def connect(url, autocommit=True, **kw):
    return Connection(url)
