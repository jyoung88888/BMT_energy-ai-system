import pymysql
import asyncio
import logging
from typing import Dict, Any, List
from contextlib import asynccontextmanager
from app.core.config import settings

logger = logging.getLogger(__name__)

class DatabaseManager:
    """데이터베이스 연결 및 쿼리 관리 클래스"""

    def __init__(self):
        self.db_config = settings.database_config

    def get_connection(self):
        """데이터베이스 연결 생성"""
        try:
            connection = pymysql.connect(**self.db_config)
            return connection
        except Exception as e:
            logger.error(f"데이터베이스 연결 실패: {str(e)}")
            raise Exception(f"데이터베이스 연결 실패: {str(e)}")

    @asynccontextmanager
    async def get_async_connection(self):
        """비동기 데이터베이스 연결 컨텍스트 매니저"""
        connection = None
        try:
            loop = asyncio.get_event_loop()
            connection = await loop.run_in_executor(None, self.get_connection)
            yield connection
        finally:
            if connection:
                connection.close()

    async def test_connection(self) -> bool:
        """데이터베이스 연결 테스트"""
        try:
            async with self.get_async_connection() as connection:
                cursor = connection.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                cursor.close()
                return result[0] == 1
        except Exception as e:
            logger.error(f"데이터베이스 연결 테스트 실패: {str(e)}")
            return False

# 전역 데이터베이스 매니저 인스턴스
db_manager = DatabaseManager()

async def init_db():
    """데이터베이스 초기화"""
    logger.info("데이터베이스 연결 테스트 중...")

    result = await db_manager.test_connection()

    if result:
        logger.info("✅ 데이터베이스 연결 성공")
    else:
        logger.error("❌ 데이터베이스 연결 실패")
        raise Exception("데이터베이스 초기화 실패")

async def get_db_manager() -> DatabaseManager:
    """데이터베이스 매니저 의존성 주입"""
    return db_manager
