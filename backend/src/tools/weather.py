import logging
import random

logger = logging.getLogger(__name__)

# Mock data for Pakistani cities
MOCK_WEATHER = {
    "karachi": {"temp": 32, "condition": "Sunny", "humidity": "65%"},
    "lahore": {"temp": 38, "condition": "Hot and Clear", "humidity": "30%"},
    "islamabad": {"temp": 28, "condition": "Pleasant", "humidity": "45%"},
    "peshawar": {"temp": 34, "condition": "Hazy", "humidity": "40%"},
    "quetta": {"temp": 22, "condition": "Windy", "humidity": "20%"},
    "multan": {"temp": 41, "condition": "Dusty", "humidity": "25%"},
}

def get_weather(city: str) -> str:
    """
    Fetches the current weather for a given city in Pakistan.
    """
    try:
        city_lower = city.lower().strip()
        if city_lower in MOCK_WEATHER:
            data = MOCK_WEATHER[city_lower]
            return (f"The current weather in {city.capitalize()} is {data['temp']}°C with {data['condition']} conditions. "
                    f"Humidity is at {data['humidity']}.")
        else:
            # Random fallback for other cities
            temp = random.randint(15, 40)
            return f"The current weather in {city.capitalize()} is {temp}°C with clear skies."
    except Exception as e:
        logger.error(f"Weather tool error: {e}")
        return f"I couldn't fetch the weather for {city} right now."
