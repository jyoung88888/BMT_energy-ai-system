import pandas as pd
import numpy as np
from workalendar.asia import SouthKorea
from datetime import timedelta
import logging
import holidays
from app.utils.config import config

logger = logging.getLogger(__name__)

# 전역 공휴일 캐시 (성능 최적화)
_holiday_cache = {}

def prepare_power_demand_data(df):
    """
    전력 수요 데이터 전처리 - 시간 특성, 캘린더 특성, 전력 품질 지표 생성

    Args:
        df: 원본 DataFrame (ymdhms는 컬럼이어야 함)

    Returns:
        DataFrame: 전처리된 DataFrame
    """
    logger.info(f"[특성생성] 입력 데이터: {len(df)}개 레코드")

    # ymdhms가 인덱스인 경우 컬럼으로 변환
    if df.index.name == 'ymdhms':
        logger.info(f"[특성생성] ymdhms를 인덱스에서 컬럼으로 변환 전: {len(df)}개")
        df = df.reset_index()
        logger.info(f"[특성생성] ymdhms를 인덱스에서 컬럼으로 변환 후: {len(df)}개")
    # ymdhms 컬럼이 없으면 오류
    elif 'ymdhms' not in df.columns:
        raise ValueError("DataFrame must have 'ymdhms' as either column or index")

    
    # 시간 특성 (주기성 학습)
    df['hour'] = df['ymdhms'].dt.hour
    df['dayofweek'] = df['ymdhms'].dt.dayofweek
    df['month'] = df['ymdhms'].dt.month
    df['quarter'] = df['ymdhms'].dt.quarter
    df['day'] = df['ymdhms'].dt.day
    df['weekofyear'] = df['ymdhms'].dt.isocalendar().week
    
    # 캘린더 특성
    df['is_weekend'] = (df['ymdhms'].dt.dayofweek >= 5).astype(int)
    df['is_business_hour'] = df['hour'].between(9, 18).astype(int)
    df['is_night'] = ((df['hour'] >= 22) | (df['hour'] <= 6)).astype(int)
    
    # 순환 인코딩 (시간의 연속성)
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 48)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 48)
    df['day_sin'] = np.sin(2 * np.pi * df['day'] / 31)
    df['day_cos'] = np.cos(2 * np.pi * df['day'] / 31)
    df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
    df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)
    
    # 전력 품질 지표
    df['power_quality'] = df['역률(%)_지상'] * df['최대수요(kW)'] / 100
    df['reactive_ratio'] = df['무효전력(지상)'] / (df['무효전력(진상)'] + 1)
    df['power_factor_avg'] = (df['역률(%)_지상'] + df['역률(%)_진상']) / 2

    logger.info(f"[특성생성] 특성 생성 완료: {len(df)}개 레코드")
    logger.info(f"[특성생성] 추가된 컬럼: hour, dayofweek, month, quarter, day, weekofyear, is_weekend, is_business_hour, is_night, hour_sin, hour_cos, day_sin, day_cos, month_sin, month_cos, power_quality, reactive_ratio, power_factor_avg")
    return df


