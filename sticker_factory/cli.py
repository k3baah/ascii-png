"""CLI entry point -- single command group with subcommands for the sticker pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from sticker_factory.config import get_config
from sticker_factory.renderer import render_ascii_to_png

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
@click.option(
    "--concept",
    default=None,
    help="Concept id override (default: auto-discover from ASCII filename).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Re-render all variations and supersede existing active DB rows.",
)
def render(
    ascii_file: str,
    output_dir: str,
    name: str | None,
    concept: str | None,
    force: bool,
) -> None:
    """Render an ASCII art file to print-ready PNGs in all color variations."""
    from sticker_factory.concepts import (
        concept_path_for_id,
        discover_concept_for_ascii,
        load_concept,
    )
    from sticker_factory.db import (
        get_active_design_by_key,
        get_design_by_png_path,
        init_db,
        insert_design,
        update_design,
    )

    ascii_path = Path(ascii_file)
    design_name = name if name else ascii_path.stem
    ascii_text = ascii_path.read_text()

    cfg = get_config()
    rendering = cfg.get("rendering", {})
    font_size = rendering.get("font_size", 300)
    padding = rendering.get("padding", 40)
    fill_gaps = rendering.get("fill_gaps", True)
    fill_gaps_alpha_threshold = rendering.get("fill_gaps_alpha_threshold", 1)
    fill_gaps_bridge_radius_px = rendering.get("fill_gaps_bridge_radius_px", 0)

    concept_data = None
    concept_id = concept
    if concept_id:
        concept_path = concept_path_for_id(concept_id)
        if not concept_path.exists():
            click.echo(f"Concept file not found for id '{concept_id}': {concept_path}")
            raise SystemExit(1)
        concept_data = load_concept(concept_path)
    else:
        concept_data = discover_concept_for_ascii(ascii_path)
        concept_id = concept_data["id"] if concept_data else None

    if concept_data and concept_data.get("variations"):
        color_schemes = [
            {"name": v["scheme"], "fg": v["fg"], "bg": v["bg"]}
            for v in concept_data["variations"]
        ]
        click.echo(f"Using {len(color_schemes)} variation(s) from concept '{concept_data['id']}'.")
    else:
        color_schemes = rendering.get("color_schemes", [])

    if not color_schemes:
        click.echo("No color_schemes defined in config.yaml. Nothing to render.")
        raise SystemExit(1)

    init_db()

    output_root = Path(output_dir)
    rendered: list[tuple[Path, int]] = []
    skipped: list[str] = []
    superseded_count = 0
    for scheme in color_schemes:
        scheme_name = scheme.get("name") or scheme.get("scheme")
        fg = scheme.get("fg")
        bg = scheme.get("bg")
        if not scheme_name or not fg or bg is None:
            click.echo(f"Skipping invalid color scheme: {scheme}")
            continue

        output_path = output_root / f"{design_name}_{scheme_name}.png"
        design_key_prefix = concept_id if concept_id else design_name
        design_key = f"{design_key_prefix}::{scheme_name}"

        active_by_key = get_active_design_by_key(design_key)
        if active_by_key and not force:
            existing_path = active_by_key.get("png_path_canonical") or active_by_key.get("png_path")
            if existing_path and Path(existing_path).exists():
                skipped.append(scheme_name)
                continue

        # On --force (or stale records), supersede any active rows that would
        # conflict with this render's logical key/path before inserting a new row.
        superseded_ids: set[int] = set()
        if active_by_key and active_by_key.get("id") is not None:
            superseded_ids.add(int(active_by_key["id"]))

        active_by_path = get_design_by_png_path(output_path, include_superseded=False)
        if active_by_path and active_by_path.get("id") is not None:
            superseded_ids.add(int(active_by_path["id"]))

        for existing_id in superseded_ids:
            superseded_count += update_design(existing_id, is_superseded=1)

        bg_color = None if str(bg).lower() == "transparent" else bg
        rendered_path = render_ascii_to_png(
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
        design_id = insert_design(
            concept_id=concept_id,
            variation_name=scheme_name,
            variation_fg=fg,
            variation_bg=bg,
            png_path=str(rendered_path.resolve(strict=False)),
            ascii_file_path=str(ascii_path.resolve(strict=False)),
            copy_state="missing",
            copy_revision=0,
            publish_state="never",
            published_copy_revision=0,
            is_superseded=0,
        )
        rendered.append((rendered_path, design_id))

    click.echo(f"Rendered {len(rendered)} variation(s).")
    for path, design_id in rendered:
        click.echo(f"  {path} (design_id={design_id})")
    if skipped:
        click.echo(f"Skipped {len(skipped)} variation(s): {', '.join(skipped)}")
    if superseded_count:
        click.echo(f"Superseded {superseded_count} existing active row(s).")


@sticker.command()
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True))
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Regenerate copy even if a sidecar file already exists.",
)
def copywrite(paths: tuple[str, ...], overwrite: bool) -> None:
    """Generate Etsy listing copy (title, description, tags) for sticker PNGs.

    Accepts one or more PNG files or directories. Writes a .copy.json sidecar
    next to each image.
    """
    from sticker_factory.copywriter import (
        find_concept,
        generate_copy,
        read_sidecar,
        write_sidecar,
    )

    png_files: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            png_files.extend(sorted(path.glob("*.png")))
        elif path.suffix.lower() == ".png":
            png_files.append(path)
        else:
            click.echo(f"Skipping non-PNG: {path}")

    if not png_files:
        click.echo("No PNG files found.")
        raise SystemExit(1)

    click.echo(f"Processing {len(png_files)} image(s)...")
    for png_path in png_files:
        if not overwrite and read_sidecar(png_path) is not None:
            click.echo(f"  {png_path.name}: sidecar exists, skipping (use --overwrite)")
            continue

        concept = find_concept(png_path)
        if concept:
            click.echo(f"  {png_path.name}: found concept '{concept.get('id')}', generating copy...")
        else:
            click.echo(f"  {png_path.name}: no concept file found, generating copy from image only...")

        try:
            copy = generate_copy(png_path, concept=concept)
        except Exception as exc:
            click.echo(f"    ERROR: {exc}")
            continue

        sidecar = write_sidecar(png_path, copy)
        click.echo(f"    Title: {copy['title']}")
        click.echo(f"    Tags:  {', '.join(copy['tags'][:5])}...")
        click.echo(f"    Saved: {sidecar}")

    click.echo("Done.")


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
    help="Printify blueprint ID (default: from config).",
)
@click.option(
    "--surface",
    default="White",
    show_default=True,
    type=click.Choice(["White", "Transparent"], case_sensitive=False),
    help="Sticker surface type.",
)
@click.option(
    "--etsy/--no-etsy",
    default=False,
    show_default=True,
    help="Also publish to Etsy (default: Printify only).",
)
def publish(
    png_file: str,
    title: str | None,
    description: str | None,
    blueprint_id: int | None,
    surface: str,
    etsy: bool,
) -> None:
    """Upload a PNG sticker design to Printify. Use --etsy to also publish to Etsy."""
    from sticker_factory.copywriter import read_sidecar
    from sticker_factory.db import init_db, insert_design, update_design
    from sticker_factory.publisher import PrintifyClient

    png_path = Path(png_file)

    # --- Defaults: sidecar > filename-derived > generic ---------------------
    sidecar = read_sidecar(png_path)

    if title is None:
        if sidecar and sidecar.get("title"):
            title = sidecar["title"]
            click.echo(f"Using title from sidecar: {title}")
        else:
            title = png_path.stem.replace("_", " ").replace("-", " ").title()

    if description is None:
        if sidecar and sidecar.get("description"):
            description = sidecar["description"]
            click.echo("Using description from sidecar.")
        else:
            description = (
                f"<p>High-quality die-cut sticker printed on durable vinyl.</p>"
                f"<p>{title} -- perfect for laptops, water bottles, and notebooks.</p>"
            )

    cfg = get_config()
    printify_cfg = cfg.get("printify", {})
    shop_id = printify_cfg.get("shop_id", "25769339")
    print_provider_id = printify_cfg.get("print_provider_id", 1)
    pricing = printify_cfg.get("pricing", {})

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

    # Filter variants by surface type, set retail prices from config
    variants = []
    all_variant_ids = []
    for v in raw_variants:
        vid = v.get("id")
        if vid is None:
            continue
        v_surface = v.get("options", {}).get("surface", "")
        if v_surface.lower() != surface.lower():
            continue
        v_size = v.get("options", {}).get("size", "")
        price = pricing.get(v_size, 499)  # default $4.99 if size not in config
        all_variant_ids.append(vid)
        variants.append(
            {
                "id": vid,
                "price": price,
                "is_enabled": True,
            }
        )

    if not variants:
        click.echo("Error: no variants found for this blueprint/provider combo.")
        raise SystemExit(1)

    click.echo(f"  Found {len(variants)} variant(s):")
    for v, rv in zip(variants, [r for r in raw_variants if r.get("options", {}).get("surface", "").lower() == surface.lower()]):
        size = rv.get("options", {}).get("size", "?")
        click.echo(f"    {size} @ ${v['price'] / 100:.2f}")

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

    # --- Step 5: Optionally publish to Etsy ----------------------------------
    status = "uploaded"
    if etsy:
        click.echo("Publishing product to Etsy...")
        client.publish_product(shop_id, product_id)
        click.echo("  Product published to Etsy!")
        status = "published"
    else:
        click.echo("  Product created on Printify (not published to Etsy).")
        click.echo("  Use --etsy flag to also publish to Etsy.")

    # --- Step 6: Store in DB ------------------------------------------------
    design_id = insert_design(
        concept_title=title,
        png_file_paths=[str(png_path.resolve())],
        status=status,
        printify_product_id=str(product_id),
    )
    click.echo(f"  Design saved to DB (ID: {design_id})")

    click.echo()
    click.echo(f"Done! Product '{title}' on Printify.")
    click.echo(f"  Printify product ID: {product_id}")
    click.echo(f"  Design DB ID:        {design_id}")
