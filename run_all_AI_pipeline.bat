@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM BMT AI ���������� ���� ��ġ ����
REM
REM ��������: ���/����/�¾籤 ���� �����Ͱ� DB�� �̹� ����� ����
REM          (weather ���� ��ũ��Ʈ�� ���� �����ٷ� ����)
REM
REM ���� ����:
REM   1�ܰ�: �¾籤 ������ ���� (solar_api)
REM   2�ܰ�: ���� ��뷮 ���� (ems_api)
REM   3�ܰ�: ESS ������ ���� (ess_api)
REM   4�ܰ�: AI ���� ���̺� ���� (ess_api)
REM
REM ����:
REM   run_all_AI_pipeline.bat                    (���� ��¥ �ڵ�)
REM   run_all_AI_pipeline.bat 2025-01-14         (Ư�� ��¥ ����)
REM ============================================================

REM �⺻ ��� ����
set "BASE_DIR=C:\Users\Administrator\Desktop\api\AI_scripts"
set "TARGET_DATE=%~1"

REM Python ����ȯ�� ��� (�ȯ�� ���� �� ���� ��η� ����)
set "PYTHON=C:\Users\Administrator\Desktop\api\solar_env\python.exe"

REM ����ȯ�� ���� Ȯ��
if not exist "%PYTHON%" (
    echo [����] Python ����ȯ���� ã�� �� �����ϴ�: %PYTHON%
    echo        PYTHON ��θ� Ȯ���ϼ���.
    exit /b 1
)

REM ���� ����
echo ============================================================
echo BMT AI ���������� ���� ���� ����
echo ���� �ð�: %date% %time%
if defined TARGET_DATE (
    echo ���� ��¥: %TARGET_DATE%
    set "DATE_OPT=--date %TARGET_DATE%"
) else (
    echo ��¥: �ڵ� (����)
    set "DATE_OPT="
)
echo ============================================================

REM ��ü ����/���� ����
set "FAIL_COUNT=0"
set "FAIL_LIST="

REM ============================================================
REM [1�ܰ�] �¾籤 ������ ����
REM ============================================================
echo.
echo [1/4] �¾籤 ������ ���� (schedule_solar_AI)
echo ------------------------------------------------------------
cd /d "%BASE_DIR%\solar_api"
"%PYTHON%" schedule_solar_AI.py %DATE_OPT%
if !errorlevel! NEQ 0 (
    echo [1/4] !! ���� - �¾籤 ���� ����
    set /a FAIL_COUNT+=1
    set "FAIL_LIST=!FAIL_LIST! [1]�¾籤����"
) else (
    echo [1/4] OK �Ϸ� - �¾籤 ���� ����
)

REM ============================================================
REM [2�ܰ�] ���� ��뷮 ����
REM ============================================================
echo.
echo [2/4] ���� ��뷮 ���� (schedule_ems_AI)
echo ------------------------------------------------------------
cd /d "%BASE_DIR%\ems_api"
"%PYTHON%" schedule_ems_AI.py %DATE_OPT%
if !errorlevel! NEQ 0 (
    echo [2/4] !! ���� - ���� ��뷮 ���� ����
    set /a FAIL_COUNT+=1
    set "FAIL_LIST=!FAIL_LIST! [2]���¿���"
) else (
    echo [2/4] OK �Ϸ� - ���� ��뷮 ���� ����
)

REM ============================================================
REM [3�ܰ�] ESS ������ ����
REM ============================================================
echo.
echo [3/4] ESS ������ ���� (schedule_ess_AI)
echo ------------------------------------------------------------
cd /d "%BASE_DIR%\ess_api"
"%PYTHON%" schedule_ess_AI.py %DATE_OPT%
if !errorlevel! NEQ 0 (
    echo [3/4] !! ���� - ESS ������ ���� ����
    set /a FAIL_COUNT+=1
    set "FAIL_LIST=!FAIL_LIST! [3]ESS����"
) else (
    echo [3/4] OK �Ϸ� - ESS ������ ���� ����
)

REM ============================================================
REM [4�ܰ�] AI ���� ���̺� ����
REM ============================================================
echo.
echo [4/4] AI ���� ���̺� ���� (schedule_AI_log_table)
echo ------------------------------------------------------------
cd /d "%BASE_DIR%\ess_api"
"%PYTHON%" schedule_AI_log_table.py %DATE_OPT%
if !errorlevel! NEQ 0 (
    echo [4/4] !! ���� - AI ���� ���� ����
    set /a FAIL_COUNT+=1
    set "FAIL_LIST=!FAIL_LIST! [4]��������"
) else (
    echo [4/4] OK �Ϸ� - AI ���� ���� ����
)

REM ============================================================
REM ���� ��� ���
REM ============================================================
echo.
echo ============================================================
echo ���������� ���� �Ϸ�
echo ���� �ð�: %date% %time%
echo ------------------------------------------------------------

if !FAIL_COUNT! EQU 0 (
    echo ���: ��ü ���� (4/4)
    echo ============================================================
    exit /b 0
) else (
    set /a SUCCESS_COUNT=4-!FAIL_COUNT!
    echo ���: �Ϻ� ���� (!SUCCESS_COUNT!/4 ����, !FAIL_COUNT!�� ����)
    echo ���� ���:!FAIL_LIST!
    echo ============================================================
    echo.
    echo ** ������ �ܰ踦 ���� ������Ϸ���:
    echo    �� ������Ʈ �������� �ش� ��ũ��Ʈ�� --date �ɼ����� �����ϼ���.
    exit /b 1
)
