# core/db_saver.py
"""
예측 결과를 데이터베이스에 저장하는 모듈
"""
import pandas as pd
import asyncio
import logging
from typing import Dict, Any, List
from datetime import datetime

from app.core.config import settings
from app.core.exceptions import DatabaseError

logger = logging.getLogger(__name__)


class ResultSaver:
    """예측 결과 저장 클래스"""

    def __init__(self, db_manager):
        """
        Args:
            db_manager: DatabaseManager 인스턴스
        """
        self.db = db_manager
        self.table_name = settings.table_names.get('solar_data', 'tb_solar_hour')
        # config에서 공장별 ID 매핑 가져오기
        self.factory_id_mapping = settings.factory_id_mapping

    def _get_id_mapping(self) -> Dict[str, int]:
        """
        공장명 -> ID 매핑 딕셔너리 반환
        'FactoryA'와 'A' 형식 모두 지원

        Returns:
            {'FactoryA': 1, 'A': 1, 'FactoryB': 13, 'B': 13, ...}
        """
        id_mapping = {}
        for factory_name, ids in self.factory_id_mapping.items():
            if ids:
                id_mapping[factory_name] = ids[0]  # 'FactoryA' -> 1
                # 단축 형식도 매핑 ('A' -> 1)
                short_name = factory_name.replace('Factory', '')
                id_mapping[short_name] = ids[0]
        return id_mapping

    async def save_predictions_hour_db(self, predictions_dict: Dict[str, Any]) -> Dict[str, int]:
        """
        공장별 시간별 예측 결과를 tb_solar_hour에 저장 (UPSERT)
        - 각 공장의 대표 ID 1개에 24시간 예측값 저장
        - ID 매핑: FactoryA->1, FactoryB->13, FactoryC->16
        - reg_dt: 예측 실행 시간 (현재 시각)

        Returns:
            {'FactoryA': 24, 'FactoryB': 24, 'FactoryC': 24}
        """
        logger.info("💾 시간별 예측 결과 저장 시작...")

        # 테이블명
        table_hour = self.table_name
        logger.info(f"📊 저장 테이블: {table_hour}")

        # ID 매핑 가져오기
        id_mapping = self._get_id_mapping()
        logger.info(f"📊 ID 매핑: {id_mapping}")

        # 현재 시간을 reg_dt로 설정 (예측 실행 시간)
        reg_dt = datetime.now()
        logger.info(f"📊 등록 시간 (reg_dt): {reg_dt}")

        result_counts = {}

        for factory_name, prediction_data in predictions_dict.items():
            try:

                # ID 매핑 확인 ('A' 또는 'FactoryA' 모두 지원)
                target_id = id_mapping.get(factory_name)
                if not target_id:
                    logger.warning(f"⚠️ {factory_name}은 ID 매핑에 없습니다. 건너뜁니다.")
                    continue

                # 예측값과 타임스탬프 추출
                timestamps = prediction_data.get('timestamps') or prediction_data.get('ensemble_timestamps') or []
                predictions = prediction_data.get('predictions') or prediction_data.get('ensemble_predictions') or []

                if not timestamps or not predictions:
                    logger.warning(f"⚠️ {factory_name}의 예측 데이터가 비어있습니다.")
                    continue

                logger.info(f"📊 {factory_name} 데이터: 시간 {len(timestamps)}개, 예측값 {len(predictions)}개")

                # 레코드 생성 (tz-naive datetime으로 통일)
                records = []
                for ts, pred in zip(timestamps, predictions):
                    # utc=False로 naive datetime 보장
                    ts_parsed = pd.to_datetime(ts, errors="coerce", utc=False)
                    # Timestamp인 경우 tz 제거
                    if isinstance(ts_parsed, pd.Timestamp) and ts_parsed.tz is not None:
                        ts_parsed = ts_parsed.tz_localize(None)

                    # YEAR 필드 추출
                    year = ts_parsed.year if hasattr(ts_parsed, 'year') else None

                    records.append({
                        'id': target_id,
                        'ymdhms': ts_parsed,
                        'YEAR': year,
                        'forecast_quantity': round(float(pred), 5),
                        'reg_dt': reg_dt
                    })

                if not records:
                    logger.warning(f"⚠️ {factory_name}: 저장할 유효 레코드가 없습니다.")
                    continue

                logger.info(f"📊 레코드 생성 완료: {len(records)}건 (ID={target_id})")

                # 데이터베이스에 UPSERT
                saved_count = await self._upsert(table_hour, records)
                result_counts[factory_name] = saved_count

                logger.info(f"✅ {factory_name}: {saved_count}건 UPSERT 완료 (ID={target_id})")

            except Exception as e:
                logger.error(f"❌ {factory_name} 시간별 저장 실패: {str(e)}")
                result_counts[factory_name] = 0

        total_saved = sum(result_counts.values())
        logger.info(f"📊 시간별 전체 저장 완료: {total_saved}건 (공장별: {result_counts})")
        return result_counts


    # --- _upsert 내 동기 드라이버만 쓰는 버전 (추천) ---
    async def _upsert(self, table_name: str, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0

        # YEAR 필드 존재 여부 확인
        has_year_field = 'YEAR' in records[0]
        has_reg_dt_field = 'reg_dt' in records[0]

        if has_year_field and has_reg_dt_field:
            upsert_query = f"""
            INSERT INTO {table_name} (id, ymdhms, YEAR, forecast_quantity, reg_dt)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE forecast_quantity = VALUES(forecast_quantity), reg_dt = VALUES(reg_dt)
            """
        elif has_year_field:
            upsert_query = f"""
            INSERT INTO {table_name} (id, ymdhms, YEAR, forecast_quantity)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE forecast_quantity = VALUES(forecast_quantity)
            """
        elif has_reg_dt_field:
            upsert_query = f"""
            INSERT INTO {table_name} (id, ymdhms, forecast_quantity, reg_dt)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE forecast_quantity = VALUES(forecast_quantity), reg_dt = VALUES(reg_dt)
            """
        else:
            upsert_query = f"""
            INSERT INTO {table_name} (id, ymdhms, forecast_quantity)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE forecast_quantity = VALUES(forecast_quantity)
            """

        async with self.db.get_async_solar_connection() as connection:
            try:
                def _do_all():
                    cursor = connection.cursor()
                    try:
                        values = []
                        for r in records:
                            ts = r['ymdhms']
                            # datetime/Timestamp 객체를 문자열로 변환
                            ymdhms_str = ts.strftime('%Y-%m-%d %H:%M:%S') if hasattr(ts, 'strftime') else str(ts)

                            # reg_dt 처리 (datetime을 문자열로 변환)
                            reg_dt_value = r.get('reg_dt')
                            reg_dt_str = reg_dt_value.strftime('%Y-%m-%d %H:%M:%S') if hasattr(reg_dt_value, 'strftime') else str(reg_dt_value)

                            if has_year_field and has_reg_dt_field:
                                values.append((r['id'], ymdhms_str, r['YEAR'], r['forecast_quantity'], reg_dt_str))
                            elif has_year_field:
                                values.append((r['id'], ymdhms_str, r['YEAR'], r['forecast_quantity']))
                            elif has_reg_dt_field:
                                values.append((r['id'], ymdhms_str, r['forecast_quantity'], reg_dt_str))
                            else:
                                values.append((r['id'], ymdhms_str, r['forecast_quantity']))

                        cursor.executemany(upsert_query, values)
                        connection.commit()  # 커밋은 반드시 같은 스레드에서

                        return len(values)
                    finally:
                        cursor.close()

                # 모든 DB 호출을 '한 번의' executor에서 처리
                return await asyncio.get_event_loop().run_in_executor(None, _do_all)

            except Exception as e:
                logger.error(f"❌ 데이터베이스 저장 오류: {e}")
                # 롤백도 같은 executor에서
                try:
                    await asyncio.get_event_loop().run_in_executor(None, connection.rollback)
                except Exception as rollback_error:
                    logger.warning(f"⚠️ 롤백 실패 (무시됨): {rollback_error}")
                raise DatabaseError(f"예측 결과 저장 실패: {e}")

    async def verify_saved_predictions(
        self,
        factory_name: str,
        start_time: str,
        end_time: str) -> pd.DataFrame:
        """
        저장된 예측 결과 확인

        Args:
            factory_name: 공장명
            start_time: 시작 시간
            end_time: 종료 시간

        Returns:
            pd.DataFrame: 저장된 예측 데이터
        """
        factory_ids = self.factory_id_mapping.get(factory_name)
        if not factory_ids:
            raise ValueError(f"잘못된 공장명: {factory_name}")

        # SQL Injection 방지: 파라미터 바인딩 사용
        placeholders = ','.join(['%s'] * len(factory_ids))
        query = f"""
        SELECT id, ymdhms, forecast_quantity
        FROM {self.table_name}
        WHERE id IN ({placeholders})
          AND ymdhms BETWEEN %s AND %s
        ORDER BY ymdhms, id
        """

        params = list(factory_ids) + [start_time, end_time]

        async with self.db.get_async_solar_connection() as connection:
            try:
                df = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: pd.read_sql(query, connection, params=params)
                )
                return df
            except Exception as e:
                logger.error(f"예측 결과 조회 실패: {str(e)}")
                raise DatabaseError(f"예측 결과 조회 실패: {str(e)}")
    
    async def save_predictions_day_db(self, result_predict: Dict[str, Any]) -> Dict[str, float]:
        """
        'Factory_Total'의 24시간 예측 합계를 tb_solar_day에 저장(UPSERT).
        - 기준 ymdhms: target_date + 1일 (자정 00:00:00)
        - 저장 대상: 'Factory_Total' 결과만 저장
        - ID 매핑: Factory_Total -> 설정된 ID
        - reg_dt: 예측 실행 시간 (현재 시각)
        - UNIQUE KEY (id, ymdhms) 필요

        Returns:
            {'Factory_Total': total}
        """
        logger.info("📊 일간 합계 저장 시작 (Factory_Total만 저장)...")

        # 테이블명
        table_day = settings.table_names.get('solar_day', 'tb_solar_day')
        logger.info(f"📊 저장 테이블: {table_day}")

        # target_date + 1 → 자정(naive)
        tgt = pd.to_datetime(result_predict["target_date"], errors="coerce")
        if tgt is pd.NaT:
            raise ValueError("result_predict['target_date'] 파싱 실패")
        ymdhms = (tgt + pd.Timedelta(days=1)).normalize()  # YYYY-MM-DD 00:00:00
        logger.info(f"📊 기준 날짜: {ymdhms}")

        # 현재 시간을 reg_dt로 설정 (예측 실행 시간)
        reg_dt = datetime.now()
        logger.info(f"📊 등록 시간 (reg_dt): {reg_dt}")

        # Factory_Total 결과 추출 ('Total' 키로 저장됨)
        results = result_predict.get("results", {})
        factory_total_data = results.get("Total")

        if not factory_total_data:
            logger.warning("⚠️ Factory_Total 예측 데이터가 없습니다.")
            return {}

        # Factory_Total의 예측값 추출
        preds = factory_total_data.get("predictions", []) or factory_total_data.get("ensemble_predictions", [])
        if not preds:
            logger.warning("⚠️ Factory_Total의 예측값이 비어있습니다.")
            return {}

        # Factory_Total 합계 계산
        total = float(pd.Series(preds, dtype="float64").sum())
        total = round(total, 5)
        logger.info(f"📊 Factory_Total 합계: {total}")

        # Factory_Total ID (config.py에서 설정, 없으면 기본값 0)
        factory_total_id_list = settings.factory_id_mapping.get('Factory_Total', [0])
        target_id = factory_total_id_list[0] if factory_total_id_list else 0

        # YEAR 필드 추출
        year = ymdhms.year if hasattr(ymdhms, 'year') else None

        # 업서트용 레코드 생성
        records: List[Dict[str, Any]] = [{
            'id': target_id,
            'ymdhms': ymdhms,
            'YEAR': year,
            'forecast_quantity': total,
            'reg_dt': reg_dt
        }]
        logger.info(f"📊 레코드 생성: ID={target_id}, ymdhms={ymdhms}, YEAR={year}, forecast_quantity={total}, reg_dt={reg_dt}")

        # _upsert 헬퍼 함수 사용
        saved_count = await self._upsert(table_day, records)
        logger.info(f"✅ Factory_Total 일간 합계 저장 완료: {saved_count}건 @ {ymdhms} | reg_dt: {reg_dt}")

        return {"Factory_Total": total}

# 전역 인스턴스 (database.py의 db_manager 사용)
_db_saver = None


async def get_db_saver():
    """DB Saver 의존성 주입"""
    global _db_saver
    if _db_saver is None:
        from app.core.database import db_manager
        _db_saver = ResultSaver(db_manager)
    return _db_saver
