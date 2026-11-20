#!/usr/bin/env python3
"""Bitcoin stratum <-> PlayStation bridge: the PC talks to the pool, the PS1 (PSXLinux, `btc stratum`)
does the hashing over the serial console.

  python stratum_bridge.py --selftest                       # offline checks, no pool, no PS1
  python stratum_bridge.py --genesis-test [--port COM14]    # PS1 re-mines block 0 through the bridge
  python stratum_bridge.py --pool HOST:PORT --user ADDRESS[.worker] [--password x] [--port COM14]
                           [--suggest-diff 1] [--chunk 0x4000] [--zeros 10]

The PSXLinux shell must be at its prompt on the port (close any other terminal first).
Serial protocol (see btc_stratum() in src/psxsh.c):
  PS1 -> PC  R | S <nonce hex> | Z <nonce hex> <zero bits> (10+, shown) | D <count hex> <seconds> | E ...
  PC -> PS1  W <header bytes 0..75, 152 hex> <first nonce hex> <count hex> <min zero bits hex> | Q
The PS1 reports hashes with at least N leading zero bits; every candidate is checked here against
the exact share target before it is submitted.
"""
import argparse, hashlib, json, socket, sys, threading, time

DIFF1 = 0xFFFF * 2 ** 208


def dsha(b):
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def hash_value(header80):                      # the number compared to the target
    return int.from_bytes(dsha(header80)[::-1], "big")


def zero_bits(header80):
    return 256 - hash_value(header80).bit_length()


# ---------------------------------------------------------------------------- work from stratum
class Job:
    def __init__(self, params, extranonce1, en2_size):
        (self.job_id, prevhash, self.coinb1, self.coinb2, self.branches, self.version, self.nbits,
         self.ntime, self.clean) = params[:9]
        p = bytes.fromhex(prevhash)                     # stratum: 8 words, each byte-swapped
        self.prev = b"".join(p[i:i + 4][::-1] for i in range(0, 32, 4))
        self.extranonce1 = extranonce1
        self.en2_size = en2_size

    def header76(self, en2):
        cb = bytes.fromhex(self.coinb1 + self.extranonce1 + en2 + self.coinb2)
        root = dsha(cb)
        for b in self.branches:
            root = dsha(root + bytes.fromhex(b))
        return (bytes.fromhex(self.version)[::-1] + self.prev + root +
                bytes.fromhex(self.ntime)[::-1] + bytes.fromhex(self.nbits)[::-1])


class Stratum:
    def __init__(self, host, port, user, password, suggest):
        self.user, self.lock = user, threading.Lock()
        self.job, self.difficulty, self.msgid = None, 1.0, 10
        self.accepted = self.rejected = 0
        self.sock = socket.create_connection((host, port), timeout=30)
        self.sock.settimeout(None)
        self.f = self.sock.makefile("r", encoding="ascii", newline="\n")
        self.send(1, "mining.subscribe", ["psx-miner/0.1"])
        r = self.wait_result(1)
        self.extranonce1, self.en2_size = r[1], r[2]
        if suggest:
            self.send(2, "mining.suggest_difficulty", [suggest])
        self.send(3, "mining.authorize", [user, password])
        threading.Thread(target=self.reader, daemon=True).start()

    def send(self, i, method, params):
        self.sock.sendall((json.dumps({"id": i, "method": method, "params": params}) + "\n").encode())

    def wait_result(self, i):
        while True:
            m = json.loads(self.f.readline())
            if m.get("id") == i:
                if m.get("error"):
                    sys.exit("pool error: %s" % (m["error"],))
                return m["result"]
            self.handle(m)

    def handle(self, m):
        meth = m.get("method")
        if meth == "mining.notify":
            with self.lock:
                self.job = Job(m["params"], self.extranonce1, self.en2_size)
            print("[pool] new job %s%s" % (self.job.job_id, " (clean)" if self.job.clean else ""))
        elif meth == "mining.set_difficulty":
            self.difficulty = float(m["params"][0])
            print("[pool] share difficulty %g" % self.difficulty)
        elif meth:                                          # other notifications: show them
            print("[pool] %s %s" % (meth, json.dumps(m.get("params"))[:200]))
        elif m.get("id") == 3:
            print("[pool] authorize: %s" % ("ok" if m.get("result") else m.get("error")))
        elif isinstance(m.get("id"), int) and m["id"] >= 100:
            ok = bool(m.get("result"))
            self.accepted += ok
            self.rejected += not ok
            print("[pool] share %s %s" % ("ACCEPTED" if ok else "rejected", m.get("error") or ""))
        elif m.get("error"):
            print("[pool] error: %s" % (m["error"],))

    def reader(self):
        for line in self.f:
            if not line.strip():
                continue
            try:
                self.handle(json.loads(line))
            except Exception as e:                          # never let one odd message stop the miner
                print("[pool] ignored message (%s): %s" % (e, line.strip()[:200]))
        print("[pool] connection closed")

    def submit(self, job, en2, nonce):
        with self.lock:
            self.msgid += 1
            i = 100 + self.msgid
        self.send(i, "mining.submit", [self.user, job.job_id, en2, job.ntime, "%08x" % nonce])


