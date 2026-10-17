import requests
import time
from typing import Tuple, Optional
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from config import ORIGIN_ADDRESS, GEMINI_API_KEY
from google import genai
from google.genai import types

# Default coordinates for Hakaf-Gimel 5, Herzliya (32.1643, 34.8437)
DEFAULT_ORIGIN_COORDS = (32.1643, 34.8437)

geolocator = Nominatim(user_agent="travel_expense_agent_il")
geocode_rate_limited = RateLimiter(geolocator.geocode, min_delay_seconds=1)

def get_driving_distance_osrm(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> Optional[float]:
    """Calculate driving distance in KM between two coordinates using OSRM."""
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    url = f"https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == "Ok" and "routes" in data and len(data["routes"]) > 0:
                distance_meters = data["routes"][0]["distance"]
                return round(distance_meters / 1000.0, 1)
    except Exception as e:
        print(f"OSRM Routing error: {e}")
    return None

def geocode_address(address: str) -> Optional[Tuple[float, float]]:
    """Geocode an address in Israel to (lat, lon)."""
    try:
        # Search specifically in Israel
        search_query = f"{address}, ישראל" if "ישראל" not in address and "Israel" not in address else address
        location = geocode_rate_limited(search_query, country_codes="il")
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        print(f"Geocoding error: {e}")
    return None

def calculate_distance_with_ai_fallback(destination: str, origin: str = ORIGIN_ADDRESS) -> Tuple[float, str]:
    """
    Calculate distance in KM from origin to destination.
    Uses Nominatim + OSRM first; if not resolved, uses Gemini for address resolution or estimation.
    """
    # 1. Try Nominatim Geocoding + OSRM
    dest_coords = geocode_address(destination)
    if dest_coords:
        dist = get_driving_distance_osrm(DEFAULT_ORIGIN_COORDS, dest_coords)
        if dist is not None:
            return dist, f"חושב בדיוק לפי מפות OSRM ({dist} ק\"מ)"

    # 2. AI Fallback: Ask Gemini to clarify address / calculate driving distance
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = f"""
אתה עוזר לחישוב מרחקי נסיעה ברכב בישראל.
נקודת מוצא: {origin}
נקודת יעד: {destination}

1. זהה את כתובת היעד המדויקת.
2. חשב/הערך את מרחק הנסיעה הריאלי בכביש (בקילומטרים, בכיוון אחד).
החזר אך ורק מספר עשרוני המייצג את הקילומטרים (למשל: 14.5).
"""
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt
            )
            text = response.text.strip().replace("ק\"מ", "").replace("קמ", "").strip()
            # Extract number
            import re
            match = re.search(r"(\d+(?:\.\d+)?)", text)
            if match:
                dist = round(float(match.group(1)), 1)
                return dist, f"הוערך באמצעות מודל AI ({dist} ק\"מ)"
        except Exception as e:
            print(f"Gemini fallback error: {e}")

    # Fallback placeholder if nothing worked
    return 10.0, "מרחק משוער (לא זוהתה כתובת מדויקת, ברירת מחדל 10 ק\"מ)"
