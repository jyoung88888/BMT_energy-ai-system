import pickle
import json
import torch
from darts.models import TFTModel
from app.utils.config import config
import logging
import os

logger = logging.getLogger(__name__)

class ModelLoader:
    """TFT 모델 및 스케일러 로드 클래스"""

    def __init__(self, has_work_calendar=True):
        """
        Args:
            has_work_calendar: HOLI_TYPE_NUM 필드 존재 여부 (True: work_model, False: not_work_model)
        """
        self.model = None
        self.target_scaler = None
        self.past_scaler = None
        self.future_scaler = None
        self.model_config = None
        self.has_work_calendar = has_work_calendar

        # 동적으로 경로 설정
        paths = config.get_model_paths(has_work_calendar)
        self.model_path = paths['model_path']
        self.scaler_path = paths['scaler_path']
        self.config_path = paths['config_path']

        logger.info(f"[ModelLoader] 캘린더 데이터 포함: {has_work_calendar}")
        logger.info(f"[ModelLoader] 모델 경로: {self.model_path}")

        self.past_cols = config.PAST_COLS
        self.future_cols = config.FUTURE_COLS
        self.target_col = config.TARGET_COL

    def load_model(self):
        """TFT 모델 로드"""
        try:
            if not os.path.exists(self.model_path):
                raise FileNotFoundError(f"모델 파일을 찾을 수 없음: {self.model_path}")

            # CPU에서 로드
            self.model = TFTModel.load(
                self.model_path,
                map_location=torch.device('cpu')
            )
            logger.info(f"{self.model_path}에서 모델 로드 성공")
            return self.model
        except Exception as e:
            logger.error(f"모델 로드 실패: {e}")
            raise

    def load_scalers(self):
        """스케일러 로드"""
        try:
            if not os.path.exists(self.scaler_path):
                raise FileNotFoundError(f"스케일러 파일을 찾을 수 없음: {self.scaler_path}")

            with open(self.scaler_path, "rb") as f:
                scalers = pickle.load(f)

            self.target_scaler = scalers["target_scaler"]
            self.past_scaler = scalers["past_scaler"]
            self.future_scaler = scalers["future_scaler"]

            logger.info(f"{self.scaler_path}에서 스케일러 로드 성공")
            return self.target_scaler, self.past_scaler, self.future_scaler
        except Exception as e:
            logger.error(f"스케일러 로드 실패: {e}")
            raise

    def load_config(self):
        """모델 설정 로드"""
        try:
            if not os.path.exists(self.config_path):
                raise FileNotFoundError(f"설정 파일을 찾을 수 없음: {self.config_path}")

            with open(self.config_path, "r", encoding='utf-8') as f:
                self.model_config = json.load(f)

            logger.info(f"{self.config_path}에서 설정 로드 성공")
            return self.model_config
        except Exception as e:
            logger.error(f"설정 로드 실패: {e}")
            raise

    def load_all(self):
        """모델, 스케일러, 설정 전체 로드"""
        try:
            self.load_model()
            self.load_scalers()
            self.load_config()

            logger.info("모든 모델 구성 요소 로드 성공")
            return {
                'model': self.model,
                'target_scaler': self.target_scaler,
                'past_scaler': self.past_scaler,
                'future_scaler': self.future_scaler,
                'config': self.model_config,
                'past_cols': self.past_cols,
                'future_cols': self.future_cols,
                'target_col': self.target_col
            }
        except Exception as e:
            logger.error(f"모델 구성 요소 로드 실패: {e}")
            raise

    def get_model_info(self):
        """모델 정보 반환"""
        if self.model_config is None:
            raise ValueError("모델 설정이 로드되지 않았습니다. 먼저 load_all()을 호출하세요.")

        return {
            'input_chunk_length': self.model_config.get('input_chunk_length'),
            'output_chunk_length': self.model_config.get('output_chunk_length'),
            'hidden_size': self.model_config.get('hidden_size'),
            'lstm_layers': self.model_config.get('lstm_layers'),
            'num_attention_heads': self.model_config.get('num_attention_heads'),
            'past_features': len(self.past_cols),
            'future_features': len(self.future_cols)
        }
