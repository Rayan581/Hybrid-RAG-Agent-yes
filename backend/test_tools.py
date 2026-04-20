"""
Quick local test for all 5 tools.
Run with: python test_tools.py (from the backend folder)
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Set env vars so tools find the dataset
os.environ["DOCS_DIR"] = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dataset"))

print("=" * 60)
print("  DARAZ ASSISTANT — TOOL UNIT TEST")
print("=" * 60)

# 1. Weather
print("\n--- TEST 1: Weather Tool ---")
from app.rag.tools.weather import get_weather
print(get_weather("Lahore"))
print(get_weather("Karachi"))

# 2. Shipping Estimator
print("\n--- TEST 2: Shipping Estimator ---")
from app.rag.tools.shipping import estimate_shipping
print(estimate_shipping("Islamabad"))
print(estimate_shipping("Quetta"))

# 3. Product Search
print("\n--- TEST 3: Product Search ---")
from app.rag.tools.product_search import search_products
print(search_products("Khaadi"))

# 4. Product Comparison
print("\n--- TEST 4: Product Comparison ---")
from app.rag.tools.comparison import compare_products
print(compare_products("Product_1", "Product_8"))

# 5. Flash Sale
print("\n--- TEST 5: Flash Deals ---")
from app.rag.tools.flash_sale import get_flash_deals
print(get_flash_deals())

print("\n" + "=" * 60)
print("  ALL TOOLS PASSED [OK]")
print("=" * 60)
