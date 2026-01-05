# core/exceptions.py
"""
계층화된 예외 처리 시스템

예외 계층 구조:
- SolarAPIException (최상위 기본 예외)
  - DatabaseError (데이터베이스 관련)
    - ConnectionError (연결 실패)
    - QueryError (쿼리 실행 실패)
  - DataProcessingError (데이터 처리 관련)
    - ValidationError (데이터 검증 실패)
    - TransformError (데이터 변환 실패)
  - PredictionError (예측 관련)
    - ModelLoadError (모델 로드 실패)
    - InferenceError (추론 실패)
  - PostProcessingError (후처리 관련)
  - WeatherAPIError (외부 API 관련)
"""

from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class SolarAPIException(Exception):
    """
    Solar API 최상위 기본 예외 클래스

    모든 커스텀 예외는 이 클래스를 상속받습니다.
    """
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        """
        Args:
            message: 에러 메시지
            error_code: 에러 코드 (예: "DB001", "PRED002")
            details: 추가 상세 정보
            original_exception: 원본 예외 (체이닝용)
        """
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.original_exception = original_exception

        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """예외 정보를 딕셔너리로 반환 (API 응답용)"""
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details
        }

    def log_error(self, level: str = "ERROR"):
        """예외를 로깅"""
        log_func = getattr(logger, level.lower(), logger.error)
        log_func(
            f"[{self.error_code}] {self.message}",
            extra={"details": self.details},
            exc_info=self.original_exception is not None
        )


# ============================================================
# 데이터베이스 관련 예외
# ============================================================

class DatabaseError(SolarAPIException):
    """데이터베이스 관련 오류 (기본)"""
    def __init__(
        self,
        message: str,
        error_code: str = "DB000",
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        super().__init__(message, error_code, details, original_exception)


class ConnectionError(DatabaseError):
    """데이터베이스 연결 실패"""
    def __init__(
        self,
        message: str,
        host: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        details = details or {}
        if host:
            details["host"] = host
        super().__init__(message, "DB001", details, original_exception)


class QueryError(DatabaseError):
    """쿼리 실행 실패"""
    def __init__(
        self,
        message: str,
        query: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        details = details or {}
        if query:
            details["query"] = query[:200]  # 쿼리 일부만 저장
        super().__init__(message, "DB002", details, original_exception)


# ============================================================
# 데이터 처리 관련 예외
# ============================================================

class DataProcessingError(SolarAPIException):
    """데이터 전처리 관련 오류 (기본)"""
    def __init__(
        self,
        message: str,
        error_code: str = "DP000",
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        super().__init__(message, error_code, details, original_exception)


class ValidationError(DataProcessingError):
    """데이터 검증 실패"""
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        expected: Optional[Any] = None,
        actual: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        details = details or {}
        if field:
            details["field"] = field
        if expected is not None:
            details["expected"] = str(expected)
        if actual is not None:
            details["actual"] = str(actual)
        super().__init__(message, "DP001", details, original_exception)


class TransformError(DataProcessingError):
    """데이터 변환 실패"""
    def __init__(
        self,
        message: str,
        transform_type: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        details = details or {}
        if transform_type:
            details["transform_type"] = transform_type
        super().__init__(message, "DP002", details, original_exception)


# ============================================================
# 예측 관련 예외
# ============================================================

class PredictionError(SolarAPIException):
    """예측 관련 오류 (기본)"""
    def __init__(
        self,
        message: str,
        error_code: str = "PRED000",
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        super().__init__(message, error_code, details, original_exception)


class ModelLoadError(PredictionError):
    """모델 로드 실패"""
    def __init__(
        self,
        message: str,
        model_path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        details = details or {}
        if model_path:
            details["model_path"] = model_path
        super().__init__(message, "PRED001", details, original_exception)


class InferenceError(PredictionError):
    """모델 추론 실패"""
    def __init__(
        self,
        message: str,
        model_name: Optional[str] = None,
        input_shape: Optional[tuple] = None,
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        details = details or {}
        if model_name:
            details["model_name"] = model_name
        if input_shape:
            details["input_shape"] = str(input_shape)
        super().__init__(message, "PRED002", details, original_exception)


# ============================================================
# 후처리 관련 예외
# ============================================================

class PostProcessingError(SolarAPIException):
    """후처리 관련 오류"""
    def __init__(
        self,
        message: str,
        error_code: str = "POST000",
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        super().__init__(message, error_code, details, original_exception)


# ============================================================
# 외부 API 관련 예외
# ============================================================

class WeatherAPIError(SolarAPIException):
    """기상 API 관련 오류"""
    def __init__(
        self,
        message: str,
        error_code: str = "API000",
        api_endpoint: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        details = details or {}
        if api_endpoint:
            details["api_endpoint"] = api_endpoint
        if status_code:
            details["status_code"] = status_code
        super().__init__(message, error_code, details, original_exception)