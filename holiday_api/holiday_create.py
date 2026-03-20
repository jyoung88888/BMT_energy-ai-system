"""
윈도우 스케줄러용 공휴일 적재 스크립트
API 서버를 실행하지 않고 바로 DB에 공휴일 데이터를 적재합니다.
"""
from datetime import date
import sys
import os
import holidays
import pymysql

# 공통 DB 설정 import
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from db_config import DB_CONFIG


def get_db_connection():
    """MariaDB 연결을 생성하는 함수"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        return connection
    except Exception as e:
        raise Exception(f"Database connection failed: {str(e)}")


def get_holidays_for_year(year: int):
    """특정 연도의 한국 공휴일 및 대체공휴일을 가져오는 함수"""
    # 한국 공휴일 객체 생성
    kr_holidays = holidays.KR(years=year)

    # 제외할 공휴일 목록
    excluded_holidays = ["Presidential Election Day", "Temporary Public Holiday"]

    holiday_list = []
    for holiday_date, holiday_name in sorted(kr_holidays.items()):
        # 제외 목록에 없는 공휴일만 추가
        if holiday_name not in excluded_holidays:
            holiday_list.append((holiday_date, holiday_name))

    return holiday_list


def insert_holidays_to_db(holiday_list):
    """공휴일 데이터를 DB에 삽입하는 함수"""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        # 기존 데이터 삭제 (올해 데이터만 삭제)
        today = date.today()
        year = today.year
        cursor.execute(f"DELETE FROM tb_holiday WHERE YEAR(hol_date) = {year}")

        # 공휴일 데이터 삽입
        insert_query = "INSERT INTO tb_holiday (hol_date) VALUES (%s)"
        inserted_count = 0

        for holiday_date, _ in holiday_list:
            cursor.execute(insert_query, (holiday_date,))
            inserted_count += 1

        connection.commit()

        return {
            "status": "success",
            "year": year,
            "inserted_count": inserted_count,
            "holidays": [{"date": str(hdate), "name": hname} for hdate, hname in holiday_list]
        }

    except Exception as e:
        if connection:
            connection.rollback()
        raise Exception(f"Database operation failed: {str(e)}")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def main():
    """메인 실행 함수"""
    try:
        print("\n" + "="*60)
        print("공휴일 데이터 적재 시작...")
        print("="*60 + "\n")

        # 현재 날짜에서 연도 추출
        today = date.today()
        current_year = today.year
        print(f"현재 연도: {current_year}")

        # 공휴일 데이터 가져오기
        print(f"\n{current_year}년 공휴일 데이터 조회 중...")
        holiday_list = get_holidays_for_year(current_year)

        if not holiday_list:
            print(f"⚠️  {current_year}년도 공휴일 데이터가 없습니다.")
            return

        print(f"조회 완료: {len(holiday_list)}개의 공휴일 발견")

        # DB에 삽입
        print(f"\nMariaDB에 데이터 적재 중...")
        result = insert_holidays_to_db(holiday_list)

        print(f"\n✅ 성공: {result['year']}년 공휴일 {result['inserted_count']}개 적재 완료!")
        print("\n공휴일 목록:")
        for holiday in result['holidays']:
            print(f"  - {holiday['date']}: {holiday['name']}")

        print("\n" + "="*60)
        print("적재 완료")
        print("="*60 + "\n")

    except Exception as e:
        print(f"\n❌ 오류 발생: {str(e)}\n")
        raise


if __name__ == "__main__":
    main()
