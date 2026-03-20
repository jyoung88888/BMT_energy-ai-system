"""
AI 로그 테이블 데이터 집계 스케줄러 스크립트
Solar Power, Power Usage, ESS Charge 데이터를 집계하여 AI 테이블에 적재합니다.

집계 방식:
    - 모든 집계: 오늘 날짜 기준

사용법:
    python schedule_AI_log_table.py                    # 오늘 날짜 자동 계산
    python schedule_AI_log_table.py --date 2025-01-01  # 2025-01-01 기준 집계
    python schedule_AI_log_table.py -d 2025-01-01      # 축약형
    python schedule_AI_log_table.py --help             # 도움말 표시
"""

import pymysql
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta
from typing import Dict, Any
import sys
import argparse
from pathlib import Path
import os


# 프로젝트 루트 경로를 sys.path에 추가
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 공통 DB 설정 import
GIT_ROOT = os.path.join(BASE_DIR, '..')
if GIT_ROOT not in sys.path:
    sys.path.insert(0, GIT_ROOT)
from db_config import DB_CONFIG

def setup_logging():
    """로깅 설정 (날짜별 분리)"""
    log_dir = Path(BASE_DIR) / "aggregate_logs"
    log_dir.mkdir(exist_ok=True)

    # 현재 날짜를 기반으로 로그 파일명 생성
    current_date = datetime.now().strftime('%Y-%m-%d')
    log_file = log_dir / f"ai_log_table_scheduler_{current_date}.log"

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    return logging.getLogger(__name__)


logger = None

# ============================================================
# 설정
# ============================================================

TABLE_NAMES = {
    # 소스 테이블 - 태양광
    'solar_day': 'tb_solar_day',
    'weather_info': 'tb_weather_info',

    # 소스 테이블 - 전력
    'smarteye_day': 'tb_aggregate_smarteye_day',

    # 소스 테이블 - ESS
    'bms_daily_stat': 'tb_nrt_bms_daily_stat',

    # AI 테이블
    'ai_solar_power': 'tb_ai_solar_power',
    'ai_ess_charge_amt': 'tb_ai_ess_charge_amt',
    'ai_pwr_usage': 'tb_ai_pwr_usage'
}

# ============================================================
# 데이터베이스 연결
# ============================================================

