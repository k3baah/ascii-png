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
@click.argument("paths", nargs=-1, required=False, type=click.Path(exists=True))
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Regenerate copy even if DB copy already exists.",
)
@click.option(
    "--no-copy",
    "no_copy",
    is_flag=True,
    default=False,
    help="Process active DB rows where copy_state=missing.",
)
def copywrite(paths: tuple[str, ...], overwrite: bool, no_copy: bool) -> None:
    """Generate Etsy listing copy and write it directly to DB rows."""
    from sticker_factory.copywriter import find_concept, generate_copy
    from sticker_factory.db import (
        get_design_by_png_path,
        init_db,
        list_designs,
        update_design,
    )

    if not paths and not no_copy:
        click.echo("Provide PNG path(s)/directory(ies), or use --no-copy.")
        raise SystemExit(1)

    init_db()

    rows_to_process: dict[int, dict] = {}

    # Mode 1: explicit files/directories resolved to DB rows by png path.
    png_files: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            png_files.extend(sorted(path.glob("*.png")))
        elif path.suffix.lower() == ".png":
            png_files.append(path)
        else:
            click.echo(f"Skipping non-PNG: {path}")

    for png_path in png_files:
        row = get_design_by_png_path(png_path, include_superseded=False)
        if row is None:
            click.echo(f"  {png_path.name}: no active DB row found, skipping")
            continue
        rows_to_process[int(row["id"])] = row

    # Mode 2: select missing-copy rows from DB.
    if no_copy:
        for row in list_designs(copy_state="missing", is_superseded=0):
            rows_to_process[int(row["id"])] = row

    if not rows_to_process:
        click.echo("No DB rows selected for copywriting.")
        return

    click.echo(f"Processing {len(rows_to_process)} design row(s)...")
    success = 0
    errors = 0
    skipped = 0

    for row_id in sorted(rows_to_process):
        row = rows_to_process[row_id]
        png_path = row.get("png_path_canonical") or row.get("png_path")
        if not png_path:
            click.echo(f"  id={row_id}: missing png_path, skipping")
            skipped += 1
            continue

        image_path = Path(png_path)
        if not image_path.exists():
            click.echo(f"  id={row_id}: PNG not found on disk, skipping ({image_path})")
            skipped += 1
            continue

        if not overwrite and row.get("copy_state") == "ready":
            click.echo(f"  id={row_id}: copy already ready, skipping (use --overwrite)")
            skipped += 1
            continue

        concept = find_concept(image_path)
        context_note = (
            f"concept '{concept.get('id')}'" if concept else "image-only context"
        )
        click.echo(f"  id={row_id}: generating copy ({context_note})...")

        try:
            copy = generate_copy(image_path, concept=concept)
            current_revision = int(row.get("copy_revision") or 0)
            update_design(
                row_id,
                listing_title=copy["title"],
                listing_description=copy["description"],
                listing_tags=copy["tags"],
                copy_state="ready",
                copy_revision=current_revision + 1,
                last_error=None,
            )
            click.echo(f"    Title: {copy['title']}")
            click.echo(f"    Tags:  {', '.join(copy['tags'][:5])}...")
            success += 1
        except Exception as exc:
            update_design(row_id, copy_state="error", last_error=str(exc))
            click.echo(f"    ERROR: {exc}")
            errors += 1

    click.echo(
        f"Done. Updated={success}, skipped={skipped}, errors={errors}."
    )


