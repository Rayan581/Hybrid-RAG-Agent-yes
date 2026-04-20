import os
import logging
import re

logger = logging.getLogger(__name__)

DOCS_DIR = os.getenv("DOCS_DIR", "/app/dataset")
# On host (Windows) during dev, it might be different, but in Docker it's /app/dataset
# For the script to work during development, let's try a relative path if the absolute one fails
if not os.path.exists(DOCS_DIR):
    # Try a relative path for local testing
    DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "dataset")

def search_products(query: str) -> str:
    """
    Simulates a database search for products matching a query (title, brand, category).
    """
    try:
        if not os.path.exists(DOCS_DIR):
            return "Product catalog is currently offline (directory not found)."

        query_lower = query.lower().strip()
        results = []
        
        # Limit to checking first 100 files for speed
        files = [f for f in os.listdir(DOCS_DIR) if f.endswith(".txt")][:100]
        
        for filename in files:
            file_path = os.path.join(DOCS_DIR, filename)
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                # Search across the full file content (title, brand, category, description)
                if query_lower in content.lower():
                    # Extract Title and Price
                    title_match = re.search(r"Title:\s*(.*)", content, re.IGNORECASE)
                    price_match = re.search(r"Deal Alert:.*?for\s*([\d,]+\s*PKR)", content, re.IGNORECASE)
                    if not price_match:
                        price_match = re.search(r"Base Price:\s*(.*)", content, re.IGNORECASE)
                    
                    title = title_match.group(1).strip() if title_match else filename
                    price = price_match.group(1).strip() if price_match else "Price on request"
                    results.append(f"- {title} ({price})")
            
            if len(results) >= 5: # Limit results
                break
        
        if not results:
            return f"I couldn't find any products matching '{query}' in our local catalog."
            
        return f"I found {len(results)} matching products:\n" + "\n".join(results)

    except Exception as e:
        logger.error(f"Product search tool error: {e}")
        return "I'm having trouble searching the catalog right now."
