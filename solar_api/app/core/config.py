import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from pydantic import Field
from pydantic_settings import BaseSettings

# 공통 DB 설정 import
GIT_ROOT = str(Path(__file__).parent.parent.parent.parent)
if GIT_ROOT not in sys.path:
    sys.path.insert(0, GIT_ROOT)
from db_config import DB_CONFIG as COMMON_DB_CONFIG

logger = logging.getLogger(__name__)

def _load_config7_json() -> Dict[str, Any]:
    """
    config7.json 파일을 로드하여 캐싱하는 헬퍼 함수
    모든 config 로딩에서 중복 없이 사용
    """
    try:
        config_path = Path(__file__).parent / "weights" / "config7.json"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            logger.warning(f"config7.json not found at {config_path}. Using default values.")
            return {}
    except Exception as e:
        logger.error(f"Error loading config7.json: {e}. Using default values.")
        return {}


class Settings(BaseSettings):
    """애플리케이션 설정"""

    # 기본 경로 설정
    PROJECT_ROOT: Path = Path(__file__).parent.parent.parent
    MODEL_DIR: Path = PROJECT_ROOT / "weights"
    DATA_DIR: Path = PROJECT_ROOT / "data"
    LOG_DIR: Path = PROJECT_ROOT / "logs"
    
    
    # 로깅 설정
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # API 설정
    API_TITLE: str = "Solar Energy Prediction API"
    API_VERSION: str = "2.0.0"
    API_DESCRIPTION: str = "태양광 발전량 예측 API 서비스"

    # 데이터베이스 설정 (공통 db_config.py에서 로드)
    DB_HOST: str = COMMON_DB_CONFIG['host']
    DB_USER: str = COMMON_DB_CONFIG['user']
    DB_PASSWORD: str = COMMON_DB_CONFIG['password']
    DB_NAME: str = COMMON_DB_CONFIG['database']
    DB_CHARSET: str = COMMON_DB_CONFIG['charset']

    @property
    def database_config(self) -> Dict[str, Any]:
        """데이터베이스 설정을 딕셔너리로 반환"""
        return COMMON_DB_CONFIG.copy()

    # 테이블명 설정
    table_names: Dict[str, str] = {
        'solar_data': 'tb_solar_hour',  # 태양광 발전 데이터
        'solar_day':'tb_solar_day',
        'weather_forecast': 'tb_weather_info',  # 기상 예보 데이터
    }

    # 공장별 저장 ID 매핑 설정 (각 공장당 대표 ID 1개)
    factory_id_mapping: Dict[str, List[int]] = {
        'FactoryA': [1],   # A 공장: ID 1
        'FactoryB': [13],  # B 공장: ID 13
        'FactoryC': [16],   # C 공장: ID 16
        'Factory_Total' : [1]
    }

    # 데이터 처리 임계값
    MISSING_VALUE_THRESHOLD: float = 0.1

    # 모델 경로 (app/weights 기준)
    WEIGHTS_DIR: Path = Path(__file__).parent.parent / "weights/model9/"
    WEIGHTS_PATH: str = str(WEIGHTS_DIR)

    MODEL_A_PATH: str = str(WEIGHTS_DIR / 'A_multimodal_solar_model_e500_b8_p100.keras')
    MODEL_B_PATH: str = str(WEIGHTS_DIR / 'B_multimodal_solar_model_e500_b8_p100.keras')
    MODEL_C_PATH: str = str(WEIGHTS_DIR / 'C_multimodal_solar_model_e500_b8_p100.keras')
    MODEL_T_PATH : str = str(WEIGHTS_DIR / 'T_multimodal_solar_model_e500_b8_p100.keras')


    # SOLAR SCALER
    SOLAR_SCALER_A_PATH: str = str(WEIGHTS_DIR / 'A_solar_scaler_e500_b8_p100.pkl')
    SOLAR_SCALER_B_PATH: str = str(WEIGHTS_DIR / 'B_solar_scaler_e500_b8_p100.pkl')
    SOLAR_SCALER_C_PATH: str = str(WEIGHTS_DIR / 'C_solar_scaler_e500_b8_p100.pkl')
    SOLAR_SCALER_T_PATH: str = str(WEIGHTS_DIR / 'T_solar_scaler_e500_b8_p100.pkl')
    
    # WEATHER SCALER
    WEATHER_SCALER_PATH: str = str(WEIGHTS_DIR / 'T_weather_scaler_e500_b8_p100.pkl')

    # TARGET SCALER 
    A_TARGET_SCALER_PATH: str = str(WEIGHTS_DIR / 'A_target_scaler_e500_b8_p100.pkl')
    B_TARGET_SCALER_PATH: str = str(WEIGHTS_DIR / 'B_target_scaler_e500_b8_p100.pkl')
    C_TARGET_SCALER_PATH: str = str(WEIGHTS_DIR / 'C_target_scaler_e500_b8_p100.pkl')
    T_TARGET_SCALER_PATH: str = str(WEIGHTS_DIR / 'T_target_scaler_e500_b8_p100.pkl')

    # MODEL
    MODEL_METADATA_PATH: str = str(WEIGHTS_DIR / 'T_multimodal_solar_model_e500_b8_p100_v6.keras')

    # config7.json에서 동적으로 로드 (future_target, past_history)
    _config7_data = _load_config7_json()
    DEFAULT_FORECAST_PERIODS: int = _config7_data.get("future_target", 24)
    MAX_FORECAST_PERIODS: int = _config7_data.get("past_history", 168)

    class Config:
        env_file = ".env"

