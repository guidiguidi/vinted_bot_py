from pyVintedVN.items.item import Item
from pyVintedVN.requester import requester
from urllib.parse import urlparse, parse_qsl
from requests.exceptions import HTTPError
import json
import gzip
import zlib
from typing import List, Dict, Optional
from pyVintedVN.settings import Urls
import logging

logger = logging.getLogger(__name__)


class Items:
    """
    A class for searching and retrieving items from Vinted.

    This class provides methods to search for items on Vinted using a search URL
    and to parse Vinted search URLs into API parameters.

    Example:
        >>> items = Items()
        >>> results = items.search("https://www.vinted.fr/catalog?search_text=shoes")
    """

    def search(self, url: str, nbr_items: int = 20, page: int = 1,
               time: Optional[int] = None, json_output: bool = False, since_id: Optional[int] = None) -> List[Item]:
        """
        Retrieve items from a given search URL on Vinted.

        Args:
            url (str): The URL of the search on Vinted.
            nbr_items (int, optional): Number of items to be returned. Defaults to 20.
            page (int, optional): Page number to be returned. Defaults to 1.
            time (int, optional): Timestamp to filter items by time. Defaults to None.
            json_output (bool, optional): Whether to return raw JSON data instead of Item objects. 
                Defaults to False.
            since_id (int, optional): Only return items with ID greater than this.

        Returns:
            List[Item]: A list of Item objects.

        Raises:
            HTTPError: If the request to the Vinted API fails.
        """
        # Extract the domain from the URL and set the locale
        locale = urlparse(url).netloc
        requester.set_locale(locale)

        # Parse the URL to get the API parameters
        params = self.parse_url(url, nbr_items, page, time)
        if since_id:
            params["since_id"] = since_id

        # Construct the API URL
        api_url = f"https://{locale}{Urls.VINTED_API_URL}/{Urls.VINTED_PRODUCTS_ENDPOINT}"

        try:
            # Make the request to the Vinted API
            response = requester.get(url=api_url, params=params)
            response.raise_for_status()

            # Parse the response
            try:
                data = response.json()
                items = data.get("items", [])
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Failed to decode JSON from Vinted. Status: {response.status_code}")
                encoding = (response.headers.get("Content-Encoding") or "").lower()
                content_type = response.headers.get("Content-Type") or ""
                logger.error(f"Headers: Content-Type={content_type}, Content-Encoding={encoding}")

                # Fallback: try manual decompression for compressed payloads.
                if encoding in ("gzip", "deflate"):
                    try:
                        raw = response.content
                        decoded = gzip.decompress(raw) if encoding == "gzip" else zlib.decompress(raw)
                        data = json.loads(decoded.decode("utf-8", errors="replace"))
                        items = data.get("items", [])
                        logger.warning("Recovered JSON via manual decompression fallback")
                    except Exception:
                        items = None
                else:
                    items = None

                if items is not None:
                    if not json_output:
                        return [Item(_item) for _item in items]
                    return items

                # Try to show a bit of the response for debugging
                try:
                    snippet = response.text[:200]
                    logger.error(f"Response snippet: {snippet}")
                except Exception:
                    logger.error("Could not decode response content for logging")
                raise e

            # Return either Item objects or raw JSON data
            if not json_output:
                return [Item(_item) for _item in items]
            else:
                return items

        except HTTPError as err:
            logger.error(f"HTTP Error during search: {err}")
            raise err

    def parse_url(self, url: str, nbr_items: int = 20, page: int = 1,
                  time: Optional[int] = None) -> Dict:
        """
        Parse a Vinted search URL to get parameters for the API call.

        Args:
            url (str): The URL of the search on Vinted.
            nbr_items (int, optional): Number of items to be returned. Defaults to 20.
            page (int, optional): Page number to be returned. Defaults to 1.
            time (int, optional): Timestamp to filter items by time. Defaults to None.

        Returns:
            Dict: A dictionary of parameters for the Vinted API.
        """
        # Parse the query parameters from the URL
        queries = parse_qsl(urlparse(url).query)

        # Construct the parameters dictionary
        params = {
            "search_text": "+".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "search_text"])
            ),
            "video_game_platform_ids": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "video_game_platform_ids[]"])
            ),
            "catalog_ids": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "catalog[]"])
            ),
            "color_ids": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "color_ids[]"])
            ),
            "brand_ids": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "brand_ids[]"])
            ),
            "size_ids": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "size_ids[]"])
            ),
            "material_ids": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "material_ids[]"])
            ),
            "status_ids": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "status_ids[]"])
            ),
            "country_ids": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "country_ids[]"])
            ),
            "city_ids": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "city_ids[]"])
            ),
            "is_for_swap": ",".join(
                map(str, [1 for tpl in queries if tpl[0] == "disposal[]"])
            ),
            "currency": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "currency"])
            ),
            "price_to": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "price_to"])
            ),
            "price_from": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "price_from"])
            ),
            "page": page,
            "per_page": nbr_items,
            "order": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "order"])
            ),
            "time": time
        }

        # Remove empty string parameters
        cleaned_params = {k: v for k, v in params.items() if v is not None and v != ""}

        # Also preserve query parameters present in the URL that may not be in the predefined list
        for key, val in queries:
            norm_key = key.rstrip("[]")
            if norm_key not in cleaned_params and key not in cleaned_params and val:
                cleaned_params[key] = val

        return cleaned_params

    # Aliases for backward compatibility
    parseUrl = parse_url
