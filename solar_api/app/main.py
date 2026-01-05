from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.core.config import settings, api_config

# 로깅 설정
logging.basicConfig(level=settings.LOG_LEVEL, format=settings.LOG_FORMAT)
logger = logging.getLogger(__name__)

# FastAPI 앱 초기화
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description=settings.API_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=api_config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=api_config.CORS_METHODS,
    allow_headers=api_config.CORS_HEADERS,
)

@app.get("/")
async def root():
    """루트 경로 - API 정보 제공"""
    return {
        "message": "Solar Energy Prediction API",
        "version": settings.API_VERSION,
        "docs": "/docs",
        "redoc": "/redoc",
        "info": "/api/info",
        "health": "/api/health",
        "endpoints": {
            "predict_ensemble": "POST /api/igns/v1/solar/predict",
            "verify_predictions": "GET /api/verify/predictions/{factory_name}"
        }
    }

@app.on_event("startup")
async def startup_event():
    """서버 시작 시 초기화"""
    logger.info("Starting Solar Prediction API...")
    logger.info("✅ 태양광 예측 API 서버가 시작되었습니다.")

@app.get("/api/health")
async def health_check():
    """서비스 상태 확인"""
    return {
        "status": "healthy",
        "service": "Solar Prediction API",
        "version": settings.API_VERSION
    }

@app.get("/api/info")
async def get_api_info():
    """API 정보 조회"""
    return {
        "title": settings.API_TITLE,
        "version": settings.API_VERSION,
        "description": settings.API_DESCRIPTION,
        "endpoints": {
            "root": "GET /",
            "health": "GET /api/health",
            "info": "GET /api/info",
            "predict_ensemble": "POST /api/igns/v1/solar/predict",
            "verify_predictions": "GET /api/verify/predictions/{factory_name}",
            "docs": "/docs",
            "redoc": "/redoc"
        },
        "factory_mapping": settings.factory_id_mapping
    }

@app.get("/api/verify/predictions/{factory_name}")
async def verify_saved_predictions(
    factory_name: str,
    start_time: str,
    end_time: str
):
    """
    저장된 예측 결과 확인

    Args:
        factory_name: 공장명 (FactoryA, FactoryB, FactoryC)
        start_time: 시작 시간 (YYYY-MM-DD HH:MM:SS)
        end_time: 종료 시간 (YYYY-MM-DD HH:MM:SS)

    Returns:
        저장된 예측 데이터
    """
    try:
        from app.core.db_saver import get_db_saver

        # 공장명 검증
        if factory_name not in settings.factory_id_mapping:
            raise HTTPException(
                status_code=400,
                detail=f"잘못된 공장명입니다. 사용 가능한 값: {list(settings.factory_id_mapping.keys())}"
            )

        db_saver = await get_db_saver()
        df = await db_saver.verify_saved_predictions(factory_name, start_time, end_time)

        if df.empty:
            return {
                "status": "success",
                "factory": factory_name,
                "time_range": f"{start_time} ~ {end_time}",
                "message": "해당 기간에 저장된 예측 결과가 없습니다.",
                "data": []
            }

        # DataFrame을 dict로 변환
        data = df.to_dict(orient='records')

        return {
            "status": "success",
            "factory": factory_name,
            "time_range": f"{start_time} ~ {end_time}",
            "record_count": len(df),
            "id_range": f"{df['id'].min()} ~ {df['id'].max()}",
            "data": data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"예측 결과 확인 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"예측 결과 확인 중 오류가 발생했습니다: {str(e)}")

@app.post("/api/igns/v1/solar/predict")
async def predict_solar_ensemble(target_date_str: str = None):
    """
    앙상블 태양광 발전량 예측 (여러 시점 예측 후 평균)

    날짜를 입력하거나, 입력하지 않으면 자동으로 오늘 날짜를 기준으로 예측을 수행합니다.

    Args:
        target_date_str: 예측할 날짜 (YYYY-MM-DD 형식, 선택사항)

    Process:
        1. 입력 날짜가 있으면 해당 날짜, 없으면 오늘 날짜를 target_date로 설정
        2. 넓은 범위의 데이터 조회 (태양광 168시간, 기상 47시간) - 병렬 처리
        3. 슬라이딩 윈도우로 여러 시퀀스 생성
        4. 각 시퀀스별 예측 수행
        5. 목표 시간대에 대해 앙상블 평균
        6. 결과를 데이터베이스에 저장 (시간별 + 일간 합계)
    """
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from app.core.prediction_pipeline import run_prediction_async, _parse_target_date

        # 날짜 파싱
        kst = ZoneInfo("Asia/Seoul")
        try:
            today = _parse_target_date(target_date_str, kst)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # 파이프라인 실행
        result = await run_prediction_async(today)

        logger.info("✅ 앙상블 태양광 발전량 예측 완료")
        return result

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"데이터 검증 오류: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"앙상블 예측 파이프라인 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"앙상블 예측 중 오류가 발생했습니다: {str(e)}")