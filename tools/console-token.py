"""Decode two matching visible tokens; no frame-rate or scanout inference."""
import struct
import zlib

MAGIC=b'RGPT'
COLUMNS=16
ROWS=10


def packet(nonce,sequence):
    body=MAGIC+bytes.fromhex(nonce)+struct.pack('>I',sequence)
    if len(body)!=16:raise ValueError('nonce must have 16 hex digits')
    return body+struct.pack('>I',zlib.crc32(body))


def decode(pixels,width,height,stride,channels,nonce,scale=1):
    if scale not in (1,2) or channels not in (3,4):raise ValueError('unsupported geometry')
    if len(nonce)!=16:raise ValueError('nonce must have 16 hex digits')
    expected=bytes.fromhex(nonce)
    cell=8*scale
    def rgb(x,y):
        if not (0<=x<width and 0<=y<height):raise ValueError('token outside image')
        off=y*stride+x*channels
        p=pixels[off:off+3]
        if len(p)!=3:raise ValueError('truncated pixels')
        return tuple(p)
    decoded=[]
    for left in (16*scale,176*scale):
        top=64*scale
        # Magenta border distinguishes this token from a random desktop region.
        for x,y in ((left+cell//2,top+cell//2),(left+17*cell+cell//2,top+11*cell+cell//2)):
            r,g,b=rgb(x,y)
            if not (r>210 and g<50 and b>210):raise ValueError('missing token border')
        bits=[]
        for bit in range(160):
            x=left+(1+bit%16)*cell;y=top+(1+bit//16)*cell
            values=[]
            for dx,dy in ((2,2),(5,2),(2,5),(5,5),(4,4)):
                p=rgb(x+dx*scale,y+dy*scale)
                if min(p)>210:values.append(1)
                elif max(p)<50:values.append(0)
                else:raise ValueError('ambiguous cell')
            if len(set(values))!=1:raise ValueError('torn cell')
            bits.append(values[0])
        raw=bytes(sum(bits[i+j]<<(7-j) for j in range(8)) for i in range(0,160,8))
        if raw[:4]!=MAGIC or raw[4:12]!=expected:raise ValueError('wrong token identity')
        if zlib.crc32(raw[:16])!=struct.unpack('>I',raw[16:])[0]:raise ValueError('checksum mismatch')
        decoded.append(struct.unpack('>I',raw[12:16])[0])
    if decoded[0]!=decoded[1]:raise ValueError('torn duplicate tokens')
    return decoded[0]


class SequenceTracker:
    def __init__(self):self.last=None
    def observe(self,sequence):
        if self.last is not None and sequence<self.last:raise ValueError('out-of-order token')
        duplicate=sequence==self.last
        skipped=0 if self.last is None or duplicate else sequence-self.last-1
        self.last=sequence
        return dict(unique=not duplicate,skipped=skipped)
