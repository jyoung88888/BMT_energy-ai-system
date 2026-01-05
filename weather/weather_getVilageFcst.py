#### 단기예보 API는 복구가 되어서, 이 데이터라도 올바른 데이터로 적재하는 스크립트 


from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytz
import pandas as pd
import requests
import pymysql
import logging
from pathlib import Path
from typing import Dict, Any
from pvlib import solarposition

# ===== 설정 =====
# 서비스 키
SERVICE_KEY = "B/eXbaY8RqfKO7WugqO+4aw4PSnN+daAUt32w5EhZBKoYp58GGEyQ115JS7vTenW6gnnrM2+ZdqNOBQpMsbdqA=="

# 기상청 API URL
API_URL = 'http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst'

# 좌표 설정 (서울 기준 - 필요시 변경)
NX = 97
NY = 74

# MariaDB 설정
DB_CONFIG = {
    'host': '192.168.213.250',
    'user': 'root',
    'password': 'OnDemand%Ai',
    'database': 'db_energy',
    'charset': 'utf8mb4'
}

# 테이블명
TABLE_NAME = 'tb_weather_info'

# ===== 로깅 설정 =====
def setup_logging():
    """로깅 설정 - logs 폴더에 로그 파일 저장"""
    # logs 폴더 생성
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # 로그 파일명 (날짜별)
    log_file = log_dir / f"weather_getVilageFcst_{datetime.now().strftime('%Y%m%d')}.log"

    # 로거 설정
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # 파일 핸들러 (파일에 저장)
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)

    # 콘솔 핸들러 (콘솔에 출력)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # 로그 포맷
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # 핸들러 추가
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

# 로거 초기화
logger = setup_logging()


def fetch_vilagefcst_data(
    date_str: str,
    base_time: str,
    nx: int,
    ny: int,
    service_key: str,
    timeout: int = 20
) -> pd.DataFrame:
    """
    기상청 단기예보(VilageFcst) 조회 → DataFrame 반환

    Args:
        date_str: 기준 날짜 (YYYYMMDD 형식)
        base_time: 기준 시각 (HHMM 형식, 예: '1100')
        nx: 격자 X 좌표
        ny: 격자 Y 좌표
        service_key: 기상청 API 서비스 키
        timeout: API 요청 타임아웃 (초)

    Returns:
        pd.DataFrame: 단기예보 데이터
    """
    logger.info(f"단기예보 데이터 수집 시작: {date_str} {base_time}")

    params = {
        "serviceKey": service_key,
        "pageNo": "1",
        "numOfRows": "1000",
        "dataType": "JSON",
        "base_date": date_str,
        "base_time": base_time,
        "nx": str(nx),
        "ny": str(ny),
    }

    try:
        response = requests.get(API_URL, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        # 응답 검증
        result_code = data.get('response', {}).get('header', {}).get('resultCode')
        result_msg = data.get('response', {}).get('header', {}).get('resultMsg')

        logger.info(f"API 응답 코드: {result_code}, 메시지: {result_msg}")

        if result_code != '00':
            logger.error(f"API 응답 오류: {result_msg}")
            return pd.DataFrame()

        # 데이터 파싱
        items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])

        if not items:
            logger.warning("수집된 데이터가 없습니다.")
            return pd.DataFrame()

        if not isinstance(items, list):
            items = [items]

        logger.info(f"수집된 데이터 개수: {len(items)}")

        # DataFrame 생성
        raw = pd.DataFrame(items)

        # 피벗 테이블로 변환 (카테고리별로 컬럼 분리)
        df_wide = (
            raw.pivot_table(
                index=["fcstDate", "fcstTime"],
                columns="category",
                values="fcstValue",
                aggfunc="last",
            )
            .reset_index()
        )
        df_wide.columns.name = None

        # 숫자형 변환
        num_cols = [c for c in df_wide.columns if c not in ("fcstDate", "fcstTime")]
        df_wide[num_cols] = df_wide[num_cols].apply(pd.to_numeric, errors="coerce")

        # datetime 컬럼 생성
        df_wide["forecast_datetime"] = pd.to_datetime(
            df_wide["fcstDate"] + df_wide["fcstTime"], format="%Y%m%d%H%M"
        )

        # 다음 날짜만 가져오기
        next_date = (pd.to_datetime(date_str, format="%Y%m%d") + pd.Timedelta(days=1)).strftime("%Y%m%d")

        df_wide = df_wide.loc[df_wide['fcstDate'] == next_date][['forecast_datetime', 'PCP', 'POP', 'PTY', 'REH', 'SKY', 'SNO', 'TMN',
                                                                'TMP', 'TMX', 'UUU', 'VEC', 'VVV', 'WAV', 'WSD']]
                                                                

        # 컬럼명 매핑
        column_mapping = {
            'forecast_datetime': 'tm',
            'POP': 'pop',
            'PTY': 'pty',
            'PCP': 'pcp',
            'REH': 'reh',
            'SNO': 'sno',
            'SKY': 'sky',
            'TMP': 'tmp',
            'TMN': 'tmn',
            'TMX': 'tmx',
            'UUU': 'uuu',
            'VVV': 'vvv',
            'WAV': 'wav',
            'VEC': 'vec',
            'WSD': 'wsd',
        }

        df_wide = df_wide.rename(columns=column_mapping)

        logger.info(f"DataFrame 생성 완료: {len(df_wide)}행")
        logger.info(f"컬럼명 매핑 완료: {list(df_wide.columns)}")
        return df_wide

    except requests.exceptions.RequestException as e:
        logger.error(f"API 요청 오류: {e}", exc_info=True)
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"데이터 처리 오류: {e}", exc_info=True)
        return pd.DataFrame()

