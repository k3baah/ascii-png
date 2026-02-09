"""ASCII-to-PNG rendering engine using Pillow.

Refactored from ascii2png.py with print-quality defaults for sticker production.
Default background is WHITE (not transparent) to avoid die-cut spacing issues.
At font_size=300, output should be 2000-4000px on the longest side.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from PIL import Image, ImageDraw, ImageFont


def get_monospace_font(size: int) -> ImageFont.FreeTypeFont:
    """Get a monospace font, falling back to default if needed."""
    font_names = [
        "Menlo",
        "Monaco",
        "Consolas",
        "DejaVuSansMono",
        "LiberationMono",
        "CourierNew",
        "Courier",
    ]

    for name in font_names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue

    # Fallback to default
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Older Pillow versions don't support size param
        return ImageFont.load_default()


def render_ascii_to_png(
    ascii_text: str,
    output_path: Union[str, Path],
    font_size: int = 300,
    padding: int = 40,
    fg_color: str = "white",
    bg_color: Optional[str] = "white",
) -> Path:
    """Render ASCII art text to a print-quality PNG image.

    Args:
        ascii_text: The ASCII art string to render.
        output_path: Where to save the PNG file.
        font_size: Font size in pixels (200-400 recommended for print quality).
        padding: Padding around the text in pixels.
        fg_color: Foreground (text) color.
        bg_color: Background color. Defaults to "white" for sticker production.
                  Use None or "transparent" for a transparent background.

    Returns:
        The output path as a Path object.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    font = get_monospace_font(font_size)
    lines = ascii_text.rstrip("\n").split("\n")

    # Calculate dimensions using monospace character metrics
    test_bbox = font.getbbox("M")
    char_width = test_bbox[2] - test_bbox[0]
    char_height = int(font_size * 1.2)  # Line height with spacing

    max_line_length = max(len(line) for line in lines) if lines else 0

    img_width = (char_width * max_line_length) + (padding * 2)
    img_height = (char_height * len(lines)) + (padding * 2)

    # Normalize transparent background
    if isinstance(bg_color, str) and bg_color.lower() == "transparent":
        bg_color = None

    # Create image (RGBA for transparency support)
    if bg_color is None:
        img = Image.new("RGBA", (img_width, img_height), (0, 0, 0, 0))
    else:
        img = Image.new("RGBA", (img_width, img_height), bg_color)

    draw = ImageDraw.Draw(img)

    # Draw each line
    y = padding
    for line in lines:
        draw.text((padding, y), line, font=font, fill=fg_color)
        y += char_height

    img.save(output_path)
    return output_path


def render_variations(
    ascii_text: str,
    output_dir: Union[str, Path],
    design_name: str,
    color_schemes: list[dict],
    font_size: int = 300,
    padding: int = 40,
) -> list[Path]:
    """Render an ASCII design in multiple color variations.

    Args:
        ascii_text: The ASCII art string to render.
        output_dir: Directory to save the rendered PNGs.
        design_name: Base name for the output files.
        color_schemes: List of dicts, each with 'name', 'fg', 'bg' keys.
        font_size: Font size in pixels.
        padding: Padding around the text in pixels.

    Returns:
        List of output Paths for each rendered variation.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for scheme in color_schemes:
        scheme_name = scheme["name"]
        fg = scheme["fg"]
        bg = scheme["bg"]

        # Treat "transparent" as None for bg_color
        bg_color: Optional[str] = None if bg == "transparent" else bg

        output_path = output_dir / f"{design_name}_{scheme_name}.png"
        rendered = render_ascii_to_png(
            ascii_text=ascii_text,
            output_path=output_path,
            font_size=font_size,
            padding=padding,
            fg_color=fg,
            bg_color=bg_color,
        )
        paths.append(rendered)

    return paths
