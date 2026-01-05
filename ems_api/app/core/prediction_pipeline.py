"""
전력 사용량 예측 파이프라인 (공통 로직)

이 모듈은 main.py와 schedule_ems_predict.py에서 공통으로 사용하는
예측 로직을 하나의 함수로 통합합니다.
"""

import logging
from typing import Dict, Any
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from app.utils.config import config
from app.core.preprocess import preprocess_data
from app.core.postprocess import postprocess_predictions
from app.utils.model_loader import ModelLoader
from app.models.predictor import PowerPredictor

logger = logging.getLogger(__name__)

# 전역 predictor 캐시 (성능 최적화)
_predictor_cache = {
    True: None,   # work_model
    False: None   # not_work_model
}


def get_or_create_predictor(has_work_calendar):
    """
    캐시된 predictor 반환 또는 생성

    Args:
        has_work_calendar: HOLI_TYPE_NUM 필드 존재 여부

    Returns:
        PowerPredictor: 캐시된 또는 새로 생성된 predictor
    """
    global _predictor_cache

    if _predictor_cache[has_work_calendar] is None:
        model_type = "work_model" if has_work_calendar else "not_work_model"
        logger.info(f"[Model Cache] 💾 새 모델 로드 및 캐싱: {model_type}")

        model_loader = ModelLoader(has_work_calendar=has_work_calendar)
        model_components = model_loader.load_all()
        _predictor_cache[has_work_calendar] = PowerPredictor(
            model_components, has_work_calendar=has_work_calendar
        )
    else:
        model_type = "work_model" if has_work_calendar else "not_work_model"
        logger.info(f"[Model Cache] ⚡ 캐시된 모델 재사용: {model_type}")

    return _predictor_cache[has_work_calendar]


def run_prediction_pipeline(
    split_date: str,
    db_manager,
    forecast_saver,
    predictor
) -> Dict[str, Any]:
    """
    전력 사용량 예측 파이프라인 실행

    Args:
        split_date: 예측 기준 날짜 (YYYY-MM-DD 형식)
        db_manager: 데이터베이스 매니저 인스턴스
        forecast_saver: 예측 결과 저장 인스턴스
        predictor: 예측 모델 인스턴스

    Returns:
        dict: {
            'hourly_saved': int,           # 저장된 시간별 레코드 수
            'daily_saved': int,            # 저장된 일별 레코드 수
            'predictions_hourly': DataFrame,  # 시간별 예측 결과
            'predictions_30min': DataFrame,   # 30분 단위 예측 결과
            'df': DataFrame,                # 원본 데이터
            'fetch_period': str             # 데이터 조회 기간
        }

    Raises:
        ValueError: 데이터가 없을 경우
        Exception: 예측 중 오류 발생 시
    """
    # 0. split_timestamp 계산 (DB 조회 전)
    logger.info(f"[Pipeline] Calculating split_timestamp for split_date: {split_date}")
    output_length = config.OUTPUT_CHUNK_LENGTH
    two_days_later = pd.Timestamp(split_date) + pd.Timedelta(days=2)
    split_timestamp = two_days_later - pd.Timedelta(minutes=30*(output_length-1))
    logger.info(f"[타임스탬프 생성] split_date  : {split_date}")
    logger.info(f"[타임스탬프 생성] 마지막 날짜 : {two_days_later}")
    logger.info(f"[타임스탬프 생성] output_chunk_length={output_length}, split_timestamp={split_timestamp}")

    # 1. 데이터 조회 (병렬 처리로 성능 최적화)
    logger.info("[DB Fetch] Starting parallel database queries")
    with ThreadPoolExecutor(max_workers=2) as executor:
        # 두 쿼리를 동시에 실행
        future_power = executor.submit(db_manager.fetch_power_data, end_date=split_timestamp)
        future_work = executor.submit(db_manager.fetch_calendar_data, end_date=two_days_later)

        # 결과 대기
        df_power = future_power.result()
        df_work = future_work.result()

    if len(df_power) == 0:
        logger.error("[DB Fetch] No data found in database")
        raise ValueError("No data found in database")

    fetch_period = f"{df_power['ymdhms'].min()} ~ {df_power['ymdhms'].max()}"
    logger.info(f"[DB Fetch] {len(df_power)} power records, {len(df_work)} calendar records | Period: {fetch_period}")

    # DB에서 가져온 데이터 샘플 로깅 (DEBUG 레벨)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"[DB Fetch] 샘플 데이터 (처음 3줄):")
        for idx, row in df_power.head(3).iterrows():
            logger.debug(f"[DB Fetch]   Row {idx}: ymdhms={row['ymdhms']}, 사용량={row.get('사용량(kWh)', 'N/A'):.2f}")

    # 2. 전처리 (two_days_later 전달하여 중복 계산 방지)
    logger.info("[Preprocess] Starting data preprocessing")
    processed_df = preprocess_data(
        df_power, df_work,
        split_date=split_date,
        split_timestamp=split_timestamp,
        two_days_later=two_days_later
    )
    logger.info(f"[Preprocess] Data preprocessing completed | split_timestamp: {split_timestamp}")

    # 2-1. HOLI_TYPE_NUM 필드 존재 확인 및 모델 동적 선택 (캐시 활용)
    has_work_calendar = 'HOLI_TYPE_NUM' in processed_df.columns
    logger.info("="*80)
    logger.info(f"[Model Selection] HOLI_TYPE_NUM 필드 존재: {has_work_calendar}")

    # 캐시된 predictor 사용 (성능 최적화)
    predictor = get_or_create_predictor(has_work_calendar)
    model_type = "work_model" if has_work_calendar else "not_work_model"
    logger.info(f"[Model Selection] 사용 모델: {model_type}")
    logger.info("="*80)

    # 3. 예측 수행 (30분 단위, 모델 1회 실행)
    logger.info("[Prediction] Starting prediction")
    predictions_30min = predictor.predict(
        processed_df,
        split_date=split_date,
        split_timestamp=split_timestamp,
        aggregation='none'
    )
    pred_period = f"{predictions_30min['ymdhms'].min()} ~ {predictions_30min['ymdhms'].max()}"
    logger.info(f"[Prediction] {len(predictions_30min)} records | Period: {pred_period}")

    # 4. Hourly 집계 및 저장
    logger.info("[Hourly Save] Starting hourly aggregation and save")
    predictions_hourly = postprocess_predictions(
        predictions_30min,
        aggregation='hourly'
    )
    hourly_saved = forecast_saver.save_forecast(predictions_hourly, 'hourly')
    logger.info(f"[Hourly Save] {hourly_saved} records saved")

    # 5. Daily 집계 및 저장
    logger.info("[Daily Save] Starting daily aggregation and save")
    predictions_daily = postprocess_predictions(
        predictions_30min,
        aggregation='daily'
    )
    daily_saved = forecast_saver.save_forecast(predictions_daily, 'daily')
    logger.info(f"[Daily Save] {daily_saved} records saved")

    logger.info(f"[Pipeline] SUCCESS - Hourly: {hourly_saved} records, Daily: {daily_saved} records saved")

    return {
        'hourly_saved': hourly_saved,
        'daily_saved': daily_saved,
        'predictions_hourly': predictions_hourly,
        'predictions_30min': predictions_30min,
        'df_power': df_power,
        'fetch_period': fetch_period
    }
