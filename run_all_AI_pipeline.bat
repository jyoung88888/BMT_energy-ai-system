@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM ============================================================
REM BMT AI 파이프라인 통합 배치 실행
REM
REM 전제조건: 기상/전력/태양광 원본 데이터가 DB에 이미 적재된 상태
REM          (weather 수집 스크립트는 별도 스케줄로 실행)
REM
REM 실행 순서:
REM   1단계: 태양광 발전량 예측 (solar_api)
REM   2단계: 전력 사용량 예측 (ems_api)
REM   3단계: ESS 충전량 예측 (ess_ai_table_api)
REM   4단계: AI 종합 테이블 집계 (ess_ai_table_api)
REM
REM 사용법:
REM   run_all_AI_pipeline.bat                    (오늘 날짜 자동)
REM   run_all_AI_pipeline.bat 2025-01-14         (특정 날짜 지정)
REM ============================================================

REM 기본 경로 설정
set "BASE_DIR=F:\2.프로젝트\BMT\git"
set "TARGET_DATE=%~1"

REM Python 가상환경 경로 (운영환경 배포 시 실제 경로로 변경)
set "VENV_DIR=C:\path\to\venv"
set "PYTHON=%VENV_DIR%\Scripts\python.exe"

REM 가상환경 존재 확인
if not exist "%PYTHON%" (
    echo [오류] Python 가상환경을 찾을 수 없습니다: %PYTHON%
    echo        VENV_DIR 경로를 확인하세요.
    exit /b 1
)

REM 로그 디렉토리 생성
set "LOG_DIR=%BASE_DIR%\pipeline_logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM 로그 파일명 (실행 시간 기반)
for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set "TODAY=%%a-%%b-%%c"
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set "NOW_TIME=%%a%%b"
set "LOG_FILE=%LOG_DIR%\pipeline_%TODAY%_%NOW_TIME%.log"

REM 실행 시작
call :LOG "============================================================"
call :LOG "BMT AI 파이프라인 통합 실행 시작"
call :LOG "실행 시간: %date% %time%"
if defined TARGET_DATE (
    call :LOG "지정 날짜: %TARGET_DATE%"
    set "DATE_OPT=--date %TARGET_DATE%"
) else (
    call :LOG "날짜: 자동 (오늘)"
    set "DATE_OPT="
)
call :LOG "============================================================"

REM 전체 성공/실패 추적
set "FAIL_COUNT=0"
set "FAIL_LIST="

REM ============================================================
REM [1단계] 태양광 발전량 예측
REM ============================================================
call :LOG ""
call :LOG "[1/4] 태양광 발전량 예측 (schedule_solar_AI)"
call :LOG "------------------------------------------------------------"
cd /d "%BASE_DIR%\solar_api"
"%PYTHON%" schedule_solar_AI.py %DATE_OPT%
if !errorlevel! NEQ 0 (
    call :LOG "[1/4] !! 실패 - 태양광 예측 실패"
    set /a FAIL_COUNT+=1
    set "FAIL_LIST=!FAIL_LIST! [1]태양광예측"
) else (
    call :LOG "[1/4] OK 완료 - 태양광 예측 성공"
)

REM ============================================================
REM [2단계] 전력 사용량 예측
REM ============================================================
call :LOG ""
call :LOG "[2/4] 전력 사용량 예측 (schedule_ems_AI)"
call :LOG "------------------------------------------------------------"
cd /d "%BASE_DIR%\ems_api"
"%PYTHON%" schedule_ems_AI.py %DATE_OPT%
if !errorlevel! NEQ 0 (
    call :LOG "[2/4] !! 실패 - 전력 사용량 예측 실패"
    set /a FAIL_COUNT+=1
    set "FAIL_LIST=!FAIL_LIST! [2]전력예측"
) else (
    call :LOG "[2/4] OK 완료 - 전력 사용량 예측 성공"
)

REM ============================================================
REM [3단계] ESS 충전량 예측
REM ============================================================
call :LOG ""
call :LOG "[3/4] ESS 충전량 예측 (schedule_ess_AI)"
call :LOG "------------------------------------------------------------"
cd /d "%BASE_DIR%\ess_ai_table_api"
"%PYTHON%" schedule_ess_AI.py %DATE_OPT%
if !errorlevel! NEQ 0 (
    call :LOG "[3/4] !! 실패 - ESS 충전량 예측 실패"
    set /a FAIL_COUNT+=1
    set "FAIL_LIST=!FAIL_LIST! [3]ESS예측"
) else (
    call :LOG "[3/4] OK 완료 - ESS 충전량 예측 성공"
)

REM ============================================================
REM [4단계] AI 종합 테이블 집계
REM ============================================================
call :LOG ""
call :LOG "[4/4] AI 종합 테이블 집계 (schedule_AI_log_table)"
call :LOG "------------------------------------------------------------"
cd /d "%BASE_DIR%\ess_ai_table_api"
"%PYTHON%" schedule_AI_log_table.py %DATE_OPT%
if !errorlevel! NEQ 0 (
    call :LOG "[4/4] !! 실패 - AI 종합 집계 실패"
    set /a FAIL_COUNT+=1
    set "FAIL_LIST=!FAIL_LIST! [4]종합집계"
) else (
    call :LOG "[4/4] OK 완료 - AI 종합 집계 성공"
)

REM ============================================================
REM 최종 결과 요약
REM ============================================================
call :LOG ""
call :LOG "============================================================"
call :LOG "파이프라인 실행 완료"
call :LOG "종료 시간: %date% %time%"
call :LOG "------------------------------------------------------------"

if !FAIL_COUNT! EQU 0 (
    call :LOG "결과: 전체 성공 (4/4)"
    call :LOG "============================================================"
    exit /b 0
) else (
    set /a SUCCESS_COUNT=4-!FAIL_COUNT!
    call :LOG "결과: 일부 실패 (!SUCCESS_COUNT!/4 성공, !FAIL_COUNT!건 실패)"
    call :LOG "실패 목록:!FAIL_LIST!"
    call :LOG "============================================================"
    call :LOG ""
    call :LOG "** 실패한 단계를 개별 재실행하려면:"
    call :LOG "   각 프로젝트 폴더에서 해당 스크립트를 --date 옵션으로 실행하세요."
    exit /b 1
)

REM ============================================================
REM 로그 출력 함수
REM ============================================================
:LOG
echo %~1
echo %~1 >> "%LOG_FILE%"
goto :eof
