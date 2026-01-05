# Solar API 자동 예측 스케줄러 가이드

API 서버 없이 예측 로직을 직접 실행하는 자동화 스크립트입니다.

## 📁 관련 파일

### 1. `schedule_solar.py`
- **역할**: 태양광 예측 로직을 직접 실행하는 Python 스크립트
- **특징**: FastAPI 서버 없이 `predict_solar_ensemble()` 함수를 직접 호출
- **실행 방식**: `asyncio.run()`으로 비동기 함수 실행

### 2. `run_schedule_solar.bat`
- **역할**: Windows 작업 스케줄러에서 실행할 배치 파일
- **특징**: Anaconda 가상환경(bmt_solar) 자동 활성화 및 Python 스크립트 실행
- **환경**: `bmt_solar` conda 환경 사용

## 🚀 빠른 시작

### 수동 실행 테스트

#### 방법 1: 배치 파일 실행 (권장)
```bash
# 더블클릭하거나 CMD에서 실행
run_schedule_solar.bat
```

#### 방법 2: Python 스크립트 직접 실행
```bash
# Anaconda 환경 활성화
conda activate bmt_solar

# 프로젝트 디렉토리로 이동
cd "F:\2.프로젝트\[BMT] 수요 맞춤형AI\project\solar_api"

# 스크립트 실행
python schedule_solar.py

# 환경 비활성화
conda deactivate
```

## 🔧 동작 방식

### 전체 프로세스

```
┌─────────────────────────────────────────────────┐
│ run_schedule_solar.bat                          │
│                                                 │
│ 1. Anaconda bmt_solar 환경 활성화               │
│ 2. schedule_solar.py 실행                       │
│ 3. 환경 비활성화                                 │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│ schedule_solar.py                               │
│                                                 │
│ 1. app.main에서 predict_solar_ensemble import   │
│ 2. asyncio.run(predict_solar_ensemble())        │
│    ├─ 오늘 날짜 자동 계산 (KST)                 │
│    ├─ DB에서 데이터 조회                        │
│    ├─ 데이터 전처리 & 시퀀스 생성               │
│    ├─ AI 모델로 예측 (FactoryA/B/C)            │
│    ├─ 앙상블 평균 계산                          │
│    └─ DB에 결과 저장 (시간별 + 일간)           │
│ 3. 로그 파일 생성                               │
│    logs/schedule_predict_YYYYMMDD.log           │
└─────────────────────────────────────────────────┘
```

### 핵심 코드

```python
# schedule_solar.py의 핵심 부분

# 1. 예측 함수 직접 import
from app.main import predict_solar_ensemble

# 2. 비동기 함수 실행
result = await predict_solar_ensemble()

# 3. 결과 확인 및 로깅
if result and result.get('status') == 'success':
    logger.info(f"예측 날짜: {result.get('target_date')}")
    logger.info(f"저장된 레코드: {result['database_save']['hourly_total_records']}건")
```

## 📊 예측 결과

### 자동 처리되는 내용

1. **날짜 자동 설정**
   - 한국 표준시(KST) 기준 오늘 날짜
   - `datetime.now(ZoneInfo("Asia/Seoul")).date()`

2. **예측 범위**
   - 당일 00:00 ~ 23:00 (24시간)
   - 시간별 예측값 생성

3. **데이터베이스 저장**
   - `tb_solar_hour`: 시간별 예측 데이터 (FactoryA/B/C 각 24건)
   - `tb_solar_day`: 일간 합계 (FactoryA/B/C 각 1건)

4. **공장별 처리**
   - FactoryA (ID: 1)
   - FactoryB (ID: 13)
   - FactoryC (ID: 16)

## 📝 로그 확인

### 로그 파일 위치
```
F:\2.프로젝트\[BMT] 수요 맞춤형AI\project\solar_api\logs\schedule_predict_YYYYMMDD.log
```

### 로그 내용 예시

