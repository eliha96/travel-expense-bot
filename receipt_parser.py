import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from config import GEMINI_API_KEY
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

def parse_transit_receipt(image_path: str) -> Optional[List[Dict[str, Any]]]:
    """
    Analyzes an image (single receipt or history screen from Moovit, Rav-Kav, Pango, HopOn, etc.)
    and extracts all individual trips or daily charges.
    Returns a list of dicts: [{'date': 'YYYY-MM-DD', 'details': '...', 'cost': 15.32}, ...]
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY is not set in .env")
        return None
        
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        current_year = datetime.now().year
        prompt = f"""
אתה עוזר להפקת החזרי הוצאות נסיעה בתחבורה ציבורית בישראל.
לפניך צילום מסך של קבלה, פירוט נסיעות או היסטוריית חיובים מאפליקציית תחבורה ציבורית (כגון Moovit, רב-קו אונליין, פנגו, HopOn, רכבת ישראל וכד').

הנחיות קריטיות:
1. חלץ אך ורק את ימי הנסיעות בפועל (שורות עם מספר נסיעות, כגון "יום ראשון, 04-10-2026", "יום רביעי, 23-09-2026" וכו').
2. אל תכלול שורות כלליות של "נסיעות במועד חיוב" (כגון מועד חיוב 25-09-2026, 25-07-2026 וכו').
3. עבור כל יום/נסיעה החזר JSON עם המבנה הבא:
   - "date": תאריך מדויק בפורמט YYYY-MM-DD (למשל עבור 14-09-2026 החזר "2026-09-14").
   - "details": תיאור קצר בעברית (למשל "תחבורה ציבורית (2 נסיעות)", "רכבת ישראל", "נסיעה באוטובוס").
   - "cost": סכום החיוב בש"ח כמספר עשרוני חיובי (למשל 40.66, 15.32, 14.00).

החזר אך ורק מערך JSON תקני (JSON Array), ללא טקסט נוסף לפני או אחרי.
"""
        models = ["gemini-3.5-flash-lite", "gemini-3-flash-preview", "gemini-3.5-flash"]
        response_text = None
        for model_name in models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(
                            data=image_bytes,
                            mime_type="image/jpeg"
                        ),
                        prompt
                    ]
                )
                if response and response.text:
                    response_text = response.text
                    break
            except Exception as e:
                logger.warning(f"Failed parsing with model {model_name}: {e}")

        if response_text:
            cleaned = response_text.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()

            data = json.loads(cleaned)
            
            # If data is a list of trips
            if isinstance(data, list):
                valid_trips = []
                for item in data:
                    # Normalize date to YYYY-MM-DD
                    raw_date = item.get("date", "")
                    if "-" in raw_date:
                        parts = raw_date.split("-")
                        if len(parts) == 3:
                            if len(parts[0]) == 4:
                                norm_date = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                            else: # DD-MM-YYYY
                                norm_date = f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"
                        else:
                            norm_date = raw_date
                    else:
                        norm_date = raw_date
                        
                    raw_cost = item.get("cost", item.get("amount", 0.0))
                    if isinstance(raw_cost, str):
                        match = re.search(r"(\d+(?:\.\d+)?)", raw_cost)
                        cost_val = float(match.group(1)) if match else 0.0
                    else:
                        cost_val = float(raw_cost)

                    if cost_val > 0 and norm_date:
                        details_val = item.get("details", item.get("rides_count", "נסיעה בתחב\"צ"))
                        valid_trips.append({
                            "date": norm_date,
                            "details": details_val,
                            "cost": round(cost_val, 2)
                        })
                return valid_trips
    except Exception as e:
        logger.error(f"Receipt parsing error: {e}")
        
    return None
