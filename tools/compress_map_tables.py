"""将原始既有色库表拆成候选记录和zlib查找表，逐字节验证后替换源资产。"""
import hashlib
import json
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]


def build(folder):
    audit = {}
    for kind, expected in (('all', 12141), ('tile', 5871), ('wall', 6270)):
        path = folder / f'library_{kind}.tr'
        raw = path.read_bytes()
        offset = 2 + expected * 7
        if struct.unpack_from('<H', raw)[0] != expected:
            raise ValueError(f'地图候选数量错误：{kind}')
        if len(raw) == offset:
            lookup = zlib.decompress((folder / f'library_{kind}.lut.z').read_bytes())
            raw += lookup
        if len(raw) != offset + 2 ** 25:
            raise ValueError(f'地图查找表大小错误：{kind}')
        packed = zlib.compress(raw[offset:], level=9)
        assert raw[:offset] + zlib.decompress(packed) == raw
        (folder / f'library_{kind}.lut.z').write_bytes(packed)
        path.write_bytes(raw[:offset])
        audit[kind] = dict(original_bytes=len(raw), stored_bytes=offset + len(packed),
                          original_sha256=hashlib.sha256(raw).hexdigest(),
                          lookup_sha256=hashlib.sha256(raw[offset:]).hexdigest())
    (ROOT / 'tools/map_compression.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    return audit


if __name__ == '__main__':
    print(json.dumps(build(ROOT / 'assets'), indent=2))
