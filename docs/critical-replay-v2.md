# Critical replay schema 2

Critical replay schema 2 replaces the long `RGPU_EVENT` replay lines with
bounded hexadecimal chunks. Live `BUILD:` and `XH2` records remain unchanged.
The replay runs only from the existing deferred diagnostic thread; producer
hooks still append immutable records without allocation, MMIO, locks, or waits.

The experiment manifest selects this protocol with the numeric JSON field
`"critical_replay_schema": 2`. The `v=1` field below is the wire revision within
schema 2.

## Chunk record

```text
RGPU_CR2 v=1 b=<32hex> s=<8hex> r=<4hex> p=<2hex>/<2hex> n=<2hex> c=<8hex> d=<0..80hex>
```

All hexadecimal text is lowercase and fixed width. `b` is the 16-byte build
identity. `s` is a strictly increasing snapshot-attempt number. `r` is an
immutable record index from `0000` through `01ff`. `p` is a zero-based chunk
index followed by its total chunk count. `n` is the raw payload length from
`00` through `28` (40 bytes), and `d` is exactly `2*n` hexadecimal characters.
A zero-length record has the sole chunk `p=00/01 n=00 d=`. A 511-byte record
uses at most 13 chunks.

Decoded records contain printable ASCII bytes `0x20..0x7e`; the terminating NUL
is excluded. NUL, CR, LF, non-ASCII bytes, missing termination, and records over
511 bytes make the attempt incomplete and suppress its manifest.

`c` is CRC-32/ISO-HDLC: initial value and xor-out are `0xffffffff`, with the
reflected polynomial `0xedb88320`. Its byte domain is:

```text
u8(1) || build[16] || LE32(snapshot) || LE16(record) ||
u8(part) || u8(parts) || u8(length) || payload[length]
```

CRC and the digest below detect accidental corruption. They provide no
cryptographic authentication.

The longest controlled chunk text is 172 characters. With the observed
24-character `RaphaelGPU      rgpu: @ ` prefix and newline, it occupies 197
bytes, below the strict 240-byte physical-line limit.

## Complete-prefix manifest

```text
RGPU_END2 v=1 b=<32hex> s=<8hex> first=0000 count=<4hex> drop=<16hex> trunc=<16hex> bytes=<8hex> chunks=<8hex> crc=<8hex> fnv=<16hex> state=complete
```

Before emitting any chunk, the worker captures `count`, `drop`, and `trunc` and
checks that every record in the prefix `0..count-1` is published and canonical.
It emits nothing for a normally pending reservation. Once preflight succeeds,
all covered slots are immutable. An interruption during emission leaves a real
incomplete attempt and must fail closed.

`bytes` is the sum of decoded record lengths and `chunks` is the sum of their
part counts. `crc` is CRC-32/ISO-HDLC and `fnv` is standard FNV-1a-64 with offset
`0xcbf29ce484222325` and prime `0x100000001b3`. Both cover the same canonical
snapshot byte stream:

```text
"RGPU-CR2\0" || u8(1) || build[16] || LE32(snapshot) ||
LE16(first) || LE16(count) || LE64(drop) || LE64(trunc) ||
LE32(bytes) || LE32(chunks) ||
for each record in order: LE16(record) || LE16(record_length) || record_bytes
```

The longest manifest text is 206 characters and occupies 231 physical bytes
including the observed prefix and newline.

## Consumer rules

A consumer accepts only the expected build, a complete `0..count-1` record
range, complete ordered chunks, exact lengths, every chunk CRC, both manifest
digests, and matching manifest totals. Identical transport duplicates may be
deduplicated. Conflicting duplicates are fatal. Later complete snapshots must
have larger snapshot numbers, may only extend the prefix, and must reproduce all
earlier record bytes exactly.

`state=complete` proves only that this immutable-prefix snapshot completed. It
does not prove terminal guest state, safe cleanup, or absence of a later abort.
Cleanup authorization additionally needs the separately versioned persistent
recovery-lifetime marker.

## Cross-language boundary vector

For build `0123456789abcdef0123456789abcdef`, snapshot `01020304`, records
`A*184` and `B*511`, and zero dropped/truncated records, the stream contains 18
chunks and 695 record bytes. Its terminal line is:

```text
RGPU_END2 v=1 b=0123456789abcdef0123456789abcdef s=01020304 first=0000 count=0002 drop=0000000000000000 trunc=0000000000000000 bytes=000002b7 chunks=00000012 crc=c8001837 fnv=2231439245f39550 state=complete
```

The first chunk CRC is `5fb98dfd`; record 0 part `04/05` is `ea236aa2`; record 1
part `0c/0d` is `d8065aa9`. Guest and host tests share these literal values.
