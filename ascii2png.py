#!/usr/bin/env python3
"""
ascii2png - Convert ASCII art text files to PNG images.

Usage:
    python ascii2png.py input.txt                    # Single file
    python ascii2png.py *.txt                        # Multiple files
    python ascii2png.py input.txt -s 24              # Custom font size
    python ascii2png.py input.txt -o output.png      # Custom output name
    python ascii2png.py input.txt --bg black --fg green  # Custom colors
"""

import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def get_monospace_font(size: int) -> ImageFont.FreeTypeFont:
    """Get a monospace font, falling back to default if needed."""
    # Try common monospace fonts
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


def ascii_to_png(
    text: str,
    font_size: int = 16,
    bg_color: str | None = "black",
    fg_color: str = "white",
    padding: int = 20,
) -> Image.Image:
    """Convert ASCII art text to a PNG image."""
    
    font = get_monospace_font(font_size)
    lines = text.rstrip("\n").split("\n")
    
    # Calculate dimensions
    # Use a test character to get consistent sizing for monospace
    test_bbox = font.getbbox("M")
    char_width = test_bbox[2] - test_bbox[0]
    char_height = int(font_size * 1.2)  # Line height
    
    max_line_length = max(len(line) for line in lines) if lines else 0
    
    img_width = (char_width * max_line_length) + (padding * 2)
    img_height = (char_height * len(lines)) + (padding * 2)
    
    # Create image (RGBA for transparency support)
    if bg_color is None:
        # Transparent background
        img = Image.new("RGBA", (img_width, img_height), (0, 0, 0, 0))
    else:
        img = Image.new("RGBA", (img_width, img_height), bg_color)
    
    draw = ImageDraw.Draw(img)
    
    # Draw each line
    y = padding
    for line in lines:
        draw.text((padding, y), line, font=font, fill=fg_color)
        y += char_height
    
    return img


def convert_file(
    input_path: Path,
    output_path: Path | None = None,
    output_dir: Path | None = None,
    font_size: int = 16,
    bg_color: str | None = None,
    fg_color: str = "white",
    padding: int = 20,
) -> Path:
    """Convert a single ASCII art file to PNG."""
    
    text = input_path.read_text()
    
    if output_path is None:
        png_name = input_path.stem + ".png"
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / png_name
        else:
            output_path = input_path.with_suffix(".png")
    
    img = ascii_to_png(text, font_size, bg_color, fg_color, padding)
    img.save(output_path)
    
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert ASCII art text files to PNG images.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s art.txt                     Convert single file
  %(prog)s *.txt                       Convert all .txt files
  %(prog)s art.txt -s 32               Larger font (higher resolution)
  %(prog)s art.txt -o output.png       Specify output filename
  %(prog)s art.txt --bg black --fg green   Matrix style
  %(prog)s art.txt --bg white --fg black   Print-friendly
        """,
    )
    
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="Input ASCII art file(s)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output filename (only valid with single input file)",
    )
    parser.add_argument(
        "-d", "--output-dir",
        type=Path,
        default=Path("exports"),
        help="Output directory for generated PNGs (default: exports/)",
    )
    parser.add_argument(
        "-s", "--size",
        type=int,
        default=48,
        help="Font size in pixels (default: 48)",
    )
    parser.add_argument(
        "--bg",
        default="transparent",
        help="Background color (default: transparent)",
    )
    parser.add_argument(
        "--fg",
        default="white", 
        help="Foreground/text color (default: white)",
    )
    parser.add_argument(
        "-p", "--padding",
        type=int,
        default=20,
        help="Padding in pixels (default: 20)",
    )
    
    args = parser.parse_args()
    
    # Validate args
    if args.output and len(args.files) > 1:
        parser.error("--output can only be used with a single input file")
    
    # Handle transparent background
    bg_color = None if args.bg.lower() == "transparent" else args.bg
    
    # Convert files
    for input_file in args.files:
        if not input_file.exists():
            print(f"⚠️  Skipping {input_file}: file not found")
            continue
        
        output = args.output if args.output else None
        
        try:
            result = convert_file(
                input_file,
                output,
                output_dir=args.output_dir if not output else None,
                font_size=args.size,
                bg_color=bg_color,
                fg_color=args.fg,
                padding=args.padding,
            )
            print(f"✓ {input_file} → {result}")
        except Exception as e:
            print(f"✗ {input_file}: {e}")


if __name__ == "__main__":
    main()

