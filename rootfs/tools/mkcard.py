#!/usr/bin/env python3
"""PSXLinux root memory card image: ext2 (rev 0, 1 KB blocks) behind the header of the bu driver.

  python mkcard.py SKELDIR SHBIN OUT.mcr

Card layout expected by drivers/block/bu.c (PSXLinux beta1), 1024 frames of 128 bytes:
  frame 0      u32 id = 0x1234, u32 size = 1024 (frames), u32 serial, u32 number (0 = first card)
  frames 1-7   unused (BU_FIRST_BLOCKS = 8)
  frames 8..   the block device /dev/bu0: 127 KB, here an ext2 file system
The card is no longer a PlayStation save card after that (no "MC" header): the BIOS sees it as unformatted.

Root tree: SKELDIR copied as is (regular files and directories), plus /dev nodes, /proc, and SHBIN as
/bin/sh with hard links for /sbin/init and every applet.
"""
import os, struct, sys, time

BS = 1024
FS_BLOCKS = 127
N_INODES = 48
FIRST_INO = 11                      # rev 0
ROOT_INO = 2
APPLETS = ["btc", "cat", "chmod", "clear", "cp", "df", "dmesg", "echo", "false", "free", "halt", "help", "hexdump",
           "hostname", "kill", "ln", "ls", "mkdir", "mknod", "mount", "mv", "pad", "ps", "pwd", "reboot", "rm",
           "rmdir", "sleep", "sync", "touch", "true", "umount", "uname", "uptime"]
DEVICES = [  # name, type, major, minor
    ("console", "c", 5, 1), ("tty", "c", 5, 0), ("tty0", "c", 4, 0), ("tty1", "c", 4, 1), ("tty2", "c", 4, 2),
    ("ttyS0", "c", 4, 64), ("null", "c", 1, 3), ("zero", "c", 1, 5), ("mem", "c", 1, 1), ("kmem", "c", 1, 2),
    ("bu0", "b", 207, 0), ("bu1", "b", 207, 1),
]
S_IFDIR, S_IFREG, S_IFLNK, S_IFCHR, S_IFBLK = 0o040000, 0o100000, 0o120000, 0o020000, 0o060000


class Node:
    def __init__(self, mode, data=b"", rdev=None):
        self.mode, self.data, self.rdev = mode, data, rdev
        self.entries = []           # directories: (name, Node)
        self.ino = None
        self.links = 0
        self.parent = None

    def add(self, name, node):
        if node.mode & 0o170000 == S_IFDIR:
            node.parent = self
        self.entries.append((name, node))
        return node


def build_tree(skel, shbin):
    root = Node(S_IFDIR | 0o755)
    dirs = {"": root}

    def mkdir(path, mode=0o755):
        if path in dirs:
            return dirs[path]
        par, _, nm = path.rpartition("/")
        d = mkdir(par).add(nm, Node(S_IFDIR | mode))
        dirs[path] = d
        return d

    for top, sub, files in os.walk(skel):
        rel = os.path.relpath(top, skel).replace("\\", "/")
        rel = "" if rel == "." else rel
        d = mkdir(rel)
        for f in sorted(files):
            data = open(os.path.join(top, f), "rb").read().replace(b"\r\n", b"\n")
            mode = 0o755 if f.endswith(".sh") or rel.endswith("bin") else 0o644
            d.add(f, Node(S_IFREG | mode, data))
        for s in sorted(sub):
            mkdir((rel + "/" + s).lstrip("/"))
    for p in ("bin", "sbin", "dev", "etc", "proc", "mnt", "tmp", "root"):
        mkdir(p)
    dirs["tmp"].mode = S_IFDIR | 0o1777
    sh = dirs["bin"].add("sh", Node(S_IFREG | 0o755, open(shbin, "rb").read()))
    dirs["sbin"].add("init", sh)
    for a in APPLETS:
        dirs["bin"].add(a, sh)
    for name, t, ma, mi in DEVICES:
        dirs["dev"].add(name, Node((S_IFCHR if t == "c" else S_IFBLK) | (0o600 if name in ("mem", "kmem") else 0o666),
                                   rdev=(ma << 8) | mi))
    return root


