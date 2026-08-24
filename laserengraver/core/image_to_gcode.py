from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .gcode import GCodeBuilder, clamp


def _prepare_image(image: Image.Image, width_px: int, invert: bool) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("L")
    if invert:
        image = ImageOps.invert(image)
    if image.width > width_px:
        ratio = width_px / image.width
        height_px = max(1, int(image.height * ratio))
        image = image.resize((width_px, height_px), Image.Resampling.LANCZOS)
    return image


def image_to_scanline_gcode(
    image: Image.Image,
    title: str,
    width_mm: float = 60.0,
    feed: int = 1600,
    max_power: int = 320,
    pwm_max: int = 1000,
    threshold: int | None = 170,
    invert: bool = False,
    overscan_mm: float = 0.25,
) -> str:
    max_width_px = 220 if threshold is None else 360
    image = _prepare_image(image, max_width_px, invert)
    scale = width_mm / image.width
    height_mm = image.height * scale
    pixel = scale
    max_power = int(clamp(max_power, 1, pwm_max))

    b = GCodeBuilder(title, pwm_max)
    b.comment(f"Raster size {width_mm:.2f} x {height_mm:.2f} mm, {image.width} x {image.height} px")
    b.comment("Generated as horizontal scanlines.")
    pixels = image.load()

    if threshold is None:
        for row in range(image.height):
            y = row * pixel
            xs = range(image.width) if row % 2 == 0 else range(image.width - 1, -1, -1)
            first_x = 0 if row % 2 == 0 else image.width * pixel
            b.rapid(first_x, y)
            b.laser_on(0)
            for col in xs:
                gray = pixels[col, row]
                darkness = (255 - gray) / 255
                power = int(darkness * max_power)
                x = (col + (1 if row % 2 == 0 else 0)) * pixel
                b.cut(x, y, feed=feed, power=power)
            b.laser_off()
        return b.finish()

    for row in range(image.height):
        y = row * pixel
        dark_runs: list[tuple[int, int]] = []
        start: int | None = None
        for col in range(image.width):
            is_dark = pixels[col, row] < threshold
            if is_dark and start is None:
                start = col
            if (not is_dark or col == image.width - 1) and start is not None:
                end = col if is_dark and col == image.width - 1 else col - 1
                dark_runs.append((start, end))
                start = None
        if row % 2 == 1:
            dark_runs.reverse()
        for start_col, end_col in dark_runs:
            if row % 2 == 0:
                sx = start_col * pixel
                ex = (end_col + 1) * pixel
            else:
                sx = (end_col + 1) * pixel
                ex = start_col * pixel
            b.rapid(max(0.0, sx - overscan_mm), y)
            b.laser_on(max_power)
            b.cut(ex + (overscan_mm if ex >= sx else -overscan_mm), y, feed=feed, power=max_power)
            b.laser_off()
    return b.finish()


def text_to_image(text: str, font_size: int = 42, padding: int = 16) -> Image.Image:
    text = text.strip() or "Jambo"
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default(size=font_size)
    probe = Image.new("L", (10, 10), 255)
    draw = ImageDraw.Draw(probe)
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=8)
    width = bbox[2] - bbox[0] + padding * 2
    height = bbox[3] - bbox[1] + padding * 2
    image = Image.new("L", (max(1, width), max(1, height)), 255)
    draw = ImageDraw.Draw(image)
    draw.multiline_text((padding, padding - bbox[1]), text, font=font, fill=0, spacing=8)
    return image


def image_from_upload(raw: bytes) -> Image.Image:
    return Image.open(BytesIO(raw))
