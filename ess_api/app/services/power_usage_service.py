"""
전력 사용량 데이터 집계 서비스
tb_ai_pwr_usage 테이블에 데이터 적재
"""
import asyncio
import logging
import pymysql.cursors
from typing import Dict, Any, List
from app.core.config import settings

logger = logging.getLogger(__name__)

class PowerUsageService:
    """전력 사용량 데이터 집계 및 적재 클래스"""

    def __init__(self, db_manager):
        """
        Args:
            db_manager: DatabaseManager 인스턴스
        """
        self.db = db_manager
        self.smarteye_day_table = settings.table_names.get('smarteye_day', 'tb_aggregate_smarteye_day')
        self.ai_pwr_usage_table = settings.table_names.get('ai_pwr_usage', 'tb_ai_pwr_usage')

    async def aggregate_and_insert(self, target_date: str) -> Dict[str, Any]:
        """
        tb_aggregate_smarteye_day의 데이터를 tb_ai_pwr_usage에 적재
        지정된 날짜(YYYY-MM-DD) 하루분의 데이터만 처리

        매핑:
        - use_time → ymdhms
        - pwr_kepco_usage_tot → pwr_usage
        - forecast_quantity → pwr_forecase

        Args:
            target_date: 대상 날짜 (YYYY-MM-DD)

        Returns:
            Dict: 결과 정보 (success, inserted_count, target_date, message)
        """
        logger.info(f"📊 [Power Usage] 데이터 집계 및 적재 시작 - {target_date}")

        try:
            # 날짜 범위 계산 (인덱스 활용을 위해 범위 조건 사용)
            params = [target_date, target_date]

            logger.info(f"📅 [Power Usage] 대상 날짜: {target_date}")

            # 먼저 소스 데이터가 있는지 확인 (인덱스 활용)
            check_query = f"""
            SELECT COUNT(*) as cnt,
                   MIN(use_time) as min_time,
                   MAX(use_time) as max_time
            FROM {self.smarteye_day_table}
            WHERE use_time >= %s AND use_time < DATE_ADD(%s, INTERVAL 1 DAY)
            """

            async with self.db.get_async_connection() as connection:
                def _check():
                    cursor = connection.cursor(pymysql.cursors.DictCursor)
                    try:
                        cursor.execute(check_query, params)
                        result = cursor.fetchone()
                        return result
                    finally:
                        cursor.close()

                check_result = await asyncio.get_event_loop().run_in_executor(None, _check)
                logger.info(f"🔍 [Power Usage] 소스 데이터 확인 - 건수: {check_result['cnt']}, "
                           f"최소시간: {check_result['min_time']}, 최대시간: {check_result['max_time']}")

                if check_result['cnt'] == 0:
                    logger.warning(f"⚠️ [Power Usage] {target_date}에 해당하는 소스 데이터가 없습니다.")

            # INSERT ON DUPLICATE KEY UPDATE를 사용하여 UPSERT 구현
            # ymdhms가 이미 존재하면 pwr_usage, pwr_forecase만 업데이트 (다른 컬럼 보존)
            # ymdhms가 없으면 새로운 행 INSERT
            # 인덱스 활용을 위해 DATE() 함수 대신 범위 조건 사용
            query = f"""
            INSERT INTO {self.ai_pwr_usage_table}
                (ymdhms, pwr_usage, pwr_forecase)
            SELECT * FROM (
                SELECT
                    use_time as ymdhms,
                    pwr_kepco_usage_tot as pwr_usage,
                    forecast_quantity as pwr_forecase
                FROM {self.smarteye_day_table}
                WHERE use_time >= %s AND use_time < DATE_ADD(%s, INTERVAL 1 DAY)
            ) AS new_data
            ON DUPLICATE KEY UPDATE
                pwr_usage = new_data.pwr_usage,
                pwr_forecase = new_data.pwr_forecase
            """

            logger.info(f"🔍 [Power Usage] 파라미터: {params}")

            async with self.db.get_async_connection() as connection:
                def _execute():
                    cursor = connection.cursor()
                    try:
                        cursor.execute(query, params)
                        connection.commit()
                        logger.info(f"✅ [Power Usage] UPSERT 실행 완료")
                        return True
                    finally:
                        cursor.close()

                await asyncio.get_event_loop().run_in_executor(None, _execute)

            logger.info(f"✅ [Power Usage] 데이터 집계 및 적재 완료 (소스: {check_result['cnt']}건)")

            return {
                "success": True,
                "source_count": check_result['cnt'],
                "target_date": target_date,
                "message": f"{target_date} 날짜의 Power Usage 데이터 UPSERT 완료 (소스: {check_result['cnt']}건)"
            }

        except Exception as e:
            logger.error(f"❌ [Power Usage] 데이터 집계 및 적재 실패: {str(e)}")
            return {
                "success": False,
                "target_date": target_date,
                "message": f"Power Usage 데이터 적재 중 오류 발생: {str(e)}"
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
            ymdhms, pwr_usage, pwr_forecase
        FROM {self.ai_pwr_usage_table}
        ORDER BY ymdhms DESC
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
                logger.info(f"📊 [Power Usage] 최근 {len(results)}건의 데이터 조회 완료")
                return results

        except Exception as e:
            logger.error(f"❌ [Power Usage] 데이터 조회 실패: {str(e)}")
            return []

# 전역 인스턴스
_power_usage_service = None

async def get_power_usage_service():
    """Power Usage Service 의존성 주입"""
    global _power_usage_service
    if _power_usage_service is None:
        from app.core.database import db_manager
        _power_usage_service = PowerUsageService(db_manager)
    return _power_usage_service