```log
2025-11-07 06:00:01 - INFO - ================================================================================
2025-11-07 06:00:01 - INFO - 🌞 태양광 예측 자동 실행 시작 (직접 실행 방식)
2025-11-07 06:00:01 - INFO - 📅 실행 시간: 2025-11-07 06:00:01
2025-11-07 06:00:01 - INFO - ================================================================================
2025-11-07 06:00:01 - INFO - 🔮 예측 로직 실행 중...
2025-11-07 06:00:05 - INFO - 📅 오늘 날짜 자동 설정 (KST): 20251107
2025-11-07 06:00:05 - INFO - 🌞 앙상블 태양광 발전량 예측 시작: 20251107
2025-11-07 06:00:10 - INFO - ✅ 데이터 조회 완료 - 태양광: 3820건, 기상: 47건
2025-11-07 06:02:30 - INFO - 🏭 FactoryA 시퀀스 생성 중...
2025-11-07 06:02:35 - INFO - 🏭 FactoryB 시퀀스 생성 중...
2025-11-07 06:02:40 - INFO - 🏭 FactoryC 시퀀스 생성 중...
2025-11-07 06:03:20 - INFO - 🔮 A동: 24개 시퀀스 배치 예측 중...
2025-11-07 06:03:25 - INFO - 🔮 B동: 24개 시퀀스 배치 예측 중...
2025-11-07 06:03:30 - INFO - 🔮 C동: 24개 시퀀스 배치 예측 중...
2025-11-07 06:03:35 - INFO - 🔄 앙상블 평균 시작...
2025-11-07 06:03:40 - INFO - ✅ 3개 공장, 앙상블 예측 완료
2025-11-07 06:03:45 - INFO - 💾 예측 결과 데이터베이스 저장 시작...
2025-11-07 06:03:50 - INFO - ✅ 시간별 데이터 저장 완료: {'FactoryA': 24, 'FactoryB': 24, 'FactoryC': 24}
2025-11-07 06:03:55 - INFO - 💾 일간 합계 tb_solar_day 저장 시작...
2025-11-07 06:04:00 - INFO - ✅ 일간 합계 저장 완료: {'FactoryA': 1234.56, 'FactoryB': 2345.67, 'FactoryC': 3456.78}
2025-11-07 06:04:00 - INFO - ================================================================================
2025-11-07 06:04:00 - INFO - ✅ 예측 실행 성공!
2025-11-07 06:04:00 - INFO - 📊 예측 날짜: 20251107
2025-11-07 06:04:00 - INFO - 📊 예측 범위: 2025-11-07 00:00:00 ~ 2025-11-07 23:00:00
2025-11-07 06:04:00 - INFO - 💾 시간별 데이터 저장: 72건
2025-11-07 06:04:00 - INFO -    - FactoryA: 24건
2025-11-07 06:04:00 - INFO -    - FactoryB: 24건
2025-11-07 06:04:00 - INFO -    - FactoryC: 24건
2025-11-07 06:04:00 - INFO - 💾 일간 합계 저장:
2025-11-07 06:04:00 - INFO -    - FactoryA: 1234.56
2025-11-07 06:04:00 - INFO -    - FactoryB: 2345.67
2025-11-07 06:04:00 - INFO -    - FactoryC: 3456.78
2025-11-07 06:04:00 - INFO - ================================================================================
2025-11-07 06:04:00 - INFO - 🎉 예측 완료 및 데이터베이스 저장 성공!
2025-11-07 06:04:00 - INFO - ================================================================================
2025-11-07 06:04:00 - INFO - ✅ 스크립트 정상 종료 (Exit Code: 0)
```

### 로그 실시간 모니터링 (PowerShell)

```powershell
# 오늘 로그 파일 실시간 확인
$today = Get-Date -Format "yyyyMMdd"
Get-Content "F:\2.프로젝트\[BMT] 수요 맞춤형AI\project\solar_api\logs\schedule_predict_$today.log" -Wait -Tail 20
```

## 🕐 Windows 작업 스케줄러 설정

### GUI 방식

#### 1단계: 작업 스케줄러 열기
- `Win + R` → `taskschd.msc` 입력 → Enter

#### 2단계: 새 작업 만들기
- 오른쪽 패널 → **"작업 만들기..."** 클릭

#### 3단계: 일반 탭
- **이름**: `Solar API 자동 예측`
- **설명**: `매일 태양광 발전량 예측 및 DB 저장 (API 서버 불필요)`
- ✅ `사용자의 로그온 여부에 관계없이 실행`
- ✅ `가장 높은 수준의 권한으로 실행`

#### 4단계: 트리거 탭
- **"새로 만들기"** 클릭
- **작업 시작**: `일정`
- **설정**: `매일`
- **시작 시간**: 원하는 시간 (예: `오전 6:00`)
- ✅ `사용`

#### 5단계: 동작 탭
- **"새로 만들기"** 클릭
- **동작**: `프로그램 시작`
- **프로그램/스크립트**:
  ```
  F:\2.프로젝트\[BMT] 수요 맞춤형AI\project\solar_api\run_schedule_solar.bat
  ```
