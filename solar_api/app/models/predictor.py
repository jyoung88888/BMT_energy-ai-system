# core/predictor.py
import pickle
import numpy as np
import pandas as pd
import asyncio
import json
import os
import tensorflow as tf 
from typing import Dict, Any, List
from datetime import datetime, timedelta
import time

from app.core.config import settings
import logging
from app.core.exceptions import PredictionError
from app.core.preprocess import DataProcessor

logger = logging.getLogger(__name__)

class PredictorService:
    """태양광 발전량 예측 서비스 클래스 - 공장별 모델 지원"""

    def __init__(self):
        self.model_A = None
        self.model_B = None
        self.model_C = None
        self.model_T = None
        self.model_metadata = {}
        self.data_processor = None
        self.is_initialized = False

    @staticmethod
    def daytime_weighted_mse(y_true, y_pred):
        """
        모델 학습 시 사용된 가중치 손실 함수
        낮 시간대(생산 > 0)에 더 큰 가중치를 부여

        Args:
            y_true: 실제 값 (batch, 24, 1)
            y_pred: 예측 값 (batch, 24, 1)

        Returns:
            가중치가 적용된 MSE
        """
        # y_true > 0인 낮 시간대에 is_day=1, 밤에 is_day=0
        is_day = tf.cast(tf.greater(y_true, 0.0), tf.float32)
        # 낮:5배, 밤:1배 가중치
        weights = 1.0 + 4.0 * is_day

        mse = tf.square(y_true - y_pred)
        weighted_mse = mse * weights
        return tf.reduce_mean(weighted_mse)

    async def initialize(self):
        """예측 서비스 초기화 - 공장별 모델 로드"""
        try:
            logger.info("예측 서비스 초기화 시작...")

            # 공장별 모델 로드
            await self._load_models()

            # 메타데이터 로드
            self._load_metadata()

            # 데이터 프로세서 초기화
            from app.core.preprocess import get_data_processor
            self.data_processor = get_data_processor()

            self.is_initialized = True
            logger.info("✅ 예측 서비스 초기화 완료")

        except Exception as e:
            logger.error(f"❌ 예측 서비스 초기화 실패: {str(e)}")
            raise PredictionError(f"예측 서비스 초기화 실패: {str(e)}")

    async def _load_models(self):
        """공장별 모델 파일 로드 (비동기)"""
        import tensorflow as tf

        # 클로저를 통해 self.daytime_weighted_mse에 접근
        weighted_mse_fn = PredictorService.daytime_weighted_mse

        def _load_model(model_path: str, factory_name: str):
            if not os.path.exists(model_path):
                raise PredictionError(f"{factory_name} 모델 파일을 찾을 수 없습니다: {model_path}")

            model = tf.keras.models.load_model(
                model_path,
                custom_objects={'daytime_weighted_mse': weighted_mse_fn}
            )
            logger.info(f"{factory_name} 모델 로드 완료: {model_path}")
            return model

        # 파일 I/O를 별도 스레드에서 병렬 실행
        loop = asyncio.get_event_loop()

        # 공장별 모델 비동기 로드
        model_a_task = loop.run_in_executor(None, _load_model, settings.MODEL_A_PATH, "A공장")
        model_b_task = loop.run_in_executor(None, _load_model, settings.MODEL_B_PATH, "B공장")
        model_c_task = loop.run_in_executor(None, _load_model, settings.MODEL_C_PATH, "C공장")
        model_T_task = loop.run_in_executor(None, _load_model, settings.MODEL_T_PATH, "공장 전체")


        # 모든 모델이 로드될 때까지 대기
        self.model_A, self.model_B, self.model_C , self.model_T= await asyncio.gather(
            model_a_task, model_b_task, model_c_task , model_T_task
        )

        logger.info("✅ 모든 공장 모델 로드 완료 (A, B, C, Total)")
    
    def _load_metadata(self):
        """모델 메타데이터 로드"""
        try:
            # .keras 파일은 바이너리이므로 별도 JSON 파일을 찾거나 기본값 사용
            metadata_json_path = settings.MODEL_METADATA_PATH.replace('.keras', '_metadata.json')

            if os.path.exists(metadata_json_path):
                with open(metadata_json_path, 'r', encoding='utf-8') as f:
                    self.model_metadata = json.load(f)
                logger.info(f"모델 메타데이터 로드 완료: {metadata_json_path}")
            else:
                # 기본 메타데이터 생성
                self.model_metadata = {
                    "model_version": "1.0.0",
                    "created_at": datetime.now().isoformat(),
                    "model_type": "solar_prediction",
                    "performance_metrics": {},
                    "feature_importance": {}
                }
                logger.warning(f"메타데이터 파일이 없어 기본값으로 설정했습니다. (찾는 경로: {metadata_json_path})")
        except Exception as e:
            logger.error(f"메타데이터 로드 실패: {str(e)}")
            self.model_metadata = {"model_version": "1.0.0"}
    
    def _get_model_by_factory(self, factory_name: str):
        """공장명에 따라 해당 모델 반환"""
        if factory_name == 'FactoryA':
            return self.model_A
        elif factory_name == 'FactoryB':
            return self.model_B
        elif factory_name == 'FactoryC':
            return self.model_C
        elif factory_name == 'Factory_Total':
            return self.model_T
        else:
            raise PredictionError(f"알 수 없는 공장명: {factory_name}")

    async def predict(self, x_solar_feature: np.ndarray, x_weather_feature: np.ndarray, factory_name: str = 'FactoryA') -> Dict[str, Any]:
        """
        태양광 발전량 예측 수행

        Args:
            x_solar_feature: 정규화된 과거 태양광 시퀀스 데이터 (3D 배열)
            x_weather_feature: 정규화된 미래 기상 시퀀스 데이터 (3D 배열)
            factory_name: 공장명 ('FactoryA', 'FactoryB', 'FactoryC','Factory_Total)

        Returns:
            Dict[str, Any]: 예측 결과
        """
        if not self.is_initialized:
            raise PredictionError("예측 서비스가 초기화되지 않았습니다.")

        start_time = time.time()

        try:
            logger.info(f"🔮 AI 모델 예측 시작 ({factory_name})...")

            # 공장별 모델 선택
            model = self._get_model_by_factory(factory_name)

            # 예측 수행 (비동기)
            predictions = await self._predict_async(x_solar_feature, x_weather_feature, model)

            processing_time = time.time() - start_time

            logger.info(f"✅ 예측 완료: {predictions.shape}, 처리시간: {processing_time:.2f}초")

            return {
                'predictions': predictions.tolist(),  # numpy 배열을 리스트로 변환
                'processing_time': processing_time,
                'model_version': self.model_metadata.get('model_version', '1.0.0'),
                'prediction_shape': list(predictions.shape)
            }

        except Exception as e:
            logger.error(f"예측 수행 실패: {str(e)}")
            raise PredictionError(f"예측 수행 실패: {str(e)}")
    
    async def _predict_async(self, X_solar: np.ndarray, X_weather: np.ndarray, model) -> np.ndarray:
        """비동기 예측 수행"""
        def _predict():
            # 멀티모달 모델: 태양광 + 기상 데이터 동시 입력
            predictions = model.predict([X_solar, X_weather])
            return predictions

        # CPU 집약적 작업을 별도 스레드에서 실행
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _predict)
    
    async def get_model_info(self) -> Dict[str, Any]:
        """모델 정보 조회 (공장별 모델 포함)"""
        if not self.is_initialized:
            raise PredictionError("예측 서비스가 초기화되지 않았습니다.")

        return {
            "models_loaded": {
                "FactoryA": self.model_A is not None,
                "FactoryB": self.model_B is not None,
                "FactoryC": self.model_C is not None,
                "Factory_Total": self.model_T is not None
            },
            "model_version": self.model_metadata.get('model_version', '1.0.0'),
            "initialization_status": self.is_initialized
        }

# 전역 예측 서비스 인스턴스
_predictor_service = None

async def get_predictor_service() -> PredictorService:
    """예측 서비스 의존성 주입"""
    global _predictor_service
    if _predictor_service is None:
        _predictor_service = PredictorService()
        await _predictor_service.initialize()
    return _predictor_service