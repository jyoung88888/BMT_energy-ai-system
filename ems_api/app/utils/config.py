import os
import sys
import json
from dotenv import load_dotenv
from pathlib import Path
from typing import Dict, Any
load_dotenv()

# 공통 DB 설정 import
GIT_ROOT = str(Path(__file__).parent.parent.parent.parent)
if GIT_ROOT not in sys.path:
    sys.path.insert(0, GIT_ROOT)
from db_config import DB_CONFIG as COMMON_DB_CONFIG

class Config:

    # Database configuration - 공통 db_config.py에서 로드
    database_config: Dict[str, Any] = {
        **COMMON_DB_CONFIG,
        'port': int(os.getenv("DB_PORT", 3306)),
    }

    # 테이블명 설정
    table_names: Dict[str, str] = {
        # 30분 단위 테이블
        'tb_kepco_30_minutes': 'tb_kepco_pwr_consum_minutes',
        'tb_workcalender' : 'tb_calendar_work',
        # AI 집계 테이블
        'tb_smart_eye_hour': 'tb_aggregate_smarteye_hour',
        'tb_smart_eye_day': 'tb_aggregate_smarteye_day'
    }

    # Model configuration
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # work calendar exits
    WEIGHT_DIR_work = os.path.join(BASE_DIR, "weights/work_model")

    # work calendar not exits
    WEIGHT_DIR_not_work = os.path.join(BASE_DIR, "weights/not_work_model")

    # Default paths (work_model 기본 사용)
    MODEL_PATH = os.path.join(WEIGHT_DIR_work, "tft_model.pt")
    SCALER_PATH = os.path.join(WEIGHT_DIR_work, "scalers.pkl")
    CONFIG_PATH = os.path.join(WEIGHT_DIR_work, "config.json")

    FREQ = "30min"  # 30분 단위

    @staticmethod
    def get_model_paths(has_work_calendar=True):
        """
        캘린더 데이터 존재 여부에 따라 모델 경로 반환

        Args:
            has_work_calendar: HOLI_TYPE_NUM 필드 존재 여부

        Returns:
            dict: model_path, scaler_path, config_path
        """
        base_dir = Config.BASE_DIR

        if has_work_calendar:
            weight_dir = os.path.join(base_dir, "weights/work_model")
        else:
            weight_dir = os.path.join(base_dir, "weights/not_work_model")

        return {
            'model_path': os.path.join(weight_dir, "tft_model.pt"),
            'scaler_path': os.path.join(weight_dir, "scalers.pkl"),
            'config_path': os.path.join(weight_dir, "config.json")
        }

    # Feature columns - Load from config.json
    def __init__(self):
        self._load_model_config()

    def _load_model_config(self):
        """Load model configuration from config.json"""
        try:
            with open(self.CONFIG_PATH, 'r', encoding='utf-8') as f:
                model_config = json.load(f)

            # Load feature columns from config.json
            self.PAST_COLS = model_config.get('past_cols', [])
            self.FUTURE_COLS = model_config.get('future_cols', [])
            self.TARGET_COL = model_config.get('target_col', '사용량(kWh)')
            self.TIME_COL = model_config.get('time_col', 'user_dt')

            # Load model hyperparameters
            self.INPUT_CHUNK_LENGTH = model_config.get('input_chunk_length', 336)
            self.OUTPUT_CHUNK_LENGTH = model_config.get('output_chunk_length', 48)

        except FileNotFoundError:
            # Fallback to default values if config.json not found
            print(f"Warning: {self.CONFIG_PATH} not found. Using default feature columns.")
            self.PAST_COLS = [
                '최대수요(kW)'  ]
            self.FUTURE_COLS = [
                'hour', 'dayofweek', 'month', 'quarter', 'day', 'weekofyear',
                'is_weekend', 'is_business_hour', 'is_night',
                'hour_sin', 'hour_cos', 'day_sin', 'day_cos', 'month_sin', 'month_cos',
                'is_holiday'
            ]
            self.TARGET_COL = '사용량(kWh)'
            self.TIME_COL = 'ymdhms'
            self.INPUT_CHUNK_LENGTH = 336
            self.OUTPUT_CHUNK_LENGTH = 48

config = Config()
