import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from app.utils.config import config
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    """데이터베이스 연결 및 쿼리 관리 클래스"""

    def __init__(self):
        self.db_config = config.database_config
        self.table_names = config.table_names
        self._pool_size = 5
        self._engine = None

    def _get_sqlalchemy_url(self, config_dict: dict) -> str:
        """pymysql config를 SQLAlchemy URL로 변환"""
        user = config_dict.get('user')
        password = config_dict.get('password')
        host = config_dict.get('host')
        port = config_dict.get('port', 3306)
        database = config_dict.get('database')
        charset = config_dict.get('charset', 'utf8mb4')

        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset={charset}"

    def get_connection(self):
        """MariaDB 연결 생성 (SQLAlchemy Engine)"""
        try:
            if self._engine is None:
                logger.info(f"[DB 연결] 데이터베이스 연결 시도 중...")
                logger.info(f"[DB 연결] Host: {self.db_config['host']}")
                logger.info(f"[DB 연결] Port: {self.db_config['port']}")
                logger.info(f"[DB 연결] User: {self.db_config['user']}")
                logger.info(f"[DB 연결] Database: {self.db_config['database']}")

                url = self._get_sqlalchemy_url(self.db_config)
                self._engine = create_engine(
                    url,
                    pool_size=self._pool_size,
                    pool_pre_ping=True,
                    pool_recycle=3600
                )
                logger.info(f"[DB 연결] ✅ {self.db_config['database']} 데이터베이스 연결 성공")

            return self._engine
        except Exception as e:
            logger.error(f"[DB 연결] ❌ 연결 실패: {e}", exc_info=True)
            logger.error(f"[DB 연결] 실패한 설정 - Host: {self.db_config['host']}, Port: {self.db_config['port']}, DB: {self.db_config['database']}")
            raise

    def fetch_power_data(self, end_date=None):
        """
        전력 데이터 조회

        Args:
            end_date: 조회 종료 날짜 (datetime, timestamp 또는 str 형태)
                     제공되면 end_date 이전의 모든 데이터를 조회

        Returns:
            DataFrame: 전력 사용량 데이터
        """
        try:
            if end_date is None:
                raise ValueError("end_date parameter is required for fetch_power_data")

            engine = self.get_connection()

            table_name = self.table_names['tb_kepco_30_minutes']
            logger.info(f"[데이터 조회] 조회 테이블: {table_name}")

            # end_date를 Timestamp로 변환
            end_date = pd.Timestamp(end_date)
            logger.info(f"[데이터 조회] end_date: {end_date}까지 모든 데이터 조회")

            # SQL 쿼리 실행
            query = f"""
                SELECT
                    use_dt,
                    pwr_usage,
                    max_demand,
                    react_pwr,
                    real_react_pwr,
                    co_amt,
                    pwr_factor,
                    leading_pwr_factor
                FROM {table_name}
                WHERE use_dt < %(end_date)s
                ORDER BY use_dt ASC
            """

            logger.info(f"[데이터 조회] SQL 쿼리: WHERE use_dt < '{end_date}'")
            logger.info(f"[데이터 조회] 쿼리 실행 중...")

            df = pd.read_sql(query, engine, params={'end_date': end_date})
            logger.info(f"[데이터 조회] 쿼리 결과: {len(df)}개 행 반환")

            if len(df) == 0:
                logger.warning(f"[데이터 조회] ⚠ 날짜 범위에서 데이터를 찾을 수 없습니다!")
                logger.warning(f"[데이터 조회] 테이블: {table_name}")
                # 빈 DataFrame 반환 (컬럼 구조만 유지)
                return pd.DataFrame(columns=['ymdhms', '사용량(kWh)', '최대수요(kW)', '무효전력(지상)',
                                             '무효전력(진상)', 'CO2(tCO2)', '역률(%)_지상', '역률(%)_진상'])

            logger.info(f"[데이터 조회]  {len(df)}개 레코드 발견")

            # 컬럼명 매핑 (DB 컬럼명 -> 모델 학습 컬럼명)
            column_mapping = {
                'use_dt': 'ymdhms',
                'pwr_usage': '사용량(kWh)',
                'max_demand': '최대수요(kW)',
                'react_pwr': '무효전력(지상)',
                'real_react_pwr': '무효전력(진상)',
                'co_amt': 'CO2(tCO2)',
                'pwr_factor': '역률(%)_지상',
                'leading_pwr_factor': '역률(%)_진상'
            }

            logger.info(f"[데이터 조회] DB 형식에서 모델 형식으로 컬럼명 변경 중...")
            logger.info(f"[데이터 조회] 변경 전 컬럼: {df.columns.tolist()}")
            df.rename(columns=column_mapping, inplace=True)
            logger.info(f"[데이터 조회] 변경 후 컬럼: {df.columns.tolist()}")

            # datetime 타입 변환
            df['ymdhms'] = pd.to_datetime(df['ymdhms'])
            logger.info(f"[데이터 조회] DateTime 변환 완료")

            logger.info(f"[데이터 조회]  데이터 조회 완료: {end_date} 이전 {len(df)}개 레코드")
            logger.info(f"[데이터 조회]  날짜 범위: {df['ymdhms'].min()} ~ {df['ymdhms'].max()}")

            return df

        except Exception as e:
            logger.error(f"[데이터 조회] [오류] 전력 데이터 조회 실패: {e}", exc_info=True)
            raise

    def test_connection(self):
        """데이터베이스 연결 테스트"""
        try:
            engine = self.get_connection()
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                result.fetchone()
            logger.info("[DB 연결]  연결 테스트 통과")
            return True
        except Exception as e:
            logger.error(f"[DB 연결] [오류] 연결 테스트 실패: {e}", exc_info=True)
            return False

    def check_table_data(self, days=7, reference_date=None):
        """
        테이블 데이터 존재 여부 및 통계 확인 (디버깅용)

        Args:
            days: 최근 N일 데이터 확인 (기본 7일)
            reference_date: 기준 날짜 (datetime 객체, None이면 에러 발생)

        Returns:
            dict: 테이블 정보
        """
        try:
            engine = self.get_connection()

            table_name = self.table_names['tb_kepco_30_minutes']
            database_name = self.solar_config['database']

            info = {
                'database': database_name,
                'table': table_name,
                'exists': False,
                'total_count': 0,
                'date_range': None,
                'recent_count': 0,
                'columns': []
            }

            with engine.connect() as conn:
                # 1. 테이블 존재 확인
                result = pd.read_sql(f"""
                    SELECT COUNT(*) as cnt
                    FROM information_schema.tables
                    WHERE table_schema = '{database_name}'
                    AND table_name = '{table_name}'
                """, conn)
                info['exists'] = result['cnt'].iloc[0] > 0

                if not info['exists']:
                    logger.error(f"테이블 {database_name}.{table_name}이(가) 존재하지 않습니다!")
                    return info

                # 2. 전체 레코드 수
                result = pd.read_sql(f"SELECT COUNT(*) as cnt FROM {table_name}", conn)
                info['total_count'] = int(result['cnt'].iloc[0])

                # 3. 날짜 범위
                result = pd.read_sql(f"""
                    SELECT
                        MIN(use_dt) as min_date,
                        MAX(use_dt) as max_date
                    FROM {table_name}
                """, conn)
                info['date_range'] = {
                    'min': result['min_date'].iloc[0],
                    'max': result['max_date'].iloc[0]
                }

                # 4. 최근 N일 데이터 수
                if reference_date is None:
                    raise ValueError("reference_date parameter is required for check_table_data")
                end_date = reference_date
                start_date = end_date - timedelta(days=days)

                result = pd.read_sql(f"""
                    SELECT COUNT(*) as cnt
                    FROM {table_name}
                    WHERE use_dt >= %(start_date)s AND use_dt < %(end_date)s
                """, conn, params={'start_date': start_date, 'end_date': end_date})
                info['recent_count'] = int(result['cnt'].iloc[0])
                info['recent_range'] = {
                    'start': start_date,
                    'end': end_date
                }

                # 5. 컬럼 목록
                result = pd.read_sql(f"SHOW COLUMNS FROM {table_name}", conn)
                info['columns'] = result['Field'].tolist()

            logger.info(f"[테이블 확인] Database: {info['database']}")
            logger.info(f"[테이블 확인] Table: {info['table']}")
            logger.info(f"[테이블 확인] 존재 여부: {info['exists']}")
            logger.info(f"[테이블 확인] 전체 레코드 수: {info['total_count']}")
            logger.info(f"[테이블 확인] 날짜 범위: {info['date_range']}")
            logger.info(f"[테이블 확인] 최근 {days}일: {info['recent_count']}개 레코드")
            logger.info(f"[테이블 확인] 컬럼: {info['columns']}")

            return info

        except Exception as e:
            logger.error(f"테이블 데이터 확인 실패: {e}", exc_info=True)
            raise

    def fetch_calendar_data(self, start_date=None, end_date=None):
        """
        근무일정 데이터 조회

        Args:
            start_date: 조회 시작 날짜 (str, 'yyyy-mm-dd' 형태, 선택사항)
                       - 없으면 모든 과거 데이터부터 조회
                       - end_date와 함께 사용하면 범위 조회
            end_date: 조회 종료 날짜 (str, 'yyyy-mm-dd' 형태, 선택사항)
                     - 제공되면 end_date까지의 데이터 조회
                     - 없으면 모든 데이터 조회

        Returns:
            DataFrame: 근무일정 데이터

        조회 로직:
            - end_date만 제공: 모든 데이터 ~ end_date (inclusive)
            - start_date + end_date: start_date ~ end_date (inclusive)
            - 둘 다 없음: 모든 데이터 조회
        """
        try:
            engine = self.get_connection()

            table_name = self.table_names['tb_workcalender']
            logger.info(f"[달력 데이터 조회] 조회 테이블: {table_name}")

            # SQL 쿼리 작성
            if end_date is not None:
                if start_date is not None:
                    # start_date와 end_date 모두 제공된 경우
                    query = f"""
                        SELECT *
                        FROM {table_name}
                        WHERE DATE >= %(start_date)s AND DATE <= %(end_date)s
                        ORDER BY DATE ASC
                    """
                    logger.info(f"[달력 데이터 조회] 날짜 범위: {start_date} ~ {end_date}")
                    df = pd.read_sql(query, engine, params={'start_date': start_date, 'end_date': end_date})
                else:
                    # end_date만 제공된 경우 (모든 과거 데이터 + end_date까지)
                    query = f"""
                        SELECT *
                        FROM {table_name}
                        WHERE DATE <= %(end_date)s
                        ORDER BY DATE ASC
                    """
                    logger.info(f"[달력 데이터 조회] {end_date}까지 모든 달력 데이터 조회")
                    df = pd.read_sql(query, engine, params={'end_date': end_date})
            else:
                # end_date가 없으면 모든 달력 데이터 조회
                query = f"""
                    SELECT *
                    FROM {table_name}
                    ORDER BY DATE ASC
                """
                logger.info(f"[달력 데이터 조회] 모든 달력 데이터 조회")
                df = pd.read_sql(query, engine)

            logger.info(f"[달력 데이터 조회] 쿼리 결과: {len(df)}개 행 반환")

            if len(df) == 0:
                logger.warning(f"[달력 데이터 조회] ⚠ 날짜 범위에서 데이터를 찾을 수 없습니다!")
                return pd.DataFrame()

            logger.info(f"[달력 데이터 조회] 데이터 조회 완료: {len(df)}개 레코드")
            logger.info(f"[달력 데이터 조회] 변경 전 컬럼: {df.columns.tolist()}")

            # 컬럼명 매핑 (DB 컬럼명 -> 모델 학습 컬럼명)
            # work_date를 ymdhms로 변경
            if 'DATE' in df.columns:
                column_mapping = {'DATE': 'ymdhms'}
                logger.info(f"[달력 데이터 조회] DB 형식에서 모델 형식으로 컬럼명 변경 중...")
                df.rename(columns=column_mapping, inplace=True)
                logger.info(f"[달력 데이터 조회] 변경 후 컬럼: {df.columns.tolist()}")

            # datetime 타입 변환
            if 'ymdhms' in df.columns:
                df['ymdhms'] = pd.to_datetime(df['ymdhms'])
                logger.info(f"[달력 데이터 조회] DateTime 변환 완료")
            return df

        except Exception as e:
            logger.error(f"[달력 데이터 조회] 오류: {e}", exc_info=True)
            raise
