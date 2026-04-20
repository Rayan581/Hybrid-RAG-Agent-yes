import os
import logging
import re
import random

logger = logging.getLogger(__name__)

DOCS_DIR = os.getenv("DOCS_DIR", "/app/dataset")
if not os.path.exists(DOCS_DIR):
    DOCS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "dataset"))

def get_flash_deals() -> str:
    """
    Finds top active deals in the catalog.
    """
    try:
        if not os.path.exists(DOCS_DIR):
            return "Unable to access the deal catalog."

        files = [f for f in os.listdir(DOCS_DIR) if f.endswith(".txt")]
        random.shuffle(files) # Randomize so the "Flash Sale" feels dynamic
        
        deals = []
        for filename in files:
            with open(os.path.join(DOCS_DIR, filename), "r", encoding="utf-8") as f:
                content = f.read()
                if "Deal Alert" in content:
                    title = re.search(r"Title:\s*(.*)", content, re.IGNORECASE)
                    deal = re.search(r"Deal Alert:\s*(.*)", content, re.IGNORECASE)
                    
                    if title and deal:
                        # Add a fake countdown for urgency
                        mins = random.randint(5, 59)
                        deals.append(f"[DEAL] {title.group(1).strip()}\n   - {deal.group(1).strip()}\n   - Ends in: {mins} minutes!")
            
            if len(deals) >= 3: # Limit to top 3
                break
        
        if not deals:
            return "There are no flash sales active at this moment. Check back soon!"
            
        return "*** DARAZ FLASH SALE ACTIVE! ***\n\n" + "\n\n".join(deals)
    except Exception as e:
        logger.error(f"Flash sale tool error: {e}")
        return "I can't access live deals right now, but you can find great prices in the catalog."
