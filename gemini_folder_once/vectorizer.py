from __future__ import annotations
import numpy as np
from typing import Any

try:
    from sklearn.preprocessing import MinMaxScaler
    from sklearn.metrics.pairwise import cosine_similarity
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

# Define the features that constitute a "market state" vector.
# The order MUST remain constant.
FEATURE_KEYS = [
    "atr_m5_pips",
    "atr_h1_pips",
    "spread_points",
    "ticks_per_min_5m",
    "pos_in_day_range", # Position of current price within the day's high-low range (0 to 1)
    "dist_to_pdh_pips",
    "dist_to_pdl_pips",
    "dist_to_eq50_pips",
    "ema50_ema200_sep_m5_pips", # Separation between EMAs on M5
    "ema50_ema200_sep_h1_pips", # Separation between EMAs on H1
]

def _get_nested(d: dict, path: list[str], default: Any = None) -> Any:
    """Safely get a value from a nested dict."""
    for key in path:
        if not isinstance(d, dict) or key not in d:
            return default
        d = d[key]
    return d

def vectorize_market_state(mt5_context: dict) -> list[float] | None:
    """
    Converts a rich MT5 context dictionary into a normalized numerical vector.
    
    Returns a list of floats (the vector) or None if data is insufficient.
    """
    if not HAS_SKLEARN or not mt5_context:
        return None

    try:
        raw_features = []
        
        pip_info = _get_nested(mt5_context, ["pip"], {})
        pip_size = (pip_info.get("pip_value_per_lot", 0.00001) / pip_info.get("points_per_pip", 10)) or 0.00001

        # --- Extract features, handling missing values ---
        raw_features.append(_get_nested(mt5_context, ["volatility", "ATR", "M5"], 0.0) / pip_size)
        raw_features.append(_get_nested(mt5_context, ["volatility", "ATR", "H1"], 0.0) / pip_size)
        raw_features.append(_get_nested(mt5_context, ["info", "spread_current"], 0.0))
        raw_features.append(_get_nested(mt5_context, ["tick_stats_5m", "ticks_per_min"], 0))
        raw_features.append(_get_nested(mt5_context, ["position_in_day_range"], 0.5))

        key_levels = _get_nested(mt5_context, ["key_levels_nearby"], [])
        raw_features.append(next((x.get("distance_pips") for x in key_levels if x.get("name") == "PDH"), 100.0))
        raw_features.append(next((x.get("distance_pips") for x in key_levels if x.get("name") == "PDL"), 100.0))
        raw_features.append(next((x.get("distance_pips") for x in key_levels if x.get("name") == "EQ50_D"), 100.0))

        ema_m5 = _get_nested(mt5_context, ["trend_refs", "EMA", "M5"], {})
        ema_h1 = _get_nested(mt5_context, ["trend_refs", "EMA", "H1"], {})
        sep_m5 = abs(ema_m5.get("ema50", 0.0) - ema_m5.get("ema200", 0.0)) / pip_size if ema_m5.get("ema50") and ema_m5.get("ema200") else 0.0
        sep_h1 = abs(ema_h1.get("ema50", 0.0) - ema_h1.get("ema200", 0.0)) / pip_size if ema_h1.get("ema50") and ema_h1.get("ema200") else 0.0
        raw_features.append(sep_m5)
        raw_features.append(sep_h1)

        # Convert to numpy array for scaling
        vector = np.array(raw_features, dtype=np.float32).reshape(1, -1)
        
        # Replace any potential NaN/inf values before scaling
        vector = np.nan_to_num(vector, nan=0.0, posinf=1e9, neginf=-1e9)

        # Normalize the vector to a 0-1 range.
        scaler = MinMaxScaler()
        normalized_vector = scaler.fit_transform(vector)
        
        return normalized_vector.flatten().tolist()

    except Exception:
        return None

def find_similar_vectors(current_vector: list[float], historical_vectors: list[dict], top_n: int = 3) -> list[dict]:
    """
    Finds the most similar historical vectors to the current one using cosine similarity.
    """
    if not HAS_SKLEARN or not historical_vectors or not current_vector:
        return []

    current_v = np.array(current_vector).reshape(1, -1)
    
    # Prepare historical data
    ids = [h['id'] for h in historical_vectors]
    vectors = np.array([h['vector'] for h in historical_vectors])

    # Calculate similarities
    similarities = cosine_similarity(current_v, vectors).flatten()

    # Get top N indices, ensuring we don't get the current vector itself if it's in the list
    # (similarity of 1.0 with itself)
    top_indices = np.argsort(similarities)[::-1]

    results = []
    for i in top_indices:
        # Skip if similarity is perfect (it's the same vector)
        if np.isclose(similarities[i], 1.0):
            continue
        
        results.append({
            "id": ids[i],
            "similarity": float(similarities[i]),
        })
        if len(results) >= top_n:
            break
            
    return results
