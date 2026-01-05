# core/database.py
import pymysql
import pandas as pd
import asyncio
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager
from app.core.config import settings
import logging
from app.core.exceptions import DatabaseError
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

class DatabaseManager:
    """데이터베이스 연결 및 쿼리 관리 클래스"""

    def __init__(self):
        self.solar_config = settings.database_config
        self.weather_config = settings.database_config
        self._connection_pool = []
        self._pool_size = 5
        self._solar_engine = None
        self._weather_engine = None

    def _get_sqlalchemy_url(self, config: dict) -> str:
        """pymysql config를 SQLAlchemy URL로 변환"""
        user = config.get('user')
        password = config.get('password')
        host = config.get('host')
        port = config.get('port', 3306)
        database = config.get('database')
        charset = config.get('charset', 'utf8mb4')

        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset={charset}"

    def get_solar_engine(self):
        """태양광 데이터베이스 SQLAlchemy 엔진 생성"""
        if self._solar_engine is None:
            try:
                url = self._get_sqlalchemy_url(self.solar_config)
                self._solar_engine = create_engine(url, poolclass=NullPool)
            except Exception as e:
                logger.error(f"태양광 SQLAlchemy 엔진 생성 실패: {str(e)}")
                raise DatabaseError(f"태양광 SQLAlchemy 엔진 생성 실패: {str(e)}")
        return self._solar_engine

    def get_weather_engine(self):
        """기상 데이터베이스 SQLAlchemy 엔진 생성"""
        if self._weather_engine is None:
            try:
                url = self._get_sqlalchemy_url(self.weather_config)
                self._weather_engine = create_engine(url, poolclass=NullPool)
            except Exception as e:
                logger.error(f"기상 SQLAlchemy 엔진 생성 실패: {str(e)}")
                raise DatabaseError(f"기상 SQLAlchemy 엔진 생성 실패: {str(e)}")
        return self._weather_engine
    
    def get_solar_connection(self):
        """태양광 데이터베이스 연결 생성"""
        try:
            connection = pymysql.connect(**self.solar_config)
            return connection
        except Exception as e:
            logger.error(f"태양광 데이터베이스 연결 실패: {str(e)}")
            raise DatabaseError(f"태양광 데이터베이스 연결 실패: {str(e)}")

    def get_weather_connection(self):
        """기상 데이터베이스 연결 생성"""
        try:
            connection = pymysql.connect(**self.weather_config)
            return connection
        except Exception as e:
            logger.error(f"기상 데이터베이스 연결 실패: {str(e)}")
            raise DatabaseError(f"기상 데이터베이스 연결 실패: {str(e)}")
    
    @asynccontextmanager
    async def get_async_solar_connection(self):
        """비동기 태양광 데이터베이스 연결 컨텍스트 매니저"""
        connection = None
        try:
            loop = asyncio.get_event_loop()
            connection = await loop.run_in_executor(None, self.get_solar_connection)
            yield connection
        finally:
            if connection:
                connection.close()

    @asynccontextmanager
    async def get_async_weather_connection(self):
        """비동기 기상 데이터베이스 연결 컨텍스트 매니저"""
        connection = None
        try:
            loop = asyncio.get_event_loop()
            connection = await loop.run_in_executor(None, self.get_weather_connection)
            yield connection
        finally:
            if connection:
                connection.close()
    
    
    async def test_connections(self) -> Dict[str, bool]:
        """두 데이터베이스 연결 테스트"""
        results = {"solar": False, "weather": False}

        # 태양광 DB 테스트
        try:
            async with self.get_async_solar_connection() as connection:
                cursor = connection.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                cursor.close()
                results["solar"] = result[0] == 1
        except Exception as e:
            logger.error(f"태양광 데이터베이스 연결 테스트 실패: {str(e)}")

        # 기상 DB 테스트
        try:
            async with self.get_async_weather_connection() as connection:
                cursor = connection.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                cursor.close()
                results["weather"] = result[0] == 1
        except Exception as e:
            logger.error(f"기상 데이터베이스 연결 테스트 실패: {str(e)}")

        return results

