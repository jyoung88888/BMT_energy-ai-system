"""
ESS AI 테이블 데이터 집계 스케줄러 스크립트
ESS Predict 데이터를 집계하여 적재합니다.

집계 방식:
    - ESS Predict: 내일 날짜 기준 집계 (오늘 + 1일)

사용법:
    python schedule_ess_AI.py                    # 오늘 날짜 자동 계산 (내일 예측)
    python schedule_ess_AI.py --date 2025-01-01  # 2025-01-01 기준 (2025-01-02 예측)
    python schedule_ess_AI.py -d 2025-01-01      # 축약형
    python schedule_ess_AI.py --help             # 도움말 표시
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

def setup_logging():
    """로깅 설정 (날짜별 분리)"""
    log_dir = Path(BASE_DIR) / "predict_logs"
    log_dir.mkdir(exist_ok=True)

    # 현재 날짜를 기반으로 로그 파일명 생성
    current_date = datetime.now().strftime('%Y-%m-%d')
    log_file = log_dir / f"ess_predict_scheduler_{current_date}.log"

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

DB_CONFIG = {
    'host': '192.168.213.250',
    'user': 'root',
    'password': 'OnDemand%Ai',
    'charset': 'utf8mb4',
    'database': 'db_energy'
}

TABLE_NAMES = {
    # 소스 테이블 - 태양광
    'solar_day': 'tb_solar_day',
    # 소스 테이블 - 전력
    'smarteye_day': 'tb_aggregate_smarteye_day',
    # 소스 테이블 - ESS
    'bms_daily_stat': 'tb_nrt_bms_daily_stat'
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
# ESS Predict 집계
# ============================================================

def aggregate_ess_predict(connection, target_date: str) -> Dict[str, Any]:
    """
    solar_day와 smarteye_day의 데이터를 기반으로 ESS 예측값을 계산하여 bms_daily_stat에 적재

    Args:
        connection: DB 연결 객체
        target_date: 대상 날짜 (YYYY-MM-DD)

    Returns:
        Dict: 결과 정보
    """
    logger.info(f"📊 [ESS Predict] 데이터 집계 및 적재 시작 - {target_date}")

    try:
        cursor = connection.cursor(pymysql.cursors.DictCursor)

        # 현재 시간
        now_dt = datetime.now()
        logger.info(f"📊 [ESS Predict] 실행 시간: {now_dt}")

        start_datetime = f"{target_date} 00:00:00"
        end_datetime = f"{target_date} 23:59:59"

        # 매칭되는 데이터 조회
        select_query = f"""
        SELECT
            COUNT(*) as match_count,
            SUM(sd.forecast_quantity) as solar_forecast_sum,
            MAX(se.forecast_quantity) as smarteye_forecast,
            CASE
                WHEN (SUM(sd.forecast_quantity) + 3120) < MAX(se.forecast_quantity)
                THEN 3120
                ELSE GREATEST(0, MAX(se.forecast_quantity) - SUM(sd.forecast_quantity))
            END as pwr_ess
        FROM {TABLE_NAMES['solar_day']} sd
        INNER JOIN {TABLE_NAMES['smarteye_day']} se
            ON DATE(sd.ymdhms) = DATE(se.use_time)
        WHERE sd.ymdhms >= %s AND sd.ymdhms <= %s
          AND se.use_time >= %s AND se.use_time <= %s
        """

        cursor.execute(select_query, [start_datetime, end_datetime, start_datetime, end_datetime])
        matched_data = cursor.fetchone()

        if matched_data and matched_data['match_count'] > 0:
            logger.info(f"🔍 [ESS Predict] 매칭된 데이터 건수: {matched_data['match_count']}건")
            logger.info(f"📊 [ESS Predict] 집계 결과 - "
                       f"태양광 예측 합계: {matched_data['solar_forecast_sum']}, "
                       f"전력 사용 예측: {matched_data['smarteye_forecast']}, "
                       f"계산된 pwr_ess: {matched_data['pwr_ess']}")
        else:
            logger.warning(f"⚠️ [ESS Predict] {target_date}에 매칭되는 데이터가 없습니다.")

        # V_TIME 변환 (YYYY-MM-DD → YYYYMMDD)
        v_time_converted = target_date.replace('-', '')
        logger.info(f"🔍 [ESS Predict] 변환된 V_TIME: {v_time_converted}")

        # 기존 데이터 확인 (T_CREATE_DT 조회)
        check_query = f"""
        SELECT T_CREATE_DT FROM {TABLE_NAMES['bms_daily_stat']} WHERE V_TIME = %s
        """
        cursor.execute(check_query, [v_time_converted])
        existing_row = cursor.fetchone()

        if existing_row and existing_row.get('T_CREATE_DT'):
            # 기존 데이터가 있으면 T_CREATE_DT 유지
            t_create_dt = existing_row['T_CREATE_DT']
            logger.info(f"📊 [ESS Predict] 기존 레코드 발견 - T_CREATE_DT: {t_create_dt}")
        else:
            # 새로운 데이터면 현재 시간을 T_CREATE_DT로 설정
            t_create_dt = now_dt
            logger.info(f"📊 [ESS Predict] 새로운 레코드 - T_CREATE_DT: {t_create_dt}")

        # UPSERT 쿼리
        insert_query = f"""
        INSERT INTO {TABLE_NAMES['bms_daily_stat']}
            (V_SITE_ID, V_TIME, V_DEVICE_ID, forecast_quantity, T_CREATE_DT, T_UPDATE_DT)
        SELECT * FROM (
            SELECT
                '3024200001' as V_SITE_ID,
                %s as V_TIME,
                '2000001' as V_DEVICE_ID,
                CASE
                    WHEN (SUM(sd.forecast_quantity) + 3320) < MAX(se.forecast_quantity)
                    THEN 3320
                    ELSE GREATEST(0, MAX(se.forecast_quantity) - SUM(sd.forecast_quantity))
                END as forecast_quantity,
                %s as T_CREATE_DT,
                %s as T_UPDATE_DT
            FROM {TABLE_NAMES['solar_day']} sd
            INNER JOIN {TABLE_NAMES['smarteye_day']} se
                ON DATE(sd.ymdhms) = DATE(se.use_time)
            WHERE sd.ymdhms >= %s AND sd.ymdhms <= %s
              AND se.use_time >= %s AND se.use_time <= %s
        ) AS new_data
        ON DUPLICATE KEY UPDATE
            forecast_quantity = VALUES(forecast_quantity),
            T_UPDATE_DT = VALUES(T_UPDATE_DT)
        """

        params = [v_time_converted, t_create_dt, now_dt, start_datetime, end_datetime, start_datetime, end_datetime]
        cursor.execute(insert_query, params)
        connection.commit()

        # 적재 확인
        cursor.execute(f"SELECT V_TIME, forecast_quantity, T_CREATE_DT, T_UPDATE_DT FROM {TABLE_NAMES['bms_daily_stat']} WHERE V_TIME = %s", [v_time_converted])
        result = cursor.fetchone()
        if result:
            logger.info(f"🔍 [ESS Predict] 적재 확인 - V_TIME: {result['V_TIME']}, forecast_quantity: {result['forecast_quantity']}, T_CREATE_DT: {result['T_CREATE_DT']}, T_UPDATE_DT: {result['T_UPDATE_DT']}")
        else:
            logger.warning(f"⚠️ [ESS Predict] V_TIME '{v_time_converted}' 행이 테이블에 없습니다")

        cursor.close()

        logger.info(f"✅ [ESS Predict] 데이터 집계 및 적재 완료 | T_CREATE_DT: {t_create_dt}, T_UPDATE_DT: {now_dt}")
        return {
            "success": True,
            "target_date": target_date,
            "message": f"{target_date} 날짜의 ESS Predict 데이터 UPSERT 완료"
        }

    except Exception as e:
        logger.error(f"❌ [ESS Predict] 데이터 집계 및 적재 실패: {str(e)}")
        return {
            "success": False,
            "target_date": target_date,
            "message": f"ESS Predict 데이터 적재 중 오류 발생: {str(e)}"
        }

# ============================================================
# 통합 실행
# ============================================================

def run_aggregation(target_date: str = None):
    """
    ESS Predict 집계 작업을 실행

    Args:
        target_date: 기준 날짜 (YYYY-MM-DD). None이면 오늘 날짜 자동 계산

    Note:
        - ESS Predict: 기준 날짜 + 1일(내일) 데이터를 예측하여 집계
    """
    # target_date 계산 (오늘 날짜)
    if target_date is None:
        kst = ZoneInfo("Asia/Seoul")
        today = datetime.now(kst).date()
        target_date = today.strftime("%Y-%m-%d")

    # ESS Predict용 내일 날짜 계산
    tomorrow_date = (datetime.strptime(target_date, "%Y-%m-%d").date() + timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info("=" * 80)
    logger.info(f"📅 [ESS Predict 집계] 시작")
    logger.info(f"   - 기준 날짜: {target_date}")
    logger.info(f"   - 예측 대상 날짜: {tomorrow_date} (기준 날짜 + 1일)")
    logger.info("=" * 80)

    connection = None
    results = {}

    try:
        # DB 연결
        connection = get_db_connection()

        # ESS Predict 집계 (내일 날짜)
        try:
            ess_predict_result = aggregate_ess_predict(connection, tomorrow_date)
            results["ess_predict"] = ess_predict_result
        except Exception as e:
            logger.error(f"❌ [ESS Predict] 실패: {str(e)}")
            results["ess_predict"] = {
                "success": False,
                "target_date": tomorrow_date,
                "message": f"ESS Predict 집계 실패: {str(e)}"
            }

        logger.info("=" * 80)
        logger.info(f"📊 [ESS Predict 집계] 완료")
        logger.info("=" * 80)

        # 결과 요약 출력
        for service_name, result in results.items():
            status = "✅ 성공" if result.get("success") else "❌ 실패"
            logger.info(f"{status} [{service_name}]: {result.get('message')}")

        return results

    except Exception as e:
        logger.error(f"❌ [ESS Predict 집계] 오류: {str(e)}")
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
        logger.info("ESS Predict Data Aggregation Scheduler Started")
        logger.info(f"Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 80)

        # 커맨드라인 인자 파싱
        parser = argparse.ArgumentParser(
            description='ESS Predict 데이터 집계 스케줄러',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
사용 예시:
  python schedule_ess_ai_table.py                    # 오늘 날짜 기준 (내일 예측)
  python schedule_ess_ai_table.py --date 2025-01-01  # 2025-01-01 기준 (2025-01-02 예측)
  python schedule_ess_ai_table.py -d 2025-01-01      # 축약형

집계 방식:
  - ESS Predict: 기준 날짜 + 1일 예측 데이터를 tb_nrt_bms_daily_stat에 저장
            """
        )
        parser.add_argument(
            '--date',
            '-d',
            type=str,
            default=None,
            help='기준 날짜 (YYYY-MM-DD 형식). 생략하면 오늘 날짜 자동 계산. 내일(+1일) 예측값을 집계합니다.'
        )

        args = parser.parse_args()
        target_date = args.date
        # 날짜 형식 검증 (입력된 경우에만)
        if target_date:
            try:
                # 입력된 날짜 검증
                datetime.strptime(target_date, "%Y-%m-%d")
                logger.info(f"📅 [날짜 설정] 입력된 날짜: {target_date}")
            except ValueError:
                logger.error(f"❌ [날짜 설정] 잘못된 날짜 형식: {args.date}")
                logger.error("YYYY-MM-DD 형식으로 입력해주세요.")
                logger.info("=" * 80)
                sys.exit(1)
        else:
            logger.info(f"📅 [날짜 설정] 자동 날짜 계산 모드 (오늘 날짜)")

        # 집계 실행
        logger.info("📊 [ESS Predict] 데이터 집계 시작")
        results = run_aggregation(target_date)

        logger.info("=" * 80)
        logger.info("🎉 ESS Predict Data Aggregation Scheduler Completed Successfully")
        logger.info("=" * 80)

    except KeyboardInterrupt:
        logger.info("⚠️ 사용자에 의해 중단됨")
        logger.info("=" * 80)
        sys.exit(130)

    except Exception as e:
        #logger.info("=" * 80)
        logger.error(f"💥 스크립트 실행 중 오류 발생: {str(e)}", exc_info=True)
        #logger.info("=" * 80)
        sys.exit(1)
