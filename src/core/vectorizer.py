from __future__ import annotations
import numpy as np
from typing import Any
import logging # Thêm import logging

logger = logging.getLogger(__name__) # Khởi tạo logger

try:
    from sklearn.preprocessing import MinMaxScaler
    from sklearn.metrics.pairwise import cosine_similarity
    HAS_SKLEARN = True
    logger.debug("Đã import sklearn modules.")
except ImportError as e: # Thêm alias cho exception
    HAS_SKLEARN = False
    logger.warning(f"Không thể import sklearn modules: {e}. Vectorization và Similarity Search sẽ bị vô hiệu hóa.")

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
logger.debug(f"FEATURE_KEYS đã định nghĩa: {FEATURE_KEYS}")

def _get_nested(d: dict, path: list[str], default: Any = None) -> Any:
    """
    Truy cập an toàn một giá trị từ một từ điển lồng nhau.

    Args:
        d: Từ điển gốc.
        path: Danh sách các khóa để truy cập vào giá trị mong muốn.
        default: Giá trị mặc định nếu đường dẫn không tồn tại.

    Returns:
        Giá trị tại đường dẫn đã cho hoặc giá trị mặc định.
    """
    logger.debug(f"Bắt đầu _get_nested cho path: {path}, default: {default}")
    for key in path:
        if not isinstance(d, dict) or key not in d:
            logger.debug(f"Key '{key}' không tìm thấy hoặc d không phải dict. Trả về default.")
            return default
        d = d[key]
    logger.debug(f"Kết thúc _get_nested. Giá trị: {d}")
    return d

def vectorize_market_state(mt5_context: dict) -> list[float] | None:
    """
    Chuyển đổi một từ điển ngữ cảnh MT5 phong phú thành một vector số được chuẩn hóa.

    Returns:
        Một danh sách các số thực (vector) hoặc None nếu dữ liệu không đủ.
    """
    logger.debug("Bắt đầu vectorize_market_state.")
    if not HAS_SKLEARN:
        logger.warning("sklearn không có sẵn, không thể vectorize market state.")
        return None
    if not mt5_context:
        logger.warning("mt5_context trống, không thể vectorize market state.")
        return None

    try:
        raw_features = []
        
        pip_info = _get_nested(mt5_context, ["pip"], {})
        pip_size = (pip_info.get("pip_value_per_lot", 0.00001) / pip_info.get("points_per_pip", 10)) or 0.00001
        logger.debug(f"Pip size: {pip_size}")

        # --- Extract features, handling missing values ---
        raw_features.append(_get_nested(mt5_context, ["volatility", "ATR", "M5"], 0.0) / pip_size)
        raw_features.append(_get_nested(mt5_context, ["volatility", "ATR", "H1"], 0.0) / pip_size)
        raw_features.append(_get_nested(mt5_context, ["info", "spread_current"], 0.0))
        raw_features.append(_get_nested(mt5_context, ["tick_stats_5m", "ticks_per_min"], 0))
        raw_features.append(_get_nested(mt5_context, ["position_in_day_range"], 0.5))
        logger.debug(f"Raw features (part 1): {raw_features}")

        key_levels = _get_nested(mt5_context, ["key_levels_nearby"], [])
        raw_features.append(next((x.get("distance_pips") for x in key_levels if x.get("name") == "PDH"), 100.0))
        raw_features.append(next((x.get("distance_pips") for x in key_levels if x.get("name") == "PDL"), 100.0))
        raw_features.append(next((x.get("distance_pips") for x in key_levels if x.get("name") == "EQ50_D"), 100.0))
        logger.debug(f"Raw features (part 2 - key levels): {raw_features}")

        ema_m5 = _get_nested(mt5_context, ["trend_refs", "EMA", "M5"], {})
        ema_h1 = _get_nested(mt5_context, ["trend_refs", "EMA", "H1"], {})
        sep_m5 = abs(ema_m5.get("ema50", 0.0) - ema_m5.get("ema200", 0.0)) / pip_size if ema_m5.get("ema50") and ema_m5.get("ema200") else 0.0
        sep_h1 = abs(ema_h1.get("ema50", 0.0) - ema_h1.get("ema200", 0.0)) / pip_size if ema_h1.get("ema50") and ema_h1.get("ema200") else 0.0
        raw_features.append(sep_m5)
        raw_features.append(sep_h1)
        logger.debug(f"Raw features (part 3 - EMAs): {raw_features}")

        # Convert to numpy array for scaling
        vector = np.array(raw_features, dtype=np.float32).reshape(1, -1)
        logger.debug(f"Vector trước khi xử lý NaN/inf: {vector}")
        
        # Replace any potential NaN/inf values before scaling
        vector = np.nan_to_num(vector, nan=0.0, posinf=1e9, neginf=-1e9)
        logger.debug(f"Vector sau khi xử lý NaN/inf: {vector}")

        # Normalize the vector to a 0-1 range.
        scaler = MinMaxScaler()
        normalized_vector = scaler.fit_transform(vector)
        logger.debug(f"Normalized vector: {normalized_vector}")
        
        result = normalized_vector.flatten().tolist()
        logger.debug(f"Kết thúc vectorize_market_state. Vector: {result}")
        return result

    except Exception as e:
        logger.error(f"Lỗi khi vectorize market state: {e}")
        return None

def find_similar_vectors(current_vector: list[float], historical_vectors: list[dict], top_n: int = 3) -> list[dict]:
    """
    Tìm các vector lịch sử tương tự nhất với vector hiện tại bằng cách sử dụng độ tương đồng cosine.

    Args:
        current_vector: Vector trạng thái thị trường hiện tại.
        historical_vectors: Danh sách các từ điển chứa 'id' và 'vector' của các trạng thái lịch sử.
        top_n: Số lượng vector tương tự hàng đầu cần trả về.

    Returns:
        Danh sách các từ điển chứa 'id' và 'similarity' của các vector tương tự nhất.
    """
    logger.debug(f"Bắt đầu find_similar_vectors với {len(historical_vectors)} historical vectors, top_n: {top_n}")
    if not HAS_SKLEARN:
        logger.warning("sklearn không có sẵn, không thể tìm similar vectors.")
        return []
    if not historical_vectors or not current_vector:
        logger.warning("Không có historical vectors hoặc current_vector trống.")
        return []

    current_v = np.array(current_vector).reshape(1, -1)
    
    # Prepare historical data
    ids = [h['id'] for h in historical_vectors]
    vectors = np.array([h['vector'] for h in historical_vectors])
    logger.debug(f"Đã chuẩn bị {len(vectors)} historical vectors cho tính toán.")

    # Calculate similarities
    similarities = cosine_similarity(current_v, vectors).flatten()
    logger.debug(f"Similarities: {similarities}")

    # Get top N indices, ensuring we don't get the current vector itself if it's in the list
    # (similarity of 1.0 with itself)
    top_indices = np.argsort(similarities)[::-1]
    logger.debug(f"Top indices: {top_indices}")

    results = []
    for i in top_indices:
        # Skip if similarity is perfect (it's the same vector)
        if np.isclose(similarities[i], 1.0):
            logger.debug(f"Bỏ qua vector có similarity 1.0 (chính nó).")
            continue
        
        results.append({
            "id": ids[i],
            "similarity": float(similarities[i]),
        })
        if len(results) >= top_n:
            logger.debug(f"Đã đạt top_n={top_n} similar vectors.")
            break
            
    logger.debug(f"Kết thúc find_similar_vectors. Kết quả: {results}")
    return results
