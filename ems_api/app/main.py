from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta
import sys
import warnings
import os
import random
import numpy as np
import torch
import pandas as pd

# 재현 가능한 결과를 위한 환경변수 설정 (반드시 다른 import 전에)
os.environ['PYTHONHASHSEED'] = '42'
os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'

# PyTorch Lightning 경고 무시
warnings.filterwarnings('ignore', category=UserWarning, module='pytorch_lightning')
warnings.filterwarnings('ignore', category=UserWarning, module='torch.utils.data.dataloader')

from app.core.db import DatabaseManager
from app.core.db_saver import ForecastSaver
from app.utils.model_loader import ModelLoader
from app.models.predictor import PowerPredictor
from app.utils.config import config
from app.core.prediction_pipeline import run_prediction_pipeline


def set_global_seed(seed=42):
    """
    전역 시드 고정 (서버 시작 시 1회 실행)

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
    # PyTorch 1.8+ 추가 설정
    torch.use_deterministic_algorithms(True, warn_only=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('ems_api.log', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title="EMS Power Prediction API",
    description="전력 사용량 예측 API - TFT 모델 기반",
    version="1.0.0"
)

# 전역 변수
db_manager = None
forecast_saver = None
model_components = None
predictor = None


class PredictionResponse(BaseModel):
    """예측 응답 모델"""
    status: str
    message: str
    prediction_count: int
    predictions: Optional[list] = None


class HealthResponse(BaseModel):
    """헬스체크 응답 모델"""
    status: str
    database: str
    model: str
    timestamp: str


@app.on_event("startup")
async def startup_event():
    """서버 시작 시 모델 및 DB 연결 초기화"""
    global db_manager, forecast_saver, model_components, predictor

    try:
        logger.info("="*80)
        logger.info("Starting EMS API server...")
        logger.info("="*80)

        # 재현 가능한 결과를 위해 전역 시드 고정
        logger.info("[Startup] Setting global random seed to 42...")
        set_global_seed(42)
        logger.info("[Startup]  Global random seed fixed to 42")

        # 데이터베이스 매니저 초기화
        logger.info("[Startup] Initializing Database manager...")
        db_manager = DatabaseManager()
        logger.info(f"[Startup]  Database manager initialized")

        # DB 연결 테스트
        logger.info("[Startup] Testing database connection...")
        if db_manager.test_connection():
            logger.info("[Startup]  Database connection test passed")
        else:
            logger.error("[Startup] [ERROR] Database connection test failed")
            raise Exception("Database connection test failed")

        # ForecastSaver 초기화
        logger.info("[Startup] Initializing ForecastSaver...")
        forecast_saver = ForecastSaver()
        logger.info("[Startup]  ForecastSaver initialized")

        # 모델 로드 (기본값: work_model 사용)
        logger.info("[Startup] Loading model components...")
        model_loader = ModelLoader(has_work_calendar=True)  # 기본적으로 work_model 로드
        model_components = model_loader.load_all()
        logger.info("[Startup]  Model components loaded successfully")

        # Predictor 초기화
        logger.info("[Startup] Initializing PowerPredictor...")
        predictor = PowerPredictor(model_components, has_work_calendar=True)
        logger.info("[Startup]  PowerPredictor initialized")

        logger.info("="*80)
        logger.info("[Startup]  EMS API server started successfully ")
        logger.info("="*80)

    except Exception as e:
        logger.error("="*80)
        logger.error(f"[Startup] [ERROR][ERROR][ERROR] Failed to start server: {e}", exc_info=True)
        logger.error("="*80)
        raise


@app.get("/", tags=["Root"])
async def root():
    """루트 엔드포인트"""
    return {
        "message": "EMS Power Prediction API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/api/health",
            "predict": "/api/igns/v1/smarteye/predict",
            "model_info": "/api/model/info"
        }
    }


@app.get("/api/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """헬스체크 엔드포인트"""
    db_status = "connected" if db_manager and db_manager.test_connection() else "disconnected"
    model_status = "loaded" if model_components is not None else "not loaded"

    # KST 기준 현재 시간
    kst = ZoneInfo("Asia/Seoul")
    timestamp = datetime.now(kst).isoformat()

    return HealthResponse(
        status="healthy" if db_status == "connected" and model_status == "loaded" else "unhealthy",
        database=db_status,
        model=model_status,
        timestamp=timestamp
    )


@app.get("/debug/table-info", tags=["Debug"])
async def get_table_info(days: int = 7):
    """
    DB 테이블 데이터 존재 여부 및 통계 확인 (디버깅용)

    Args:
        days: 확인할 최근 일수 (기본 7일)

    Returns:
        테이블 정보 및 통계
    """
    try:
        # KST 기준 현재 날짜 계산
        kst = ZoneInfo("Asia/Seoul")
        reference_date = datetime.now(kst)

        info = db_manager.check_table_data(days=days, reference_date=reference_date)
        return {
            "status": "success",
            "data": info
        }
    except Exception as e:
        logger.error(f"Failed to get table info: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/model/info", tags=["Model"])
async def get_model_info():
    """모델 정보 조회"""
    try:
        if model_components is None:
            raise HTTPException(status_code=500, detail="Model not loaded")

        model_loader = ModelLoader()
        model_loader.model_config = model_components['config']
        model_loader.past_cols = model_components['past_cols']
        model_loader.future_cols = model_components['future_cols']

        info = model_loader.get_model_info()

        return {
            "status": "success",
            "model_info": info
        }

    except Exception as e:
        logger.error(f"Failed to get model info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def calculate_split_date(target_date: Optional[str] = None) -> str:
    """
    split_date 계산 (공통 함수)

    Args:
        target_date: 예측 기준 날짜 (YYYY-MM-DD 형식, Optional)
                     - 입력하면: 해당 날짜를 split_date로 사용
                     - 입력 안하면: 오늘 날짜(KST)를 자동으로 split_date로 사용

    Returns:
        str: 'YYYY-MM-DD' 형식의 날짜 문자열
    """
    kst = ZoneInfo("Asia/Seoul")

    if target_date:
        # 입력된 날짜 사용
        split_date = target_date
        logger.info(f"[날짜 설정] 입력된 날짜 사용: {split_date}")
    else:
        # 오늘 날짜 자동 생성
        today = datetime.now(kst).date()
        split_date = today.strftime('%Y-%m-%d')
        logger.info(f"[날짜 설정] 오늘 날짜 자동 생성: {split_date}")

    return split_date


@app.post("/api/igns/v1/smarteye/predict", response_model=PredictionResponse, tags=["Prediction"])
async def predict_power_consumption(target_date: Optional[str] = None):
    """
    전력 사용량 예측 및 DB 저장

    Args:
        target_date: 예측 기준 날짜 (YYYY-MM-DD 형식, Optional)
                     - 입력하면: 해당 날짜를 split_date로 사용
                     - 입력 안하면: 오늘 날짜(KST)를 자동으로 split_date로 사용

    Returns:
        PredictionResponse: 예측 결과 (hourly, daily 모두 DB 저장)
    """
    try:
        # 날짜 계산 (공통 함수 사용)
        split_date = calculate_split_date(target_date)

        logger.info("="*80)
        logger.info(f"[PREDICT START] split_date: {split_date}")

        # 공통 예측 파이프라인 실행
        result = run_prediction_pipeline(
            split_date=split_date,
            db_manager=db_manager,
            forecast_saver=forecast_saver,
            predictor=predictor
        )

        # API 응답 생성
        predictions_list = [
            {
                "datetime": row['ymdhms'].isoformat() if hasattr(row['ymdhms'], 'isoformat') else str(row['ymdhms']),
                "predicted_kwh": float(row['사용량(kWh)'])
            }
            for _, row in result['predictions_hourly'].iterrows()
        ]

        logger.info(f"[PREDICT END] SUCCESS")
        logger.info("="*80)

        return PredictionResponse(
            status="success",
            message=f"Prediction completed. Hourly: {result['hourly_saved']} records, Daily: {result['daily_saved']} records saved.",
            prediction_count=len(result['predictions_hourly']),
            predictions=predictions_list
        )

    except HTTPException as he:
        logger.error(f"[PREDICT END] HTTP Exception: {he.detail}")
        logger.info("="*80)
        raise he
    except ValueError as ve:
        logger.error(f"[PREDICT END] Value Error: {ve}")
        logger.info("="*80)
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"[PREDICT END] FAILED: {e}", exc_info=True)
        logger.info("="*80)
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
