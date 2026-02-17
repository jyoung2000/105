"""Baserow client with field introspection and auto-matching."""
from typing import Optional
from pathlib import Path
import httpx
from src.metadata.schemas import DEFAULT_FIELD_MAPPING
from src.utils.logging import setup_logging

logger = setup_logging("baserow")


class BaserowClient:
    """Client for Baserow API operations with field mapping support."""

    def __init__(self, api_url: str = "", api_token: str = "", table_id: int = 0):
        self.api_url = api_url.rstrip("/")
        self.api_token = api_token
        self.table_id = table_id
        self.field_mapping = dict(DEFAULT_FIELD_MAPPING)
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                follow_redirects=True,
                headers={"Authorization": f"Token {self.api_token}"},
            )
        return self._client

    @property
    def is_configured(self) -> bool:
        return bool(self.api_url and self.api_token and self.table_id)

    async def test_connection(self) -> dict:
        """Test connection to Baserow. Returns status dict."""
        if not self.is_configured:
            return {"success": False, "error": "Baserow not configured"}
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.api_url}/api/database/fields/table/{self.table_id}/"
            )
            response.raise_for_status()
            fields = response.json()
            return {
                "success": True,
                "fields_count": len(fields),
                "table_id": self.table_id,
            }
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def fetch_table_fields(self) -> list[dict]:
        """Fetch actual field definitions from Baserow table."""
        client = await self._get_client()
        response = await client.get(
            f"{self.api_url}/api/database/fields/table/{self.table_id}/"
        )
        response.raise_for_status()
        return response.json()

    async def auto_match_fields(self) -> dict:
        """Auto-match scraper fields to Baserow columns."""
        table_fields = await self.fetch_table_fields()
        field_names = {f["name"] for f in table_fields}
        field_names_lower = {f["name"].lower(): f["name"] for f in table_fields}

        match_results = []
        suggested_mapping = {}
        unmatched_scraper = []
        unmatched_baserow = list(field_names)

        for scraper_field, default_baserow in DEFAULT_FIELD_MAPPING.items():
            result = {"scraper_field": scraper_field, "default": default_baserow}

            # Exact match
            if default_baserow in field_names:
                result["matched"] = default_baserow
                result["match_type"] = "exact"
                suggested_mapping[scraper_field] = default_baserow
                if default_baserow in unmatched_baserow:
                    unmatched_baserow.remove(default_baserow)
            # Case-insensitive match
            elif default_baserow.lower() in field_names_lower:
                actual = field_names_lower[default_baserow.lower()]
                result["matched"] = actual
                result["match_type"] = "case_insensitive"
                suggested_mapping[scraper_field] = actual
                if actual in unmatched_baserow:
                    unmatched_baserow.remove(actual)
            # Fuzzy match — try scraper field name directly
            elif scraper_field in field_names:
                result["matched"] = scraper_field
                result["match_type"] = "fuzzy"
                suggested_mapping[scraper_field] = scraper_field
                if scraper_field in unmatched_baserow:
                    unmatched_baserow.remove(scraper_field)
            elif scraper_field.lower() in field_names_lower:
                actual = field_names_lower[scraper_field.lower()]
                result["matched"] = actual
                result["match_type"] = "fuzzy"
                suggested_mapping[scraper_field] = actual
                if actual in unmatched_baserow:
                    unmatched_baserow.remove(actual)
            else:
                result["matched"] = None
                result["match_type"] = "none"
                unmatched_scraper.append(scraper_field)

            match_results.append(result)

        return {
            "match_results": match_results,
            "suggested_mapping": suggested_mapping,
            "unmatched_scraper_fields": unmatched_scraper,
            "unmatched_baserow_fields": unmatched_baserow,
            "table_fields": table_fields,
            "total_scraper_fields": len(DEFAULT_FIELD_MAPPING),
            "total_matched": len(suggested_mapping),
        }

    async def upload_file(self, file_path: Path) -> Optional[dict]:
        """Upload a file to Baserow and return file object."""
        try:
            client = await self._get_client()
            with open(file_path, "rb") as f:
                response = await client.post(
                    f"{self.api_url}/api/user-files/upload-file/",
                    files={"file": (file_path.name, f, "image/jpeg")},
                )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"File upload failed: {e}")
            return None

    async def create_row(self, data: dict) -> Optional[dict]:
        """Create a row in the Baserow table."""
        try:
            client = await self._get_client()
            response = await client.post(
                f"{self.api_url}/api/database/rows/table/{self.table_id}/?user_field_names=true",
                json=data,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Row creation failed: {e}")
            return None

    async def check_duplicate(self, img_hash: str) -> bool:
        """Check if hash exists in table."""
        try:
            hash_field = self.field_mapping.get("imgHash", "imgHash")
            client = await self._get_client()
            response = await client.get(
                f"{self.api_url}/api/database/rows/table/{self.table_id}/",
                params={
                    "user_field_names": "true",
                    f"filter__{hash_field}__equal": img_hash,
                    "size": 1,
                },
            )
            response.raise_for_status()
            return response.json().get("count", 0) > 0
        except Exception as e:
            logger.warning(f"Dedup check failed: {e}")
            return False

    async def list_rows(self, page: int = 1, size: int = 50,
                        search: str = "", order_by: str = "",
                        filters: dict = None) -> dict:
        """List rows from the Baserow table with pagination and optional search.

        Returns dict with 'count', 'next', 'previous', 'results'.
        """
        if not self.is_configured:
            return {"count": 0, "results": [], "next": None, "previous": None}
        try:
            client = await self._get_client()
            params = {
                "user_field_names": "true",
                "page": page,
                "size": size,
            }
            if search:
                params["search"] = search
            if order_by:
                params["order_by"] = order_by
            if filters:
                for key, val in filters.items():
                    params[key] = val
            response = await client.get(
                f"{self.api_url}/api/database/rows/table/{self.table_id}/",
                params=params,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"List rows failed: {e}")
            return {"count": 0, "results": [], "next": None, "previous": None, "error": str(e)}

    async def get_row(self, row_id: int) -> dict:
        """Fetch a single row by ID."""
        if not self.is_configured:
            return {}
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.api_url}/api/database/rows/table/{self.table_id}/{row_id}/",
                params={"user_field_names": "true"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Get row failed: {e}")
            return {}

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
