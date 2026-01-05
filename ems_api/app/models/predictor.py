import pandas as pd
import numpy as np
import random
import torch
from darts import TimeSeries, concatenate
from app.utils.config import config
from app.core.postprocess import postprocess_predictions
import logging

logger = logging.getLogger(__name__)


def set_seed(seed=42):
    """
    재현 가능한 예측을 위한 시드 고정

    Args:
        seed: 랜덤 시드 값 (기본 42)
    """
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

class PowerPredictor:
    """전력 사용량 예측 클래스"""

    def __init__(self, model_components, has_work_calendar=True):
        """
        Args:
            model_components: ModelLoader.load_all()의 반환값
            has_work_calendar: HOLI_TYPE_NUM 필드 존재 여부
        """
        self.model = model_components['model']
        self.target_scaler = model_components['target_scaler']
        self.past_scaler = model_components['past_scaler']
        self.future_scaler = model_components['future_scaler']
        self.model_config = model_components['config']
        self.has_work_calendar = has_work_calendar

    def prepare_scale_timeseries(self, df, split_date, split_timestamp=None):
        """
        DataFrame을 정규화된 Darts TimeSeries로 변환 후 split_timestamp 기준으로 슬라이싱

        - 전체 데이터를 TimeSeries로 변환
        - 전체 데이터 기준으로 정규화 (fit_transform)
        - split_timestamp 기준으로 필요한 부분만 슬라이싱

        Args:
            df: 전처리된 DataFrame (과거 + 미래 데이터)
            split_date: 분할 날짜 (str, 'yyyy-mm-dd' 형태)
            split_timestamp: train/val 분할 기준 타임스탐프. None이면 split_date에서 계산

        Returns:
            tuple: (series_for_pred, past_for_pred, future_for_pred)
        """
        try:
            freq = config.FREQ

            # split_timestamp 계산
            if split_timestamp is None:
                split_timestamp = pd.Timestamp(split_date) + pd.Timedelta(days=1)

            logger.info(f"  [시계열 준비] Split timestamp: {split_timestamp}")
            logger.info(f"  [시계열 준비] 전체 데이터: {len(df)}개 레코드 ({df['ymdhms'].min()} ~ {df['ymdhms'].max()})")

            # ============================================
            # 1단계: 전체 데이터를 TimeSeries로 변환
            # ============================================
            series = TimeSeries.from_dataframe(
                df,
                time_col='ymdhms',
                value_cols='사용량(kWh)',
                freq=freq
            )

            past_cov = TimeSeries.from_dataframe(
                df,
                time_col='ymdhms',
                value_cols=self.model_config['past_cols'],
                freq=freq
            )

            future_cov = TimeSeries.from_dataframe(
                df,
                time_col='ymdhms',
                value_cols=self.model_config['future_cols'],
                freq=freq
            )

            logger.info(f"  [시계열 준비] TimeSeries 생성 완료 (series: {len(series)}, past: {len(past_cov)}, future: {len(future_cov)})")

            # 사용하는 컬럼 확인
            logger.info(f"  [시계열 준비] 모델 설정:")
            logger.info(f"    - past_cols: {self.model_config['past_cols']}")
            logger.info(f"    - future_cols: {self.model_config['future_cols']}")

            # 정규화 전 NaN 확인
            series_vals_before = series.values() if callable(series.values) else series.values
            past_vals_before = past_cov.values() if callable(past_cov.values) else past_cov.values
            future_vals_before = future_cov.values() if callable(future_cov.values) else future_cov.values

            logger.info(f"  [시계열 준비] 정규화 전 NaN 확인:")
            logger.info(f"    - series NaN: {np.isnan(series_vals_before).sum()} / {series_vals_before.size}")
            logger.info(f"    - past NaN: {np.isnan(past_vals_before).sum()} / {past_vals_before.size}")
            logger.info(f"    - future NaN: {np.isnan(future_vals_before).sum()} / {future_vals_before.size}")

            # ============================================
            # 2단계: 정규화 (전체 데이터 기준)
            # ============================================
            full_tgt_scaled = self.target_scaler.transform(series)
            full_past_scaled = self.past_scaler.transform(past_cov)
            full_fut_scaled = self.future_scaler.transform(future_cov)

            logger.info(f"  [시계열 준비] 정규화 완료")

            # 정규화 후 NaN 확인
            tgt_vals = full_tgt_scaled.values() if callable(full_tgt_scaled.values) else full_tgt_scaled.values
            past_vals_scaled = full_past_scaled.values() if callable(full_past_scaled.values) else full_past_scaled.values
            fut_vals_scaled = full_fut_scaled.values() if callable(full_fut_scaled.values) else full_fut_scaled.values

            logger.info(f"  [시계열 준비] 정규화 후 NaN 확인:")
            logger.info(f"    - series NaN: {np.isnan(tgt_vals).sum()} / {tgt_vals.size}")
            logger.info(f"    - past NaN: {np.isnan(past_vals_scaled).sum()} / {past_vals_scaled.size}")
            logger.info(f"    - future NaN: {np.isnan(fut_vals_scaled).sum()} / {fut_vals_scaled.size}")

            # ============================================
            # 3단계: split_timestamp 기준으로 슬라이싱
            # ============================================
            input_length = self.model_config['input_chunk_length']
            output_length = self.model_config['output_chunk_length']

            series_start = split_timestamp - pd.Timedelta(minutes=30 * input_length)
            series_end = split_timestamp - pd.Timedelta(minutes=30)
            future_end = split_timestamp + pd.Timedelta(minutes=30 * (output_length-1))

            series_for_pred = full_tgt_scaled[series_start:series_end]
            past_for_pred = full_past_scaled[series_start:series_end]
            future_for_pred = full_fut_scaled[:future_end]

            logger.info(f"  [시계열 준비] 슬라이싱 완료")
            logger.info(f"    - series: {len(series_for_pred)} (from {series_for_pred.time_index.min()} to {series_for_pred.time_index.max()})")
            logger.info(f"    - past: {len(past_for_pred)} (from {past_for_pred.time_index.min()} to {past_for_pred.time_index.max()})")
            logger.info(f"    - future: {len(future_for_pred)} (from {future_for_pred.time_index.min()} to {future_for_pred.time_index.max()})")

            return series_for_pred, past_for_pred, future_for_pred

        except Exception as e:
            logger.error(f"  [시계열 준비] 실패: {e}", exc_info=True)
            raise

    def predict_with_split(self, series_for_pred, past_for_pred, future_for_pred):
        """
        TFT 모델로 예측 수행

        Args:
            scaled_series: 정규화된 target TimeSeries
            scaled_past: 정규화된 past covariates TimeSeries
            scaled_future: 정규화된 future covariates TimeSeries

        Returns:
            TimeSeries: 예측 결과 (역정규화 완료)
        """
        try:
            set_seed(42)

            output_length = self.model_config['output_chunk_length']
            logger.info(f"  [분할 예측] 모델 예측 시작 (output_length={output_length})")
            logger.info(f"    - series 길이: {len(series_for_pred)}")
            logger.info(f"    - past 길이: {len(past_for_pred)}")
            logger.info(f"    - future 길이: {len(future_for_pred)}")

            # 예측
            prediction = self.model.predict(
                n=output_length,
                series=series_for_pred,
                past_covariates=past_for_pred,
                future_covariates=future_for_pred,
                num_samples=1
            )
            logger.info(f"  [분할 예측] 모델 예측 완료")

            # 역정규화
            prediction_original = self.target_scaler.inverse_transform(prediction)
            logger.info(f"  [분할 예측] 역정규화 완료")
            return prediction_original

        except Exception as e:
            logger.error(f"  [분할 예측] 실패: {e}", exc_info=True)
            raise

    def predict(self, df, split_date=None, split_timestamp=None, aggregation='none'):
        """
        전체 예측 파이프라인

        Args:
            df: 전처리된 DataFrame (과거 + 미래 데이터, 모든 특성 포함)
            split_date: 분할 날짜 (str, 'yyyy-mm-dd' 형태)
            split_timestamp: train/val 분할 기준 타임스탐프 (datetime)
            aggregation: 집계 방식 ('none', 'hourly', 'daily')

        Returns:
            DataFrame: 예측 결과
        """
        try:
            if split_date is None:
                raise ValueError("split_date는 필수 파라미터입니다. predict(df, split_date='yyyy-mm-dd', ...) 형태로 호출해주세요.")

            logger.info(f"[예측] 시작: {df.shape[0]}개 레코드, 날짜 범위: {df['ymdhms'].min()} ~ {df['ymdhms'].max()}")

            # 1. TimeSeries 생성 및 정규화
            scaled_series, scaled_past, scaled_future = self.prepare_scale_timeseries(df, split_date, split_timestamp)

            # 2. 예측 수행
            logger.info("[예측] 모델 예측 실행 중...")
            prediction = self.predict_with_split(scaled_series, scaled_past, scaled_future)

            # 3. TimeSeries를 DataFrame으로 변환
            result_df = prediction.pd_dataframe() if hasattr(prediction, 'pd_dataframe') else prediction.to_dataframe()
            result_df.reset_index(inplace=True)
            result_df.columns = ['ymdhms', '사용량(kWh)']

            # 예측값 추출 (길이가 48보다 길면 뒤에서부터 48개만 추출)
            if len(result_df) > 48:
                logger.info(f"[예측] 예측 결과 추출: 길이 {len(result_df)} → 뒤에서부터 48개만 추출")
                result_df = result_df.iloc[-48:].reset_index(drop=True)
                logger.info(f"[예측] 추출 완료: 최종 길이 {len(result_df)}")

            # 4. 후처리 (집계)
            if aggregation != 'none':
                logger.info(f"[예측] 후처리: {aggregation} 집계 중...")
                result_df = postprocess_predictions(result_df, aggregation=aggregation)

            return result_df

        except Exception as e:
            logger.error(f"[예측] 오류: {e}", exc_info=True)
            raise