# ---------------------------------------------------------------------------- PS1 side
class PS1:
    def __init__(self, port):
        import serial
        self.s = serial.Serial(port, 115200, timeout=0.2, rtscts=False)
        self.s.rts = True
        self.s.dtr = True
        self.buf = b""

    def write(self, text):
        self.s.write(text.encode("ascii"))

    def lines(self):
        while True:
            self.buf += self.s.read(256)
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                yield line.decode("latin1").strip("\r ")
            yield None                                      # nothing complete yet

    def start(self, zeros=10):
        self.write("\r")
        time.sleep(0.5)
        self.s.reset_input_buffer()
        self.write("btc stratum %d\r" % zeros)


def work_line(h76, start, count, zb):
    return "W %s %x %x %x\r" % (h76.hex(), start, count, zb)


BEST_FILE = __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)),
                                       "best_hash.txt")


def load_best():
    """Best number of leading zero bits ever logged in best_hash.txt (0 if none)."""
    best = 0
    try:
        for line in open(BEST_FILE, encoding="utf-8"):
            if " zeros " in line:
                best = max(best, int(line.split(" zeros ")[0].split()[-1]))
    except (OSError, ValueError):
        pass
    return best


class Record:
    """Tracks the best hash of this session and the all-time best (best_hash.txt)."""
    def __init__(self):
        self.session, self.ever = 0, load_best()
        if self.ever:
            print("[best] all-time record so far: %d zeros (%s)" % (self.ever, BEST_FILE))

    def check(self, z, nonce, hash_hex, job):
        if z <= self.session:
            return
        self.session = z
        line = "%s  %2d zeros  nonce %08x  job %s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), z, nonce, job, hash_hex)
        if z > self.ever:
            self.ever = z
            print("*** NEW ALL-TIME RECORD: %d zeros ***  nonce %08x  %s" % (z, nonce, hash_hex))
            try:
                with open(BEST_FILE, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError as e:
                print("[best] cannot write %s: %s" % (BEST_FILE, e))
        else:
            print("*** session record: %d zeros (all-time %d) ***" % (z, self.ever))


def run_bridge(ps1, get_work, on_share, chunk, stop, zeros=10):
    """get_work() -> (key, header76, zb, ctx); on_share(ctx, header76, nonce)."""
    ps1.start(zeros)
    rec = Record()
    cur, nonce, total, t_start = None, 0, 0, time.time()
    for line in ps1.lines():
        if stop():
            ps1.write("Q\r")
            return
        if line is None or not line or line.startswith("W "):   # nothing / tty echo of our work
            continue
        if cur is None and line[:2] in ("S ", "Z "):            # results of work sent before a restart
            continue
        if line == "R":
            key, h76, zb, ctx = get_work()
            if key != (cur and cur[0]):
                cur, nonce = (key, h76, zb, ctx), 0
            if nonce >= 1 << 32:
                print("nonce space exhausted for this work")
                cur, nonce = None, 0
                continue
            n = min(chunk, (1 << 32) - nonce)
            ps1.write(work_line(cur[1], nonce, n, cur[2]))
            nonce += n
        elif line.startswith("S "):
            n = int(line[2:], 16)
            h80 = cur[1] + n.to_bytes(4, "little")
            rec.check(zero_bits(h80), n, dsha(h80)[::-1].hex(), str(cur[0][0]))
            on_share(cur[3], cur[1], n)
        elif line.startswith("D "):
            cnt, secs = line[2:].split()
            total += int(cnt, 16)
            el = max(time.time() - t_start, 1e-6)
            print("[ps1] %d hashes (%s s for this chunk), average %.0f H/s, record %d zeros (all-time %d)"
                  % (total, secs, total / el, rec.session, rec.ever))
        elif line.startswith("Z "):
            n, z = line[2:].split()
            h = dsha(cur[1] + int(n, 16).to_bytes(4, "little"))[::-1].hex()
            print("[ps1] nonce %s  %2s zeros  %s" % (n.zfill(8), z, h))
            rec.check(int(z), int(n, 16), h, str(cur[0][0]))
        elif line.startswith("E"):
            print("[ps1]", line)
        elif line in ("bye",):
            return


# ---------------------------------------------------------------------------- modes
GENESIS76 = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000000000003ba3edfd7a7b12b2"
    "7ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a29ab5f49ffff001d")