@sticker.command("migrate-sidecars")
@click.argument("paths", nargs=-1, required=False, type=click.Path(exists=True))
@click.option(
    "--apply/--dry-run",
    "apply_changes",
    default=False,
    show_default=True,
    help="Apply DB updates, or preview what would change.",
)
def migrate_sidecars(paths: tuple[str, ...], apply_changes: bool) -> None:
    """Import existing .copy.json files into DB copy columns."""
    import json

    from sticker_factory.db import get_design_by_png_path, init_db, update_design

    init_db()

    search_targets = [Path(p) for p in paths] if paths else [Path("exports")]
    sidecars: list[Path] = []
    for target in search_targets:
        if target.is_dir():
            sidecars.extend(sorted(target.rglob("*.copy.json")))
        elif target.is_file() and target.name.endswith(".copy.json"):
            sidecars.append(target)

    if not sidecars:
        click.echo("No sidecar files found.")
        return

    click.echo(
        f"{'Applying' if apply_changes else 'Dry-run'} import for {len(sidecars)} sidecar file(s)..."
    )

    updated = 0
    skipped = 0
    failed = 0
    for sidecar_path in sidecars:
        if not sidecar_path.name.endswith(".copy.json"):
            skipped += 1
            continue

        png_name = f"{sidecar_path.name[:-10]}.png"
        png_path = sidecar_path.with_name(png_name)
        row = get_design_by_png_path(png_path, include_superseded=False)
        if row is None:
            click.echo(f"  {sidecar_path}: no active DB row for {png_name}, skipping")
            skipped += 1
            continue

        try:
            with open(sidecar_path) as f:
                copy = json.load(f)
            title = copy["title"]
            description = copy["description"]
            tags = copy["tags"]
            if not isinstance(tags, list):
                raise ValueError("tags must be a JSON list")
        except Exception as exc:
            click.echo(f"  {sidecar_path}: invalid sidecar ({exc})")
            failed += 1
            continue

        current_revision = int(row.get("copy_revision") or 0)
        click.echo(f"  {sidecar_path.name} -> design_id={row['id']}")
        if apply_changes:
            update_design(
                int(row["id"]),
                listing_title=title,
                listing_description=description,
                listing_tags=tags,
                copy_state="ready",
                copy_revision=current_revision + 1,
                last_error=None,
            )
            updated += 1

    if apply_changes:
        click.echo(f"Done. Updated={updated}, skipped={skipped}, failed={failed}.")
    else:
        click.echo(f"Dry-run complete. Matched={len(sidecars) - skipped - failed}, skipped={skipped}, failed={failed}.")


@sticker.command("list")
@click.option(
    "--no-copy",
    "no_copy",
    is_flag=True,
    default=False,
    help="Only rows where copy_state=missing.",
)
@click.option(
    "--unpublished",
    is_flag=True,
    default=False,
    help="Only rows where publish_state!=published.",
)
@click.option(
    "--needs-republish",
    is_flag=True,
    default=False,
    help="Only rows where copy_revision > published_copy_revision.",
)
def list_design_rows(no_copy: bool, unpublished: bool, needs_republish: bool) -> None:
    """List design rows from the DB with optional filters."""
    from sticker_factory.db import init_db, list_designs

    init_db()
    rows = list_designs()

    if no_copy:
        rows = [row for row in rows if row.get("copy_state") == "missing"]
    if unpublished:
        rows = [row for row in rows if row.get("publish_state") != "published"]
    if needs_republish:
        rows = [
            row
            for row in rows
            if int(row.get("copy_revision") or 0)
            > int(row.get("published_copy_revision") or 0)
        ]

    if not rows:
        click.echo("No rows found.")
        return

    header = (
        f"{'id':>4}  {'concept':<20}  {'variation':<12}  "
        f"{'copy':<7}  {'publish':<9}  {'sup':<3}  {'png_path'}"
    )
    click.echo(header)
    click.echo("-" * len(header))
    for row in rows:
        concept = row.get("concept_id") or "-"
        variation = row.get("variation_name") or "-"
        png_path = row.get("png_path_canonical") or row.get("png_path") or "-"
        click.echo(
            f"{int(row['id']):>4}  {concept[:20]:<20}  {variation[:12]:<12}  "
            f"{row.get('copy_state', '-')[:7]:<7}  {row.get('publish_state', '-')[:9]:<9}  "
            f"{int(row.get('is_superseded') or 0):<3}  {png_path}"
        )


@sticker.command("show")
@click.argument("design_id", type=int)
def show_design_row(design_id: int) -> None:
    """Show full detail for one DB design row."""
    import json

    from sticker_factory.db import get_design, init_db

    init_db()
    row = get_design(design_id)
    if row is None:
        click.echo(f"Design id {design_id} not found.")
        raise SystemExit(1)
    click.echo(json.dumps(row, indent=2, sort_keys=True))