def get_db_connection():
    """데이터베이스 연결 생성"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        logger.info("✅ 데이터베이스 연결 성공")
        return connection
    except Exception as e:
        logger.error(f"❌ 데이터베이스 연결 실패: {str(e)}")
        raise

# ============================================================
# Solar Power 집계
# ============================================================

def aggregate_solar_power(connection, target_date: str) -> Dict[str, Any]:
    """
    tb_solar_day와 tb_weather_info의 데이터를 조합하여 tb_ai_solar_power에 적재
    - pre_pwr_generation: target_date 데이터 집계 → target_date 행에 저장
    - today_generation, accum_generation: target_date - 1일 데이터 집계 → target_date - 1일 행에 저장
    - tmn, tmx, ics: target_date 데이터 집계 → target_date 행에 저장

    Args:
        connection: DB 연결 객체
        target_date: 대상 날짜 (YYYY-MM-DD)

    Returns:
        Dict: 결과 정보
    """
    logger.info(f"📊 [Solar Power] 데이터 집계 및 적재 시작 - {target_date}")

    try:
        cursor = connection.cursor(pymysql.cursors.DictCursor)

        # 집계 기간 계산
        # pre_pwr_generation, tmn, tmx, ics: target_date 데이터 사용
        # today_generation, accum_generation: target_date - 1일 데이터 사용
        prev_date = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

        logger.info(f"📅 [Solar Power] pre_pwr_generation 집계 기간: {target_date} 00:00:00 ~ 23:59:59")
        logger.info(f"📅 [Solar Power] today_generation, accum_generation 집계 기간: {prev_date} 00:00:00 ~ 23:59:59")
        logger.info(f"📅 [Solar Power] tmn, tmx, ics 집계 기간: {target_date} 00:00:00 ~ 23:59:59")
        logger.info(f"📂 [Solar Power] 소스 테이블: tb_solar_day, tb_weather_info")
        logger.info(f"📂 [Solar Power] 타겟 테이블: tb_ai_solar_power")

        # 현재 시간 (reg_dt)
        reg_dt = datetime.now()

        # ============================================================
        # Step 1: pre_pwr_generation 집계 및 적재 (target_date 데이터 → target_date 행)
        # ============================================================
        pre_pwr_check_query = f"""
        SELECT
            SUM(forecast_quantity) as pre_pwr_generation
        FROM {TABLE_NAMES['solar_day']}
        WHERE ymdhms >= %s AND ymdhms < DATE_ADD(%s, INTERVAL 1 DAY)
        """

        cursor.execute(pre_pwr_check_query, [target_date, target_date])
        pre_pwr_data = cursor.fetchone()

        if pre_pwr_data:
            logger.info(f"📊 [Solar Power] pre_pwr_generation 집계된 값:")
            logger.info(f"   - 예측 발전량 합계: {pre_pwr_data['pre_pwr_generation']} (from {target_date})")

        # pre_pwr_generation UPSERT
        pre_pwr_insert_query = f"""
        INSERT INTO {TABLE_NAMES['ai_solar_power']}
            (ymdhms, pre_pwr_generation, reg_dt)
        SELECT * FROM (
            SELECT
                %s as ymdhms,
                SUM(forecast_quantity) as pre_pwr_generation,
                %s as reg_dt
            FROM {TABLE_NAMES['solar_day']}
            WHERE ymdhms >= %s AND ymdhms < DATE_ADD(%s, INTERVAL 1 DAY)
        ) AS new_data
        ON DUPLICATE KEY UPDATE
            pre_pwr_generation = VALUES(pre_pwr_generation),
            reg_dt = VALUES(reg_dt)
        """

        cursor.execute(pre_pwr_insert_query, [target_date, reg_dt, target_date, target_date])
        logger.info(f"✅ [Solar Power] pre_pwr_generation 적재 완료 (ymdhms={target_date})")

        # ============================================================
        # Step 2: today_generation, accum_generation 집계 및 적재 (prev_date 데이터 → prev_date 행)
        # ============================================================
        generation_check_query = f"""
        SELECT
            SUM(today_generation) as today_generation,
            SUM(accum_generation) as accum_generation
        FROM {TABLE_NAMES['solar_day']}
        WHERE ymdhms >= %s AND ymdhms < DATE_ADD(%s, INTERVAL 1 DAY)
        """

        cursor.execute(generation_check_query, [prev_date, prev_date])
        generation_data = cursor.fetchone()

        if generation_data:
            logger.info(f"📊 [Solar Power] today_generation, accum_generation 집계된 값:")
            logger.info(f"   - 실제 발전량 합계: {generation_data['today_generation']} (from {prev_date})")
            logger.info(f"   - 누적 발전량 합계: {generation_data['accum_generation']} (from {prev_date})")

        # today_generation, accum_generation UPSERT
        generation_insert_query = f"""
        INSERT INTO {TABLE_NAMES['ai_solar_power']}
            (ymdhms, today_generation, accum_generation, reg_dt)
        SELECT * FROM (
            SELECT
                %s as ymdhms,
                SUM(today_generation) as today_generation,
                SUM(accum_generation) as accum_generation,
                %s as reg_dt
            FROM {TABLE_NAMES['solar_day']}
            WHERE ymdhms >= %s AND ymdhms < DATE_ADD(%s, INTERVAL 1 DAY)
        ) AS new_data
        ON DUPLICATE KEY UPDATE
            today_generation = VALUES(today_generation),
            accum_generation = VALUES(accum_generation),
            reg_dt = VALUES(reg_dt)
        """

        cursor.execute(generation_insert_query, [prev_date, reg_dt, prev_date, prev_date])
        logger.info(f"✅ [Solar Power] today_generation, accum_generation 적재 완료 (ymdhms={prev_date})")

        # ============================================================
        # Step 3: Weather 데이터 집계 및 적재 (target_date 데이터 → target_date 행)
        # ============================================================
        weather_check_query = f"""
        SELECT
            MIN(tmn) as tmn,
            MAX(tmx) as tmx,
            SUM(ics) as ics
        FROM {TABLE_NAMES['weather_info']}
        WHERE tm >= %s AND tm < DATE_ADD(%s, INTERVAL 1 DAY)
        """

        cursor.execute(weather_check_query, [target_date, target_date])
        weather_data = cursor.fetchone()

        if weather_data:
            logger.info(f"📊 [Solar Power] Weather 집계된 값:")
            logger.info(f"   - 최저 기온 (tmn): {weather_data['tmn']} (from {target_date})")
            logger.info(f"   - 최고 기온 (tmx): {weather_data['tmx']} (from {target_date})")
            logger.info(f"   - 일사량 합계 (ics): {weather_data['ics']} (from {target_date})")

        # Weather 데이터 UPSERT
        weather_insert_query = f"""
        INSERT INTO {TABLE_NAMES['ai_solar_power']}
            (ymdhms, tmn, tmx, ics, reg_dt)
        SELECT * FROM (
            SELECT
                %s as ymdhms,
                MIN(tmn) as tmn,
                MAX(tmx) as tmx,
                SUM(ics) as ics,
                %s as reg_dt
            FROM {TABLE_NAMES['weather_info']}
            WHERE tm >= %s AND tm < DATE_ADD(%s, INTERVAL 1 DAY)
        ) AS new_data
        ON DUPLICATE KEY UPDATE
            tmn = VALUES(tmn),
            tmx = VALUES(tmx),
            ics = VALUES(ics),
            reg_dt = VALUES(reg_dt)
        """

        cursor.execute(weather_insert_query, [target_date, reg_dt, target_date, target_date])
        logger.info(f"✅ [Solar Power] Weather 데이터 적재 완료 (ymdhms={target_date})")

        connection.commit()

        logger.info(f"✅ [Solar Power] tb_ai_solar_power 테이블에 데이터 적재 완료")
        logger.info(f"   - pre_pwr_generation, tmn, tmx, ics: {target_date} 행에 저장")
        logger.info(f"   - today_generation, accum_generation: {prev_date} 행에 저장")
        logger.info(f"   - 등록 시간 (reg_dt): {reg_dt}")

        cursor.close()

        return {
            "success": True,
            "target_date": target_date,
            "prev_date": prev_date,
            "message": f"Solar Power 데이터 UPSERT 완료 (target: {target_date}, prev: {prev_date})"
        }

    except Exception as e:
        logger.error(f"❌ [Solar Power] 데이터 집계 및 적재 실패: {str(e)}")
        return {
            "success": False,
            "target_date": target_date,
            "message": f"Solar Power 데이터 적재 중 오류 발생: {str(e)}"
        }

# ============================================================
# Power Usage 집계
# ============================================================

def aggregate_power_usage(connection, target_date: str) -> Dict[str, Any]:
    """
    tb_aggregate_smarteye_day의 데이터를 tb_ai_pwr_usage에 적재
    - pwr_usage: target_date - 1일 데이터 → target_date - 1일 행에 저장
    - pwr_forecase: target_date 데이터 → target_date 행에 저장

    Args:
        connection: DB 연결 객체
        target_date: 대상 날짜 (YYYY-MM-DD)

    Returns:
        Dict: 결과 정보
    """
    logger.info(f"📊 [Power Usage] 데이터 집계 및 적재 시작 - {target_date}")

    try:
        cursor = connection.cursor(pymysql.cursors.DictCursor)

        # 집계 기간 계산
        prev_date = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

        logger.info(f"📅 [Power Usage] pwr_usage 집계 기간: {prev_date}")
        logger.info(f"📅 [Power Usage] pwr_forecase 집계 기간: {target_date}")
        logger.info(f"📂 [Power Usage] 소스 테이블: tb_aggregate_smarteye_day")
        logger.info(f"📂 [Power Usage] 타겟 테이블: tb_ai_pwr_usage")

        # 현재 시간 (reg_dt)
        reg_dt = datetime.now()

        # Step 1: pwr_usage (prev_date 데이터 → prev_date 행)
        logger.info(f"🔄 [Power Usage] Step 1: pwr_usage 업데이트 (tb_aggregate_smarteye_day → tb_ai_pwr_usage)")

        # 소스 데이터 확인 (prev_date)
        check_query_prev = f"""
        SELECT COUNT(*) as cnt,
               MIN(use_time) as min_time,
               MAX(use_time) as max_time,
               SUM(pwr_kepco_usage_tot) as total_usage
        FROM {TABLE_NAMES['smarteye_day']}
        WHERE use_time >= %s AND use_time < DATE_ADD(%s, INTERVAL 1 DAY)
        """

        cursor.execute(check_query_prev, [prev_date, prev_date])
        check_result_prev = cursor.fetchone()
        logger.info(f"🔍 [Power Usage] pwr_usage 소스 데이터 확인 - 건수: {check_result_prev['cnt']}건")

        if check_result_prev['cnt'] > 0:
            logger.info(f"📊 [Power Usage] pwr_usage 집계된 값 (from {prev_date}):")
            logger.info(f"   - 전력 사용량 합계: {check_result_prev['total_usage']}")
            logger.info(f"   - 시간 범위: {check_result_prev['min_time']} ~ {check_result_prev['max_time']}")

        # pwr_usage UPSERT
        usage_query = f"""
        INSERT INTO {TABLE_NAMES['ai_pwr_usage']}
            (ymdhms, pwr_usage, reg_dt)
        SELECT * FROM (
            SELECT
                use_time as ymdhms,
                pwr_kepco_usage_tot as pwr_usage,
                %s as reg_dt
            FROM {TABLE_NAMES['smarteye_day']}
            WHERE use_time >= %s AND use_time < DATE_ADD(%s, INTERVAL 1 DAY)
        ) AS new_data
        ON DUPLICATE KEY UPDATE
            pwr_usage = VALUES(pwr_usage),
            reg_dt = VALUES(reg_dt)
        """

        cursor.execute(usage_query, [reg_dt, prev_date, prev_date])
        logger.info(f"  ✅ Step 1 완료: pwr_usage 적재 (from {prev_date} → ymdhms={prev_date})")

        # Step 2: pwr_forecase (target_date 데이터 → target_date 행)
        logger.info(f"🔄 [Power Usage] Step 2: pwr_forecase 업데이트 (tb_aggregate_smarteye_day → tb_ai_pwr_usage)")

        # 소스 데이터 확인 (target_date)
        check_query_target = f"""
        SELECT COUNT(*) as cnt,
               MIN(use_time) as min_time,
               MAX(use_time) as max_time,
               SUM(forecast_quantity) as total_forecast
        FROM {TABLE_NAMES['smarteye_day']}
        WHERE use_time >= %s AND use_time < DATE_ADD(%s, INTERVAL 1 DAY)
        """

        cursor.execute(check_query_target, [target_date, target_date])
        check_result_target = cursor.fetchone()
        logger.info(f"🔍 [Power Usage] pwr_forecase 소스 데이터 확인 - 건수: {check_result_target['cnt']}건")

        if check_result_target['cnt'] > 0:
            logger.info(f"📊 [Power Usage] pwr_forecase 집계된 값 (from {target_date}):")
            logger.info(f"   - 전력 예측 합계: {check_result_target['total_forecast']}")
            logger.info(f"   - 시간 범위: {check_result_target['min_time']} ~ {check_result_target['max_time']}")

        # pwr_forecase UPSERT
        forecase_query = f"""
        INSERT INTO {TABLE_NAMES['ai_pwr_usage']}
            (ymdhms, pwr_forecase, reg_dt)
        SELECT * FROM (
            SELECT
                use_time as ymdhms,
                forecast_quantity as pwr_forecase,
                %s as reg_dt
            FROM {TABLE_NAMES['smarteye_day']}
            WHERE use_time >= %s AND use_time < DATE_ADD(%s, INTERVAL 1 DAY)
        ) AS new_data
        ON DUPLICATE KEY UPDATE
            pwr_forecase = VALUES(pwr_forecase),
            reg_dt = VALUES(reg_dt)
        """

        cursor.execute(forecase_query, [reg_dt, target_date, target_date])
        logger.info(f"  ✅ Step 2 완료: pwr_forecase 적재 (from {target_date} → ymdhms={target_date})")

        connection.commit()

        logger.info(f"✅ [Power Usage] tb_ai_pwr_usage 테이블에 데이터 적재 완료 (2단계)")
        logger.info(f"   - pwr_usage: {prev_date} 행에 저장 ({check_result_prev['cnt']}건)")
        logger.info(f"   - pwr_forecase: {target_date} 행에 저장 ({check_result_target['cnt']}건)")
        logger.info(f"   - 등록 시간 (reg_dt): {reg_dt}")

        cursor.close()

        return {
            "success": True,
            "source_count_prev": check_result_prev['cnt'],
            "source_count_target": check_result_target['cnt'],
            "target_date": target_date,
            "prev_date": prev_date,
            "message": f"Power Usage 데이터 UPSERT 완료 (usage: {prev_date}, forecase: {target_date})"
        }

    except Exception as e:
        logger.error(f"❌ [Power Usage] 데이터 집계 및 적재 실패: {str(e)}")
        return {
            "success": False,
            "target_date": target_date,
            "message": f"Power Usage 데이터 적재 중 오류 발생: {str(e)}"
        }

# ============================================================
# ESS Charge 집계
# ============================================================

def aggregate_ess_charge(connection, target_date: str) -> Dict[str, Any]:
    """
    여러 테이블의 데이터를 기반으로 ESS 충전량 데이터를 tb_ai_ess_charge_amt에 적재
    - 예측값 (pre_pwr_generation, pre_charge): target_date 데이터 → target_date 행에 저장
    - 실제값 (today_generation, pwr_usage, AccruepowGap, charge_amount): target_date - 1일 데이터 → target_date - 1일 행에 저장

    Args:
        connection: DB 연결 객체
        target_date: 대상 날짜 (YYYY-MM-DD)

    Returns:
        Dict: 결과 정보
    """
    logger.info(f"📊 [ESS Charge] 데이터 집계 및 적재 시작 - {target_date}")

    try:
        cursor = connection.cursor(pymysql.cursors.DictCursor)

        # 집계 기간 계산
        prev_date = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

        logger.info(f"📅 [ESS Charge] 예측값 집계 기간: {target_date}")
        logger.info(f"📅 [ESS Charge] 실제값 집계 기간: {prev_date}")
        logger.info(f"📂 [ESS Charge] 소스 테이블: tb_ai_solar_power, tb_ai_pwr_usage, tb_nrt_bms_daily_stat")
        logger.info(f"📂 [ESS Charge] 타겟 테이블: tb_ai_ess_charge_amt")

        # 현재 시간 (reg_dt)
        reg_dt = datetime.now()

        # Step 1a: Solar Power - pre_pwr_generation (target_date 데이터 → target_date 행)
        logger.info(f"🔄 [ESS Charge] Step 1a: pre_pwr_generation 업데이트 (tb_ai_solar_power → tb_ai_ess_charge_amt)")

        # 소스 데이터 확인
        solar_pre_check_query = f"""
        SELECT
            sp.ymdhms,
            sp.pre_pwr_generation
        FROM {TABLE_NAMES['ai_solar_power']} sp
        WHERE DATE(sp.ymdhms) = %s
        """

        cursor.execute(solar_pre_check_query, [target_date])
        solar_pre_data = cursor.fetchone()

        if solar_pre_data:
            logger.info(f"📊 [ESS Charge] pre_pwr_generation 집계된 값:")
            logger.info(f"   - 예측 발전량: {solar_pre_data['pre_pwr_generation']} (from {target_date})")

        solar_pre_query = f"""
        INSERT INTO {TABLE_NAMES['ai_ess_charge_amt']}
            (ymdhms, pre_pwr_generation, reg_dt)
        SELECT * FROM (
            SELECT
                sp.ymdhms,
                sp.pre_pwr_generation,
                %s as reg_dt
            FROM {TABLE_NAMES['ai_solar_power']} sp
            WHERE DATE(sp.ymdhms) = %s
        ) AS new_data
        ON DUPLICATE KEY UPDATE
            pre_pwr_generation = VALUES(pre_pwr_generation),
            reg_dt = VALUES(reg_dt)
        """

        cursor.execute(solar_pre_query, [reg_dt, target_date])
        logger.info(f"  ✅ Step 1a 완료: pre_pwr_generation 적재 (from {target_date} → ymdhms={target_date})")

        # Step 1b: Solar Power - today_generation (prev_date 데이터 → prev_date 행)
        logger.info(f"🔄 [ESS Charge] Step 1b: today_generation 업데이트 (tb_ai_solar_power → tb_ai_ess_charge_amt)")

        # 소스 데이터 확인
        solar_today_check_query = f"""
        SELECT
            sp.ymdhms,
            sp.today_generation
        FROM {TABLE_NAMES['ai_solar_power']} sp
        WHERE DATE(sp.ymdhms) = %s
        """

        cursor.execute(solar_today_check_query, [prev_date])
        solar_today_data = cursor.fetchone()

        if solar_today_data:
            logger.info(f"📊 [ESS Charge] today_generation 집계된 값:")
            logger.info(f"   - today_generation: {solar_today_data['today_generation']} (from {prev_date})")

        solar_today_query = f"""
        INSERT INTO {TABLE_NAMES['ai_ess_charge_amt']}
            (ymdhms, today_generation, reg_dt)
        SELECT * FROM (
            SELECT
                sp.ymdhms,
                sp.today_generation,
                %s as reg_dt
            FROM {TABLE_NAMES['ai_solar_power']} sp
            WHERE DATE(sp.ymdhms) = %s
        ) AS new_data
        ON DUPLICATE KEY UPDATE
            today_generation = VALUES(today_generation),
            reg_dt = VALUES(reg_dt)
        """

        cursor.execute(solar_today_query, [reg_dt, prev_date])
        logger.info(f"  ✅ Step 1b 완료: today_generation 적재 (from {prev_date} → ymdhms={prev_date})")

        # Step 2: Power Usage 데이터 (prev_date 데이터 → prev_date 행)
        logger.info(f"🔄 [ESS Charge] Step 2: Power Usage 데이터 업데이트 (tb_ai_pwr_usage → tb_ai_ess_charge_amt)")

        # 소스 데이터 확인
        usage_check_query = f"""
        SELECT
            pu.ymdhms,
            pu.pwr_usage,
            pu.AccruepowGap
        FROM {TABLE_NAMES['ai_pwr_usage']} pu
        WHERE DATE(pu.ymdhms) = %s
        """

        cursor.execute(usage_check_query, [prev_date])
        usage_data = cursor.fetchone()

        if usage_data:
            logger.info(f"📊 [ESS Charge] Power Usage 집계된 값:")
            logger.info(f"   - pwr_usage : {usage_data['pwr_usage']} (from {prev_date})")
            logger.info(f"   - AccruepowGap : {usage_data['AccruepowGap']} (from {prev_date})")

        usage_query = f"""
        INSERT INTO {TABLE_NAMES['ai_ess_charge_amt']}
            (ymdhms, pwr_usage, AccruepowGap, reg_dt)
        SELECT * FROM (
            SELECT
                pu.ymdhms,
                pu.pwr_usage,
                pu.AccruepowGap,
                %s as reg_dt
            FROM {TABLE_NAMES['ai_pwr_usage']} pu
            WHERE DATE(pu.ymdhms) = %s
        ) AS new_data
        ON DUPLICATE KEY UPDATE
            pwr_usage = VALUES(pwr_usage),
            AccruepowGap = VALUES(AccruepowGap),
            reg_dt = VALUES(reg_dt)
        """

        cursor.execute(usage_query, [reg_dt, prev_date])
        logger.info(f"  ✅ Step 2 완료: pwr_usage, AccruepowGap 적재 (from {prev_date} → ymdhms={prev_date})")

        # Step 3a: BMS - pre_charge (target_date 데이터 → target_date 행)
        logger.info(f"🔄 [ESS Charge] Step 3a: pre_charge 업데이트 (tb_nrt_bms_daily_stat → tb_ai_ess_charge_amt)")

        # 소스 데이터 확인
        bms_pre_check_query = f"""
        SELECT
            STR_TO_DATE(bms.V_TIME, '%%Y%%m%%d') as ymdhms,
            bms.forecast_quantity as pre_charge
        FROM {TABLE_NAMES['bms_daily_stat']} bms
        WHERE DATE(STR_TO_DATE(bms.V_TIME, '%%Y%%m%%d')) = %s
        """

        cursor.execute(bms_pre_check_query, [target_date])
        bms_pre_data = cursor.fetchone()

        if bms_pre_data:
            logger.info(f"📊 [ESS Charge] pre_charge 집계된 값:")
            logger.info(f"   - pre_charge: {bms_pre_data['pre_charge']} (from {target_date})")

        bms_pre_query = f"""
        INSERT INTO {TABLE_NAMES['ai_ess_charge_amt']}
            (ymdhms, pre_charge, reg_dt)
        SELECT * FROM (
            SELECT
                STR_TO_DATE(bms.V_TIME, '%%Y%%m%%d') as ymdhms,
                bms.forecast_quantity as pre_charge,
                %s as reg_dt
            FROM {TABLE_NAMES['bms_daily_stat']} bms
            WHERE DATE(STR_TO_DATE(bms.V_TIME, '%%Y%%m%%d')) = %s
        ) AS new_data
        ON DUPLICATE KEY UPDATE
            pre_charge = VALUES(pre_charge),
            reg_dt = VALUES(reg_dt)
        """

        cursor.execute(bms_pre_query, [reg_dt, target_date])
        logger.info(f"  ✅ Step 3a 완료: pre_charge 적재 (from {target_date} → ymdhms={target_date})")

        # Step 3b: BMS - charge_amount (prev_date 데이터 → prev_date 행)
        logger.info(f"🔄 [ESS Charge] Step 3b: charge_amount 업데이트 (tb_nrt_bms_daily_stat → tb_ai_ess_charge_amt)")

        # 소스 데이터 확인
        bms_charge_check_query = f"""
        SELECT
            STR_TO_DATE(bms.V_TIME, '%%Y%%m%%d') as ymdhms,
            bms.CHARGE_AMOUNT as charge_amount
        FROM {TABLE_NAMES['bms_daily_stat']} bms
        WHERE DATE(STR_TO_DATE(bms.V_TIME, '%%Y%%m%%d')) = %s
        """

        cursor.execute(bms_charge_check_query, [prev_date])
        bms_charge_data = cursor.fetchone()

        if bms_charge_data:
            logger.info(f"📊 [ESS Charge] charge_amount 집계된 값:")
            logger.info(f"   - charge_amount: {bms_charge_data['charge_amount']} (from {prev_date})")

        bms_charge_query = f"""
        INSERT INTO {TABLE_NAMES['ai_ess_charge_amt']}
            (ymdhms, charge_amount, reg_dt)
        SELECT * FROM (
            SELECT
                STR_TO_DATE(bms.V_TIME, '%%Y%%m%%d') as ymdhms,
                bms.CHARGE_AMOUNT as charge_amount,
                %s as reg_dt
            FROM {TABLE_NAMES['bms_daily_stat']} bms
            WHERE DATE(STR_TO_DATE(bms.V_TIME, '%%Y%%m%%d')) = %s
        ) AS new_data
        ON DUPLICATE KEY UPDATE
            charge_amount = VALUES(charge_amount),
            reg_dt = VALUES(reg_dt)
        """

        cursor.execute(bms_charge_query, [reg_dt, prev_date])
        logger.info(f"  ✅ Step 3b 완료: charge_amount 적재 (from {prev_date} → ymdhms={prev_date})")

        connection.commit()
        cursor.close()

        logger.info(f"✅ [ESS Charge] tb_ai_ess_charge_amt 테이블에 데이터 적재 완료 (5단계)")
        logger.info(f"   - 예측값 (pre_pwr_generation, pre_charge): {target_date} 행에 저장")
        logger.info(f"   - 실제값 (today_generation, pwr_usage, AccruepowGap, charge_amount): {prev_date} 행에 저장")
        logger.info(f"   - 등록 시간 (reg_dt): {reg_dt}")

        return {
            "success": True,
            "target_date": target_date,
            "prev_date": prev_date,
            "message": f"ESS Charge 데이터 UPSERT 완료 (target: {target_date}, prev: {prev_date})"
        }

    except Exception as e:
        logger.error(f"❌ [ESS Charge] 데이터 집계 및 적재 실패: {str(e)}")
        return {
            "success": False,
            "target_date": target_date,
            "message": f"ESS Charge 데이터 적재 중 오류 발생: {str(e)}"
        }

# ============================================================
# 통합 실행
# ============================================================

def run_aggregation(target_date: str = None):
    """
    모든 집계 작업을 실행

    Args:
        target_date: 대상 날짜 (YYYY-MM-DD). None이면 오늘 날짜 자동 계산

    Note:
        - Solar Power, Power Usage, ESS Charge: 오늘 날짜 기준 집계
    """
    # target_date 계산 (오늘 날짜)
    if target_date is None:
        kst = ZoneInfo("Asia/Seoul")
        today = datetime.now(kst).date()
        target_date = today.strftime("%Y-%m-%d")

    logger.info("=" * 80)
    logger.info(f"📅 [통합 집계] 시작 - 대상 날짜: {target_date}")
    logger.info("=" * 80)

    connection = None
    results = {}

    try:
        # DB 연결
        connection = get_db_connection()

        # 1. Solar Power 집계
        try:
            solar_result = aggregate_solar_power(connection, target_date)
            results["solar_power"] = solar_result
        except Exception as e:
            logger.error(f"❌ [Solar Power] 실패: {str(e)}")
            results["solar_power"] = {
                "success": False,
                "target_date": target_date,
                "message": f"Solar Power 집계 실패: {str(e)}"
            }

        # 2. Power Usage 집계
        try:
            power_result = aggregate_power_usage(connection, target_date)
            results["power_usage"] = power_result
        except Exception as e:
            logger.error(f"❌ [Power Usage] 실패: {str(e)}")
            results["power_usage"] = {
                "success": False,
                "target_date": target_date,
                "message": f"Power Usage 집계 실패: {str(e)}"
            }

        # 3. ESS Charge 집계
        try:
            ess_charge_result = aggregate_ess_charge(connection, target_date)
            results["ess_charge"] = ess_charge_result
        except Exception as e:
            logger.error(f"❌ [ESS Charge] 실패: {str(e)}")
            results["ess_charge"] = {
                "success": False,
                "target_date": target_date,
                "message": f"ESS Charge 집계 실패: {str(e)}"
            }

        logger.info("=" * 80)
        logger.info(f"📊 [통합 집계] 완료 - 대상 날짜: {target_date}")
        logger.info("=" * 80)

        # 결과 요약 출력
        for service_name, result in results.items():
            status = "✅ 성공" if result.get("success") else "❌ 실패"
            logger.info(f"{status} [{service_name}]: {result.get('message')}")

        return results

    except Exception as e:
        logger.error(f"❌ [통합 집계] 오류: {str(e)}")
        raise

    finally:
        if connection:
            connection.close()
            logger.info("🔌 데이터베이스 연결 종료")

# ============================================================
# 메인 실행
# ============================================================

if __name__ == "__main__":
    # 로깅 초기화
    logger = setup_logging()

    try:
        logger.info("=" * 80)
        logger.info("AI Log Table Data Aggregation Scheduler Started")
        logger.info(f"Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 80)

        # 커맨드라인 인자 파싱
        parser = argparse.ArgumentParser(
            description='AI 로그 테이블 데이터 집계 스케줄러',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
    사용 예시:
    python schedule_AI_log_table.py                    # 오늘 날짜 자동 계산
    python schedule_AI_log_table.py --date 2025-01-01  # 2025-01-01 기준 집계
    python schedule_AI_log_table.py -d 2025-01-01      # 축약형

    집계 항목:
    - Solar Power: tb_ai_solar_power 테이블
    - Power Usage: tb_ai_pwr_usage 테이블
    - ESS Charge: tb_ai_ess_charge_amt 테이블
                """
        )
        parser.add_argument(
            '--date',
            '-d',
            type=str,
            default=None,
            help='집계할 날짜 (YYYY-MM-DD 형식). 생략하면 오늘 날짜 자동 계산'
        )

        args = parser.parse_args()
        target_date = args.date

        # 날짜 형식 검증 (입력된 경우에만)
        if target_date:
            try:
                datetime.strptime(target_date, '%Y-%m-%d')  # 형식 검증만 수행
                logger.info(f"📅 [날짜 설정] 입력된 날짜: {target_date}")
            except ValueError:
                logger.error(f"❌ [날짜 설정] 잘못된 날짜 형식: {args.date}")
                logger.error("YYYY-MM-DD 형식으로 입력해주세요.")
                logger.info("=" * 80)
                sys.exit(1)
        else:
            logger.info(f"📅 [날짜 설정] 자동 날짜 계산 모드 (오늘 날짜)")

        # 집계 실행
        logger.info("📊 [통합 집계] 모든 데이터 집계 시작")
        results = run_aggregation(target_date)

        logger.info("=" * 80)
        logger.info("🎉 AI Log Table Data Aggregation Scheduler Completed Successfully")
        logger.info("=" * 80)

    except KeyboardInterrupt:
        logger.info("⚠️ 사용자에 의해 중단됨")
        logger.info("=" * 80)
        sys.exit(130)

    except Exception as e:
        logger.error(f"💥 스크립트 실행 중 오류 발생: {str(e)}", exc_info=True)
        sys.exit(1)
