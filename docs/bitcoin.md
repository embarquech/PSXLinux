# `btc`: Bitcoin mining on a PlayStation

A demonstration, not a way to earn anything: `btc` computes the real Bitcoin proof of work (double
SHA-256 of an 80-byte block header) on the PlayStation's 33 MHz R3000. A block today needs about 78
leading zero bits; the PlayStation would need around 10^19 years to find one.

## Commands

```
btc [zeros] [seconds]      mine for <seconds> (default 60), print every hash with at least <zeros>
                           (default 10) leading zero bits, then the hash rate and the best hash
btc genesis [n]            re-mine block 0 of Bitcoin (3 January 2009), starting n nonces
                           (default 20000) below the real answer
btc stratum [zeros]        mine work sent by the PC (tools/stratum_bridge.py), see below
```

`btc genesis` finds nonce 2083236893 and prints the genesis block hash,
`000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f`: block 0 of the blockchain,
mined again on a PlayStation.

`btc` alone mines a header made from the genesis block with a fresh timestamp. Every 5 seconds it
prints the time, the number of hashes, the hash rate and the best result so far.

## Mining for a real pool: `btc stratum`

The PlayStation has no network. `rootfs/tools/stratum_bridge.py` runs on the PC: it talks to a
mining pool (Stratum protocol), builds the block headers, and sends them to the PlayStation over
the serial console; the PlayStation does the hashing and sends back the nonces it finds.

```
python rootfs/tools/stratum_bridge.py --selftest                  # offline checks, no pool, no PS1
python rootfs/tools/stratum_bridge.py --genesis-test --port COMx  # the PS1 re-mines block 0 through the bridge
python rootfs/tools/stratum_bridge.py --pool HOST:PORT --user ADDRESS[.worker] --port COMx
```

The shell must be at its prompt on that port (close any other terminal first): the bridge types
`btc stratum` itself. Options: `--password`, `--suggest-diff` (ask the pool for an easy share
difficulty), `--chunk` (nonces per piece of work), `--zeros` (report hashes from that many zero
bits, to watch progress). Every hash the PlayStation reports is checked again on the PC against the
exact share target before it is submitted to the pool.

Line protocol (one line each, hex numbers):

| Direction | Line | Meaning |
|---|---|---|
| PS1 to PC | `R` | ready for work |
| PC to PS1 | `W <header bytes 0-75, 152 hex digits> <first nonce> <count> <zero bits>` | a range of nonces to try |
| PS1 to PC | `S <nonce>` | a hash with at least the requested zero bits (a share candidate) |
| PS1 to PC | `Z <nonce> <bits>` | a lesser hash (progress display) |
| PS1 to PC | `D <count> <seconds>` | range done |
| PC to PS1 | `Q` | quit |

## How it works

SHA-256 is written in plain C (32-bit integer operations only, which suit the R3000). The miner uses
the **midstate** trick: the first 64 bytes of the header do not change while the nonce does, so
their SHA-256 block is computed once per piece of work, and each try costs two SHA-256 blocks
instead of three. The code is the `btc` section of `rootfs/src/psxsh.c`.
