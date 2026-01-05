"""
통합 데이터 집계 API 엔드포인트
하나의 날짜 입력으로 Solar Power, ESS Charge, Power Usage 모두 처리
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Optional
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta

from app.models.schemas import AggregationResponse
from app.services.solar_power_service import get_solar_power_service, SolarPowerService
from app.services.power_usage_service import get_power_usage_service, PowerUsageService
from app.services.ess_predict_service import get_ess_predict_service, ESSPredictService
from app.services.ess_charge_service import get_ess_charge_service, ESSChargeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Data Aggregation"])

@router.post("/aggregate", response_model=Dict[str, AggregationResponse])
async def aggregate_all_data(
    target_date: Optional[str] = Query(None, description="대상 날짜 (YYYY-MM-DD) - 미입력시 오늘 날짜 - 2개월 자동 계산"),
    solar_service: SolarPowerService = Depends(get_solar_power_service),
    power_service: PowerUsageService = Depends(get_power_usage_service),
    ess_predict_service: ESSPredictService = Depends(get_ess_predict_service),
    ess_charge_service: ESSChargeService = Depends(get_ess_charge_service)
):
    """
    Solar Power, Power Usage, ESS Predict, ESS Charge 모두 집계 및 적재

    **target_date 입력 방식**:
    - 입력함: 해당 날짜로 처리 (YYYY-MM-DD 형식)
    - 미입력: 자동으로 오늘 날짜 - 2개월 계산

    **예시**:
    - `POST /api/igns/v1/ESS/aggregate?target_date=2025-09-17` → 2025-09-17 처리
    - `POST /api/igns/v1/ESS/aggregate` → 오늘 - 2개월 자동 계산

    **응답**: 각 서비스별 처리 결과를 반환
    """
    try:
        # target_date 계산 또는 입력값 사용
        kst = ZoneInfo("Asia/Seoul")
        today = datetime.now(kst).date()

        if target_date:
            # 입력된 날짜 사용 (형식 검증)
            try:
                datetime.strptime(target_date, "%Y-%m-%d")
                logger.info(f"📅 [날짜 설정] 입력된 날짜 사용: {target_date}")
                date_source = "입력된 날짜"
            except ValueError:
                logger.error(f"❌ [날짜 설정] 잘못된 날짜 형식: {target_date}")
                raise HTTPException(
                    status_code=400,
                    detail=f"잘못된 날짜 형식입니다. YYYY-MM-DD 형식으로 입력해주세요. (입력값: {target_date})"
                )
        else:
            # 오늘 날짜 - 2개월 자동 계산
            two_months_ago = today - relativedelta(months=2)
            target_date = two_months_ago.strftime("%Y-%m-%d")
            logger.info(f"📅 [날짜 설정] 오늘 날짜 - 2개월 자동 계산: {target_date}")
            date_source = "자동 계산 (오늘 - 2개월)"

        logger.info(f"📅 [날짜 설정] 오늘: {today.strftime('%Y-%m-%d')}, 처리 대상 날짜: {target_date} ({date_source})")
        logger.info(f"📊 [통합 집계] 모든 데이터 집계 시작 - {target_date}")

        results = {}

        # Solar Power 집계
        try:
            solar_result = await solar_service.aggregate_and_insert(
                target_date=target_date
            )
            results["solar_power"] = AggregationResponse(**solar_result)
            logger.info(f"✅ [Solar Power] 완료")
        except Exception as e:
            logger.error(f"❌ [Solar Power] 실패: {str(e)}")
            results["solar_power"] = AggregationResponse(
                success=False,
                target_date=target_date,
                message=f"Solar Power 집계 실패: {str(e)}"
            )

        # Power Usage 집계
        try:
            power_result = await power_service.aggregate_and_insert(
                target_date=target_date
            )
            results["power_usage"] = AggregationResponse(**power_result)
            logger.info(f"✅ [Power Usage] 완료")
        except Exception as e:
            logger.error(f"❌ [Power Usage] 실패: {str(e)}")
            results["power_usage"] = AggregationResponse(
                success=False,
                target_date=target_date,
                message=f"Power Usage 집계 실패: {str(e)}"
            )

        # ESS Predict 집계
        try:
            ess_predict_result = await ess_predict_service.aggregate_and_insert(
                target_date=target_date
            )
            results["ess_predict"] = AggregationResponse(**ess_predict_result)
            logger.info(f"✅ [ESS Predict] 완료")
        except Exception as e:
            logger.error(f"❌ [ESS Predict] 실패: {str(e)}")
            results["ess_predict"] = AggregationResponse(
                success=False,
                target_date=target_date,
                message=f"ESS Predict 집계 실패: {str(e)}"
            )

        # ESS Charge 집계
        try:
            ess_charge_result = await ess_charge_service.aggregate_and_insert(
                target_date=target_date
            )
            results["ess_charge"] = AggregationResponse(**ess_charge_result)
            logger.info(f"✅ [ESS Charge] 완료")
        except Exception as e:
            logger.error(f"❌ [ESS Charge] 실패: {str(e)}")
            results["ess_charge"] = AggregationResponse(
                success=False,
                target_date=target_date,
                message=f"ESS Charge 집계 실패: {str(e)}"
            )

        logger.info(f"📊 [통합 집계] 완료 - {target_date}")
        return results

    except Exception as e:
        logger.error(f"❌ [통합 집계] API 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")
