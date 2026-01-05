import pandas as pd
import logging

logger = logging.getLogger(__name__)


def aggregate_to_hourly(df, time_col='ymdhms', value_col='사용량(kWh)'):
    """
    30분 단위 예측 결과를 1시간 단위로 집계
    30분 데이터는 다음 정시와 합산
    예: 00:30 + 01:00 → 01:00, 01:30 + 02:00 → 02:00

    Args:
        df: 예측 결과 DataFrame
        time_col: 시간 컬럼명
        value_col: 값 컬럼명

    Returns:
        DataFrame: 1시간 단위 집계 결과
    """
    try:
        df = df.copy()

        # 시간 컬럼을 datetime으로 변환 (필요한 경우)
        if not pd.api.types.is_datetime64_any_dtype(df[time_col]):
            df[time_col] = pd.to_datetime(df[time_col])

        # 30분 데이터는 다음 정시로 올림 (ceil)
        df['hour'] = df[time_col].dt.ceil('h')

        # 시간별로 그룹화하여 합계 계산
        hourly_df = df.groupby('hour')[value_col].sum().reset_index()
        hourly_df.rename(columns={'hour': time_col}, inplace=True)

        return hourly_df

    except Exception as e:
        logger.error(f"시간별 집계 실패: {e}")
        raise


def aggregate_to_daily(df, time_col='ymdhms', value_col='사용량(kWh)'):
    """
    30분 단위 예측 결과를 1일 단위로 집계 (전체 합계)

    Args:
        df: 예측 결과 DataFrame
        time_col: 시간 컬럼명
        value_col: 값 컬럼명

    Returns:
        DataFrame: 1일 단위 집계 결과 (1행: 전체 합계 + 첫 번째 날짜)
    """
    try:
        df = df.copy()

        # 시간 컬럼을 datetime으로 변환 (필요한 경우)
        if not pd.api.types.is_datetime64_any_dtype(df[time_col]):
            df[time_col] = pd.to_datetime(df[time_col])

        # 전체 합계 계산
        total_sum = df[value_col].sum()

        # 첫 번째 행의 날짜만 추출 (yyyy-mm-dd)
        first_date = df[time_col].iloc[0].normalize()  # 시간을 00:00:00으로 설정

        # 결과 DataFrame 생성 (1행)
        daily_df = pd.DataFrame({
            time_col: [first_date],
            value_col: [total_sum]
        })

        return daily_df

    except Exception as e:
        logger.error(f"일별 집계 실패: {e}")
        raise


def postprocess_predictions(df, aggregation='none', time_col='ymdhms', value_col='사용량(kWh)'):
    """
    예측 결과 후처리 - 음수 값 처리 및 집계 수준에 따라 처리

    Args:
        df: 예측 결과 DataFrame
        aggregation: 집계 방식 ('none', 'hourly', 'daily')
        time_col: 시간 컬럼명
        value_col: 값 컬럼명

    Returns:
        DataFrame: 후처리된 예측 결과
    """
    try:
        # 1. 음수 값 처리 (집계 전에 먼저 수행)
        df = df.copy()
        negative_count = (df[value_col] < 0).sum()
        if negative_count > 0:
            logger.warning(f"[후처리] 음수 값 {negative_count}개 발견 ({negative_count/len(df)*100:.1f}%) → 0으로 변환")
            df[value_col] = df[value_col].clip(lower=0)

        # 2. 집계 처리
        if aggregation == 'hourly':
            return aggregate_to_hourly(df, time_col, value_col)
        elif aggregation == 'daily':
            return aggregate_to_daily(df, time_col, value_col)
        else:
            return df

    except Exception as e:
        logger.error(f"후처리 실패: {e}")
        raise