def make_effective_holiday_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    df 를 입력으로 받아서 'ymdhms' 컬럼을 기준으로
    휴일/주말/연속 휴무 여부 컬럼을 생성한 후 df 를 반환.

    필수: df['ymdhms'] 가 datetime64 타입이어야 함.
    """
    # ---- (1) ymdhms 컬럼 확인 & datetime 변환 ----
    if "ymdhms" not in df.columns:
        raise ValueError("'ymdhms' 컬럼이 필요합니다.")

    if not pd.api.types.is_datetime64_any_dtype(df["ymdhms"]):
        df["ymdhms"] = pd.to_datetime(df["ymdhms"])

    # ---- (2) 날짜 컬럼 생성 (자정 기준 normalize) ----
    df["date"] = df["ymdhms"].dt.normalize()

    # ---- (3) 한국 공휴일 계산 (캐싱 적용) ----
    years = tuple(sorted({d.year for d in df["ymdhms"]}))

    # 캐시 확인
    global _holiday_cache
    if years not in _holiday_cache:
        logger.info(f"[Holiday Cache] 공휴일 데이터 계산 및 캐싱: {years}")
        kr_holidays = holidays.KR(years=years)
        holiday_dates = pd.to_datetime(list(kr_holidays.keys()))
        _holiday_cache[years] = holiday_dates
    else:
        logger.info(f"[Holiday Cache] 캐시된 공휴일 데이터 사용: {years}")
        holiday_dates = _holiday_cache[years]

    df["is_kor_holiday"] = df["date"].isin(holiday_dates).astype(int)

    # ---- (4) 주말 여부 (토=5, 일=6) ----
    df["is_weekend"] = (df["ymdhms"].dt.dayofweek >= 5).astype(int)

    # ---- (5) 기본 off day (주말 또는 공휴일) ----
    df["base_off"] = ((df["is_weekend"] == 1) |
                      (df["is_kor_holiday"] == 1)).astype(int)

    # ---- (6) 날짜 단위 연속 블럭 계산 ----
    # 날짜별로 하루 1개만 있도록 정리
    day_df = df[["date", "base_off"]].drop_duplicates().copy()

    # base_off가 0→1, 1→0 으로 바뀌는 지점마다 그룹 번호 증가
    grp = (day_df["base_off"] != day_df["base_off"].shift()).cumsum()
    day_df["block_len"] = day_df.groupby(grp)["base_off"].transform("size")

    # ---- (7) 연속 2일 이상 off-day 블럭을 실제 휴무로 인정 ----
    day_df["is_effective_off"] = (
        (day_df["base_off"] == 1) &
        (day_df["block_len"] >= 2)
    ).astype(int)

    # 날짜를 key로 merge
    df = df.merge(
        day_df[["date", "is_effective_off"]],
        on="date",
        how="left"
    )

    return df


def preprocess_data(df_power, df_work, split_date=None, split_timestamp=None, two_days_later=None):
    """
    전체 데이터 전처리 파이프라인

    Args:
        df_power: 전력 데이터 DataFrame
        df_work: 캘린더 데이터 DataFrame
        split_date: 분할 날짜 (str, 'yyyy-mm-dd' 형태). 미래 타임스탬프 생성 시 사용
        split_timestamp: train/val 분할 기준 타임스탬프 (미리 계산된 값, 있으면 사용)
        two_days_later: 미래 데이터 종료 시점 (미리 계산된 값, 중복 계산 방지)

    Returns:
        DataFrame: 전처리 완료된 DataFrame (과거 + 미래 데이터)
    """
    # datetime 변환 및 정렬
    df_power['ymdhms'] = pd.to_datetime(df_power['ymdhms'])
    df_power = df_power.sort_values('ymdhms').reset_index(drop=True)

    # two_days_later 계산 (전달되지 않은 경우에만)
    if two_days_later is None:
        two_days_later = pd.Timestamp(split_date) + pd.Timedelta(days=2)

    logger.info(f"[전처리] 전력 원본 데이터: {df_power['ymdhms'].min()}부터 {df_power['ymdhms'].max()}까지 {len(df_power)}개 레코드")
        # Step 2: split_date가 제공되면 미래 타임스탬프 생성 및 결합
    if split_date is not None:
        output_length = config.OUTPUT_CHUNK_LENGTH

        future_timestamps = pd.date_range(
            start=split_timestamp,
            end=two_days_later,
            freq='30min'
        )

        logger.info(f"[타임스탬프 생성] 미래 데이터 범위: {split_timestamp} ~ {two_days_later} ({len(future_timestamps)}개)")

        # DataFrame 생성
        future_df = pd.DataFrame({'ymdhms': future_timestamps})

        # 전력 데이터 컬럼들을 0으로 초기화 (예측 시점에는 실제 값이 없음)
        future_df['사용량(kWh)'] = 0.0
        future_df['최대수요(kW)'] = 0.0
        future_df['무효전력(지상)'] = 0.0
        future_df['무효전력(진상)'] = 0.0
        future_df['CO2(tCO2)'] = 0.0
        future_df['역률(%)_지상'] = 0.0
        future_df['역률(%)_진상'] = 0.0

        # 과거 데이터와 미래 데이터 결합
        df = pd.concat([df_power, future_df], ignore_index=True)
        logger.info(f"[전처리] 데이터 결합 완료: {len(df)}개 레코드 (과거 + 미래, output_chunk_length={output_length})")

    df_work['ymdhms'] = pd.to_datetime(df_work['ymdhms'])
    df_work = df_work.sort_values('ymdhms').reset_index(drop=True)

    logger.info(f"split_date :{split_date}, split_timestamp : {split_timestamp}, two_days_later : {two_days_later}")
    logger.info(f"[전처리] 캘린더 원본 데이터: {df_work['ymdhms'].min()}부터 {df_work['ymdhms'].max()}까지 {len(df_work)}개 레코드")


    # df_work의 ymdhms에 two_days_later 값이 포함되어 있는지 확인
    if two_days_later.normalize() in df_work['ymdhms'].values:
        logger.info(f"[전처리] ✅ two_days_later({two_days_later.date()})가 캘린더 데이터에 포함됨 → 30분 단위 확장 수행")

        # work 전처리 (벡터화 방식으로 성능 개선)
        n_periods = 48  # 하루 30분 단위

        # numpy 기반 벡터화로 30분 단위 타임스탬프 생성
        timestamps = np.concatenate([
            pd.date_range(start=date, periods=n_periods, freq='30T').values
            for date in df_work['ymdhms']
        ])

        # WEEK_DAY, HOLI_TYPE 값 반복
        week_day = np.repeat(df_work['WEEK_DAY'].values, n_periods)
        holi_type = np.repeat(df_work['HOLI_TYPE'].values, n_periods)

        # DataFrame 생성
        df_work_30min = pd.DataFrame({
            'ymdhms': timestamps,
            'WEEK_DAY': week_day,
            'HOLI_TYPE': holi_type
        })

        # 휴일 데이터 숫자화
        mapping = {
            'D': 0,
            'S': 1,
            'H': 2
        }
        df_work_30min['HOLI_TYPE_NUM'] = df_work_30min['HOLI_TYPE'].map(mapping)
        logger.info(f"[전처리] 캘린더 30분 단위 확장 완료: {len(df_work_30min)}개 레코드 (벡터화 방식)")

        # Step 3: 전력 데이터와 캘린더 데이터 병합 (ymdhms 기준)
        if split_date is not None:
            # df는 Line 168에서 정의됨 (df_power + future_df)
            df = pd.merge(df, df_work_30min)
        else:
            # df_power 사용
            df = pd.merge(df_power, df_work_30min)
        logger.info(f"[전처리] 전력 데이터와 캘린더 데이터 병합 완료: {len(df)}개 레코드")
    else:
        logger.warning(f"[전처리] ⚠️ two_days_later({two_days_later.date()})가 캘린더 데이터에 없음 → 30분 단위 확장 스킵")
        # split_date가 있으면 df 사용 (미래 타임스탬프 포함), 없으면 df_power 사용
        if split_date is not None:
            # df는 이미 Line 168에서 정의됨 (df_power + future_df)
            logger.info(f"[전처리] 미래 타임스탬프 포함 전력 데이터: {len(df)}개 레코드")
        else:
            # df_power만 사용
            df = df_power.copy()
            logger.info(f"[전처리] 과거 전력 데이터: {len(df)}개 레코드")

    # Step 4: 휴일 특성 생성 및 전력 수요 특성 생성
    df = make_effective_holiday_features(df)
    df = prepare_power_demand_data(df)

    logger.info(f"[전처리] 전처리 완료: {len(df)}개 레코드")

    # ymdhms 중복 확인
    duplicate_count = df['ymdhms'].duplicated().sum()
    if duplicate_count > 0:
        logger.warning(f"[전처리] ⚠️ ymdhms 중복 발견: {duplicate_count}개")
        duplicate_timestamps = df[df['ymdhms'].duplicated(keep=False)]['ymdhms'].unique()
        logger.warning(f"[전처리] 중복된 타임스탬프: {duplicate_timestamps[:10]}")  # 처음 10개만 로깅
    else:
        logger.info(f"[전처리] ✅ ymdhms 중복 없음 (전체 {len(df)}개 행)")

    return df
