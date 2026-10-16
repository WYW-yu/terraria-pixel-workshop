"""地图候选与无损压缩查找表；仅在首次地图匹配时解压到内存。"""
import struct
import zlib
from functools import lru_cache

from .material_library import ASSETS

MAP_COUNTS = {'all': 12141, 'tile': 5871, 'wall': 6270}
TABLE_BYTES = 2 ** 25


@lru_cache(maxsize=3)
def candidate_records(kind):
    expected = MAP_COUNTS[kind]
    path = ASSETS / f'library_{kind}.tr'
    try:
        with path.open('rb') as stream:
            header = stream.read(2 + expected * 7)
        # Also accept a complete original table when rebuilding the source assets.
        if len(header) != 2 + expected * 7 or path.stat().st_size not in (len(header), len(header) + TABLE_BYTES):
            raise ValueError()
        if struct.unpack_from('<H', header)[0] != expected:
            raise ValueError()
    except (OSError, ValueError, struct.error) as exc:
        raise ValueError('地图颜色库不完整，请重新解压完整程序') from exc
    return header[2:]


def table_bytes(kind):
    """返回精确的RGB索引表，不在程序目录或临时目录释放大文件。"""
    candidate_records(kind)
    packed = ASSETS / f'library_{kind}.lut.z'
    try:
        if packed.is_file():
            decoder = zlib.decompressobj()
            content = decoder.decompress(packed.read_bytes(), TABLE_BYTES + 1)
            if not decoder.eof or decoder.unused_data or len(content) != TABLE_BYTES:
                raise ValueError()
        else:
            with (ASSETS / f'library_{kind}.tr').open('rb') as stream:
                stream.seek(2 + MAP_COUNTS[kind] * 7)
                content = stream.read(TABLE_BYTES + 1)
            if len(content) != TABLE_BYTES:
                raise ValueError()
    except (OSError, ValueError, zlib.error) as exc:
        raise ValueError('地图查找表损坏或缺失，请重新解压完整程序') from exc
    return content
