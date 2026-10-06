import time
from datetime import datetime, timezone

class Item:
    """
    Represents a single item from Vinted.

    This class parses and stores various attributes of a Vinted item,
    such as id, title, brand, size, price, etc.
    """
    def __init__(self, data):
        """
        Initialize an Item with data from the Vinted API.

        Args:
            data (dict): The item data from the Vinted API.
        """
        self.raw_data = data
        prod = data.get("productItem", data) if isinstance(data, dict) else {}

        self.id = prod.get("id") or (data.get("id") if isinstance(data, dict) else None)
        self.title = prod.get("title") or (data.get("title", "") if isinstance(data, dict) else "")

        # Brand title
        if isinstance(data, dict) and "brand_title" in data:
            self.brand_title = data["brand_title"]
        elif isinstance(prod, dict) and "brand_title" in prod:
            self.brand_title = prod["brand_title"]
        elif isinstance(prod, dict) and "itemBox" in prod and isinstance(prod["itemBox"], dict) and prod["itemBox"].get("firstLine"):
            self.brand_title = prod["itemBox"]["firstLine"]
        else:
            self.brand_title = "N/A"

        # Size title
        if isinstance(data, dict) and "size_title" in data:
            self.size_title = data["size_title"]
        elif isinstance(prod, dict) and "size_title" in prod:
            self.size_title = prod["size_title"]
        elif isinstance(prod, dict) and "itemBox" in prod and isinstance(prod["itemBox"], dict) and prod["itemBox"].get("secondLine"):
            parts = str(prod["itemBox"]["secondLine"]).split("·")
            self.size_title = parts[0].strip() if parts else None
        else:
            self.size_title = None

        # Price & Currency
        price_obj = prod.get("price") or (data.get("price") if isinstance(data, dict) else {})
        if isinstance(price_obj, dict):
            self.currency = price_obj.get("currency_code") or price_obj.get("currencyCode") or "EUR"
            try:
                self.price = float(price_obj.get("amount", 0.0))
            except (ValueError, TypeError):
                self.price = price_obj.get("amount", 0.0)
        else:
            self.currency = "EUR"
            try:
                self.price = float(price_obj)
            except (ValueError, TypeError):
                self.price = price_obj

        # Photo URL
        if isinstance(data, dict) and "photo" in data and isinstance(data["photo"], dict) and "url" in data["photo"]:
            self.photo = data["photo"]["url"]
        elif isinstance(prod, dict) and "thumbnailUrl" in prod:
            self.photo = prod["thumbnailUrl"]
        elif isinstance(prod, dict) and "photos" in prod and isinstance(prod["photos"], list) and len(prod["photos"]) > 0:
            self.photo = prod["photos"][0].get("url", "")
        else:
            self.photo = ""

        # Item URL
        raw_url = prod.get("url") or (data.get("url", "") if isinstance(data, dict) else "")
        if str(raw_url).startswith("http"):
            self.url = str(raw_url)
        else:
            self.url = f"https://www.vinted.fr{raw_url}"

        # Buy URL
        if isinstance(data, dict) and "url" in data and "items" in str(data["url"]):
            self.buy_url = str(data["url"]).split("items")[0] + "transaction/buy/new?source_screen=item&transaction%5Bitem_id%5D=" + str(self.id)
        else:
            self.buy_url = f"https://www.vinted.fr/transaction/buy/new?source_screen=item&transaction%5Bitem_id%5D={self.id}"

        # Timestamp
        ts = None
        if isinstance(data, dict) and "photo" in data and isinstance(data["photo"], dict) and "high_resolution" in data["photo"]:
            ts = data["photo"]["high_resolution"].get("timestamp")
        elif isinstance(data, dict) and "raw_timestamp" in data:
            ts = data["raw_timestamp"]

        if not ts:
            ts = int(time.time())

        self.raw_timestamp = int(ts)
        self.created_at_ts = datetime.fromtimestamp(self.raw_timestamp, tz=timezone.utc)

    def __eq__(self, other):
        """
        Compare this item with another one.

        Two items are considered the same if they have the same ID.

        Args:
            other (Item): The other item to compare with.

        Returns:
            bool: True if the items have the same ID, False otherwise.
        """
        if not isinstance(other, Item):
            return False
        return self.id == other.id

    def __hash__(self):
        """
        Return a hash value for this item.

        The hash is based on the item's ID, which allows items to be used
        as keys in dictionaries and elements in sets.

        Returns:
            int: A hash value for the item.
        """
        return hash(('id', self.id))

    def is_new_item(self, minutes=20):
        """
        Check if this item is newly listed.

        An item is considered new if it was created within the specified
        number of minutes from the current time.

        Args:
            minutes (int, optional): The number of minutes to consider an item as new.
                Defaults to 5.

        Returns:
            bool: True if the item is new, False otherwise.
        """
        delta = datetime.now(timezone.utc) - self.created_at_ts
        return delta.total_seconds() < minutes * 60

    # Alias for backward compatibility
    isNewItem = is_new_item
