import os
import logging
import re

logger = logging.getLogger(__name__)

DOCS_DIR = os.getenv("DOCS_DIR", "/app/dataset")
if not os.path.exists(DOCS_DIR):
    DOCS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "dataset"))

def _get_product_details(query: str) -> dict:
    """Helper to find first matching product and extract details."""
    query_lower = query.lower().strip()
    files = [f for f in os.listdir(DOCS_DIR) if f.endswith(".txt")][:100]
    
    for filename in files:
        with open(os.path.join(DOCS_DIR, filename), "r", encoding="utf-8") as f:
            content = f.read()
            if query_lower in content.lower():
                title = re.search(r"Title:\s*(.*)", content, re.IGNORECASE)
                price = re.search(r"Currently on sale for\s*(.*)", content, re.IGNORECASE)
                rating = re.search(r"Users rate this\s*(.*?)\s*based", content, re.IGNORECASE)
                
                return {
                    "title": title.group(1).strip() if title else filename,
                    "price": price.group(1).strip() if price else "N/A",
                    "rating": rating.group(1).strip() if rating else "N/A"
                }
    return None

def compare_products(product_a: str, product_b: str) -> str:
    """
    Compares two products side-by-side.
    """
    try:
        details_a = _get_product_details(product_a)
        details_b = _get_product_details(product_b)
        
        if not details_a or not details_b:
            missing = []
            if not details_a: missing.append(product_a)
            if not details_b: missing.append(product_b)
            return f"I couldn't find information for: {', '.join(missing)} to perform a comparison."

        comparison = (
            f"Here is a quick comparison:\n\n"
            f"1. {details_a['title']}\n"
            f"   - Price: {details_a['price']}\n"
            f"   - Rating: {details_a['rating']}/5\n\n"
            f"2. {details_b['title']}\n"
            f"   - Price: {details_b['price']}\n"
            f"   - Rating: {details_b['rating']}/5\n\n"
        )
        
        # Simple recommendation logic
        try:
            p_a = int(re.sub(r'[^0-9]', '', details_a['price']))
            p_b = int(re.sub(r'[^0-9]', '', details_b['price']))
            cheaper = details_a['title'] if p_a < p_b else details_b['title']
            comparison += f"Choice: {cheaper} is the more budget-friendly option."
        except:
            pass
            
        return comparison
    except Exception as e:
        logger.error(f"Comparison tool error: {e}")
        return "I encountered an error while comparing the products."
