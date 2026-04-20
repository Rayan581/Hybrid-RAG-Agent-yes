import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Delivery rates and days from a central warehouse (e.g., Karachi or Lahore)
CITY_LOGISTICS = {
    "karachi": {"fee": 150, "days": 1},
    "lahore": {"fee": 250, "days": 2},
    "islamabad": {"fee": 250, "days": 2},
    "rawalpindi": {"fee": 250, "days": 2},
    "faisalabad": {"fee": 300, "days": 3},
    "multan": {"fee": 300, "days": 3},
    "peshawar": {"fee": 350, "days": 4},
    "quetta": {"fee": 450, "days": 5},
}

DEFAULT_FEE = 350
DEFAULT_DAYS = 4

def estimate_shipping(city: str) -> str:
    """
    Calculates shipping cost and estimated delivery date for a city.
    """
    try:
        city_lower = city.lower().strip()
        logistics = CITY_LOGISTICS.get(city_lower, {"fee": DEFAULT_FEE, "days": DEFAULT_DAYS})
        
        fee = logistics["fee"]
        days = logistics["days"]
        
        delivery_date = datetime.now() + timedelta(days=days)
        date_str = delivery_date.strftime("%A, %B %d")
        
        return (f"Shipping to {city.capitalize()} costs {fee} PKR. Your package is estimated to arrive "
                f"by {date_str} ({days} day{'s' if days > 1 else ''} from now).")
    except Exception as e:
        logger.error(f"Shipping tool error: {e}")
        return f"I'm unable to calculate shipping for {city} at the moment."