- **시작 위치(선택 사항)**:
  ```
  F:\2.프로젝트\[BMT] 수요 맞춤형AI\project\solar_api
  ```

#### 6단계: 조건 탭
- ❌ `AC 전원을 사용할 때만 작업 시작` (체크 해제)
- ✅ `작업을 실행하기 위해 절전 모드 종료`

#### 7단계: 설정 탭
- ✅ `요청 시 작업 실행 허용`
- ✅ `작업이 실패하면 다시 시작 간격`: `1분`
- **다시 시작 시도 횟수**: `3`

#### 8단계: 저장
- **"확인"** 클릭
- 필요 시 Windows 사용자 암호 입력

### PowerShell 방식

```powershell
# 관리자 권한으로 PowerShell 실행

$action = New-ScheduledTaskAction `
    -Execute "F:\2.프로젝트\[BMT] 수요 맞춤형AI\project\solar_api\run_schedule_solar.bat" `
    -WorkingDirectory "F:\2.프로젝트\[BMT] 수요 맞춤형AI\project\solar_api"

$trigger = New-ScheduledTaskTrigger -Daily -At "06:00AM"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest

Register-ScheduledTask `
    -TaskName "Solar API 자동 예측" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "매일 태양광 발전량 예측 및 DB 저장 (API 서버 불필요)"
```

## 📊 성능 및 소요 시간

### 예상 실행 시간
- **데이터 조회**: 5-10초
- **전처리 및 시퀀스 생성**: 30-60초
- **AI 모델 예측**: 2-3분
- **앙상블 평균**: 10-20초
- **DB 저장**: 5-10초
- **총 소요 시간**: 약 3-5분

### 시스템 요구사항
- **Python**: 3.12+
- **RAM**: 최소 8GB (권장 16GB)
- **GPU**: 선택사항 (CPU로도 동작)
- **디스크**: 예측 모델 및 데이터용 최소 5GB

## ⚙️ 고급 설정

### 여러 시간대에 실행

하루에 여러 번 예측을 실행하려면 트리거를 추가하세요:

1. 오전 6시: 전날 데이터로 당일 예측
2. 오전 10시: 최신 데이터로 재예측
3. 오후 2시: 최종 재예측

각 시간대마다 작업 스케줄러에서 새 트리거를 추가합니다.

### 로그 파일 자동 정리

오래된 로그 파일을 자동으로 삭제하는 스크립트:

```python
# cleanup_logs.py
from pathlib import Path
from datetime import datetime, timedelta

LOG_DIR = Path("F:/2.프로젝트/[BMT] 수요 맞춤형AI/project/solar_api/logs")
KEEP_DAYS = 30  # 30일 이상 된 로그 삭제

cutoff = datetime.now() - timedelta(days=KEEP_DAYS)

for log_file in LOG_DIR.glob("schedule_predict_*.log"):
    if datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff:
        log_file.unlink()
        print(f"삭제됨: {log_file.name}")
```

## 🎯 장점 및 특징

### ✅ 장점

1. **API 서버 불필요**
   - `run.py` 실행할 필요 없음
   - HTTP 서버 관리 불필요

2. **단순한 구조**
   - 배치 파일 하나로 모든 것 처리
   - Conda 환경 자동 활성화/비활성화

3. **안정성**
   - HTTP 통신 오류 가능성 제거
   - 네트워크 의존성 없음

4. **빠른 실행**
   - 네트워크 오버헤드 없음
   - 직접 함수 호출로 빠른 처리

5. **자동 날짜 설정**
   - 날짜 입력 불필요
   - KST 타임존 자동 처리

### ⚠️ 제한사항

1. **수동 실행 번거로움**
   - 웹 브라우저에서 실행 불가
   - Postman 같은 도구로 테스트 불가

2. **외부 호출 불가**
   - 다른 시스템에서 API로 호출 못함
   - REST API 방식의 통합 불가

## 📚 참고 문서

- [main.py](app/main.py) - 예측 로직 구현
- [config.py](app/core/config.py) - 설정 파일
- [db_saver.py](app/core/db_saver.py) - DB 저장 로직
- [SCHEDULER_SETUP.md](SCHEDULER_SETUP.md) - 상세 설정 가이드

## 🆘 지원

문제가 발생하면:

1. 로그 파일 확인: `logs/schedule_predict_YYYYMMDD.log`
2. 수동으로 실행하여 오류 메시지 확인
3. Python 환경 및 패키지 버전 확인
4. 데이터베이스 연결 상태 확인

---

**마지막 업데이트**: 2025-11-07
**작성자**: Claude Code
**버전**: 1.0.0