class SolarDataRepository:
    """태양광 데이터 저장소 클래스"""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    async def fetch_solar_hour_data(self, target_date: str, days_back: int = 7) -> pd.DataFrame:
        """
        태양광 과거 데이터 조회 (target_date 포함 이전 168시간, 모든 ID)

        Args:
            target_date: 기준 시점 (YYYY-MM-DD HH:MM:SS)
            days_back: 사용하지 않음 (하위 호환성 유지)

        Returns:
            pd.DataFrame: 태양광 시간별 데이터 (모든 ID, 168시간 범위)
        """
        solar_table = settings.table_names.get('solar_data')
        query = f"""
        SELECT * FROM {solar_table}
        WHERE ymdhms >= DATE_SUB(%s, INTERVAL 167 HOUR)
        AND ymdhms <= %s
        ORDER BY ymdhms ASC, id ASC
        """

        try:
            engine = self.db.get_solar_engine()
            df = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: pd.read_sql(query, engine, params=(target_date, target_date))
            )

            # ymdhms를 datetime 타입으로 변환
            if not df.empty and 'ymdhms' in df.columns:
                try:
                    df['ymdhms'] = pd.to_datetime(df['ymdhms'])
                except Exception as _:
                    logger.warning("ymdhms 컬럼 datetime 변환 실패. 원본 타입 유지")

            logger.info(f"태양광 과거 데이터 조회 완료: {len(df)}건 (과거 168시간, 모든 ID)")

            if not df.empty:
                logger.info(f"📊 태양광 데이터 시간 범위: {df['ymdhms'].min()} ~ {df['ymdhms'].max()}")
                unique_ids = df['id'].unique() if 'id' in df.columns else []
                logger.info(f"📊 포함된 ID: {sorted(unique_ids)} (총 {len(unique_ids)}개)")
                unique_times = df['ymdhms'].nunique() if 'ymdhms' in df.columns else 0
                logger.info(f"📊 시간대 수: {unique_times}개")

            return df
        except Exception as e:
            logger.error(f"태양광 데이터 조회 실패: {str(e)}")
            raise DatabaseError(f"태양광 데이터 조회 실패: {str(e)}")

    async def fetch_weather_data(self, target_date: str) -> pd.DataFrame:
        """
        기상 데이터 조회 (target_date +1시간부터 24시간)

        Args:
            target_date: 예측 대상 날짜 (YYYY-MM-DD)

        Returns:
            pd.DataFrame: 기상 데이터 (+1시간부터 24시간)
        """
        weather_table = settings.table_names.get('weather_forecast', 'tb_weather_info')
        query = f"""
        SELECT
            *
        FROM {weather_table}
        WHERE tm BETWEEN CAST(DATE_ADD(%s, INTERVAL 1 HOUR) AS DATETIME)
                     AND CAST(DATE_ADD(%s, INTERVAL 24 HOUR) AS DATETIME)
        ORDER BY tm
        """

        try:
            engine = self.db.get_weather_engine()
            df = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: pd.read_sql(query, engine, params=(target_date, target_date))
            )
            # tm을 datetime으로 변환
            if not df.empty and 'tm' in df.columns:
                try:
                    df['tm'] = pd.to_datetime(df['tm'])
                except Exception as _:
                    logger.warning("tm 컬럼 datetime 변환 실패. 원본 타입 유지")
            logger.info(f"기상 데이터 조회 완료: {len(df)}건 ({target_date} +1시간~24시간)")

            if not df.empty:
                logger.info(f"   시간 범위: {df['tm'].min()} ~ {df['tm'].max()}")

            return df
        except Exception as e:
            logger.error(f"기상 데이터 조회 실패: {str(e)}")
            raise DatabaseError(f"기상 데이터 조회 실패: {str(e)}")

    async def fetch_ensemble_data(self, solar_start: str, solar_end: str,
                                   weather_start: str, weather_end: str) -> Dict[str, pd.DataFrame]:
        """
        앙상블 예측을 위한 데이터 조회 (병렬 처리)

        Args:
            solar_start: 태양광 데이터 시작 시각 (YYYY-MM-DD HH:MM:SS)
            solar_end: 태양광 데이터 종료 시각 (YYYY-MM-DD HH:MM:SS)
            weather_start: 기상 데이터 시작 시각 (YYYY-MM-DD HH:MM:SS)
            weather_end: 기상 데이터 종료 시각 (YYYY-MM-DD HH:MM:SS)
        """
        # 조회 범위 로깅
        logger.info(f"🔍 Solar SQL 조회 범위: {solar_start} ~ {solar_end}")
        logger.info(f"🔍 Weather SQL 조회 범위: {weather_start} ~ {weather_end}")

        # 병렬 조회 실행
        solar_task = asyncio.create_task(
            self._fetch_solar_data_range(solar_start, solar_end)
        )
        weather_task = asyncio.create_task(
            self._fetch_weather_data_range(weather_start, weather_end)
        )

        # 두 작업 동시 실행 및 대기
        solar_df, weather_df = await asyncio.gather(solar_task, weather_task)

        # Missing 시간 채우기
        solar_df = self._fill_missing_solar_hours(solar_df)

        return {
            'solar_df': solar_df,
            'weather_df': weather_df
        }

    async def _fetch_solar_data_range(self, solar_start: str, solar_end: str) -> pd.DataFrame:
        """태양광 데이터 조회 (내부 메서드)"""
        from datetime import datetime, timedelta

        # 테이블명 가져오기
        solar_table = settings.table_names.get('solar_data', 'tb_solar_hour')

        # 태양광 데이터 조회
        solar_query = f"""
        SELECT  *
        FROM {solar_table}
        WHERE ymdhms BETWEEN CAST(%s AS DATETIME)
                         AND CAST(%s AS DATETIME)
        ORDER BY ymdhms ASC, id ASC
        """

        try:
            solar_engine = self.db.get_solar_engine()
            solar_df = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: pd.read_sql(solar_query, solar_engine,
                                   params=(solar_start, solar_end))
            )

            # ymdhms를 datetime 타입으로 변환 (mixed format 지원)
            if not solar_df.empty and 'ymdhms' in solar_df.columns:
                try:
                    solar_df['ymdhms'] = pd.to_datetime(solar_df['ymdhms'], format='mixed')
                except Exception as _:
                    logger.warning("ymdhms 컬럼 datetime 변환 실패. 원본 타입 유지")

            logger.info(f"📊 앙상블용 태양광 데이터 조회: {len(solar_df)}건")
            if not solar_df.empty:
                logger.info(f"   시간 범위: {solar_df['ymdhms'].min()} ~ {solar_df['ymdhms'].max()}")
                logger.info(f"   🔍 Solar 데이터 NaN 체크: {solar_df.isnull().sum().sum()}개")
            else:
                logger.warning(f"   ⚠️ 태양광 데이터가 비어있습니다!")

            return solar_df

        except Exception as e:
            logger.error(f"태양광 데이터 조회 실패: {str(e)}")
            raise DatabaseError(f"태양광 데이터 조회 실패: {str(e)}")

    async def _fetch_weather_data_range(self, weather_start: str, weather_end: str) -> pd.DataFrame:
        """기상 데이터 조회 (내부 메서드)"""
        # 테이블명 가져오기
        weather_table = settings.table_names.get('weather_forecast', 'tb_weather_info')

        # 기상 데이터 조회
        weather_query = f"""
        SELECT
            *
        FROM {weather_table}
        WHERE tm BETWEEN CAST(%s AS DATETIME)
                     AND CAST(%s AS DATETIME)
        ORDER BY tm
        """

        # 예상 조회 범위 계산
        weather_start_dt = pd.to_datetime(weather_start)
        weather_end_dt = pd.to_datetime(weather_end)
        hours_diff = int((weather_end_dt - weather_start_dt).total_seconds() / 3600) + 1
        logger.info(f"🔍 예상 Weather 조회 범위: {weather_start_dt} ~ {weather_end_dt} (총 {hours_diff}개 시간대)")

        try:
            weather_engine = self.db.get_weather_engine()
            weather_df = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: pd.read_sql(weather_query, weather_engine,
                                   params=(weather_start, weather_end))
            )
            # tm을 datetime으로 변환
            if not weather_df.empty and 'tm' in weather_df.columns:
                try:
                    weather_df['tm'] = pd.to_datetime(weather_df['tm'], format='mixed')
                except Exception as _:
                    logger.warning("tm 컬럼 datetime 변환 실패. 원본 타입 유지")

            logger.info(f"📊 앙상블용 기상 데이터 조회: {len(weather_df)}건")

            if not weather_df.empty:
                logger.info(f"   🔍 Weather 데이터 NaN 체크: {weather_df.isnull().sum().sum()}개")
                logger.info(f"   시간 범위: {weather_df['tm'].min()} ~ {weather_df['tm'].max()}")
                logger.info(f"   📊 조회된 데이터 개수: {len(weather_df)}개 (기대: {hours_diff}개)")

                # 조회된 데이터의 시간 분포 확인
                logger.info(f"   📊 조회된 시간대 샘플 (처음 3개):")
                for i, tm in enumerate(weather_df['tm'].head(3)):
                    logger.info(f"      [{i}] {tm}")

                # 연속성 체크: 조회된 데이터가 기대한 범위를 포함하는지 확인
                try:
                    expected_hours = pd.date_range(start=weather_start_dt, end=weather_end_dt, freq='h')
                    actual_hours = pd.to_datetime(weather_df['tm'], format='mixed').dt.floor('h').drop_duplicates().sort_values()

                    if len(expected_hours) == len(actual_hours):
                        logger.info(f"   ✅ Weather 시간 연속성 OK: {len(actual_hours)}시간 (기대: {len(expected_hours)}시간)")
                    else:
                        logger.warning(f"   ⚠️ Weather 시간 데이터 부족: {len(actual_hours)}시간 (기대: {len(expected_hours)}시간)")
                except Exception as e:
                    logger.warning(f"   ⚠️ Weather 연속성 체크 실패: {str(e)}")
            else:
                logger.warning(f"   ⚠️ 기상 데이터가 비어있습니다!")

            return weather_df

        except Exception as e:
            logger.error(f"기상 데이터 조회 실패: {str(e)}")
            raise DatabaseError(f"기상 데이터 조회 실패: {str(e)}")

    def _fill_missing_solar_hours(self, solar_df: pd.DataFrame) -> pd.DataFrame:
        """
        Solar 데이터의 누락된 시간대를 0으로 채우는 로직

        Args:
            solar_df: 태양광 데이터프레임

        Returns:
            pd.DataFrame: 누락 시간이 채워진 데이터프레임
        """
        if solar_df.empty:
            return solar_df

        try:
            solar_df['_dt'] = pd.to_datetime(solar_df['ymdhms'], format='mixed')
            solar_df['_hour'] = solar_df['_dt'].dt.floor('h')

            # 전체 시간대 범위
            hours = solar_df['_hour'].drop_duplicates().sort_values()
            if len(hours) > 0:
                start_hour = hours.iloc[0]
                end_hour = hours.iloc[-1]
                expected = pd.date_range(start=start_hour, end=end_hour, freq='h')
                missing = expected.difference(hours)

                if len(missing) == 0:
                    logger.info(f"   ✅ Solar 시간 연속성 OK: {len(hours)}시간 연속")
                else:
                    logger.warning(f"   ⚠️ Solar 시간 누락 {len(missing)}개, 0으로 채우는 중...")

                    # 각 ID별로 missing 시간 채우기
                    if 'id' in solar_df.columns:
                        unique_ids = solar_df['id'].unique()
                        rows_to_add = []

                        for missing_time in missing:
                            for uid in unique_ids:
                                rows_to_add.append({
                                    'id': uid,
                                    'ymdhms': missing_time,
                                    '_dt': missing_time,
                                    '_hour': missing_time
                                })

                        if rows_to_add:
                            # 0으로 채울 컬럼들 (숫자형 컬럼)
                            numeric_cols = solar_df.select_dtypes(include=['number']).columns.tolist()
                            for row in rows_to_add:
                                for col in numeric_cols:
                                    if col not in ['id']:
                                        row[col] = 0

                            # 기존 컬럼들 추가
                            for col in solar_df.columns:
                                if col not in rows_to_add[0]:
                                    for row in rows_to_add:
                                        row[col] = None

                            # DataFrame에 추가
                            missing_df = pd.DataFrame(rows_to_add)
                            solar_df = pd.concat([solar_df, missing_df], ignore_index=True)
                            solar_df = solar_df.sort_values(['id', '_hour']).reset_index(drop=True)

                            logger.info(f"   ✅ {len(missing)}개 시간대 × {len(unique_ids)}개 ID = {len(rows_to_add)}개 행 추가 완료 (0으로 채움)")
                            logger.info(f"   최종 데이터: {len(solar_df)}건")

                # _hour 컬럼 삭제
                if '_hour' in solar_df.columns:
                    solar_df = solar_df.drop(columns=['_hour'])

        except Exception as e:
            logger.warning(f"   ⚠️ Solar 누락 시간 채우기 실패: {str(e)}")
        finally:
            if '_dt' in solar_df.columns:
                solar_df = solar_df.drop(columns=['_dt'])

        return solar_df


# 전역 데이터베이스 매니저 인스턴스
db_manager = DatabaseManager()
solar_repository = SolarDataRepository(db_manager)

async def init_db():
    """데이터베이스 초기화"""
    logger.info("데이터베이스 연결 테스트 중...")

    results = await db_manager.test_connections()

    if results["solar"] and results["weather"]:
        logger.info("✅ 모든 데이터베이스 연결 성공")
    elif results["solar"]:
        logger.warning("⚠️ 태양광 DB 연결 성공, 기상 DB 연결 실패")
    elif results["weather"]:
        logger.warning("⚠️ 기상 DB 연결 성공, 태양광 DB 연결 실패")
    else:
        logger.error("❌ 모든 데이터베이스 연결 실패")
        raise DatabaseError("데이터베이스 초기화 실패")

async def get_db_manager() -> DatabaseManager:
    """데이터베이스 매니저 의존성 주입"""
    return db_manager

async def get_solar_repository() -> SolarDataRepository:
    """태양광 데이터 저장소 의존성 주입"""
    return solar_repository