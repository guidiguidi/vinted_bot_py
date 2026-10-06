import sys
import logging
from pyVintedVN import Vinted, requester
from search_manager import SearchManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("smoke_test")

def run_smoke_test():
    logger.info("=== STEP 1: Testing /api/v2/catalog/items (Session Warmup & TLS Spoofing) ===")
    test_url = "https://www.vinted.fr/api/v2/catalog/items?search_text=nike"
    response = requester.get(test_url)
    
    assert response.status_code == 200, f"Expected HTTP 200, got {response.status_code}"
    data = response.json()
    assert isinstance(data, dict), "Response JSON must be a dictionary"
    assert "items" in data, "Expected 'items' key in JSON response"
    items = data["items"]
    assert len(items) > 0, "Expected non-empty items list"
    logger.info(f"✅ /api/v2/catalog/items returned HTTP 200 with {len(items)} items")

    logger.info("\n=== STEP 2: Testing Vinted.items.search ===")
    vinted = Vinted()
    catalog_url = "https://www.vinted.fr/catalog?search_text=nike"
    parsed_items = vinted.items.search(catalog_url)
    assert len(parsed_items) > 0, "Vinted.items.search returned 0 items"
    
    sample = parsed_items[0]
    logger.info(f"✅ Parsed {len(parsed_items)} items. Sample item: id={sample.id}, title='{sample.title}', price={sample.price} {sample.currency}, brand='{sample.brand_title}'")
    assert sample.id is not None
    assert sample.title != ""
    assert sample.price is not None

    logger.info("\n=== STEP 3: Testing SearchManager.consolidate_and_search ===")
    sm = SearchManager(vinted)
    query_results = sm.consolidate_and_search([(1, catalog_url)])
    assert len(query_results) == 1
    found_items, q_id = query_results[0]
    assert q_id == 1
    assert len(found_items) > 0
    logger.info(f"✅ SearchManager returned {len(found_items)} items for query_id {q_id}")

    logger.info("\n🎉 All smoke tests passed successfully!")

if __name__ == "__main__":
    try:
        run_smoke_test()
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Smoke test failed: {e}", exc_info=True)
        sys.exit(1)