class Ext2:
    def __init__(self):
        self.img = bytearray(FS_BLOCKS * BS)
        # block 0 boot, 1 superblock, 2 group descriptors, 3 block bitmap, 4 inode bitmap, 5.. inode table
        self.itable = 5
        self.itable_blocks = N_INODES * 128 // BS
        self.next_block = self.itable + self.itable_blocks
        self.used_blocks = set(range(1, self.next_block))
        self.next_ino = FIRST_INO
        self.ndirs = 0
        self.now = int(time.time())

    def alloc_block(self):
        b = self.next_block
        if b >= FS_BLOCKS:
            raise SystemExit("mkcard: file system full (%d KB)" % FS_BLOCKS)
        self.next_block += 1
        self.used_blocks.add(b)
        return b

    def write_data(self, data):
        """Data blocks + indirect block; returns (i_block[15], blocks used)."""
        nb = (len(data) + BS - 1) // BS
        blocks = []
        for k in range(nb):
            b = self.alloc_block()
            blocks.append(b)
            chunk = data[k * BS:(k + 1) * BS]
            self.img[b * BS:b * BS + len(chunk)] = chunk
        iblock = blocks[:12] + [0] * (12 - min(12, nb)) + [0, 0, 0]
        total = nb
        if nb > 12:
            rest = blocks[12:]
            if len(rest) > BS // 4:
                raise SystemExit("mkcard: file too large")
            ind = self.alloc_block()
            struct.pack_into("<%dI" % len(rest), self.img, ind * BS, *rest)
            iblock[12] = ind
            total += 1
        return iblock, total

    def write_inode(self, ino, mode, size, links, iblock, nblocks):
        off = self.itable * BS + (ino - 1) * 128
        struct.pack_into("<HHIIIIIHHII", self.img, off, mode, 0, size, self.now, self.now, self.now, 0, 0, links,
                         nblocks * (BS // 512), 0)
        struct.pack_into("<15I", self.img, off + 40, *iblock)

    def assign(self, node):
        if node.ino is None:
            if node is self.root:
                node.ino = ROOT_INO
            else:
                node.ino = self.next_ino
                self.next_ino += 1
                if self.next_ino > N_INODES + 1:
                    raise SystemExit("mkcard: out of inodes")
        node.links += 1
        if node.mode & 0o170000 == S_IFDIR:
            for _, ch in node.entries:
                self.assign(ch)

    def dir_data(self, node):
        ents = [(".", node), ("..", node.parent or node)] + node.entries
        out, blk = bytearray(), bytearray()
        for i, (name, ch) in enumerate(ents):
            nm = name.encode()
            rec = (8 + len(nm) + 3) & ~3
            if len(blk) + rec > BS:
                last = blk_last
                struct.pack_into("<H", blk, last + 4, BS - last)
                out += blk + bytes(BS - len(blk))
                blk = bytearray()
            blk_last = len(blk)
            blk += struct.pack("<IHH", ch.ino, rec, len(nm)) + nm + bytes(rec - 8 - len(nm))
        struct.pack_into("<H", blk, blk_last + 4, BS - blk_last)
        out += blk + bytes(BS - len(blk))
        return bytes(out)

    def emit(self, node, done):
        if node.ino in done:
            return
        done.add(node.ino)
        t = node.mode & 0o170000
        links = node.links
        if t == S_IFDIR:
            self.ndirs += 1
            links = 2 + sum(1 for _, c in node.entries if c.mode & 0o170000 == S_IFDIR)
            data = self.dir_data(node)
            ib, nb = self.write_data(data)
            self.write_inode(node.ino, node.mode, len(data), links, ib, nb)
            for _, ch in node.entries:
                self.emit(ch, done)
        elif t in (S_IFCHR, S_IFBLK):
            self.write_inode(node.ino, node.mode, 0, links, [node.rdev] + [0] * 14, 0)
        elif t == S_IFLNK and len(node.data) < 60:
            ib = list(struct.unpack("<15I", node.data.ljust(60, b"\0")))
            self.write_inode(node.ino, node.mode, len(node.data), links, ib, 0)
        else:
            ib, nb = self.write_data(node.data)
            self.write_inode(node.ino, node.mode, len(node.data), links, ib, nb)

    def build(self, root):
        self.root = root
        self.assign(root)
        root.links = 1
        self.emit(root, set())
        used_inodes = self.next_ino - 1           # 1..10 reserved + allocated
        free_inodes = N_INODES - used_inodes
        nblocks_grp = FS_BLOCKS - 1               # blocks 1..126
        free_blocks = nblocks_grp - len(self.used_blocks)
        # block bitmap: bit i = block i+1, bits past the end set
        bm = bytearray(BS)
        for i in range(BS * 8):
            if i >= nblocks_grp or (i + 1) in self.used_blocks:
                bm[i >> 3] |= 1 << (i & 7)
        self.img[3 * BS:4 * BS] = bm
        im = bytearray(BS)
        for i in range(BS * 8):
            if i >= N_INODES or i < used_inodes:
                im[i >> 3] |= 1 << (i & 7)
        self.img[4 * BS:5 * BS] = im
        struct.pack_into("<IIIHHH", self.img, 2 * BS, 3, 4, self.itable, free_blocks, free_inodes, self.ndirs)
        sb = struct.pack("<IIIIIIIIIIIIIHhHHHHIIIIHH",
                         N_INODES, FS_BLOCKS, 0, free_blocks, free_inodes, 1, 0, 0, 8192, 8192, N_INODES,
                         self.now, self.now, 0, -1, 0xEF53, 1, 1, 0, self.now, 0, 0, 0, 0, 0)
        self.img[BS:BS + len(sb)] = sb
        return bytes(self.img), free_blocks, free_inodes


def main():
    skel, shbin, out = sys.argv[1:4]
    root = build_tree(skel, shbin)
    fs, fb, fi = Ext2().build(root)
    head = struct.pack("<IIII", 0x1234, 1024, 0x50535801, 0).ljust(128, b"\0")
    card = head + bytes(7 * 128) + fs
    assert len(card) == 131072
    open(out, "wb").write(card)
    print("%s: ext2 %d KB, %d KB free, %d inodes free" % (out, FS_BLOCKS, fb, fi))


main()
