# BMT Energy AI System

수요 맞춤형 AI 기반 에너지 관리 시스템 - 전력 사용량, 태양광 발전량, ESS 예측 통합 플랫폼

## 목차
- [프로젝트 개요](#프로젝트-개요)
- [시스템 아키텍처](#시스템-아키텍처)
- [프로젝트 구조](#프로젝트-구조)
- [주요 컴포넌트](#주요-컴포넌트)
- [설치 및 실행](#설치-및-실행)
- [API 엔드포인트](#api-엔드포인트)
- [데이터 파이프라인](#데이터-파이프라인)

---

## 프로젝트 개요

이 프로젝트는 AI 기반 에너지 관리를 위한 통합 시스템으로, 다음과 같은 핵심 기능을 제공합니다:

- **전력 사용량 예측**: TFT(Temporal Fusion Transformer) 모델 기반 30분 단위 전력 소비 예측
- **태양광 발전량 예측**: 앙상블 모델 기반 태양광 에너지 생산량 예측
- **데이터 통합 집계**: 예측 데이터의 시간별/일별 자동 집계 및 저장
- **기상 데이터 수집**: 기상청 API를 통한 실시간 날씨 및 태양 위치 정보 수집
- **공휴일 관리**: 한국 공휴일 자동 등록 및 관리

### 핵심 특징
- FastAPI 기반 고성능 RESTful API 구조
- 딥러닝 모델(TFT, PyTorch) 활용
- MariaDB/MySQL 데이터베이스 연동
- 자동화된 스케줄링 및 배치 처리
- UPSERT 방식의 효율적인 데이터 저장

### 운영 방식
- **EMS/Solar**: FastAPI로 구성되어 있으나, 실제 운영 환경에서는 스케줄러 스크립트(`schedule_*.py`)를 통해 예측 로직을 직접 실행
- **ESS AI Table**: API 서버 방식으로 운영 (포트 8080)
- **Weather/Holiday**: 단독 스크립트로 실행

---

## 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                      External Data Sources                   │
│  - 기상청 API (날씨 예보)                                    │
│  - 전력 사용 데이터 (KEPCO)                                 │
│  - 태양광 발전 데이터                                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    Data Collection Layer                     │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ weather     │  │ holiday_api  │  │ Data Loaders │      │
│  │ (기상 수집)  │  │ (공휴일 등록)│  │              │      │
│  └─────────────┘  └──────────────┘  └──────────────┘      │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                        Database (MariaDB)                    │
│  - tb_kepco_pwr_consum_minutes (전력 사용 데이터)           │
│  - tb_weather_info (기상 데이터)                            │
│  - tb_holiday (공휴일 데이터)                               │
│  - tb_aggregate_* (집계 데이터)                             │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              Prediction Layer (Scheduler Scripts)            │
│  ┌────────────────────┐        ┌────────────────────┐      │
│  │  schedule_ems_AI   │        │ schedule_solar_AI  │      │
│  │  (전력 예측 실행)   │        │ (태양광 예측 실행) │      │
│  │  - TFT Model 호출  │        │ - Ensemble 호출    │      │
│  └────────────────────┘        └────────────────────┘      │
│  * FastAPI 코드 구조이나 스케줄러 스크립트로 직접 실행      │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    Aggregation Layer                         │
│  ┌──────────────────────────────────────────────────┐      │
│  │       schedule_ess_AI / ess_ai_table_api         │      │
│  │  (Solar + Power + ESS 통합 집계)                 │      │
│  │  - Hourly Aggregation                            │      │
│  │  - Daily Aggregation                             │      │
│  └──────────────────────────────────────────────────┘      │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  Result Storage (MariaDB)                    │
│  - 예측 결과 테이블 (시간별/일별 집계)                      │
│  - 대시보드 조회용 통합 데이터                              │
└─────────────────────────────────────────────────────────────┘

                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    Client Applications                       │
│  - Dashboard / Monitoring Tools                              │
│  - Energy Management System                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 프로젝트 구조

```
git/
├── ems_api/                    # 전력 사용량 예측 (FastAPI 구조)
│   ├── app/
│   │   ├── main.py            # FastAPI 애플리케이션 (개발용)
│   │   ├── core/              # 핵심 로직 (DB, 전처리, 후처리)
│   │   ├── models/            # 예측 모델
│   │   ├── utils/             # 유틸리티 (설정, 모델 로더)
│   │   └── weights/           # 학습된 TFT 모델
│   ├── run.py                 # FastAPI 서버 실행 (개발/테스트용)
│   ├── schedule_ems_AI.py     # ★ 운영 환경 실행 스크립트 ★
│   └── README.md
│
├── solar_api/                  # 태양광 발전량 예측 (FastAPI 구조)
│   ├── app/
│   │   ├── main.py            # FastAPI 애플리케이션 (개발용)
│   │   └── core/              # 예측 파이프라인
│   ├── run.py                 # FastAPI 서버 실행 (개발/테스트용)
│   ├── schedule_solar_AI.py   # ★ 운영 환경 실행 스크립트 ★
│   ├── run_README.md
│   └── sch_README.md
│
├── ess_ai_table_api/          # 예측 데이터 통합 집계 API
│   ├── app/
│   │   ├── main.py            # FastAPI 애플리케이션
│   │   ├── api/               # API 엔드포인트
│   │   └── core/              # 집계 로직
│   ├── run.py                 # API 서버 실행 (운영 환경)
│   ├── schedule_AI_log_table.py
│   └── schedule_ess_AI.py     # 스케줄러 스크립트
│
├── holiday_api/                # 공휴일 데이터 관리
│   ├── holiday_create.py      # 공휴일 DB 등록 스크립트
│   └── config.py              # DB 설정
│
├── weather/                    # 기상 데이터 수집
│   ├── weather_getVilageFcst.py  # 기상청 API 데이터 수집 스크립트
│   └── logs/                  # 로그 파일
│
└── README.md                   # 본 문서

★ 주요 실행 파일:
  - schedule_ems_AI.py: 전력 예측 실행 (FastAPI 서버 없이 내부 로직 직접 호출)
  - schedule_solar_AI.py: 태양광 예측 실행 (FastAPI 서버 없이 내부 로직 직접 호출)
  - schedule_ess_AI.py: 데이터 집계 실행
  - weather_getVilageFcst.py: 기상 데이터 수집
  - holiday_create.py: 공휴일 등록
```

---

## 주요 컴포넌트

### 1. EMS API (전력 사용량 예측)

**실행 방식**: 스케줄러 스크립트 (`schedule_ems_AI.py`)
**기술 스택**: FastAPI, PyTorch, Darts TFT, PyMySQL

#### 주요 기능
- TFT(Temporal Fusion Transformer) 모델 기반 전력 사용량 예측
- 30분 단위로 24시간(48개 타임스텝) 예측
- 자동 시간별/일별 집계 및 DB 저장 (UPSERT 방식)

#### 실행 방법
**주의**: FastAPI 서버 형태로 구성되어 있으나, 실제 운영 환경에서는 API 서버를 실행하지 않고 스케줄러 스크립트를 직접 실행합니다.

```bash
cd ems_api
python schedule_ems_AI.py  # 스케줄러로 자동 실행 (권장)
```

#### API 엔드포인트 (개발/테스트용)
FastAPI 서버를 실행할 경우 사용 가능한 엔드포인트:
- `GET /api/health` - 서비스 상태 확인
- `GET /api/model/info` - 모델 정보 조회
- `POST /api/igns/v1/smarteye/predict` - 전력 사용량 예측

#### 주요 테이블
- 입력: `tb_kepco_pwr_consum_minutes`
- 출력: `tb_aggregate_smarteye_hour`, `tb_aggregate_smarteye_day`

자세한 내용은 [ems_api/README.md](ems_api/README.md)를 참조하세요.

---

### 2. Solar API (태양광 발전량 예측)

**실행 방식**: 스케줄러 스크립트 (`schedule_solar_AI.py`)
**기술 스택**: FastAPI, PyTorch, Ensemble Models

#### 주요 기능
- 앙상블 모델 기반 태양광 발전량 예측
- 여러 시점 예측 후 평균 (슬라이딩 윈도우 방식)
- 3개 공장(FactoryA, FactoryB, FactoryC) 별도 예측
- 시간별 + 일간 합계 자동 저장

#### 실행 방법
**주의**: FastAPI 서버 형태로 구성되어 있으나, 실제 운영 환경에서는 API 서버를 실행하지 않고 스케줄러 스크립트를 직접 실행합니다.

```bash
cd solar_api
python schedule_solar_AI.py  # 스케줄러로 자동 실행 (권장)
```

#### API 엔드포인트 (개발/테스트용)
FastAPI 서버를 실행할 경우 사용 가능한 엔드포인트:
- `GET /api/health` - 서비스 상태 확인
- `GET /api/info` - API 정보 및 공장 매핑
- `POST /api/igns/v1/solar/predict` - 태양광 발전량 예측
- `GET /api/verify/predictions/{factory_name}` - 저장된 예측 결과 확인

---

### 3. ESS AI Table API (데이터 통합 집계)

**포트**: 8080
**기술 스택**: FastAPI, Pandas, PyMySQL

#### 주요 기능
- Solar Power, Power Usage, ESS 예측 데이터 통합 집계
- 시간별/일별 집계 자동화
- 대용량 데이터 효율적 처리

#### API 엔드포인트
- `GET /health` - 서비스 상태 확인
- `POST /api/igns/v1/ESS/aggregate` - 통합 데이터 집계

---

### 4. Holiday API (공휴일 관리)

**실행 방식**: 스크립트 (API 서버 아님)

#### 주요 기능
- Python `holidays` 라이브러리 활용
- 한국 공휴일 자동 조회 및 DB 등록
- 대통령 선거일, 임시 공휴일 제외
- 연도별 자동 업데이트

#### 실행 방법
```bash
cd holiday_api
python holiday_create.py
```

#### 테이블
- `tb_holiday` (hol_date: 공휴일 날짜)

---

### 5. Weather (기상 데이터 수집)

**실행 방식**: 스크립트 (스케줄러로 자동 실행)

#### 주요 기능
- 기상청 단기예보 API 연동
- 기상 데이터 + 태양 위치 정보 통합
- 1시간 간격 예보 데이터 수집
- MariaDB 자동 저장 (INSERT/UPDATE)

#### 수집 데이터
- 기상: 기온(TMP), 습도(REH), 하늘상태(SKY), 강수확률(POP) 등
- 태양: apparent_zenith, apparent_elevation, azimuth

#### 실행 방법
```bash
cd weather
python weather_getVilageFcst.py
```

#### 테이블
- `tb_weather_info`

---

## 설치 및 실행

### 환경 요구사항
- Python 3.9+
- MariaDB 10.x 또는 MySQL 8.x
- GPU (선택사항, CPU 실행 가능)

### 공통 설치 단계

1. **Python 가상환경 생성**
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

2. **각 서비스별 의존성 설치**
```bash
# EMS API
cd ems_api
pip install -r requirements.txt

# Solar API
cd ../solar_api
pip install -r requirements.txt

# ESS AI Table API
cd ../ess_ai_table_api
pip install -r requirements.txt

# Weather & Holiday (공통)
pip install pymysql pandas requests holidays pvlib
```

3. **환경 변수 설정**

각 API 디렉토리에 `.env` 파일 생성:
```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_username
DB_PASSWORD=your_password
DB_NAME=solar_mokup
```

4. **서비스 실행**

#### 운영 환경 (권장)
실제 운영 환경에서는 스케줄러 스크립트를 직접 실행합니다:

```bash
# 전력 사용량 예측 (EMS)
cd ems_api
python schedule_ems_AI.py

# 태양광 발전량 예측 (Solar)
cd solar_api
python schedule_solar_AI.py

# 데이터 통합 집계 (ESS AI Table) - API 서버 방식
cd ess_ai_table_api
python run.py  # 포트 8080
```

#### 개발/테스트 환경 (선택사항)
FastAPI 서버를 직접 실행하여 테스트할 수 있습니다:

```bash
# EMS API (포트 8000)
cd ems_api
python run.py

# Solar API (포트 8001)
cd solar_api
python run.py
```

---

## 실행 방식 및 엔드포인트

### 운영 환경 실행 방식

| 서비스 | 실행 방식 | 스크립트 | 설명 |
|--------|----------|---------|------|
| EMS | 스케줄러 스크립트 | `schedule_ems_AI.py` | 전력 사용량 예측 (직접 실행) |
| Solar | 스케줄러 스크립트 | `schedule_solar_AI.py` | 태양광 발전량 예측 (직접 실행) |
| ESS AI Table | API 서버 (포트 8080) | `run.py` | 통합 데이터 집계 |

**참고**: EMS API와 Solar API는 FastAPI로 구성되어 있지만, 실제 운영 환경에서는 스케줄러 스크립트를 통해 내부 코드를 직접 호출하는 방식으로 사용됩니다.

### API 엔드포인트 (개발/테스트용)

FastAPI 서버를 실행할 경우 사용 가능한 엔드포인트:

| 서비스 | 포트 | 주요 엔드포인트 | 설명 |
|--------|------|-----------------|------|
| EMS API | 8000 | `POST /api/igns/v1/smarteye/predict` | 전력 사용량 예측 |
| Solar API | 8001 | `POST /api/igns/v1/solar/predict` | 태양광 발전량 예측 |
| ESS AI Table API | 8080 | `POST /api/igns/v1/ESS/aggregate` | 통합 데이터 집계 |

### API 문서 (Swagger UI - 개발/테스트용)
FastAPI 서버를 실행한 경우 다음 주소에서 인터랙티브 API 문서 확인 가능:
- EMS API: http://localhost:8000/docs
- Solar API: http://localhost:8001/docs
- ESS AI Table API: http://localhost:8080/docs

---

## 데이터 파이프라인

### 일일 실행 프로세스

```
1. 기상 데이터 수집 (매일 20:00)
   └─> weather/weather_getVilageFcst.py (스크립트 직접 실행)
       └─> tb_weather_info 업데이트

2. 공휴일 업데이트 (매년 1월 1일)
   └─> holiday_api/holiday_create.py (스크립트 직접 실행)
       └─> tb_holiday 업데이트

3. 전력 사용량 예측 (매일 자동)
   └─> ems_api/schedule_ems_AI.py (스크립트 직접 실행)
       └─> 내부적으로 예측 로직 호출
           └─> tb_aggregate_smarteye_hour/day 저장

4. 태양광 발전량 예측 (매일 자동)
   └─> solar_api/schedule_solar_AI.py (스크립트 직접 실행)
       └─> 내부적으로 예측 로직 호출
           └─> 각 공장별 예측 결과 저장

5. 통합 데이터 집계 (매일 자동)
   └─> ess_ai_table_api/schedule_ess_AI.py (스크립트 직접 실행)
       └─> 내부적으로 집계 로직 호출
           └─> 통합 집계 테이블 업데이트
```

**참고**: EMS와 Solar는 FastAPI 구조를 가지고 있지만, 운영 환경에서는 API 서버를 띄우지 않고 스케줄러 스크립트가 내부 코드를 직접 호출합니다.

### 스케줄러 설정

각 API의 `schedule_*.py` 파일을 사용하여 자동화 가능:
- Windows: 작업 스케줄러
- Linux: Cron

예시 (Linux Cron):
```bash
# 매일 20:00 기상 데이터 수집
0 20 * * * cd /path/to/weather && python weather_getVilageFcst.py

# 매일 21:00 전력 예측
0 21 * * * cd /path/to/ems_api && python schedule_ems_AI.py

# 매일 21:30 태양광 예측
30 21 * * * cd /path/to/solar_api && python schedule_solar_AI.py

# 매일 22:00 데이터 집계
0 22 * * * cd /path/to/ess_ai_table_api && python schedule_ess_AI.py
```

---

## 데이터베이스 스키마

### 주요 테이블

#### 입력 데이터
- `tb_kepco_pwr_consum_minutes` - 30분 단위 전력 사용량
- `tb_weather_info` - 기상 예보 데이터
- `tb_holiday` - 공휴일 정보

#### 예측 결과
- `tb_aggregate_smarteye_hour` - 전력 예측 (시간별)
- `tb_aggregate_smarteye_day` - 전력 예측 (일별)
- 태양광 예측 테이블 (공장별)

#### 통합 집계
- ESS 통합 집계 테이블

---

## 모니터링 및 로깅

### 로그 파일 위치
- `ems_api/ems_api.log` - EMS API 로그
- `ems_api/logs/` - EMS 상세 로그
- `solar_api/logs/` - Solar API 로그
- `weather/logs/` - 기상 데이터 수집 로그
- `holiday_api/holiday_create_log.txt` - 공휴일 등록 로그

### 헬스 체크

운영 환경에서는 스케줄러 스크립트 실행 결과 및 로그 파일을 모니터링합니다.

개발/테스트 환경에서 FastAPI 서버를 실행한 경우:
```bash
# EMS API (개발 환경에서만)
curl http://localhost:8000/api/health

# Solar API (개발 환경에서만)
curl http://localhost:8001/api/health

# ESS AI Table API (운영 환경)
curl http://localhost:8080/health
```

---

## 문제 해결

### 공통 이슈

#### 1. 데이터베이스 연결 실패
- `.env` 파일의 DB 설정 확인
- MariaDB/MySQL 서버 실행 상태 확인
- 방화벽 설정 확인

#### 2. 모델 로딩 실패
- `weights/` 디렉토리에 모델 파일 존재 확인
- 경로 설정 확인

#### 3. 스케줄러 스크립트 실행 실패
- 로그 파일 확인 (각 디렉토리의 `logs/` 폴더)
- Python 가상환경 활성화 여부 확인
- 의존성 패키지 설치 확인
- DB 연결 정보 확인

#### 4. API 응답 없음 (개발 환경)
- 포트 충돌 확인 (8000, 8001, 8080)
- 로그 파일 확인
- **참고**: 운영 환경에서는 EMS/Solar API 서버를 실행하지 않음

---

## 기술 스택

### Backend
- **FastAPI** - 고성능 비동기 웹 프레임워크
- **Uvicorn** - ASGI 서버

### AI/ML
- **PyTorch** - 딥러닝 프레임워크
- **Darts** - 시계열 예측 라이브러리
- **PyTorch Lightning** - 학습 자동화

### Database
- **MariaDB/MySQL** - 관계형 데이터베이스
- **PyMySQL** - Python MySQL 클라이언트

### Data Processing
- **Pandas** - 데이터 처리 및 분석
- **NumPy** - 수치 연산

### External APIs
- **기상청 단기예보 API** - 날씨 데이터
- **pvlib** - 태양 위치 계산

---

## 라이선스

이 프로젝트는 내부 사용을 위한 프로젝트입니다.

---

## 업데이트 이력

### 2026-01-05
- 통합 README 작성
- 프로젝트 구조 문서화
- 시스템 아키텍처 다이어그램 추가
- 운영 방식 명확화: EMS/Solar는 스케줄러 스크립트로 실행, API 서버 방식이 아님

---

**문의 및 지원**: 프로젝트 관리자에게 문의하세요.
