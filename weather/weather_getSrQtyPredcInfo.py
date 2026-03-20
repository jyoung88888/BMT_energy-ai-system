
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytz
import pandas as pd
import requests
import pymysql
import logging
import time
import sys
from pathlib import Path
from typing import Dict, Any
import os
import argparse

# 공통 DB 설정 import
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from db_config import DB_CONFIG

# ===== 설정 =====
# 서비스 키
SERVICE_KEY = "B/eXbaY8RqfKO7WugqO+4aw4PSnN+daAUt32w5EhZBKoYp58GGEyQ115JS7vTenW6gnnrM2+ZdqNOBQpMsbdqA=="

# 기상청 API URL
API_URL = 'http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst'

lat = '35.3110000000'
lot = '129.2430000000'

# ===== 명령줄 인자 파싱 =====
parser = argparse.ArgumentParser(description='일사량 정보 수집 및 DB 적재')
parser.add_argument('--date', type=str, help='날짜 지정 (형식: YYYY-MM-DD, 예: 2025-01-14)')
args = parser.parse_args()

# 날짜 설정
seoul = pytz.timezone("Asia/Seoul")
if args.date:
    # --date 파라미터가 있으면 해당 날짜 사용
    target_date = datetime.strptime(args.date, "%Y-%m-%d")
    basedate = target_date.strftime("%Y%m%d")
else:
    # --date 파라미터가 없으면 오늘 날짜 사용
    now_seoul = datetime.now(seoul)
    basedate = now_seoul.strftime("%Y%m%d")

print(f"처리 날짜: {basedate}")

# ===== 로깅 설정 =====
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f"weather_getSrQtyPredcInfo_{basedate}.log"

# 실행 시작 시간
execution_start = datetime.now(seoul)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, mode='a', encoding='utf-8'),  # append 모드
        logging.StreamHandler()
    ],
    force=True  # 기존 설정 덮어쓰기
)
logger = logging.getLogger(__name__)

# 실행 구분자
logger.info("=" * 80)
logger.info(f"실행 시작: {execution_start.strftime('%Y-%m-%d %H:%M:%S')}")
logger.info("=" * 80)
logger.info(f"처리 날짜: {basedate}")


# ===== API 재시도 설정 =====
RETRY_WAIT_MINUTES = [1, 3, 5]  # 재시도별 대기 시간(분)
MAX_RETRIES = 3


def request_with_retry(url, params, max_retries=MAX_RETRIES, timeout=20):
    """
    API 호출 재시도 (분 단위 대기)

    성공/실패 구분:
        - 성공: HTTP 200 + 정상 데이터 반환
        - 일시적 실패: 타임아웃, 네트워크 오류, 서버 오류 → 재시도
        - 영구적 실패: 서비스키 만료, 잘못된 파라미터 → 즉시 중단

    Args:
        url: API URL
        params: 요청 파라미터
        max_retries: 최대 재시도 횟수
        timeout: 요청 타임아웃 (초)

    Returns:
        dict: API 응답 JSON (성공 시)
        None: 실패 시
    """
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()

            data = response.json()

            # 응답 구조 검증
            result_code = data.get('response', {}).get('header', {}).get('resultCode')
            result_msg = data.get('response', {}).get('header', {}).get('resultMsg', '')

            if result_code and result_code != '00':
                # 재시도 불가 에러
                if result_code in ('10', '20', '30'):
                    logger.error(f"[API 영구실패] 코드: {result_code}, 메시지: {result_msg}")
                    return None
                # 일시적 에러 → 재시도
                raise Exception(f"API 응답 오류 - 코드: {result_code}, 메시지: {result_msg}")

            # 정상 응답
            logger.info(f"[API 성공] 시도 {attempt}/{max_retries} - 정상 응답")
            return data

        except requests.exceptions.Timeout as e:
            logger.warning(f"[API 타임아웃] 시도 {attempt}/{max_retries} - {timeout}초 초과")

        except requests.exceptions.ConnectionError as e:
            logger.warning(f"[API 연결실패] 시도 {attempt}/{max_retries} - 서버 연결 불가")

        except requests.exceptions.HTTPError as e:
            logger.warning(f"[API HTTP에러] 시도 {attempt}/{max_retries} - 상태코드: {response.status_code}")

        except Exception as e:
            logger.warning(f"[API 일시실패] 시도 {attempt}/{max_retries} - {e}")

        # 재시도 또는 최종 실패
        if attempt < max_retries:
            wait = RETRY_WAIT_MINUTES[attempt - 1]
            logger.info(f"[API 재시도] {wait}분 후 재시도 예정... ({attempt + 1}/{max_retries}차)")
            time.sleep(wait * 60)
        else:
            logger.error(f"[API 최종실패] {max_retries}회 모두 실패 - 수동 확인 필요")
            return None


