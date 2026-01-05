from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.config import settings
from app.core.database import init_db
from app.api.aggregate_endpoints import router as aggregate_router

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 시작/종료 이벤트"""
    # 시작 이벤트
    logger.info("🚀 애플리케이션 시작")
    try:
        await init_db()
        logger.info("✅ 데이터베이스 초기화 완료")
    except Exception as e:
        logger.error(f"❌ 데이터베이스 초기화 실패: {str(e)}")
        raise

    yield

    # 종료 이벤트
    logger.info("👋 애플리케이션 종료")

# FastAPI 앱 생성
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description=settings.API_DESCRIPTION,
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(aggregate_router, prefix="/api/igns/v1/ESS")  # 통합 엔드포인트

@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "message": "TB AI Data Aggregation API",
        "version": settings.API_VERSION,
        "description": "태양광, 전력 사용량, ESS 예측 데이터 통합 집계 API",
        "docs_url": "/docs",
        "endpoints": {
            "aggregate_all": "/api/igns/v1/ESS/aggregate - Solar Power, Power Usage, ESS Predict 통합 집계"
        }
    }

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {
        "status": "healthy",
        "message": "TB AI Data Aggregation API is running"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
