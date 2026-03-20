import os
from typing import Dict, Any
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """애플리케이션 설정"""

    # API 설정
    API_TITLE: str = "TB AI Data Aggregation API"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = "TB AI 테이블 데이터 집계 및 적재 API"

    # 데이터베이스 설정
    database_config: Dict[str, Any] = {
        'host': '192.168.213.250',
        'user': 'root',
        'password': 'OnDemand%Ai',
        'charset': 'utf8mb4',
        'database' : "db_energy"
    }

    # 테이블명 설정
    table_names: Dict[str, str] = {
        # 소스 테이블 - 태양 
        'solar_day': 'tb_solar_day',
        'weather_info': 'tb_weather_info',
        
        # 소스 테이블 - 전력 
        'smarteye_day' : 'tb_aggregate_smarteye_day',

        # 소스 테이블 - ESS 
        'bms_daily_stat': 'tb_nrt_bms_daily_stat',
        # AI 테이블
        'ai_solar_power': 'tb_ai_solar_power',
        'ai_ess_charge_amt': 'tb_ai_ess_charge_amt',
        'ai_pwr_usage': 'tb_ai_pwr_usage'
    }

    class Config:
        env_file = ".env"

# 전역 설정 인스턴스
settings = Settings()