def fetch_apparent_zenith_data(date_str: str, tz: str, latitude: float, longitude: float):
    """
    태양 위치 데이터 계산 함수

    Args:
        date_str: 기준 날짜 (YYYY-MM-DD 형식)
        tz: 타임존 (예: 'Asia/Seoul')
        latitude: 위도
        longitude: 경도

    Returns:
        pd.DataFrame: 태양 위치 데이터 (tm, apparent_zenith, apparent_elevation, azimuth)
    """
    logger.info(f"태양 위치 데이터 계산 시작: {date_str}")

    # 문자열 -> Timestamp로 변환 (기준 날짜 +1일 = 다음날)
    next_date = (pd.to_datetime(date_str, format="%Y-%m-%d") + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    base = pd.Timestamp(next_date)

    # start = 00:00, end = 다음날 00:00
    end = base + pd.Timedelta(days=1)
    # 1시간 간격으로 시간대 생성
    times = pd.date_range(
        start=base,
        end=end,
        freq='1h',
        tz=tz,
        inclusive='left'   # 다음날 00:00 제외
    )

    # 태양 위치 계산
    solar_position = solarposition.get_solarposition(
        time=times,
        latitude=latitude,
        longitude=longitude
    )

    # 태양 고도각이 음수(해가 지평선 아래)인 경우 0으로 설정
    solar_position.loc[solar_position.apparent_elevation < 0, 'apparent_elevation'] = 0
    solar_position = solar_position.reset_index()

    # 필요한 컬럼만 선택
    solar_position = solar_position[['index', 'apparent_zenith', 'apparent_elevation', 'azimuth']]

    # 컬럼명 매핑
    column_mapping = {
        'index': 'tm',
        'apparent_zenith': 'apparent_zenith',
        'apparent_elevation': 'apparent_elevation',
        'azimuth': 'azimuth'
    }

    solar_position = solar_position.rename(columns=column_mapping)

    # timezone 정보 제거 (naive datetime으로 변환)
    solar_position['tm'] = solar_position['tm'].dt.tz_localize(None)

    logger.info(f"태양 위치 DataFrame 생성 완료: {len(solar_position)}행")
    return solar_position




def update_to_mariadb(df: pd.DataFrame, db_config: Dict[str, Any], table_name: str, pk_column: str = 'tm'):
    """
    DataFrame을 MariaDB에 업데이트 (PK 기준 INSERT/UPDATE)

    - PK가 존재하면 UPDATE
    - PK가 없으면 INSERT
    - reg_dt에 현재 실행 시각(KST)을 자동으로 추가

    Args:
        df: 저장할 데이터프레임
        db_config: DB 연결 설정
        table_name: 테이블명
        pk_column: Primary Key 컬럼명 (기본값: 'tm')
    """
    if df.empty:
        logger.warning("저장할 데이터가 없습니다.")
        return

    # 현재 시각(KST) 추가 (타임존 정보 제거, naive datetime으로 변환)
    kst = ZoneInfo("Asia/Seoul")
    reg_dt = datetime.now(kst).replace(tzinfo=None)
    df['reg_dt'] = reg_dt

    logger.info("MariaDB 연결 시작...")
    logger.info(f"PK 컬럼: {pk_column}")
    logger.info(f"등록 시각(reg_dt): {reg_dt}")

    try:
        # DB 연결
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()

        logger.info(f"테이블 '{table_name}'에 데이터 적재 시작...")

        # 데이터 삽입/업데이트
        insert_count = 0
        update_count = 0
        error_count = 0

        for idx, row in df.iterrows():
            # 컬럼명과 값 추출
            columns = list(row.index)
            values = [row[col] for col in columns]

            # NULL 처리
            values = [None if pd.isna(val) else val for val in values]

            # INSERT ... ON DUPLICATE KEY UPDATE 쿼리 생성
            # PK가 중복되면 UPDATE, 없으면 INSERT
            placeholders = ', '.join(['%s'] * len(columns))
            columns_str = ', '.join([f'`{col}`' for col in columns])

            # UPDATE 부분: PK를 제외한 모든 컬럼 업데이트 (reg_dt 포함)
            update_parts = ', '.join([f'`{col}`=VALUES(`{col}`)' for col in columns if col != pk_column])

            sql = f"""
                INSERT INTO `{table_name}` ({columns_str})
                VALUES ({placeholders})
                ON DUPLICATE KEY UPDATE {update_parts}
            """

            try:
                cursor.execute(sql, values)

                # rowcount로 INSERT/UPDATE 구분
                # 1: 새로운 행 삽입 (INSERT)
                # 2: 기존 행 업데이트 (UPDATE)
                if cursor.rowcount == 1:
                    insert_count += 1
                elif cursor.rowcount == 2:
                    update_count += 1

            except Exception as e:
                error_count += 1
                logger.error(f"행 적재 오류 (index={idx}): {e}", exc_info=True)
                logger.error(f"PK 값: {row.get(pk_column, 'N/A')}")
                continue

        # 커밋
        conn.commit()
        logger.info("데이터 적재 완료")
        logger.info(f"신규 INSERT: {insert_count}건")
        logger.info(f"기존 UPDATE: {update_count}건")
        if error_count > 0:
            logger.warning(f"오류: {error_count}건")

    except pymysql.Error as e:
        logger.error(f"DB 오류: {e}", exc_info=True)
        if 'conn' in locals():
            conn.rollback()
            logger.info("트랜잭션 롤백 완료")
    except Exception as e:
        logger.error(f"예상치 못한 오류: {e}", exc_info=True)
        if 'conn' in locals():
            conn.rollback()
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()
        logger.info("DB 연결 종료")


def main():
    """메인 실행 함수"""
    logger.info("=" * 50)
    logger.info("기상청 단기예보 데이터 수집 및 DB 저장")
    logger.info("=" * 50)

    try:
        # 오늘 날짜 및 시간 계산
        seoul = pytz.timezone("Asia/Seoul")
        now_seoul = datetime.now(seoul) # 오늘 기준

        # 기준 날짜
        base_date = now_seoul.strftime("%Y%m%d")
        base_date_with_hyphen = now_seoul.strftime("%Y-%m-%d")

        # 기준 시각 계산 (단기예보 API는 0200, 0500, 0800, 1100, 1400, 1700, 2000, 2300 발표)
        base_time = "2000"  # 기본값

        # 태양 위치 계산용 좌표 설정 (기장)
        latitude = 35.3107027777777    # 북위 35.24도
        longitude = 129.246288888888  # 동경 129.22도
        timezone = 'Asia/Seoul'

        logger.info(f"기준 날짜: {base_date}")
        logger.info(f"기준 시각: {base_time}")
        logger.info(f"좌표: nx={NX}, ny={NY}")
        logger.info(f"태양 위치 좌표: 위도={latitude}, 경도={longitude}")

        # 1. 단기예보 데이터 수집
        df_weather = fetch_vilagefcst_data(
            date_str=base_date,
            base_time=base_time,
            nx=NX,
            ny=NY,
            service_key=SERVICE_KEY
        )

        if df_weather.empty:
            logger.error("날씨 데이터 수집 실패")
            return

        logger.info(f"날씨 데이터 수집 완료: {len(df_weather)}건")

        # 2. 태양 위치 데이터 수집
        df_solar = fetch_apparent_zenith_data(
            date_str=base_date_with_hyphen,
            tz=timezone,
            latitude=latitude,
            longitude=longitude
        )

        if df_solar.empty:
            logger.error("태양 위치 데이터 수집 실패")
            return

        logger.info(f"태양 위치 데이터 수집 완료: {len(df_solar)}건")

        # 3. 두 데이터프레임 병합 (tm 기준으로 left join)
        logger.info("날씨 데이터와 태양 위치 데이터 병합 중...")
        df_merged = pd.merge(
            df_weather,
            df_solar[['tm', 'apparent_zenith', 'apparent_elevation', 'azimuth']],
            on='tm',
            how='left'
        )
        logger.info(f"병합 완료: {len(df_merged)}건")

        logger.debug(f"병합된 데이터 샘플:\n{df_merged.head()}")

        # 4. MariaDB에 저장
        update_to_mariadb(df_merged, DB_CONFIG, TABLE_NAME)

        logger.info("=" * 50)
        logger.info("작업 완료")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"작업 중 오류 발생: {e}", exc_info=True)
        logger.error("=" * 50)


if __name__ == "__main__":
    main()
