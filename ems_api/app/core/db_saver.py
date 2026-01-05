import pandas as pd
import logging
from typing import Optional
from sqlalchemy import text
from datetime import datetime
from zoneinfo import ZoneInfo
from app.utils.config import config
from app.core.db import DatabaseManager

logger = logging.getLogger(__name__)


class ForecastSaver:
    """예측 결과를 DB에 저장하는 클래스"""

    def __init__(self):
        """설정에서 DB 정보 로드"""
        self.db_config = config.database_config
        self.table_names = config.table_names
        self.db_manager = DatabaseManager()

    def get_connection(self):
        """SQLAlchemy 엔진 가져오기"""
        try:
            return self.db_manager.get_connection()
        except Exception as e:
            logger.error(f"데이터베이스 연결 가져오기 실패: {e}")
            raise

    def save_hourly_forecast(self, predictions_df: pd.DataFrame) -> int:
        """
        1시간 단위 예측 결과를 tb_smart_eye_hour 테이블에 저장
        use_time이 이미 존재하면 forecast_quantity를 업데이트하고, 없으면 새로 삽입

        Args:
            predictions_df: 예측 결과 DataFrame (컬럼: ymdhms, 사용량(kWh))

        Returns:
            int: 처리된 레코드 수 (삽입 + 업데이트)
        """
        try:
            table_name = self.table_names['tb_smart_eye_hour']
            engine = self.get_connection()

            affected_count = 0
            insert_count = 0
            update_count = 0

            # 현재 시간 (KST) - reg_dt용
            kst = ZoneInfo("Asia/Seoul")
            reg_dt = datetime.now(kst)

            # 저장 기간 정보
            date_range = f"{predictions_df['ymdhms'].min()} ~ {predictions_df['ymdhms'].max()}"

            with engine.connect() as connection:
                for _, row in predictions_df.iterrows():
                    use_time = row['ymdhms']
                    forecast_quantity = float(row['사용량(kWh)'])

                    upsert_query = f"""
                        INSERT INTO {table_name} (use_time, forecast_quantity, reg_dt)
                        VALUES (:use_time, :forecast_quantity, :reg_dt)
                        ON DUPLICATE KEY UPDATE
                            forecast_quantity = :forecast_quantity,
                            reg_dt = :reg_dt
                    """

                    result = connection.execute(
                        text(upsert_query),
                        {
                            "use_time": use_time,
                            "forecast_quantity": forecast_quantity,
                            "reg_dt": reg_dt
                        }
                    )

                    rowcount = result.rowcount
                    affected_count += rowcount
                    if rowcount == 1:
                        insert_count += 1
                    elif rowcount == 2:
                        update_count += 1

                connection.commit()
                logger.info(f"[DB 저장 - 시간별] {table_name}: INSERT={insert_count}, UPDATE={update_count} | 기간: {date_range} | reg_dt: {reg_dt}")

            return affected_count

        except Exception as e:
            logger.error(f"[DB 저장 - 시간별] 실패: {e}", exc_info=True)
            raise

    def save_daily_forecast(self, predictions_df: pd.DataFrame) -> int:
        """
        1일 단위 예측 결과를 tb_smart_eye_day 테이블에 저장
        use_time이 이미 존재하면 forecast_quantity를 업데이트하고, 없으면 새로 삽입

        Args:
            predictions_df: 예측 결과 DataFrame (컬럼: ymdhms, 사용량(kWh))

        Returns:
            int: 처리된 레코드 수 (삽입 + 업데이트)
        """
        try:
            table_name = self.table_names['tb_smart_eye_day']
            engine = self.get_connection()

            affected_count = 0
            insert_count = 0
            update_count = 0

            # 현재 시간 (KST) - reg_dt용
            kst = ZoneInfo("Asia/Seoul")
            reg_dt = datetime.now(kst)

            # 저장 기간 정보
            date_range = f"{predictions_df['ymdhms'].min()} ~ {predictions_df['ymdhms'].max()}"

            with engine.connect() as connection:
                for _, row in predictions_df.iterrows():
                    use_time = row['ymdhms']
                    forecast_quantity = float(row['사용량(kWh)'])

                    upsert_query = f"""
                        INSERT INTO {table_name} (use_time, forecast_quantity, reg_dt)
                        VALUES (:use_time, :forecast_quantity, :reg_dt)
                        ON DUPLICATE KEY UPDATE
                            forecast_quantity = :forecast_quantity,
                            reg_dt = :reg_dt
                    """

                    result = connection.execute(
                        text(upsert_query),
                        {
                            "use_time": use_time,
                            "forecast_quantity": forecast_quantity,
                            "reg_dt": reg_dt
                        }
                    )

                    rowcount = result.rowcount
                    affected_count += rowcount
                    if rowcount == 1:
                        insert_count += 1
                    elif rowcount == 2:
                        update_count += 1

                connection.commit()
                logger.info(f"[DB 저장 - 일별] {table_name}: INSERT={insert_count}, UPDATE={update_count} | 기간: {date_range} | reg_dt: {reg_dt}")

            return affected_count

        except Exception as e:
            logger.error(f"[DB 저장 - 일별] 실패: {e}", exc_info=True)
            raise

    def save_forecast(self, predictions_df: pd.DataFrame, aggregation: str) -> int:
        """
        예측 결과를 집계 수준에 맞는 테이블에 저장

        Args:
            predictions_df: 예측 결과 DataFrame (컬럼: ymdhms, 사용량(kWh))
            aggregation: 집계 방식 ('hourly', 'daily')

        Returns:
            int: 업데이트된 레코드 수
        """
        try:
            if aggregation == 'hourly':
                return self.save_hourly_forecast(predictions_df)
            elif aggregation == 'daily':
                return self.save_daily_forecast(predictions_df)
            else:
                logger.warning(f"집계 수준에 대한 DB 저장 작업 없음: {aggregation}")
                return 0

        except Exception as e:
            logger.error(f"예측 결과 저장 실패: {e}")
            raise

    def check_existing_records(self, time_values: list, aggregation: str) -> dict:
        """
        주어진 시간 값들에 대해 DB에 레코드가 존재하는지 확인

        Args:
            time_values: 확인할 시간 값 리스트
            aggregation: 집계 방식 ('hourly', 'daily')

        Returns:
            dict: {time: exists(bool)} 형태
        """
        try:
            if aggregation == 'hourly':
                table_name = self.table_names['tb_smart_eye_hour']
            elif aggregation == 'daily':
                table_name = self.table_names['tb_smart_eye_day']
            else:
                return {}

            engine = self.get_connection()
            existing_records = {}

            with engine.connect() as connection:
                for time_val in time_values:
                    query = f"""
                        SELECT COUNT(*) as cnt
                        FROM {table_name}
                        WHERE use_time = :use_time
                    """
                    result = connection.execute(text(query), {"use_time": time_val})
                    row = result.fetchone()
                    existing_records[time_val] = row[0] > 0

            return existing_records

        except Exception as e:
            logger.error(f"기존 레코드 확인 실패: {e}")
            raise
