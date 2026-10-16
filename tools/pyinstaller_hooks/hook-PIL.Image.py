"""Collect the application's supported image formats, not every Pillow codec."""
hiddenimports = [
    'PIL.BmpImagePlugin', 'PIL.GifImagePlugin',
    'PIL.JpegImagePlugin', 'PIL.PngImagePlugin', 'PIL.PpmImagePlugin',
    'PIL.TiffImagePlugin', 'PIL.WebPImagePlugin', 'PIL.IcoImagePlugin',
]
