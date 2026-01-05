"""
EMS 전력 사용량 예측 스케줄러 스크립트
Windows 작업 스케줄러를 통해 일 1회 실행하기 위한 독립 실행 스크립트

사용법:
    python schedule_ems_predict.py                    # 오늘 날짜 자동 사용
    python schedule_ems_predict.py --date 2024-10-15  # 특정 날짜로 실행
    python schedule_ems_predict.py -d 2024-10-15      # 특정 날짜로 실행 (단축)
    python schedule_ems_predict.py --help             # 도움말 표시

설명:
    - 날짜 입력 옵션: --date 또는 -d (YYYY-MM-DD 형식)
    - 날짜 미입력 시: app.main.calculate_split_date()를 사용하여 KST 기준 오늘 날짜 자동 생성
    - 전력 사용량 예측 후 Hourly/Daily로 집계하여 DB 저장
"""

import sys
import os
import logging
import warnings
import random
import numpy as np
import torch
import argparse
from datetime import datetime
from pathlib import Path

# 재현 가능한 결과를 위한 환경변수 설정 (반드시 다른 import 전에)
os.environ['PYTHONHASHSEED'] = '42'
os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'

# PyTorch Lightning 경고 무시
warnings.filterwarnings('ignore', category=UserWarning, module='pytorch_lightning')
warnings.filterwarnings('ignore', category=UserWarning, module='torch.utils.data.dataloader')

# 프로젝트 루트 경로를 sys.path에 추가
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.core.db import DatabaseManager
from app.core.db_saver import ForecastSaver
from app.utils.model_loader import ModelLoader
from app.models.predictor import PowerPredictor
from app.main import calculate_split_date
from app.core.prediction_pipeline import run_prediction_pipeline


def set_global_seed(seed=42):
    """
    전역 시드 고정

    Args:
        seed: 랜덤 시드 값
    """
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=True)


def setup_logging():
    """로깅 설정 (날짜별 분리)"""
    log_dir = Path(BASE_DIR) / "logs"

    # logs 폴더 생성 시도
    try:
        log_dir.mkdir(exist_ok=True)
        print(f"[LOG SETUP] Log directory created/verified: {log_dir}")
    except Exception as e:
        print(f"[LOG SETUP ERROR] Failed to create log directory: {e}")
        raise

    # 현재 날짜를 기반으로 로그 파일명 생성
    current_date = datetime.now().strftime('%Y-%m-%d')
    log_file = log_dir / f"ems_AI_scheduler_{current_date}.log"
    print(f"[LOG SETUP] Log file path: {log_file}")

    try:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ],
            force=True  # 기존 설정 강제 덮어쓰기
        )
        print(f"[LOG SETUP] Logging configured successfully")
    except Exception as e:
        print(f"[LOG SETUP ERROR] Failed to configure logging: {e}")
        raise

    logger = logging.getLogger(__name__)
    logger.info(f"[LOG SETUP] Log file initialized: {log_file}")
    return logger

def initialize_components(logger):
    """
    필요한 컴포넌트 초기화

    Returns:
        tuple: (db_manager, forecast_saver, predictor)
    """
    try:
        logger.info("=" * 80)
        logger.info("Initializing EMS Prediction Components...")
        logger.info("=" * 80)

        # 재현 가능한 결과를 위해 전역 시드 고정
        logger.info("[Init] Setting global random seed to 42...")
        set_global_seed(42)
        logger.info("[Init]  Global random seed fixed to 42")

        # 데이터베이스 매니저 초기화
        logger.info("[Init] Initializing Database manager...")
        db_manager = DatabaseManager()
        logger.info(f"[Init]  Database manager initialized")

        # DB 연결 테스트
        logger.info("[Init] Testing database connection...")
        if db_manager.test_connection():
            logger.info("[Init]  Database connection test passed")
        else:
            logger.error("[Init] [ERROR] Database connection test failed")
            raise Exception("Database connection test failed")

        # ForecastSaver 초기화
        logger.info("[Init] Initializing ForecastSaver...")
        forecast_saver = ForecastSaver()
        logger.info("[Init]  ForecastSaver initialized")

        # 모델 로드
        logger.info("[Init] Loading model components...")
        model_loader = ModelLoader()
        model_components = model_loader.load_all()
        logger.info("[Init]  Model components loaded successfully")

        # Predictor 초기화
        logger.info("[Init] Initializing PowerPredictor...")
        predictor = PowerPredictor(model_components)
        logger.info("[Init]  PowerPredictor initialized")

        logger.info("=" * 80)
        logger.info("[Init]  All components initialized successfully")
        logger.info("=" * 80)

        return db_manager, forecast_saver, predictor

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"[Init] [ERROR] Failed to initialize components: {e}", exc_info=True)
        logger.error("=" * 80)
        raise


