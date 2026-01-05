"""
ESS 충전량 데이터 집계 서비스
여러 테이블에서 데이터를 수집하여 tb_ai_ess_charge_amt 테이블에 적재
"""
import asyncio
import logging
import pymysql.cursors
from typing import Dict, Any, List
from app.core.config import settings

logger = logging.getLogger(__name__)

class ESSChargeService:
    """ESS 충전량 데이터 집계 및 적재 클래스"""

    def __init__(self, db_manager):
        """
        Args:
            db_manager: DatabaseManager 인스턴스
        """
        self.db = db_manager
        self.ai_solar_power_table = settings.table_names.get('ai_solar_power', 'tb_ai_solar_power')
        self.ai_pwr_usage_table = settings.table_names.get('ai_pwr_usage', 'tb_ai_pwr_usage')

        self.bms_daily_stat_table = settings.table_names.get('bms_daily_stat', 'tb_nrt_bms_daily_stat')
        self.ai_ess_charge_table = settings.table_names.get('ai_ess_charge_amt', 'tb_ai_ess_charge_amt')

    async def aggregate_and_insert(self, target_date: str) -> Dict[str, Any]:
        """
        여러 테이블의 데이터를 기반으로 ESS 충전량 데이터를 tb_ai_ess_charge_amt에 적재

        데이터 소스:
        1. ai_solar_power (ymdhms 기준) -> pre_pwr_generation, today_generation
        2. ai_pwr_usage (ymdhms 기준) -> pwr_usage, AccruepowGap, pwr_forecase -> pre_pwr_generation
        3. bms_daily_stat (V_TIME 기준) -> forecast_quantity, CHARGE_AMOUNT

        Args:
            target_date: 대상 날짜 (YYYY-MM-DD)

        Returns:
            Dict: 결과 정보 (success, inserted_count, target_date, message)
        """
        logger.info(f"📊 [ESS Charge] 데이터 집계 및 적재 시작 - {target_date}")

        try:
            logger.info(f"📅 [ESS Charge] 대상 날짜: {target_date}")

            # 1단계: ai_solar_power 데이터 UPSERT
            logger.info(f"🔄 [ESS Charge] Step 1: Solar Power 데이터 업데이트")
            solar_query = f"""
            INSERT INTO {self.ai_ess_charge_table}
                (ymdhms, pre_pwr_generation, today_generation)
            SELECT * FROM (
                SELECT
                    sp.ymdhms,
                    sp.pre_pwr_generation,
                    sp.today_generation
                FROM {self.ai_solar_power_table} sp
                WHERE DATE(sp.ymdhms) = %s
            ) AS new_data
            ON DUPLICATE KEY UPDATE
                pre_pwr_generation = new_data.pre_pwr_generation,
                today_generation = new_data.today_generation
            """

            # 2단계: ai_pwr_usage 데이터 UPSERT
            # pwr_usage, AccruepowGap만 처리 (pre_pwr_generation은 1단계에서 이미 처리됨)
            logger.info(f"🔄 [ESS Charge] Step 2: Power Usage 데이터 업데이트")
            usage_query = f"""
            INSERT INTO {self.ai_ess_charge_table}
                (ymdhms, pwr_usage, AccruepowGap)
            SELECT * FROM (
                SELECT
                    pu.ymdhms,
                    pu.pwr_usage,
                    pu.AccruepowGap
                FROM {self.ai_pwr_usage_table} pu
                WHERE DATE(pu.ymdhms) = %s
            ) AS new_data
            ON DUPLICATE KEY UPDATE
                pwr_usage = new_data.pwr_usage,
                AccruepowGap = new_data.AccruepowGap
            """

            # 3단계: bms_daily_stat 데이터 UPSERT
            logger.info(f"🔄 [ESS Charge] Step 3: BMS Daily Stat 데이터 업데이트")
            bms_query = f"""
            INSERT INTO {self.ai_ess_charge_table}
                (ymdhms, pre_charge, charge_amount)
            SELECT * FROM (
                SELECT
                    STR_TO_DATE(bms.V_TIME, '%%Y%%m%%d') as ymdhms,
                    bms.forecast_quantity as pre_charge,
                    bms.CHARGE_AMOUNT as charge_amount
                FROM {self.bms_daily_stat_table} bms
                WHERE DATE(STR_TO_DATE(bms.V_TIME, '%%Y%%m%%d')) = %s
            ) AS new_data
            ON DUPLICATE KEY UPDATE
                pre_charge = new_data.pre_charge,
                charge_amount = new_data.charge_amount
            """

            async with self.db.get_async_connection() as connection:
                def _execute():
                    cursor = connection.cursor()

                    try:
                        # Step 1: Solar Power
                        cursor.execute(solar_query, [target_date])
                        logger.info(f"  ✅ Solar Power UPSERT 완료")

                        # Step 2: Power Usage
                        cursor.execute(usage_query, [target_date])
                        logger.info(f"  ✅ Power Usage UPSERT 완료")

                        # Step 3: BMS Daily Stat
                        cursor.execute(bms_query, [target_date])
                        logger.info(f"  ✅ BMS Daily Stat UPSERT 완료")

                        connection.commit()
                        logger.info(f"✅ [ESS Charge] 모든 데이터 UPSERT 완료")
                        return True
                    finally:
                        cursor.close()

                await asyncio.get_event_loop().run_in_executor(None, _execute)

            logger.info(f"✅ [ESS Charge] 데이터 집계 및 적재 완료")

            return {
                "success": True,
                "target_date": target_date,
                "message": f"{target_date} 날짜의 ESS Charge 데이터 UPSERT 완료"
            }

        except Exception as e:
            logger.error(f"❌ [ESS Charge] 데이터 집계 및 적재 실패: {str(e)}")
            return {
                "success": False,
                "target_date": target_date,
                "message": f"ESS Charge 데이터 적재 중 오류 발생: {str(e)}"
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
            ymdhms, pre_pwr_generation, today_generation,
            pwr_usage, AccruepowGap,
            pre_charge, charge_amount
        FROM {self.ai_ess_charge_table}
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
                logger.info(f"📊 [ESS Charge] 최근 {len(results)}건의 데이터 조회 완료")
                return results

        except Exception as e:
            logger.error(f"❌ [ESS Charge] 데이터 조회 실패: {str(e)}")
            return []

# 전역 인스턴스
_ess_charge_service = None

async def get_ess_charge_service():
    """ESS Charge Service 의존성 주입"""
    global _ess_charge_service
    if _ess_charge_service is None:
        from app.core.database import db_manager
        _ess_charge_service = ESSChargeService(db_manager)
    return _ess_charge_service
