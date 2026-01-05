# core/postprocess.py
import numpy as np
import pandas as pd
import joblib
import os
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from app.core.config import settings
import logging
from app.core.exceptions import PostProcessingError

logger = logging.getLogger(__name__)

class PostProcessor:
    """예측 결과 후처리 클래스"""

    def __init__(self):
        self.output_scaler_A = None
        self.output_scaler_B = None
        self.output_scaler_C = None
        self.output_scaler_T = None
        self.is_initialized = False

    async def initialize(self):
        """후처리기 초기화"""
        try:
            logger.info("후처리기 초기화 시작...")
            await self._load_output_scalers()
            self.is_initialized = True
            logger.info("✅ 후처리기 초기화 완료")
        except Exception as e:
            logger.error(f"❌ 후처리기 초기화 실패: {str(e)}")
            raise PostProcessingError(f"후처리기 초기화 실패: {str(e)}")

    async def _load_output_scalers(self):
        """출력 스케일러들 로드"""
        def _load():
            scalers = {}

            # A동 스케일러 로드
            scaler_a_path = settings.A_TARGET_SCALER_PATH
            if os.path.exists(scaler_a_path):
                scalers['A'] = joblib.load(scaler_a_path)
                logger.info(f"A동 출력 스케일러 로드 완료: {scaler_a_path}")
            else:
                logger.warning(f"A동 스케일러 파일을 찾을 수 없습니다: {scaler_a_path}")

            # B동 스케일러 로드
            scaler_b_path = settings.B_TARGET_SCALER_PATH
            if os.path.exists(scaler_b_path):
                scalers['B'] = joblib.load(scaler_b_path)
                logger.info(f"B동 출력 스케일러 로드 완료: {scaler_b_path}")
            else:
                logger.warning(f"B동 스케일러 파일을 찾을 수 없습니다: {scaler_b_path}")

            # C동 스케일러 로드
            scaler_c_path = settings.C_TARGET_SCALER_PATH
            if os.path.exists(scaler_c_path):
                scalers['C'] = joblib.load(scaler_c_path)
                logger.info(f"C동 출력 스케일러 로드 완료: {scaler_c_path}")
            else:
                logger.warning(f"C동 스케일러 파일을 찾을 수 없습니다: {scaler_c_path}")

            # 공장 전체 스케일러 로드
            scaler_T_path = settings.T_TARGET_SCALER_PATH
            if os.path.exists(scaler_T_path):
                scalers['Total'] = joblib.load(scaler_T_path)
                logger.info(f"공장 전체 출력 스케일러 로드 완료: {scaler_T_path}")
            else:
                logger.warning(f"공장 전체 스케일러 파일을 찾을 수 없습니다: {scaler_T_path}")

            return scalers

        # 파일 I/O를 별도 스레드에서 실행
        loop = asyncio.get_event_loop()
        scalers = await loop.run_in_executor(None, _load)
        
        self.output_scaler_A = scalers.get('A')
        self.output_scaler_B = scalers.get('B')
        self.output_scaler_C = scalers.get('C')
        self.output_scaler_T = scalers.get('Total')

    async def simple_postprocess_predictions(
        self,
        predictions: Dict[str, np.ndarray],
        weather_df: pd.DataFrame = None
    ) -> Dict[str, Any]:
        """
        간단한 예측 결과 후처리 - 음수값만 0으로 처리 후 기상 데이터와 매칭

        Args:
            predictions: 건물별 예측값 딕셔너리 {'A': array, 'B': array, 'C': array}
            weather_df: 기상 데이터 DataFrame (tm 컬럼 포함)

        Returns:
            Dict[str, Any]: 후처리된 예측 결과 (timestamps 포함)
        """
        if not self.is_initialized:
            raise PostProcessingError("후처리기가 초기화되지 않았습니다.")

        try:
            logger.info("🔄 간단한 예측 결과 후처리 시작...")

            processed_results = {}

            # 각 건물별 예측값 후처리
            for building, prediction_array in predictions.items():
                logger.info(f"📍 {building}동 예측값 후처리 중...")

                # 1. 정규화 역변환 수행
                denormalized_preds = await self._denormalize_predictions(
                    prediction_array, building
                )

                # 2. 음수값만 0으로 처리
                processed_preds = np.maximum(denormalized_preds, 0)

                # 후처리 결과 로깅
                logger.info(f"📊 {building}동 후처리 결과:")
                logger.info(f"   - 역정규화 결과: {denormalized_preds}")
                logger.info(f"   - 최종 처리 결과: {processed_preds}")

                processed_results[building] = {
                    'predictions': processed_preds.tolist()
                }

                logger.info(f"✅ {building}동 후처리 완료")

            # 기상 데이터와 매칭 (tm 컬럼 추출)
            if weather_df is not None and not weather_df.empty:
                timestamps = weather_df['tm'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist()
                logger.info(f"⏰ 기상 데이터 시간대 매칭: {len(timestamps)}개")

                # 각 건물별 결과에 타임스탬프와 함께 DataFrame 생성
                for building, result in processed_results.items():
                    preds = result['predictions']

                    # 길이 맞추기
                    if len(preds) != len(timestamps):
                        logger.warning(f"{building}동 예측값({len(preds)})과 기상 데이터({len(timestamps)}) 길이 불일치")
                        # 짧은 쪽에 맞춤
                        min_len = min(len(preds), len(timestamps))
                        preds = preds[:min_len]
                        timestamps_matched = timestamps[:min_len]
                    else:
                        timestamps_matched = timestamps

                    # DataFrame 생성
                    result_df = pd.DataFrame({
                        'timestamp': timestamps_matched,
                        'prediction': preds
                    })

                    processed_results[building]['dataframe'] = result_df.to_dict(orient='records')
                    processed_results[building]['timestamps'] = timestamps_matched

            else:
                logger.warning("⚠️ 기상 데이터가 없어 타임스탬프를 추가하지 못했습니다.")

            logger.info("✅ 간단한 예측 결과 후처리 완료")

            return processed_results

        except Exception as e:
            logger.error(f"예측 결과 후처리 실패: {str(e)}")
            raise PostProcessingError(f"예측 결과 후처리 실패: {str(e)}")


    async def _denormalize_predictions(
        self,
        predictions: np.ndarray,
        building: str
    ) -> np.ndarray:
        """예측값 역정규화"""

        def _denormalize():
            # Total의 경우 output_scaler_T를 사용
            scaler_attr = 'output_scaler_T' if building == 'Total' else f'output_scaler_{building}'
            scaler = getattr(self, scaler_attr, None)

            if scaler is None:
                logger.warning(f"{building}동 스케일러({scaler_attr})가 없어 역정규화를 건너뜁니다.")
                return predictions
            
            # 2차원 배열로 변환 (스케일러가 2D 입력을 요구)
            if predictions.ndim == 1:
                predictions_2d = predictions.reshape(-1, 1)
            else:
                predictions_2d = predictions
            
            # 역정규화 수행
            denormalized = scaler.inverse_transform(predictions_2d)
            
            # 원래 형태로 복원
            if predictions.ndim == 1 and denormalized.shape[1] == 1:
                return denormalized.flatten()
            
            return denormalized

        # CPU 집약적 작업을 별도 스레드에서 실행
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _denormalize)


    async def ensemble_average_predictions(
        self,
        all_predictions: Dict[str, Dict],
        target_start: str,
        target_end: str
    ) -> Dict[str, Any]:
        """
        여러 시퀀스의 예측 결과를 앙상블 평균

        Args:
            all_predictions: 공장별 예측 결과
                {
                    'FactoryA': {
                        'predictions': [[...], [...], ...],  # 여러 시퀀스의 예측 (정규화된 상태)
                        'timestamps': [[...], [...], ...],   # 각 시퀀스의 타임스탬프
                        'num_predictions': int
                    }
                }
            target_start: 목표 시작 시간 (YYYY-MM-DD HH:MM:SS)
            target_end: 목표 종료 시간 (YYYY-MM-DD HH:MM:SS)

        Returns:
            Dict with ensemble averaged results
        """
        try:
            import pandas as pd
            from collections import defaultdict

            target_start_dt = pd.to_datetime(target_start)
            target_end_dt = pd.to_datetime(target_end)

            logger.info(f"🔄 앙상블 평균 시작: {target_start} ~ {target_end}")

            ensemble_results = {}

            for factory_name, pred_data in all_predictions.items():
                # Factory_Total은 'Total'로, 나머지는 'A', 'B', 'C'로 변환
                if factory_name == 'Factory_Total':
                    building_code = 'Total'
                else:
                    building_code = factory_name.replace('Factory', '')

                # 모든 예측을 하나의 배열로 변환 (N, 24)
                all_preds = np.array(pred_data['predictions'])  # (N, 24)
                all_timestamps = pred_data['timestamps']  # (N, 24)

                logger.info(f"   {building_code}동: {all_preds.shape[0]}개 시퀀스, shape={all_preds.shape}")

                # 🔥 배치로 한 번에 역정규화 (Notebook과 동일)
                denormalized = await self._denormalize_predictions(all_preds, building_code)

                # 음수 제거
                denormalized = np.maximum(denormalized, 0)

                logger.info(f"   역정규화 완료: {denormalized.shape}")

                # 시간대별 예측값 수집
                time_predictions = defaultdict(list)

                for seq_idx in range(len(denormalized)):
                    for t in range(len(denormalized[seq_idx])):
                        ts = all_timestamps[seq_idx][t]
                        pred_val = denormalized[seq_idx][t]

                        ts_dt = pd.to_datetime(ts)
                        # 목표 범위 내에 있는 경우만
                        if target_start_dt <= ts_dt <= target_end_dt:
                            time_predictions[ts].append(pred_val)

                # 시간대별 평균 계산
                ensemble_preds = []
                ensemble_timestamps = []
                num_preds_averaged = []

                for ts in sorted(time_predictions.keys()):
                    ts_dt = pd.to_datetime(ts)
                    if target_start_dt <= ts_dt <= target_end_dt:
                        avg_pred = np.mean(time_predictions[ts])

                        # 🌙 계절별 시간대 필터링 (발전량이 없는 시간)
                        month = ts_dt.month
                        hour = ts_dt.hour

                        # 겨울철 [10,11,12,1,2,3]: 7 <= hour <= 17 범위 외 0으로 설정
                        if month in [10, 11, 12, 1, 2, 3]:
                            if not (7 <= hour <= 17):
                                avg_pred = 0.0
                        # 여름철 [4,5,6,7,8,9]: 6 <= hour <= 18 범위 외 0으로 설정
                        elif month in [4, 5, 6, 7, 8, 9]:
                            if not (6 <= hour <= 18):
                                avg_pred = 0.0

                        ensemble_preds.append(float(avg_pred))
                        ensemble_timestamps.append(ts_dt)  # datetime 객체로 유지
                        num_preds_averaged.append(len(time_predictions[ts]))

                # 결과 저장 (DataFrame에서는 datetime 타입 유지)
                result_df = pd.DataFrame({
                    'timestamp': ensemble_timestamps,
                    'prediction': ensemble_preds,
                    'num_predictions_averaged': num_preds_averaged
                })

                # JSON 응답용 문자열 변환
                timestamps_str = [ts.strftime('%Y-%m-%d %H:%M:%S') for ts in ensemble_timestamps]

                # DataFrame을 JSON 직렬화 가능한 형태로 변환 (timestamp만 문자열로)
                result_df_for_json = result_df.copy()
                result_df_for_json['timestamp'] = timestamps_str

                result_entry = {
                    'predictions': ensemble_preds,
                    'timestamps': timestamps_str,  # JSON용 문자열 리스트
                    'dataframe': result_df_for_json.to_dict(orient='records'),
                    'num_sequences_used': pred_data['num_predictions']
                }

                ensemble_results[building_code] = result_entry

                logger.info(f"✅ {building_code}동 앙상블 완료: {len(ensemble_preds)}개 시간대, 평균 {np.mean(ensemble_preds):.2f}")

            logger.info("✅ 앙상블 평균 완료")
            return ensemble_results

        except Exception as e:
            logger.error(f"앙상블 평균 실패: {str(e)}")
            raise PostProcessingError(f"앙상블 평균 실패: {str(e)}")


# 전역 후처리기 인스턴스
_postprocessor = None

async def get_postprocessor() -> PostProcessor:
    """후처리기 의존성 주입"""
    global _postprocessor
    if _postprocessor is None:
        _postprocessor = PostProcessor()
        await _postprocessor.initialize()
    return _postprocessor