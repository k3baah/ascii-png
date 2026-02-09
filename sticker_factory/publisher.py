"""Printify API integration for publishing sticker products."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Optional

import requests

from sticker_factory.config import get_config

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.printify.com/v1/"


class PrintifyClient:
    """Wrapper around the Printify REST API.

    Parameters
    ----------
    api_key : str, optional
        Printify API token.  When *None* (the default) the key is read from
        the project config / ``.env`` via :func:`get_config`.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        if api_key is None:
            cfg = get_config()
            api_key = cfg.get("secrets", {}).get("printify_api_key")
        if not api_key:
            raise ValueError(
                "No Printify API key provided. Set PRINTIFY_API_KEY in .env "
                "or pass api_key= explicitly."
            )
        self._api_key = api_key
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "sticker-factory/0.1",
            }
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        """Build a full URL from a relative path."""
        return f"{_BASE_URL}{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Send an HTTP request and handle errors."""
        url = self._url(path)
        logger.debug("%s %s", method.upper(), url)
        try:
            resp = self._session.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.HTTPError as exc:
            logger.error(
                "Printify API error: %s %s -> %s %s",
                method.upper(),
                url,
                exc.response.status_code,
                exc.response.text[:500] if exc.response.text else "",
            )
            raise
        except requests.RequestException as exc:
            logger.error("Printify request failed: %s", exc)
            raise

    def _get(self, path: str, **kwargs) -> requests.Response:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs) -> requests.Response:
        return self._request("POST", path, **kwargs)

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_shops(self) -> list[dict]:
        """List shops connected to the Printify account."""
        resp = self._get("shops.json")
        shops = resp.json()
        logger.info("Found %d shop(s)", len(shops))
        return shops

    def upload_image(self, image_path: Path, filename: str) -> str:
        """Upload an image to Printify and return the image ID.

        The image is base64-encoded and sent to the Printify uploads
        endpoint.

        Parameters
        ----------
        image_path : Path
            Local path to the image file (PNG).
        filename : str
            The filename to use on Printify (e.g. ``"design_classic.png"``).

        Returns
        -------
        str
            The Printify image ID.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        with open(image_path, "rb") as f:
            contents = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "file_name": filename,
            "contents": contents,
        }
        resp = self._post("uploads/images.json", json=payload)
        data = resp.json()
        image_id = data["id"]
        logger.info("Uploaded image %s -> Printify image ID: %s", filename, image_id)
        return image_id

    def get_blueprints(self) -> list[dict]:
        """List all available product blueprints."""
        resp = self._get("catalog/blueprints.json")
        blueprints = resp.json()
        logger.info("Found %d blueprint(s)", len(blueprints))
        return blueprints

    def get_blueprint_providers(self, blueprint_id: int) -> list[dict]:
        """Get print providers for a specific blueprint.

        Parameters
        ----------
        blueprint_id : int
            The Printify blueprint ID.

        Returns
        -------
        list[dict]
            Print providers that can fulfill this blueprint.
        """
        resp = self._get(f"catalog/blueprints/{blueprint_id}/print_providers.json")
        providers = resp.json()
        logger.info(
            "Blueprint %d has %d print provider(s)", blueprint_id, len(providers)
        )
        return providers

    def get_provider_variants(
        self, blueprint_id: int, provider_id: int
    ) -> list[dict]:
        """Get available variants for a blueprint + provider combination.

        Parameters
        ----------
        blueprint_id : int
            The Printify blueprint ID.
        provider_id : int
            The print provider ID.

        Returns
        -------
        list[dict]
            Variant information (sizes, prices, etc.).
        """
        resp = self._get(
            f"catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json"
        )
        data = resp.json()
        variants = data.get("variants", data) if isinstance(data, dict) else data
        logger.info(
            "Blueprint %d / provider %d has %d variant(s)",
            blueprint_id,
            provider_id,
            len(variants) if isinstance(variants, list) else 0,
        )
        return variants

    def create_product(
        self,
        shop_id: str,
        title: str,
        description: str,
        blueprint_id: int,
        print_provider_id: int,
        variants: list,
        print_areas: list,
    ) -> dict:
        """Create a new product in a Printify shop.

        Parameters
        ----------
        shop_id : str
            The Printify shop ID.
        title : str
            Product title.
        description : str
            Product description / body HTML.
        blueprint_id : int
            The product blueprint ID.
        print_provider_id : int
            The print provider ID.
        variants : list
            List of variant dicts (id, price, is_enabled).
        print_areas : list
            List of print area dicts (variant_ids, placeholders with images).

        Returns
        -------
        dict
            The created product data (includes ``id``).
        """
        payload = {
            "title": title,
            "description": description,
            "blueprint_id": blueprint_id,
            "print_provider_id": print_provider_id,
            "variants": variants,
            "print_areas": print_areas,
        }
        resp = self._post(f"shops/{shop_id}/products.json", json=payload)
        product = resp.json()
        logger.info(
            "Created product '%s' (ID: %s) in shop %s",
            title,
            product.get("id"),
            shop_id,
        )
        return product

    def list_products(self, shop_id: str, page: int = 1, limit: int = 100) -> dict | list:
        """Fetch one page of products for a Printify shop."""
        resp = self._get(f"shops/{shop_id}/products.json?page={page}&limit={limit}")
        data = resp.json()
        logger.info(
            "Fetched products page %d for shop %s (type=%s)",
            page,
            shop_id,
            type(data).__name__,
        )
        return data

    def list_all_products(self, shop_id: str, limit: int = 100) -> list[dict]:
        """Fetch all products in a Printify shop, handling pagination."""
        page = 1
        products: list[dict] = []

        while True:
            payload = self.list_products(shop_id=shop_id, page=page, limit=limit)

            if isinstance(payload, list):
                products.extend(payload)
                break

            page_items = payload.get("data", []) if isinstance(payload, dict) else []
            if isinstance(page_items, list):
                products.extend(page_items)

            if not isinstance(payload, dict):
                break

            current_page = int(payload.get("current_page", page))
            last_page = int(payload.get("last_page", current_page))
            if current_page >= last_page or not page_items:
                break

            page = current_page + 1

        logger.info("Fetched %d total product(s) for shop %s", len(products), shop_id)
        return products

    def publish_product(self, shop_id: str, product_id: str) -> dict:
        """Publish a product to the connected sales channel (e.g. Etsy).

        Parameters
        ----------
        shop_id : str
            The Printify shop ID.
        product_id : str
            The product ID to publish.

        Returns
        -------
        dict
            Publish response data.
        """
        payload = {
            "title": True,
            "description": True,
            "images": True,
            "variants": True,
            "tags": True,
            "keyFeatures": True,
            "shipping_template": True,
        }
        resp = self._post(
            f"shops/{shop_id}/products/{product_id}/publish.json", json=payload
        )
        # publish endpoint returns 200 with empty body on success
        if resp.status_code == 200 and not resp.text.strip():
            logger.info(
                "Published product %s in shop %s", product_id, shop_id
            )
            return {"status": "published"}
        data = resp.json()
        logger.info("Published product %s in shop %s", product_id, shop_id)
        return data