def run_prediction(split_date, db_manager, forecast_saver, predictor, logger, date_source):
    """
    전력 사용량 예측 실행

    Args:
        split_date: 분할 시점 ('yyyy-mm-dd' 형태)
        db_manager: 데이터베이스 매니저
        forecast_saver: 예측 결과 저장 객체
        predictor: 예측 모델
        logger: 로거
        date_source: 날짜 소스 ("입력된 날짜" 또는 "자동 생성")

    Returns:
        bool: 성공 여부
    """
    try:
        logger.info("=" * 80)
        logger.info(f"[PREDICT START] split_date: {split_date} ({date_source})")

        # 공통 예측 파이프라인 실행
        result = run_prediction_pipeline(
            split_date=split_date,
            db_manager=db_manager,
            forecast_saver=forecast_saver,
            predictor=predictor
        )

        logger.info(f"[PREDICT END] SUCCESS - Hourly: {result['hourly_saved']} records, Daily: {result['daily_saved']} records saved")
        logger.info("=" * 80)

        return True

    except ValueError as ve:
        logger.error(f"[PREDICT END] ValueError: {ve}", exc_info=True)
        logger.info("=" * 80)
        return False
    except Exception as e:
        logger.error(f"[PREDICT END] FAILED: {e}", exc_info=True)
        logger.info("=" * 80)
        return False


def main():
    """메인 실행 함수"""
    # 명령행 인자 파싱
    parser = argparse.ArgumentParser(
        description='EMS 전력 사용량 예측 스케줄러',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    사용 예시:
    python schedule_ems_predict.py                    # 오늘 날짜 자동 사용
    python schedule_ems_predict.py --date 2024-10-15  # 특정 날짜로 실행
    """
    )
    parser.add_argument(
        '--date',
        type=str,
        default=None,
        help='예측 기준 날짜 (YYYY-MM-DD 형식). 생략 시 오늘 날짜 자동 생성'
    )
    args = parser.parse_args()

    # 로깅 설정
    logger = setup_logging()

    try:
        # split_date 계산 - app.main.calculate_split_date() 사용
        split_date = calculate_split_date(args.date)

        date_source = "입력된 날짜" if args.date else "자동 생성"
        logger.info("=" * 80)
        logger.info(f"EMS Prediction Scheduler Started")
        logger.info(f"Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Split Date: {split_date} ({date_source})")
        logger.info("=" * 80)

        # 컴포넌트 초기화
        db_manager, forecast_saver, predictor = initialize_components(logger)

        # 예측 실행
        success = run_prediction(split_date, db_manager, forecast_saver, predictor, logger, date_source)

        if success:
            logger.info("=" * 80)
            logger.info("EMS Prediction Scheduler Completed Successfully")
            logger.info("=" * 80)
            return 0
        else:
            logger.error("=" * 80)
            logger.error("EMS Prediction Scheduler Failed")
            logger.error("=" * 80)
            return 1

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"Fatal Error: {e}", exc_info=True)
        logger.error("=" * 80)
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