GENESIS_NONCE = 2083236893
GENESIS_HASH = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"


def selftest():
    h = GENESIS76 + GENESIS_NONCE.to_bytes(4, "little")
    assert dsha(h)[::-1].hex() == GENESIS_HASH, "genesis hash"
    assert zero_bits(h) >= 32
    # stratum header assembly, checked against the genesis block written as a stratum job
    coinbase = bytes.fromhex(
        "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff4d04ffff001d"
        "0104455468652054696d65732030332f4a616e2f32303039204368616e63656c6c6f72206f6e206272696e6b206f66"
        "207365636f6e64206261696c6f757420666f722062616e6b73ffffffff0100f2052a01000000434104678afdb0fe55"
        "48271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba"
        "0b8d578a4c702b6bf11d5fac00000000")
    assert dsha(coinbase)[::-1].hex() == "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"
    pv = "".join(bytes.fromhex("00" * 32)[i:i + 4][::-1].hex() for i in range(0, 32, 4))
    split = 60
    job = Job([ "g", pv, coinbase[:split].hex(), coinbase[split + 4:].hex(), [], "00000001", "1d00ffff",
               "495fab29", True], coinbase[split:split + 2].hex(), 2)
    assert job.header76(coinbase[split + 2:split + 4].hex()) == GENESIS76, "stratum header assembly"
    print("selftest OK: genesis hash, coinbase/merkle and stratum header assembly")


def genesis_test(port, back):
    ps1 = PS1(port)
    found = []

    def get_work():
        return ("genesis", GENESIS76, 32, None)

    def on_share(ctx, h76, nonce):
        h = h76 + nonce.to_bytes(4, "little")
        print("[ps1] candidate nonce %d -> %s" % (nonce, dsha(h)[::-1].hex()))
        found.append(nonce)

    print("genesis test: the PS1 hashes nonces %d..%d" % (GENESIS_NONCE - back, GENESIS_NONCE + 10))
    # start the bridge at the right nonce: patch the first chunk
    orig = work_line

    def first_line(h76, start, count, zb):
        return orig(h76, GENESIS_NONCE - back, back + 10, zb)
    globals()["work_line"] = first_line
    try:
        run_bridge(ps1, get_work, on_share, back + 10, lambda: bool(found))
    finally:
        globals()["work_line"] = orig
    ok = found and found[0] == GENESIS_NONCE
    print("genesis test %s" % ("OK: the PS1 found block 0" if ok else "FAILED"))


def mine(args):
    host, port = args.pool.split("://")[-1].rsplit(":", 1)
    pool = Stratum(host, int(port), args.user, args.password, args.suggest_diff)
    while pool.job is None:
        time.sleep(0.2)
    ps1 = PS1(args.port)
    state = {"en2": 0}

    def get_work():
        with pool.lock:
            job = pool.job
        en2 = ("%0*x" % (job.en2_size * 2, state["en2"]))[-job.en2_size * 2:]
        target = int(DIFF1 / pool.difficulty)
        zb = max(256 - target.bit_length(), 1)
        return ((job.job_id, en2, pool.difficulty), job.header76(en2), zb, (job, en2, target))

    def on_share(ctx, h76, nonce):
        job, en2, target = ctx
        h = h76 + nonce.to_bytes(4, "little")
        v = hash_value(h)
        print("[ps1] candidate nonce %08x, hash %s" % (nonce, dsha(h)[::-1].hex()))
        if v <= target:
            print("[pool] submitting share")
            pool.submit(job, en2, nonce)
        else:
            print("       above the share target, not submitted")

    print("mining: Ctrl+C to stop (the PS1 goes back to its shell)")
    try:
        run_bridge(ps1, get_work, on_share, args.chunk, lambda: False, args.zeros)
    except KeyboardInterrupt:
        ps1.write("Q\r")
        print("\nstopped: %d accepted, %d rejected" % (pool.accepted, pool.rejected))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--genesis-test", action="store_true")
    ap.add_argument("--back", type=int, default=3000, help="genesis test: nonces before the answer")
    ap.add_argument("--pool", help="HOST:PORT of a stratum v1 pool")
    ap.add_argument("--user", help="pool login, usually your BTC address (+ .worker)")
    ap.add_argument("--password", default="x")
    ap.add_argument("--suggest-diff", type=float, default=None)
    ap.add_argument("--port", default="COM14")
    ap.add_argument("--zeros", type=int, default=10, help="show every PS1 hash with this many leading zero bits")
    ap.add_argument("--chunk", type=lambda x: int(x, 0), default=0x4000, help="nonces per work unit")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.genesis_test:
        genesis_test(a.port, a.back)
    elif a.pool and a.user:
        mine(a)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