@sticker.command()
@click.argument("design_id", required=False, type=int)
@click.option(
    "--ready",
    "publish_ready",
    is_flag=True,
    default=False,
    help="Batch publish rows with copy_state=ready and publish_state=never.",
)
@click.option(
    "--republish",
    is_flag=True,
    default=False,
    help="Allow publishing a specific row again if it is already uploaded/published.",
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
    design_id: int | None,
    publish_ready: bool,
    republish: bool,
    blueprint_id: int | None,
    surface: str,
    etsy: bool,
) -> None:
    """Publish DB-backed design rows to Printify (and optionally Etsy)."""
    from sticker_factory.db import get_design, init_db, list_designs, update_design
    from sticker_factory.publisher import PrintifyClient

    if publish_ready and design_id is not None:
        click.echo("Use either a specific <design_id> or --ready, not both.")
        raise SystemExit(1)
    if not publish_ready and design_id is None:
        click.echo("Provide <design_id> or use --ready for batch publish.")
        raise SystemExit(1)
    if publish_ready and republish:
        click.echo("--republish is only supported with a specific <design_id>.")
        raise SystemExit(1)

    init_db()
    if publish_ready:
        rows = list_designs(
            copy_state="ready",
            publish_state="never",
            is_superseded=0,
        )
        if not rows:
            click.echo("No ready rows found for batch publish.")
            return
    else:
        row = get_design(design_id)
        if row is None:
            click.echo(f"Design id {design_id} not found.")
            raise SystemExit(1)
        rows = [row]

    cfg = get_config()
    printify_cfg = cfg.get("printify", {})
    shop_id = printify_cfg.get("shop_id", "25769339")
    print_provider_id = printify_cfg.get("print_provider_id", 1)
    pricing = printify_cfg.get("pricing", {})

    if blueprint_id is None:
        blueprint_id = printify_cfg.get("default_blueprint_id", 600)

    client = PrintifyClient()

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

    click.echo(f"Publishing {len(rows)} row(s)...")
    published = 0
    skipped = 0
    errored = 0

    for row in rows:
        row_id = int(row["id"])
        row_publish_state = row.get("publish_state") or "never"
        row_copy_state = row.get("copy_state") or "missing"
        title = row.get("listing_title")
        description = row.get("listing_description")
        png_path_value = row.get("png_path_canonical") or row.get("png_path")

        if row.get("is_superseded"):
            click.echo(f"  id={row_id}: superseded row, skipping")
            skipped += 1
            continue

        if row_copy_state != "ready" or not title or not description:
            message = "copy not ready (run copywrite first)"
            click.echo(f"  id={row_id}: {message}")
            if publish_ready:
                skipped += 1
                continue
            raise SystemExit(1)

        if not publish_ready:
            if republish:
                if row_publish_state not in {"uploaded", "published"}:
                    click.echo(
                        f"  id={row_id}: --republish requires current publish_state uploaded/published."
                    )
                    raise SystemExit(1)
            elif row_publish_state != "never":
                click.echo(
                    f"  id={row_id}: publish_state is '{row_publish_state}'. Use --republish to override."
                )
                raise SystemExit(1)

        if not png_path_value:
            message = "missing png_path in DB row"
            update_design(row_id, publish_state="error", last_error=message)
            click.echo(f"  id={row_id}: {message}")
            errored += 1
            continue

        png_path = Path(png_path_value)
        if not png_path.exists():
            message = f"PNG not found: {png_path}"
            update_design(row_id, publish_state="error", last_error=message)
            click.echo(f"  id={row_id}: {message}")
            errored += 1
            continue

        try:
            click.echo(f"  id={row_id}: uploading {png_path.name}...")
            image_id = client.upload_image(png_path, png_path.name)

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

            click.echo(f"  id={row_id}: creating Printify product...")
            product = client.create_product(
                shop_id=shop_id,
                title=title,
                description=description,
                blueprint_id=blueprint_id,
                print_provider_id=print_provider_id,
                variants=variants,
                print_areas=print_areas,
            )
            product_id = str(product["id"])
            new_publish_state = "uploaded"
            if etsy:
                click.echo(f"  id={row_id}: publishing product to Etsy...")
                client.publish_product(shop_id, product_id)
                new_publish_state = "published"

            update_design(
                row_id,
                printify_product_id=product_id,
                publish_state=new_publish_state,
                published_copy_revision=int(row.get("copy_revision") or 0),
                last_error=None,
            )
            click.echo(
                f"  id={row_id}: success (product_id={product_id}, state={new_publish_state})"
            )
            published += 1
        except Exception as exc:
            update_design(row_id, publish_state="error", last_error=str(exc))
            click.echo(f"  id={row_id}: ERROR {exc}")
            errored += 1

    click.echo(f"Done. Published={published}, skipped={skipped}, errors={errored}.")
