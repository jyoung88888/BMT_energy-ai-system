"""
태양광 앙상블 예측 파이프라인

이 모듈은 태양광 발전량 예측의 전체 파이프라인을 관리합니다.
- FastAPI 엔드포인트와 스케줄러에서 공통으로 사용 가능
- 비동기 및 동기 인터페이스 모두 제공
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np
import asyncio

logger = logging.getLogger(__name__)


def run_solar_prediction_pipeline(target_date_str: Optional[str] = None) -> Dict[str, Any]:
    """
    태양광 앙상블 예측 파이프라인 (동기식 래퍼)

    스케줄러 등 동기 환경에서 사용하기 위한 래퍼 함수

    Args:
        target_date_str: 예측할 날짜 (YYYY-MM-DD 형식, None이면 오늘 날짜)

    Returns:
        dict: 예측 결과 및 DB 저장 정보

    Raises:
        ValueError: 날짜 형식 오류 또는 데이터 부족
        Exception: 예측 중 오류
    """
    try:
        # 날짜 설정
        kst = ZoneInfo("Asia/Seoul")
        today = _parse_target_date(target_date_str, kst)

        logger.info(f"🌞 앙상블 태양광 발전량 예측 시작: {today}")

        # 비동기 함수를 동기식으로 실행
        result = asyncio.run(run_prediction_async(today))

        logger.info("✅ 앙상블 태양광 발전량 예측 완료")
        return result

    except ValueError as e:
        logger.error(f"[Pipeline] ValueError: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"[Pipeline] 예측 파이프라인 오류: {str(e)}", exc_info=True)
        raise


async def run_prediction_async(today) -> Dict[str, Any]:
    """
    태양광 앙상블 예측 파이프라인 (비동기)

    FastAPI 엔드포인트에서 직접 사용 가능한 비동기 함수

    Args:
        today: 예측 대상 날짜 (date 객체)

    Returns:
        dict: 예측 결과 및 DB 저장 정보
    """
    from app.core.database import get_solar_repository
    from app.core.preprocess import get_data_processor
    from app.models.predictor import get_predictor_service
    from app.core.postprocess import get_postprocessor
    from app.core.db_saver import get_db_saver

    # 날짜 객체 변환
    target_date = datetime.combine(today, datetime.min.time())
    logger.info(f"📅 날짜 객체 생성 완료: {target_date}")

    # 목표 시간대 및 조회 범위 계산
    time_ranges = _calculate_time_ranges(target_date)

    logger.info(f"🎯 목표 시간대(미래 24h): {time_ranges['target_start']} ~ {time_ranges['target_end']}")
    logger.info(
        f"🔎 조회 범위 | "
        f"Solar: {time_ranges['solar_start']} ~ {time_ranges['solar_end']}, "
        f"Weather: {time_ranges['weather_start']} ~ {time_ranges['weather_end']}"
    )

    # === 1단계: 데이터 조회 (병렬) ===
    repository = await get_solar_repository()
    ensemble_data = await repository.fetch_ensemble_data(
        solar_start=time_ranges['solar_start'],
        solar_end=time_ranges['solar_end'],
        weather_start=time_ranges['weather_start'],
        weather_end=time_ranges['weather_end']
    )

    solar_df = ensemble_data['solar_df']
    weather_df = ensemble_data['weather_df']

    if solar_df.empty or weather_df.empty:
        logger.error("❌ 앙상블 예측을 위한 충분한 데이터가 없습니다")
        raise ValueError("앙상블 예측을 위한 충분한 데이터가 없습니다")

    logger.info(f"✅ 데이터 조회 완료 - 태양광: {len(solar_df)}건, 기상: {len(weather_df)}건")

    # === 2단계: 데이터 전처리 ===
    processor = get_data_processor()
    factory_data = processor.preprocess_solar_data(solar_df)
    weather_df_processed = processor.preprocess_weather_data(weather_df)

    # === 3단계: 공장별 시퀀스 생성 ===
    all_sequences = _create_factory_sequences(factory_data, weather_df_processed, processor)

    if not all_sequences:
        logger.error("❌ 앙상블 시퀀스 생성 실패")
        raise ValueError("앙상블 시퀀스 생성 실패")

    # === 4단계: 배치 예측 수행 ===
    predictor = await get_predictor_service()
    factory_predictions = await _batch_predict_factories(all_sequences, predictor)

    # === 5단계: 앙상블 평균 ===
    postprocessor = await get_postprocessor()
    logger.info("🔄 앙상블 평균 시작...")
    all_predictions = await postprocessor.ensemble_average_predictions(
        all_predictions=factory_predictions,
        target_start=time_ranges['target_start'],
        target_end=time_ranges['target_end']
    )
    logger.info(f"✅ {len(all_predictions)}개 공장, 앙상블 예측 완료")

    # === 6단계: 데이터베이스 저장 ===
    db_saver = await get_db_saver()

    # 시간별 데이터 저장
    logger.info("💾 예측 결과 데이터베이스 저장 시작...")
    saved_counts = await db_saver.save_predictions_hour_db(all_predictions)
    logger.info(f"✅ 시간별 데이터 저장 완료: {saved_counts}")

    # 일간 합계 저장
    logger.info("💾 일간 합계 tb_solar_day 저장 시작...")
    result_predict = {
        "target_date": target_date,
        "target_range": f"{time_ranges['target_start']} ~ {time_ranges['target_end']}",
        "results": all_predictions
    }

    try:
        daily_sums = await db_saver.save_predictions_day_db(result_predict)
        logger.info(f"✅ 일간 합계 저장 완료: {daily_sums}")
    except Exception as e:
        logger.error(f"⚠️ 일간 합계 저장 실패 (무시하고 계속): {str(e)}")
        daily_sums = {}

    # === 7단계: 결과 반환 ===
    return {
        "status": "success",
        "target_date": target_date,
        "target_range": f"{time_ranges['target_start']} ~ {time_ranges['target_end']}",
        "data_info": {
            "solar_records": len(solar_df),
            "weather_records": len(weather_df)
        },
        "ensemble_info": {
            "factories": list(all_predictions.keys()),
            "sequences_per_factory": {k: v.get('num_sequences_used', 0) for k, v in all_predictions.items()}
        },
        "database_save": {
            "hourly_saved_counts": saved_counts,
            "hourly_total_records": sum(saved_counts.values()),
            "daily_sums": daily_sums
        },
        "results": all_predictions
    }


# ============================================================
# 헬퍼 함수들
# ============================================================

def _parse_target_date(target_date_str: Optional[str], kst: ZoneInfo):
    """날짜 문자열 파싱"""
    if target_date_str:
        try:
            today = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            logger.info(f"📅 입력 날짜 사용: {today}")
        except ValueError as e:
            logger.error(f"❌ 잘못된 날짜 형식: {target_date_str}")
            raise ValueError(f"잘못된 날짜 형식입니다. YYYY-MM-DD 형식으로 입력해주세요. 오류: {e}")
    else:
        today = datetime.now(kst).date()
        logger.info(f"📅 오늘 날짜 자동 설정 (KST): {today}")

    return today


def _calculate_time_ranges(target_date: datetime) -> Dict[str, str]:
    """
    예측 범위 계산

    Returns:
        Dict with target_start, target_end, solar_start, solar_end, weather_start, weather_end
    """
    # 목표 시간대: 당일 23:00 ~ 다음날 22:00 (24시간)
    A_dt = target_date + timedelta(hours=23)
    B_dt = target_date + timedelta(days=1, hours=22)

    # 조회 범위
    weather_start_dt = A_dt - timedelta(hours=23)  # 당일 00:00
    weather_end_dt = B_dt
    solar_start_dt = weather_start_dt - timedelta(hours=168)
    solar_end_dt = A_dt - timedelta(hours=1)  # 당일 22:00

    return {
        'target_start': A_dt.strftime("%Y-%m-%d %H:%M:%S"),
        'target_end': B_dt.strftime("%Y-%m-%d %H:%M:%S"),
        'solar_start': solar_start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        'solar_end': solar_end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        'weather_start': weather_start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        'weather_end': weather_end_dt.strftime("%Y-%m-%d %H:%M:%S")
    }


def _create_factory_sequences(factory_data: Dict, weather_df_processed: pd.DataFrame, processor) -> Dict:
    """
    공장별 시퀀스 생성

    Args:
        factory_data: 공장별로 분류된 태양광 데이터
        weather_df_processed: 전처리된 기상 데이터
        processor: DataProcessor 인스턴스

    Returns:
        Dict: 공장별 시퀀스 데이터
    """
    all_sequences = {}

    for factory_name, factory_df in factory_data.items():
        if factory_df.empty:
            continue

        logger.info(f"🏭 {factory_name} 시퀀스 생성 중...")

        # Solar/Weather 데이터를 각각 시퀀스로 생성
        factory_df = factory_df.copy()
        factory_df['ymdhms'] = pd.to_datetime(factory_df['ymdhms'])

        weather_df_copy = weather_df_processed.copy()

        # 공장별 스케일러 선택
        solar_scaler = processor._get_solar_scaler_by_factory(factory_name)

        # 개별 시퀀스 생성
        sequences_result = processor.create_separate_sequences(
            solar_df=factory_df,
            weather_df=weather_df_copy,
            solar_scaler=solar_scaler,
            weather_scaler=processor.weather_scaler,
            past_history=168,
            future_target=24
        )

        all_sequences[factory_name] = sequences_result
        logger.info(f"   ✅ {len(sequences_result['X_solar'])}개 시퀀스 생성")

    return all_sequences


async def _batch_predict_factories(all_sequences: Dict, predictor) -> Dict:
    """
    공장별 배치 예측 수행

    Args:
        all_sequences: 공장별 시퀀스 데이터
        predictor: PredictorService 인스턴스

    Returns:
        Dict: 공장별 예측 결과
    """
    factory_predictions_for_ensemble = {}

    for factory_name, sequence_data in all_sequences.items():
        building_code = factory_name.replace('Factory', '') if 'Factory' in factory_name else factory_name
        num_sequences = len(sequence_data['X_solar'])

        logger.info(f"🔮 {building_code}동: {num_sequences}개 시퀀스 배치 예측 중...")

        # 배치 예측
        X_solar_batch = sequence_data['X_solar']
        X_weather_batch = sequence_data['X_weather']

        # ⚠️ 배치 데이터 유효성 검사
        if X_solar_batch is None or X_weather_batch is None:
            logger.warning(f"   ⚠️ {building_code}동: 배치 데이터가 None입니다. 스킵합니다.")
            continue

        if len(X_solar_batch) == 0 or len(X_weather_batch) == 0:
            logger.warning(f"   ⚠️ {building_code}동: 배치 데이터가 비어있습니다 (Solar: {len(X_solar_batch)}, Weather: {len(X_weather_batch)}). 스킵합니다.")
            continue

        if X_solar_batch.shape[0] <= 0 or X_weather_batch.shape[0] <= 0:
            logger.warning(f"   ⚠️ {building_code}동: 배치 크기가 유효하지 않습니다 (Solar: {X_solar_batch.shape}, Weather: {X_weather_batch.shape}). 스킵합니다.")
            continue

        # 공장명 전달하여 해당 모델 사용
        pred_result = await predictor.predict(X_solar_batch, X_weather_batch, factory_name=factory_name)
        y_pred = np.array(pred_result['predictions'])

        logger.info(f"   예측 완료: {y_pred.shape}")

        # 3D 배열을 2D로 변환
        if y_pred.ndim == 3:
            y_pred = y_pred.reshape(len(y_pred), 24)

        # ensemble_average_predictions에 전달할 형식으로 변환
        predictions_list = y_pred.tolist()
        timestamps_list = sequence_data['timestamps'].tolist()

        factory_predictions_for_ensemble[factory_name] = {
            'predictions': predictions_list,
            'timestamps': timestamps_list,
            'num_predictions': num_sequences
        }

        logger.info(f"   ✅ {building_code}동 예측 데이터 준비 완료: {num_sequences}개 시퀀스")

    return factory_predictions_for_ensemble
