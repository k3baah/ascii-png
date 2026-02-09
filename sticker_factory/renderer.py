"""ASCII-to-PNG rendering engine using Pillow.

Refactored from ascii2png.py with print-quality defaults for sticker production.
Default background is WHITE (not transparent) to avoid die-cut spacing issues.
At font_size=300, output should be 2000-4000px on the longest side.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Optional, Union

from PIL import Image, ImageDraw, ImageFilter, ImageFont


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


def _build_interior_fill_mask(
    alpha: Image.Image,
    alpha_threshold: int = 1,
    bridge_radius_px: int = 0,
    bridge_working_max_dim: int = 1200,
) -> Image.Image:
    """Build a mask for the interior silhouette using border-connected flood fill.

    Transparent pixels connected to the border are exterior.
    Everything else (solid pixels + enclosed transparent pockets) is interior.
    """
    threshold = max(1, min(255, int(alpha_threshold)))
    bridge_radius = max(0, int(bridge_radius_px))
    width, height = alpha.size
    bbox = alpha.getbbox()
    if bbox is None:
        return Image.new("L", (width, height), 0)

    left = max(0, bbox[0] - bridge_radius)
    top = max(0, bbox[1] - bridge_radius)
    right = min(width, bbox[2] + bridge_radius)
    bottom = min(height, bbox[3] + bridge_radius)

    roi_alpha = alpha.crop((left, top, right, bottom))
    roi_w, roi_h = roi_alpha.size

    # Solid mask from original alpha.
    solid_roi = roi_alpha.point(lambda a: 255 if a >= threshold else 0, mode="L")

    # Optional bridge/stroke pass to close channels before interior fill.
    # This approximates "group then stroke" while keeping runtime practical
    # on large render sizes.
    if bridge_radius > 0:
        max_dim = max(roi_w, roi_h)
        scale = min(1.0, bridge_working_max_dim / max_dim) if max_dim > 0 else 1.0

        if scale < 1.0:
            work_w = max(1, int(round(roi_w * scale)))
            work_h = max(1, int(round(roi_h * scale)))
            solid_work = solid_roi.resize((work_w, work_h), Image.NEAREST)
        else:
            work_w, work_h = roi_w, roi_h
            solid_work = solid_roi

        bridge_work = max(1, int(round(bridge_radius * scale)))
        kernel_size = (bridge_work * 2) + 1
        sealed_work = solid_work.filter(ImageFilter.MaxFilter(size=kernel_size))

        if scale < 1.0:
            solid_roi = sealed_work.resize((roi_w, roi_h), Image.NEAREST)
        else:
            solid_roi = sealed_work

    # Synthetic transparent padding guarantees a known exterior seed.
    pad = 1
    padded_w = roi_w + 2 * pad
    padded_h = roi_h + 2 * pad
    padded_solid = Image.new("L", (padded_w, padded_h), 0)
    padded_solid.paste(solid_roi, (pad, pad))
    solid_pixels = padded_solid.tobytes()

    # Flood-fill transparent pixels from the border to mark exterior.
    exterior = bytearray(padded_w * padded_h)
    queue = deque()

    for x in range(padded_w):
        for y in (0, padded_h - 1):
            idx = y * padded_w + x
            if solid_pixels[idx] == 0 and not exterior[idx]:
                exterior[idx] = 1
                queue.append((x, y))
    for y in range(padded_h):
        for x in (0, padded_w - 1):
            idx = y * padded_w + x
            if solid_pixels[idx] == 0 and not exterior[idx]:
                exterior[idx] = 1
                queue.append((x, y))

    while queue:
        cx, cy = queue.popleft()
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < padded_w and 0 <= ny < padded_h:
                nidx = ny * padded_w + nx
                if solid_pixels[nidx] == 0 and not exterior[nidx]:
                    exterior[nidx] = 1
                    queue.append((nx, ny))

    # Fill = everything not connected to exterior (includes solids + interior holes).
    fill_data = bytearray(padded_w * padded_h)
    for i in range(padded_w * padded_h):
        if not exterior[i]:
            fill_data[i] = 255

    fill_mask_padded = Image.frombytes("L", (padded_w, padded_h), bytes(fill_data))
    fill_mask_roi = fill_mask_padded.crop((pad, pad, pad + roi_w, pad + roi_h))

    fill_mask = Image.new("L", (width, height), 0)
    fill_mask.paste(fill_mask_roi, (left, top))
    return fill_mask


def _fill_gaps(
    img: Image.Image,
    alpha_threshold: int = 1,
    bridge_radius_px: int = 0,
) -> Image.Image:
    """Fill enclosed transparent gaps with white while preserving exterior transparency."""
    width, height = img.size
    alpha = img.split()[3]
    fill_mask = _build_interior_fill_mask(
        alpha,
        alpha_threshold=alpha_threshold,
        bridge_radius_px=bridge_radius_px,
    )

    backing = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    backing.putalpha(fill_mask)

    result = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    result = Image.alpha_composite(result, backing)
    result = Image.alpha_composite(result, img)

    return result


def render_ascii_to_png(
    ascii_text: str,
    output_path: Union[str, Path],
    font_size: int = 300,
    padding: int = 40,
    fg_color: str = "white",
    bg_color: Optional[str] = "white",
    fill_gaps: bool = False,
    fill_gaps_alpha_threshold: int = 1,
    fill_gaps_bridge_radius_px: int = 0,
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
        fill_gaps: If True and bg is transparent, fill internal gaps with white
                   so kiss-cut stickers cut around the whole design.
        fill_gaps_alpha_threshold: Alpha threshold used to define solid pixels
                                   during gap filling. Lower is more inclusive.
        fill_gaps_bridge_radius_px: Optional pre-fill bridge radius in source
                                    pixels. Set >0 to close channels/spaces.

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

    # Fill internal gaps for kiss-cut stickers (only on transparent bg)
    if fill_gaps and bg_color is None:
        img = _fill_gaps(
            img,
            alpha_threshold=fill_gaps_alpha_threshold,
            bridge_radius_px=fill_gaps_bridge_radius_px,
        )

    img.save(output_path)
    return output_path


def render_variations(
    ascii_text: str,
    output_dir: Union[str, Path],
    design_name: str,
    color_schemes: list[dict],
    font_size: int = 300,
    padding: int = 40,
    fill_gaps: bool = True,
    fill_gaps_alpha_threshold: int = 1,
    fill_gaps_bridge_radius_px: int = 0,
) -> list[Path]:
    """Render an ASCII design in multiple color variations.

    Args:
        ascii_text: The ASCII art string to render.
        output_dir: Directory to save the rendered PNGs.
        design_name: Base name for the output files.
        color_schemes: List of dicts, each with 'name', 'fg', 'bg' keys.
        font_size: Font size in pixels.
        padding: Padding around the text in pixels.
        fill_gaps: If True and bg is transparent, fill internal gaps with white.
        fill_gaps_alpha_threshold: Alpha threshold used for gap fill masking.
        fill_gaps_bridge_radius_px: Optional pre-fill bridge radius in pixels.

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
            fill_gaps=fill_gaps,
            fill_gaps_alpha_threshold=fill_gaps_alpha_threshold,
            fill_gaps_bridge_radius_px=fill_gaps_bridge_radius_px,
        )
        paths.append(rendered)

    return paths
