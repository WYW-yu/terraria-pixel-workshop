"""轻量格式定义；启动桌面时无需导入转换算法和游戏色表。"""
import re

VERSIONS = ('fine', 'wall', 'map')
PREVIEW_NAMES = ('像素画预览.png', '像素画预览-背景墙版.png', '像素画预览-地图版.png')
VERSION_DESCRIPTIONS = {
    'fine': '适合直接观看，使用物块和背景墙，搭配喷漆。',
    'wall': '适合直接观看，只使用背景墙，搭配喷漆。',
    'map': '适合从大小地图观看，使用物块和背景墙，搭配喷漆。',
}
PREVIEW_DESCRIPTIONS = {
    0: '导入的原始图片。',
    4: '已缩小和调色，尚未匹配游戏材料。',
    1: VERSION_DESCRIPTIONS['fine'],
    3: VERSION_DESCRIPTIONS['wall'],
    5: VERSION_DESCRIPTIONS['map'],
}


class ConversionCancelled(Exception):
    """用户主动取消生成。"""


def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:100]
    if name.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1, 10)], *[f'LPT{i}' for i in range(1, 10)]}:
        name = '_' + name
    return name or '像素画'