url = 'https://apis.data.go.kr/B551184/SrQtyService/getSrQtyPredcInfo'
params ={'serviceKey' : SERVICE_KEY, 'pageNo' : "1", 'numOfRows' : "50", 'date':basedate,'lat' : '35.31','lot':'129.24' }

logger.info(f"API 요청: {url}")
j = request_with_retry(url, params)

if j is None:
    logger.error("API 데이터 수집 실패 - 스크립트를 종료합니다.")
    sys.exit(1)

items = j["response"]["body"]["items"]["item"] if j["response"]["body"]["totalCount"] else []
logger.info(f"총 {len(items)}개 데이터 수신")

df = pd.DataFrame(items)
final_df = df.loc[(df.lat ==lat) &(df.lot == lot)].reset_index(drop=True)
logger.info(f"필터링 후 {len(final_df)}개 데이터")

if len(final_df) == 0:
    logger.error("필터링 후 데이터가 0건입니다. DB 적재를 건너뜁니다.")
    sys.exit(1)

# ===== 데이터 전처리 =====
logger.info("데이터 전처리 시작")

# 1. datetime 컬럼 생성 (yr, mm, day, hm을 활용)
final_df['tm'] = pd.to_datetime(
    final_df['yr'].astype(str) + '-' +
    final_df['mm'].astype(str).str.zfill(2) + '-' +
    final_df['day'].astype(str).str.zfill(2) + ' ' +
    final_df['hm'].astype(str).str.zfill(4).str[:2] + ':' +
    final_df['hm'].astype(str).str.zfill(4).str[2:] + ':00'
)

# 2. ics 컬럼 생성 (ghi * 0.0036)
final_df['ics'] = final_df['ghi'].astype(float) * 0.0036
logger.info("tm 및 ics 컬럼 생성 완료")

# ===== DB 적재 =====
try:
    logger.info("DB 연결 시작")
    # MariaDB 연결
    connection = pymysql.connect(**DB_CONFIG)
    cursor = connection.cursor()
    logger.info(f"DB 연결 성공: {DB_CONFIG['host']}")

    # 적재할 데이터 준비 (tm, ics 컬럼만 사용)
    logger.info(f"{len(final_df)}개 데이터 적재 시작")
    for idx, row in final_df.iterrows():
        insert_query = """
            INSERT INTO tb_weather_info (tm, ics)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE ics = VALUES(ics)
        """
        cursor.execute(insert_query, (row['tm'], row['ics']))

    connection.commit()
    logger.info(f"DB 적재 완료: {len(final_df)}개 행 처리")

except pymysql.Error as e:
    logger.error(f"DB 오류 발생: {e}")
    if connection:
        connection.rollback()

finally:
    if cursor:
        cursor.close()
    if connection:
        connection.close()
    logger.info("DB 연결 종료")

# 실행 종료
execution_end = datetime.now(seoul)
execution_time = (execution_end - execution_start).total_seconds()

logger.info("\n=== Final DataFrame ===")
logger.info(f"\n{final_df[['tm', 'ghi', 'ics']].head().to_string()}")
logger.info("")
logger.info("=" * 80)
logger.info(f"실행 종료: {execution_end.strftime('%Y-%m-%d %H:%M:%S')}")
logger.info(f"실행 시간: {execution_time:.2f}초")
logger.info("=" * 80)
logger.info("")  # 빈 줄 추가

print("\n=== Final DataFrame ===")
print(final_df[['tm', 'ghi', 'ics']].head())