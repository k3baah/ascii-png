"""CLI entry point -- single command group with subcommands for the sticker pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from sticker_factory.config import get_config
from sticker_factory.renderer import render_variations

logger = logging.getLogger(__name__)


@click.group()
def sticker() -> None:
    """Sticker Factory -- ASCII art to print-ready PNG pipeline."""


@sticker.command()
@click.argument("ascii_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--output-dir",
    default="exports/",
    show_default=True,
    help="Directory to save rendered PNGs.",
)
@click.option(
    "--name",
    default=None,
    help="Override the design name (default: stem of the input filename).",
)
def render(ascii_file: str, output_dir: str, name: str | None) -> None:
    """Render an ASCII art file to print-ready PNGs in all color variations."""
    ascii_path = Path(ascii_file)
    design_name = name if name else ascii_path.stem
    ascii_text = ascii_path.read_text()

    cfg = get_config()
    rendering = cfg.get("rendering", {})
    color_schemes = rendering.get("color_schemes", [])
    font_size = rendering.get("font_size", 300)
    padding = rendering.get("padding", 40)

    if not color_schemes:
        click.echo("No color_schemes defined in config.yaml. Nothing to render.")
        raise SystemExit(1)

    paths = render_variations(
        ascii_text=ascii_text,
        output_dir=output_dir,
        design_name=design_name,
        color_schemes=color_schemes,
        font_size=font_size,
        padding=padding,
    )

    click.echo(f"Rendered {len(paths)} variation(s):")
    for p in paths:
        click.echo(f"  {p}")


@sticker.command()
@click.argument("png_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--title",
    default=None,
    help="Product title (default: derived from filename).",
)
@click.option(
    "--description",
    default=None,
    help="Product description (default: a generic sticker description).",
)
@click.option(
    "--blueprint-id",
    default=None,
    type=int,
    help="Printify blueprint ID (default: from config, typically 600 for die-cut stickers).",
)
def publish(
    png_file: str,
    title: str | None,
    description: str | None,
    blueprint_id: int | None,
) -> None:
    """Publish a PNG sticker design to Printify and list it on Etsy."""
    from sticker_factory.db import init_db, insert_design, update_design
    from sticker_factory.publisher import PrintifyClient

    png_path = Path(png_file)

    # --- Defaults -----------------------------------------------------------
    if title is None:
        title = png_path.stem.replace("_", " ").replace("-", " ").title()

    if description is None:
        description = (
            f"<p>High-quality die-cut sticker printed on durable vinyl.</p>"
            f"<p>{title} -- perfect for laptops, water bottles, and notebooks.</p>"
        )

    cfg = get_config()
    printify_cfg = cfg.get("printify", {})
    shop_id = printify_cfg.get("shop_id", "25769339")
    print_provider_id = printify_cfg.get("print_provider_id", 1)

    if blueprint_id is None:
        blueprint_id = printify_cfg.get("default_blueprint_id", 600)

    # --- Init DB & Printify client -----------------------------------------
    init_db()
    client = PrintifyClient()

    # --- Step 1: Upload image to Printify -----------------------------------
    click.echo(f"Uploading {png_path.name} to Printify...")
    image_id = client.upload_image(png_path, png_path.name)
    click.echo(f"  Image uploaded (ID: {image_id})")

    # --- Step 2: Fetch variants for blueprint + provider --------------------
    click.echo(f"Fetching variants for blueprint {blueprint_id}...")
    raw_variants = client.get_provider_variants(blueprint_id, print_provider_id)

    # Enable all variants at default pricing
    variants = []
    all_variant_ids = []
    for v in raw_variants:
        vid = v.get("id")
        if vid is None:
            continue
        all_variant_ids.append(vid)
        variants.append(
            {
                "id": vid,
                "price": v.get("price", 400),   # cents; fall back to $4.00
                "is_enabled": True,
            }
        )

    if not variants:
        click.echo("Error: no variants found for this blueprint/provider combo.")
        raise SystemExit(1)

    click.echo(f"  Found {len(variants)} variant(s)")

    # --- Step 3: Build print areas ------------------------------------------
    print_areas = [
        {
            "variant_ids": all_variant_ids,
            "placeholders": [
                {
                    "position": "front",
                    "images": [
                        {
                            "id": image_id,
                            "x": 0.5,
                            "y": 0.5,
                            "scale": 1,
                            "angle": 0,
                        }
                    ],
                }
            ],
        }
    ]

    # --- Step 4: Create product on Printify ---------------------------------
    click.echo(f"Creating product '{title}' on Printify...")
    product = client.create_product(
        shop_id=shop_id,
        title=title,
        description=description,
        blueprint_id=blueprint_id,
        print_provider_id=print_provider_id,
        variants=variants,
        print_areas=print_areas,
    )
    product_id = product["id"]
    click.echo(f"  Product created (ID: {product_id})")

    # --- Step 5: Publish product to Etsy ------------------------------------
    click.echo("Publishing product to Etsy...")
    client.publish_product(shop_id, product_id)
    click.echo("  Product published!")

    # --- Step 6: Store in DB ------------------------------------------------
    design_id = insert_design(
        concept_title=title,
        png_file_paths=[str(png_path.resolve())],
        status="published",
        printify_product_id=str(product_id),
    )
    click.echo(f"  Design saved to DB (ID: {design_id})")

    click.echo()
    click.echo(f"Done! Product '{title}' is live.")
    click.echo(f"  Printify product ID: {product_id}")
    click.echo(f"  Design DB ID:        {design_id}")
