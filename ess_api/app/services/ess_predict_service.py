"""
ESS 예측 데이터 집계 서비스
tb_ai_pwr_usage 테이블에 ESS 예측값 적재
"""
import asyncio
import logging
import pymysql.cursors
from typing import Dict, Any, List
from app.core.config import settings

logger = logging.getLogger(__name__)

class ESSPredictService:
    """ESS 예측 데이터 집계 및 적재 클래스"""

    def __init__(self, db_manager):
        """
        Args:
            db_manager: DatabaseManager 인스턴스
        """
        self.db = db_manager
        self.solar_day_table = settings.table_names.get('solar_day', 'tb_solar_day')
        self.smarteye_day_table = settings.table_names.get('smarteye_day', 'tb_aggregate_smarteye_day')
        self.ess_day_table = settings.table_names.get('bms_daily_stat', 'tb_nrt_bms_daily_stat')

    async def aggregate_and_insert(self, target_date: str) -> Dict[str, Any]:
        """
        solar_day와 smarteye_day의 데이터를 기반으로 ESS 예측값을 계산하여 ess_day_table에 적재

        처리 흐름:
        1. target_date (예: '2025-09-20')로 solar_day의 ymdhms, smarteye_day의 use_time 필터링
        2. solar_day의 forecast_quantity는 SUM으로 집계 (여러 시간대 데이터)
        3. smarteye_day의 forecast_quantity는 단일 값 사용 (이미 1건)
        4. 집계된 값으로 pwr_ess 계산
        5. target_date를 '20250920' 형식으로 변환
        6. ess_day_table의 V_TIME과 매칭하여 forecast_quantity에 pwr_ess를 UPSERT

        계산 로직:
        - SUM(solar_day.forecast_quantity) + 3120 < smarteye_day.forecast_quantity인 경우:
          pwr_ess = 3120
        - 그렇지 않은 경우:
          pwr_ess = smarteye_day.forecast_quantity - SUM(solar_day.forecast_quantity)

        Args:
            target_date: 대상 날짜 (YYYY-MM-DD)

        Returns:
            Dict: 결과 정보 (success, inserted_count, target_date, message)
        """
        logger.info(f"📊 [ESS Predict] 데이터 집계 및 적재 시작 - {target_date}")

        try:
            logger.info(f"📅 [ESS Predict] 대상 날짜: {target_date}")

            # 날짜 범위 계산 (YYYY-MM-DD 00:00:00 ~ YYYY-MM-DD 23:59:59)
            start_datetime = f"{target_date} 00:00:00"
            end_datetime = f"{target_date} 23:59:59"

            # 먼저 매칭되는 데이터를 조회하여 로그 출력
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
            FROM {self.solar_day_table} sd
            INNER JOIN {self.smarteye_day_table} se
                ON DATE(sd.ymdhms) = DATE(se.use_time)
            WHERE sd.ymdhms >= %s AND sd.ymdhms <= %s
              AND se.use_time >= %s AND se.use_time <= %s
            """

            async with self.db.get_async_connection() as connection:
                def _select():
                    cursor = connection.cursor(pymysql.cursors.DictCursor)
                    try:
                        cursor.execute(select_query, [start_datetime, end_datetime, start_datetime, end_datetime])
                        result = cursor.fetchone()
                        return result
                    finally:
                        cursor.close()

                matched_data = await asyncio.get_event_loop().run_in_executor(None, _select)

            if matched_data and matched_data['match_count'] > 0:
                logger.info(f"🔍 [ESS Predict] 매칭된 원본 데이터 건수: {matched_data['match_count']}건")
                logger.info(f"📊 [ESS Predict] 집계 결과 - "
                           f"태양광 예측 합계(SUM): {matched_data['solar_forecast_sum']}, "
                           f"전력 사용 예측: {matched_data['smarteye_forecast']}, "
                           f"계산된 pwr_ess: {matched_data['pwr_ess']}")
            else:
                logger.warning(f"⚠️ [ESS Predict] {target_date}에 매칭되는 데이터가 없습니다.")

            # V_TIME 변환 (YYYY-MM-DD → YYYYMMDD)
            v_time_converted = target_date.replace('-', '')
            logger.info(f"🔍 [ESS Predict] 변환된 V_TIME: {v_time_converted}")

            # INSERT ON DUPLICATE KEY UPDATE를 사용하여 UPSERT 구현
            # V_TIME을 매칭 키로 사용하여 중복 시 forecast_quantity 필드만 업데이트 (다른 필드는 유지)
            # V_TIME은 VARCHAR 타입으로 '20241130' 형식
            # V_SITE_ID는 기본값 'SITE001' 사용 (기존 데이터 확인 필요)
            # 태양광은 SUM으로 집계, 전력 사용은 MAX(1건이므로 SUM 불필요)
            insert_query = f"""
            INSERT INTO {self.ess_day_table}
                (V_SITE_ID, V_TIME, V_DEVICE_ID, forecast_quantity)
            SELECT * FROM (
                SELECT
                    '3024200001' as V_SITE_ID,
                    %s as V_TIME,
                    '2000001' as V_DEVICE_ID,
                    CASE
                        WHEN (SUM(sd.forecast_quantity) + 3120) < MAX(se.forecast_quantity)
                        THEN 3120
                        ELSE GREATEST(0, MAX(se.forecast_quantity) - SUM(sd.forecast_quantity))
                    END as forecast_quantity
                FROM {self.solar_day_table} sd
                INNER JOIN {self.smarteye_day_table} se
                    ON DATE(sd.ymdhms) = DATE(se.use_time)
                WHERE sd.ymdhms >= %s AND sd.ymdhms <= %s
                  AND se.use_time >= %s AND se.use_time <= %s
            ) AS new_data
            ON DUPLICATE KEY UPDATE
                forecast_quantity = VALUES(forecast_quantity)
            """

            params = [v_time_converted, start_datetime, end_datetime, start_datetime, end_datetime]

            async with self.db.get_async_connection() as connection:
                def _execute():
                    cursor = connection.cursor()
                    try:
                        logger.info(f"🔍 [ESS Predict] 실행 쿼리 파라미터: {params}")
                        cursor.execute(insert_query, params)
                        connection.commit()

                        # 적재 확인 쿼리
                        cursor.execute(f"SELECT V_TIME, forecast_quantity FROM {self.ess_day_table} WHERE V_TIME = %s", [v_time_converted])
                        result = cursor.fetchone()
                        if result:
                            logger.info(f"🔍 [ESS Predict] 적재 확인 - V_TIME: {result[0]}, forecast_quantity: {result[1]}")
                        else:
                            logger.warning(f"⚠️ [ESS Predict] V_TIME '{v_time_converted}' 행이 테이블에 없습니다")

                        return True
                    except Exception as e:
                        logger.error(f"❌ [ESS Predict] 쿼리 실행 오류: {str(e)}")
                        raise
                    finally:
                        cursor.close()

                await asyncio.get_event_loop().run_in_executor(None, _execute)

            logger.info(f"✅ [ESS Predict] 데이터 집계 및 적재 완료")

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

    async def verify_data(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        적재된 데이터 확인

        Args:
            limit: 조회할 레코드 수

        Returns:
            List[Dict]: 적재된 데이터 리스트
        """
        query = f"""
        SELECT
            V_TIME, forecast_quantity
        FROM {self.ess_day_table}
        WHERE forecast_quantity IS NOT NULL
        ORDER BY V_TIME DESC
        LIMIT %s
        """

        try:
            async with self.db.get_async_connection() as connection:
                def _fetch():
                    cursor = connection.cursor(pymysql.cursors.DictCursor)
                    try:
                        cursor.execute(query, (limit,))
                        results = cursor.fetchall()
                        return results
                    finally:
                        cursor.close()

                results = await asyncio.get_event_loop().run_in_executor(None, _fetch)
                logger.info(f"📊 [ESS Predict] 최근 {len(results)}건의 데이터 조회 완료")
                return results

        except Exception as e:
            logger.error(f"❌ [ESS Predict] 데이터 조회 실패: {str(e)}")
            return []

# 전역 인스턴스
_ess_predict_service = None

async def get_ess_predict_service():
    """ESS Predict Service 의존성 주입"""
    global _ess_predict_service
    if _ess_predict_service is None:
        from app.core.database import db_manager
        _ess_predict_service = ESSPredictService(db_manager)
    return _ess_predict_service
