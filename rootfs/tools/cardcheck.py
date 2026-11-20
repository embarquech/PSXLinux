#!/usr/bin/env python3
"""Consistency check of a PSXLinux root card (bu header + ext2), e2fsck-style, plus a tree listing.

  python cardcheck.py card.mcr [SHBIN]
"""
import struct, sys

card = open(sys.argv[1], "rb").read()
shbin = open(sys.argv[2], "rb").read() if len(sys.argv) > 2 else None
errors = []


def err(m):
    errors.append(m)


assert len(card) == 131072, "card must be 128 KB"
bid, bsize, serial, number = struct.unpack_from("<IIII", card, 0)
if bid != 0x1234 or bsize != 1024 or number != 0:
    err("bad bu header %x %d %d" % (bid, bsize, number))
dev = card[8 * 128:]                                  # /dev/bu0
devsize = ((bsize >> 3) - 1) * 1024
assert len(dev) == devsize

sb = dev[1024:2048]
(s_inodes, s_blocks, _, s_free_b, s_free_i, s_first, s_logbs, _, s_bpg, _, s_ipg) = struct.unpack_from("<11I", sb)
magic, = struct.unpack_from("<H", sb, 56)
rev, = struct.unpack_from("<I", sb, 76)
BS = 1024 << s_logbs
if magic != 0xEF53: err("bad magic")
if rev != 0: err("rev %d (2.4.0 handles 0 best)" % rev)
if s_blocks * BS > devsize: err("fs larger than device")
if s_first != 1: err("first data block %d" % s_first)
ngroups = (s_blocks - s_first + s_bpg - 1) // s_bpg
if ngroups != 1: err("%d groups" % ngroups)
bb, ib, it, gfree_b, gfree_i, gdirs = struct.unpack_from("<IIIHHH", dev, 2 * BS)


def blk(n): return dev[n * BS:(n + 1) * BS]


def inode(n):
    off = it * BS + (n - 1) * 128
    mode, uid, size, at, ct, mt, dt, gid, links, nblk, flags = struct.unpack_from("<HHIIIIIHHII", dev, off)
    iblock = struct.unpack_from("<15I", dev, off + 40)
    return dict(mode=mode, size=size, links=links, nblk=nblk, iblock=iblock)


used_blocks = {b for b in range(1, it + (s_inodes * 128 + BS - 1) // BS)}
used_inodes = set(range(1, 11))
refcount = {}


def blocks_of(ino, register=True):
    i = inode(ino)
    t = i["mode"] & 0o170000
    if t in (0o020000, 0o060000) or (t == 0o120000 and i["nblk"] == 0):
        return []
    n = (i["size"] + BS - 1) // BS
    lst = [b for b in i["iblock"][:12]][:n]
    meta = []
    if n > 12:
        meta.append(i["iblock"][12])
        lst += list(struct.unpack_from("<%dI" % (n - 12), blk(i["iblock"][12])))
    if n > 12 + BS // 4: err("inode %d needs double indirect" % ino)
    if i["nblk"] != (len(lst) + len(meta)) * (BS // 512): err("inode %d i_blocks %d" % (ino, i["nblk"]))
    for b in (lst + meta) if register else []:
        if not (s_first <= b < s_blocks): err("inode %d block %d out of range" % (ino, b))
        if b in used_blocks: err("block %d used twice (inode %d)" % (b, ino))
        used_blocks.add(b)
    return lst


def read(ino, register=False):
    i = inode(ino)
    return b"".join(blk(b) for b in blocks_of(ino, register))[:i["size"]]


tree = []
seen = set()
ndirs = 0


def walk(ino, path, parent):
    global ndirs
    if ino in seen:
        return
    seen.add(ino)
    used_inodes.add(ino)
    i = inode(ino)
    data = read(ino, True)
    ndirs += 1
    subdirs = 0
    p = 0
    names = []
    while p < len(data):
        e_ino, rec, nlen = struct.unpack_from("<IHH", data, p)
        if rec < 8 or rec % 4 or p % BS + rec > BS: err("bad rec_len in %s at %d" % (path, p)); break
        nm = data[p + 8:p + 8 + nlen].decode()
        p += rec
        if not e_ino: continue
        names.append(nm)
        if nm == ".":
            if e_ino != ino: err("%s: bad ." % path)
            continue
        if nm == "..":
            if e_ino != parent: err("%s: bad .." % path)
            continue
        refcount[e_ino] = refcount.get(e_ino, 0) + 1
        ci = inode(e_ino)
        t = ci["mode"] & 0o170000
        full = path.rstrip("/") + "/" + nm
        if t == 0o040000:
            subdirs += 1
            tree.append((full + "/", e_ino, ci))
            walk(e_ino, full, ino)
        else:
            tree.append((full, e_ino, ci))
            if e_ino not in seen:
                seen.add(e_ino)
                used_inodes.add(e_ino)
                blocks_of(e_ino)
    if names[:2] != [".", ".."]: err("%s: . and .. must come first" % path)
    if i["links"] != 2 + subdirs: err("%s: links %d, expected %d" % (path, i["links"], 2 + subdirs))


walk(2, "/", 2)
for ino, n in refcount.items():
    i = inode(ino)
    if i["mode"] & 0o170000 != 0o040000 and i["links"] != n:
        err("inode %d: links %d, %d names" % (ino, i["links"], n))

bmap = blk(bb)
for b in range(1, s_blocks):
    bit = bool(bmap[(b - 1) >> 3] & (1 << ((b - 1) & 7)))
    if bit != (b in used_blocks): err("block bitmap: block %d bit %d, used %d" % (b, bit, b in used_blocks))
imap = blk(ib)
for n in range(1, s_inodes + 1):
    bit = bool(imap[(n - 1) >> 3] & (1 << ((n - 1) & 7)))
    if bit != (n in used_inodes): err("inode bitmap: inode %d bit %d, used %d" % (n, bit, n in used_inodes))
fb = s_blocks - 1 - len(used_blocks)
fi = s_inodes - len(used_inodes)
if (s_free_b, gfree_b) != (fb, fb): err("free blocks sb %d gd %d real %d" % (s_free_b, gfree_b, fb))
if (s_free_i, gfree_i) != (fi, fi): err("free inodes sb %d gd %d real %d" % (s_free_i, gfree_i, fi))
if gdirs != ndirs: err("used dirs %d real %d" % (gdirs, ndirs))

for path, ino, i in tree:
    t = i["mode"] & 0o170000
    extra = ""
    if t in (0o020000, 0o060000):
        extra = "dev %d,%d" % (i["iblock"][0] >> 8, i["iblock"][0] & 255)
    elif t == 0o100000:
        extra = "%d bytes" % i["size"]
        if shbin is not None and path == "/bin/sh" and read(ino) != shbin: err("/bin/sh content differs")
    print("%-18s ino %2d mode %06o links %2d %s" % (path, ino, i["mode"], i["links"], extra))
for path, ino, i in tree:
    if path == "/etc/motd": print(read(ino).decode())
print("%d KB used, %d KB free, %d inodes free" % (len(used_blocks) + 1, fb, fi))
if errors:
    print("ERRORS:\n  " + "\n  ".join(errors))
    sys.exit(1)
print("OK: file system consistent")
