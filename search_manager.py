from logger import get_logger

logger = get_logger(__name__)

class SearchManager:
    def __init__(self, vinted_instance):
        self.vinted = vinted_instance

    def consolidate_and_search(self, all_queries):
        results = []
        for query in all_queries:
            query_id, query_url = query[0], query[1]  # query_url уже обработана в process_query()
            
            try:
                # Точный API: vinted.items.search(full_catalog_url)
                search_result = self.vinted.items.search(query_url)
                # Items.search returns a List[Item] or List[dict], not a dict with 'items' key
                items = search_result
                results.append((items, query_id))
                logger.info(f"Found {len(items)} items for query: {query_url[:50]}...")
            except Exception as e:
                logger.error(f"Vinted search failed for {query_url[:50]}: {e}")
                results.append(([], query_id))
        return results