class ModelConfig:
    """모델별 설정 및 특성 정의"""

    # config7.json에서 동적으로 로드 (solar_features, weather_features)
    _config7_data = _load_config7_json()
    FEATURES = {
        "solar_features": _config7_data.get("solar_features", ["generate_gap", "PV_Amp"]),
        "weather_features": _config7_data.get("weather_features", [
            'hour_cos', 'peak_hours', '1시간기온', '강수확률',
            '습도', '풍속', '하늘상태', 'apparent_elevation', 'is_daylight'
        ])
    }
    
    # 데이터 전처리 설정
    DATA_PROCESSING = {
        "outlier_method": "iqr",
        "outlier_factor": 1.5,
        "interpolation_method": "linear",
        "missing_value_threshold": 0.1,  # 10% 이상 결측치면 경고
        
        "lag_windows": [1, 2, 3, 6, 12, 24],
        "rolling_windows": [3, 6, 12, 24],
        
        "battery_soc_limits": {"min": 0, "max": 100},
        "solar_irradiance_max": 1200,  # W/m²
        
        "peak_hours": [17, 18, 19, 20, 21],
        "night_hours": list(range(0, 6)) + list(range(22, 24))
    }
    
    # 모델 후처리 설정
    POST_PROCESSING = {
        "solar": {
            "night_production": 0,  # 야간 생산량은 0
            "seasonal_adjustments": {
                "winter_factor": 0.7,  # 겨울철 감소
                "summer_factor": 1.2,  # 여름철 증가
                "winter_months": [12, 1, 2],
                "summer_months": [6, 7, 8]
            }
    }}
    
    # 예측 품질 임계값
    QUALITY_THRESHOLDS = {
        "max_ci_width_ratio": 0.5,  # 신뢰구간 폭이 평균 예측값의 50% 이하
        "max_volatility_ratio": 0.3,  # 변동성이 평균값의 30% 이하
        "min_r2_score": 0.7,  # R² 점수 최소값
        "max_mae_ratio": 0.15  # MAE가 평균값의 15% 이하
    }


class APIConfig:
    """API 관련 설정"""
    
    # CORS 설정
    CORS_ORIGINS: List[str] = ["*"]
    CORS_METHODS: List[str] = ["GET", "POST", "PUT", "DELETE"]
    CORS_HEADERS: List[str] = ["*"]
    
    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_PERIOD: int = 3600  # 1시간
    
    # Response 설정
    MAX_RESPONSE_SIZE: int = 10 * 1024 * 1024  # 10MB
    REQUEST_TIMEOUT: int = 300  # 5분
    
    # Validation 설정
    MAX_FORECAST_PERIODS: int = 168  # 최대 7일
    MIN_DATA_POINTS: int = 24  # 최소 24시간 데이터

# 전역 설정 인스턴스
settings = Settings()
model_config = ModelConfig()
api_config = APIConfig()

