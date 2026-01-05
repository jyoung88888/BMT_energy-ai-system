"""
Solar API 자동 예측 실행 스크립트 (동기식)
Windows 작업 스케줄러에서 사용하기 위한 독립 실행 스크립트

사용법:
    python schedule_solar.py                    # 오늘 날짜 기준
    python schedule_solar.py --date 2025-10-25  # 특정 날짜 기준
    python schedule_solar.py --help             # 도움말 표시

설명:
    - 날짜 입력 옵션: --date (YYYY-MM-DD 형식)
    - 날짜 미입력 시: KST 기준 오늘 날짜 자동 사용
    - 태양광 발전량 예측 후 Hourly/Daily로 저장
"""
import logging
import sys
import argparse
from datetime import datetime
from pathlib import Path
import os

# 프로젝트 루트 경로를 sys.path에 추가
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def setup_logging():
    """로깅 설정 (날짜별 분리)"""
    log_dir = Path(BASE_DIR) / "logs"

    # ⚠️ logs 디렉토리 생성 시도 (Windows 작업 스케줄러 SYSTEM 계정 호환성)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"⚠️ logs 디렉토리 생성 실패: {str(e)}. 현재 디렉토리에 로그를 저장합니다.")
        log_dir = Path(BASE_DIR)

    # 현재 날짜를 기반으로 로그 파일명 생성
    current_date = datetime.now().strftime('%Y-%m-%d')
    log_file = log_dir / f"solar_AI_scheduler_{current_date}.log"

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    return logging.getLogger(__name__)


logger = None


def run_prediction(target_date: str = None):
    """
    태양광 예측 로직 직접 실행 (동기식)

    prediction_pipeline.py의 run_solar_prediction_pipeline() 함수를 호출

    Args:
        target_date: 예측할 날짜 (YYYY-MM-DD 형식, None이면 오늘 날짜)

    Returns:
        bool: 성공 여부
    """
    try:
        logger.info("=" * 80)
        logger.info("🌞 태양광 예측 자동 실행 시작 (동기식)")
        logger.info(f"📅 실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        date_source = "입력된 날짜" if target_date else "자동 생성"
        logger.info(f"📅 날짜 소스: {date_source}")
        if target_date:
            logger.info(f"📅 지정 날짜: {target_date}")
        else:
            logger.info(f"📅 오늘 날짜 자동 사용")
        logger.info("=" * 80)

        # prediction_pipeline.py의 동기식 함수 호출
        from app.core.prediction_pipeline import run_solar_prediction_pipeline

        logger.info("🔮 예측 로직 실행 중...")
        result = run_solar_prediction_pipeline(target_date_str=target_date)

        # 결과 확인
        if result and result.get('status') == 'success':
            logger.info("✅ 예측 실행 성공!")
            logger.info(f"📊 예측 날짜: {result.get('target_date', 'N/A')}")
            logger.info(f"📊 예측 범위: {result.get('target_range', 'N/A')}")

            # 저장 결과 확인
            db_save = result.get('database_save', {})
            hourly_counts = db_save.get('hourly_saved_counts', {})
            hourly_total = db_save.get('hourly_total_records', 0)
            daily_sums = db_save.get('daily_sums', {})

            logger.info(f"💾 시간별 데이터 저장: {hourly_total}건")
            for factory, count in hourly_counts.items():
                logger.info(f"   - {factory}: {count}건")

            if daily_sums:
                logger.info(f"💾 일간 합계 저장:")
                for factory, total in daily_sums.items():
                    logger.info(f"   - {factory}: {total:.2f}")

            logger.info("=" * 80)
            logger.info("🎉 예측 완료 및 데이터베이스 저장 성공!")
            logger.info("=" * 80)
            return True
        else:
            logger.error("❌ 예측 실행 실패")
            return False

    except ValueError as ve:
        logger.error(f"❌ ValueError: {str(ve)}", exc_info=True)
        logger.info("=" * 80)
        return False

    except ImportError as e:
        logger.error(f"❌ 모듈 import 오류: {str(e)}", exc_info=True)
        logger.error("app.core.prediction_pipeline 모듈을 찾을 수 없습니다. 프로젝트 루트에서 실행하세요.")
        logger.info("=" * 80)
        return False

    except Exception as e:
        logger.error(f"❌ 예상치 못한 오류 발생: {str(e)}", exc_info=True)
        logger.info("=" * 80)
        return False


def main():
    """메인 함수"""
    global logger
    logger = setup_logging()

    try:
        logger.info("=" * 80)
        logger.info("Solar Prediction Scheduler Started")
        logger.info(f"Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 80)

        # 커맨드라인 인자 파싱
        parser = argparse.ArgumentParser(
            description='태양광 예측 자동 실행 스크립트',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
사용 예시:
  python schedule_solar.py                    # 오늘 날짜 기준
  python schedule_solar.py --date 2025-10-25  # 특정 날짜 기준
            """
        )
        parser.add_argument(
            '--date',
            type=str,
            default=None,
            help='예측할 날짜 (YYYY-MM-DD 형식). 생략하면 오늘 날짜 사용'
        )

        args = parser.parse_args()

        # 날짜 형식 검증 (입력된 경우에만)
        if args.date:
            try:
                datetime.strptime(args.date, '%Y-%m-%d')
                logger.info(f"📅 입력 날짜: {args.date}")
            except ValueError:
                logger.error(f"❌ 잘못된 날짜 형식: {args.date}. YYYY-MM-DD 형식으로 입력해주세요.")
                logger.error("=" * 80)
                return 1

        # 동기식 함수 실행
        success = run_prediction(target_date=args.date)

        if success:
            logger.info("=" * 80)
            logger.info("Solar Prediction Scheduler Completed Successfully")
            logger.info("=" * 80)
            return 0
        else:
            logger.error("=" * 80)
            logger.error("Solar Prediction Scheduler Failed")
            logger.error("=" * 80)
            return 1

    except KeyboardInterrupt:
        logger.info("⚠️ 사용자에 의해 중단됨")
        logger.info("=" * 80)
        return 130

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"❌ 치명적 오류: {str(e)}", exc_info=True)
        logger.error("=" * 80)
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
