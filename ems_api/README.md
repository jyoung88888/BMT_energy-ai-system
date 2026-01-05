# EMS API - Energy Management System Forecasting API

전력 사용량 예측 및 관리를 위한 FastAPI 기반 RESTful API 서비스

## 목차
- [프로젝트 개요](#프로젝트-개요)
- [주요 기능](#주요-기능)
- [기술 스택](#기술-스택)
- [프로젝트 구조](#프로젝트-구조)
- [설치 및 실행](#설치-및-실행)
- [API 사용법](#api-사용법)
- [데이터베이스 설정](#데이터베이스-설정)
- [환경 변수 설정](#환경-변수-설정)
- [로깅](#로깅)
- [문제 해결](#문제-해결)

---

## 프로젝트 개요

EMS API는 시계열 딥러닝 모델(TFT - Temporal Fusion Transformer)을 활용하여 전력 사용량을 예측하고, 예측 결과를 데이터베이스에 자동으로 저장하는 API 서비스입니다.

### 핵심 특징
- **30분 단위 예측**: 48개 타임스텝 (24시간) 예측
- **자동 집계**: 30분 예측 결과를 시간별/일별로 자동 집계
- **UPSERT 방식**: 기존 데이터 자동 업데이트 또는 신규 삽입
- **효율적 실행**: 모델 1회 실행으로 여러 집계 수준 제공

---

## 주요 기능

### 1. 전력 사용량 예측 (`/predict`)
- 지정된 날짜 이후 24시간(48개 타임스텝)의 전력 사용량 예측
- 30분 단위 예측 결과 생성
- 자동으로 시간별 및 일별 집계 수행
- 예측 결과를 데이터베이스에 자동 저장 (UPSERT)

### 2. 데이터베이스 자동 저장
- **시간별 테이블** (`tb_aggregate_smarteye_hour`): 1시간 단위 집계
- **일별 테이블** (`tb_aggregate_smarteye_day`): 1일 단위 집계
- 중복 데이터 자동 업데이트 (ON DUPLICATE KEY UPDATE)

### 3. 시스템 상태 확인
- **Health Check** (`/health`): API 서버 상태 확인
- **Model Info** (`/model/info`): 로드된 모델 정보 조회

---

## 기술 스택

### Backend Framework
- **FastAPI** 0.104.1 - 고성능 비동기 웹 프레임워크
- **Uvicorn** 0.24.0 - ASGI 서버

### Machine Learning
- **Darts** 0.27.0 - 시계열 예측 라이브러리
- **PyTorch** 2.1.1 - 딥러닝 프레임워크
- **PyTorch Lightning** 2.1.2 - 학습 자동화
- **Scikit-learn** 1.3.2 - 데이터 전처리 및 스케일링

### Database
- **PyMySQL** 1.1.0 - MariaDB/MySQL 연결
- **SQLAlchemy** - 데이터베이스 엔진 관리

### Data Processing
- **Pandas** 2.1.3 - 데이터 처리
- **NumPy** 1.26.2 - 수치 연산

### Utilities
- **Workalendar** 17.0.0 - 공휴일 처리
- **python-dotenv** 1.0.0 - 환경 변수 관리
- **colorlog** 6.8.0 - 컬러 로깅

---

## 프로젝트 구조

```
ems_api/
├── app/
│   ├── main.py                      # FastAPI 애플리케이션 진입점
│   ├── core/
│   │   ├── db.py                    # 데이터베이스 연결 및 조회
│   │   ├── db_saver.py              # 예측 결과 저장 (UPSERT)
│   │   ├── preprocess.py            # 데이터 전처리
│   │   └── postprocess.py           # 예측 결과 후처리 (집계)
│   ├── models/
│   │   └── predictor.py             # TFT 모델 예측 로직
│   ├── utils/
│   │   ├── config.py                # 설정 관리
│   │   └── model_loader.py          # 모델 로딩
│   └── weights/                     # 학습된 모델 파일
│       ├── tft_model.pt             # PyTorch 모델 가중치
│       ├── scalers.pkl              # 데이터 스케일러
│       └── config.json              # 모델 설정
├── .env                             # 환경 변수 (DB 연결 정보)
├── requirements.txt                 # Python 의존성
├── ems_api.log                      # 애플리케이션 로그
└── README.md                        # 프로젝트 문서
```

---

## 설치 및 실행

### 1. 환경 요구사항
- Python 3.9+
- MariaDB 10.x 또는 MySQL 8.x
- GPU (선택사항, CPU에서도 실행 가능)

### 2. 의존성 설치
```bash
pip install -r requirements.txt
```

### 3. 환경 변수 설정
`.env` 파일 생성:
```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_username
DB_PASSWORD=your_password
DB_NAME=solar_mokup
```

### 4. 데이터베이스 설정
```sql
-- 시간별 테이블에 UNIQUE 제약조건 추가 (UPSERT 작동을 위해 필수)
ALTER TABLE tb_aggregate_smarteye_hour
ADD PRIMARY KEY (use_time);

-- 일별 테이블에 UNIQUE 제약조건 추가
ALTER TABLE tb_aggregate_smarteye_day
ADD PRIMARY KEY (use_time);
```

### 5. API 서버 실행
```bash
# 개발 모드
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 프로덕션 모드
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

서버가 실행되면 다음 주소로 접속 가능:
- API 문서: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## API 사용법

### 1. Health Check
서버 상태 확인

**Endpoint:** `GET /health`

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-10-31T10:00:00"
}
```

### 2. 모델 정보 조회
로드된 모델 설정 정보 확인

**Endpoint:** `GET /model/info`

**Response:**
```json
{
  "status": "success",
  "model_info": {
    "input_chunk_length": 336,
    "output_chunk_length": 48,
    "past_covariates": ["최대수요(kW)", "무효전력(지상)", ...],
    "future_covariates": ["hour", "dayofweek", "is_holiday", ...],
    "target": "사용량(kWh)"
  }
}
```

### 3. 전력 사용량 예측
지정된 날짜 이후 24시간 예측

**Endpoint:** `POST /predict`

**Request Body:**
```json
{
  "split_date": "2025-10-20"
}
```

**Parameters:**
- `split_date` (string, required): 예측 시작일 (yyyy-mm-dd 형식)
  - 지정된 날짜의 다음 날 00:00부터 24시간을 예측합니다

**Response:**
```json
{
  "status": "success",
  "message": "Prediction completed. Hourly: 24 records, Daily: 1 records saved.",
  "prediction_count": 24,
  "predictions": [
    {
      "datetime": "2025-10-21T01:00:00",
      "predicted_kwh": 250.5
    },
    {
      "datetime": "2025-10-21T02:00:00",
      "predicted_kwh": 245.3
    }
  ]
}
```

### cURL 예시
```bash
curl -X POST "http://localhost:8000/predict" \
  -H "Content-Type: application/json" \
  -d '{"split_date": "2025-10-20"}'
```

### Python 예시
```python
import requests

response = requests.post(
    "http://localhost:8000/predict",
    json={"split_date": "2025-10-20"}
)

data = response.json()
print(f"Status: {data['status']}")
print(f"Predictions: {len(data['predictions'])} records")
```

---

## 데이터베이스 설정

### 필수 테이블 구조

#### 1. 입력 데이터 테이블 (`tb_kepco_pwr_consum_minutes`)
30분 단위 실제 전력 사용량 데이터

```sql
CREATE TABLE tb_kepco_pwr_consum_minutes (
    use_dt DATETIME PRIMARY KEY,
    pwr_usage DECIMAL(10,2),
    max_demand DECIMAL(10,2),
    react_pwr DECIMAL(10,2),
    real_react_pwr DECIMAL(10,2),
    co_amt DECIMAL(10,2),
    pwr_factor DECIMAL(5,2),
    leading_pwr_factor DECIMAL(5,2)
);
```

#### 2. 시간별 예측 결과 테이블 (`tb_aggregate_smarteye_hour`)
1시간 단위 예측 결과 저장

```sql
CREATE TABLE tb_aggregate_smarteye_hour (
    use_time DATETIME PRIMARY KEY,
    forecast_quantity DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

#### 3. 일별 예측 결과 테이블 (`tb_aggregate_smarteye_day`)
1일 단위 예측 결과 저장

```sql
CREATE TABLE tb_aggregate_smarteye_day (
    use_time DATE PRIMARY KEY,
    forecast_quantity DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

### UPSERT 동작 방식

API는 `ON DUPLICATE KEY UPDATE`를 사용하여 데이터를 저장합니다:

```sql
INSERT INTO tb_aggregate_smarteye_hour (use_time, forecast_quantity)
VALUES ('2025-10-21 01:00:00', 250.5)
ON DUPLICATE KEY UPDATE forecast_quantity = 250.5;
```

**동작:**
- `use_time`이 존재하지 않으면 → **INSERT** (신규 삽입)
- `use_time`이 이미 존재하면 → **UPDATE** (값 갱신)

---

## 환경 변수 설정

### `.env` 파일 템플릿

```env
# Database Configuration
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=solar_mokup

# Optional: Logging Level
LOG_LEVEL=INFO
```

### 설정 우선순위
1. 환경 변수 (`.env` 파일)
2. 기본값 (`app/utils/config.py`)

---

## 로깅

### 로그 파일
- **위치**: `ems_api.log`
- **로테이션**: 10MB 단위, 최대 5개 파일 백업
- **형식**: `[YYYY-MM-DD HH:MM:SS] [LEVEL] [Module] Message`

### 로그 레벨
```python
# main.py에서 설정 변경 가능
logging.basicConfig(level=logging.INFO)
```

### 주요 로그 예시

#### 성공적인 예측 실행
```log
================================================================================
[PREDICT START] split_date: 2025-10-20
[DB Fetch] 15000 records | Period: 2024-01-01 00:00:00 ~ 2025-10-20 23:30:00
[Prediction] 48 records | Period: 2025-10-21 00:00:00 ~ 2025-10-21 23:30:00
[DB Save - Hourly] tb_aggregate_smarteye_hour: INSERT=5, UPDATE=19 | Period: 2025-10-21 01:00:00 ~ 2025-10-22 00:00:00
[DB Save - Daily] tb_aggregate_smarteye_day: INSERT=0, UPDATE=1 | Period: 2025-10-21 00:00:00 ~ 2025-10-21 00:00:00
[PREDICT END] SUCCESS
================================================================================
```

#### 로그 항목 설명
- **DB Fetch**: 데이터베이스에서 읽은 레코드 수와 기간
- **Prediction**: 예측 생성된 레코드 수와 기간
- **DB Save**: INSERT/UPDATE 개수와 저장된 데이터 기간
  - `INSERT=n`: 신규 삽입된 레코드 수
  - `UPDATE=n`: 업데이트된 레코드 수

---

## 주요 알고리즘

### 1. 시간별 집계 (Hourly Aggregation)
30분 데이터를 1시간 단위로 합산

**규칙:**
- `00:30` + `01:00` → `01:00` (다음 정시와 합산)
- `01:30` + `02:00` → `02:00`
- `23:30` + `00:00(다음날)` → `00:00(다음날)`

**구현:**
```python
df['hour'] = df['ymdhms'].dt.ceil('h')
hourly_df = df.groupby('hour')['사용량(kWh)'].sum()
```

### 2. 일별 집계 (Daily Aggregation)
30분 데이터를 1일 단위로 전체 합산

**구현:**
```python
total_sum = df['사용량(kWh)'].sum()
first_date = df['ymdhms'].iloc[0].normalize()
```

### 3. 모델 실행 최적화
모델을 1번만 실행하고 결과를 재사용:

```
30분 예측 (1회 실행)
    ↓
    ├─→ 시간별 집계 → DB 저장
    └─→ 일별 집계 → DB 저장
```

---

## 문제 해결

### 1. UPSERT가 작동하지 않는 경우
**증상:** 항상 INSERT만 발생하고 UPDATE가 0

**원인:** `use_time` 컬럼에 UNIQUE 제약조건이 없음

**해결:**
```sql
ALTER TABLE tb_aggregate_smarteye_hour ADD PRIMARY KEY (use_time);
ALTER TABLE tb_aggregate_smarteye_day ADD PRIMARY KEY (use_time);
```

### 2. 모델 로딩 실패
**증상:** `Model not loaded` 에러

**원인:** 모델 파일이 없거나 경로가 잘못됨

**해결:**
```bash
# 모델 파일 확인
ls app/weights/
# 필요한 파일: tft_model.pt, scalers.pkl, config.json
```

### 3. 데이터베이스 연결 실패
**증상:** `Failed to connect to database` 에러

**해결:**
1. `.env` 파일의 DB 설정 확인
2. MariaDB/MySQL 서버 실행 상태 확인
3. 방화벽 설정 확인

### 4. 예측 값 불일치
**증상:** hourly 합계 ≠ daily 합계

**원인:** 시간별 집계 로직 오류

**해결:** 최신 버전의 `postprocess.py` 사용 (dt.ceil('h') 적용)

---

## 성능 최적화

### 1. 모델 실행 최적화
- **이전**: 모델 3회 실행 (30분, 시간별, 일별)
- **현재**: 모델 1회 실행 후 결과 재사용
- **개선율**: 약 66% 실행 시간 단축

### 2. 데이터베이스 최적화
- UPSERT 사용으로 중복 체크 및 삽입/업데이트를 1번의 쿼리로 처리
- 인덱스 활용으로 빠른 중복 검사

### 3. 로깅 최적화
- 불필요한 상세 로그 제거
- 핵심 정보만 기록하여 로그 파일 크기 감소

---

## 예측 프로세스 상세

### 전체 플로우

```
1. [DB Fetch]
   ↓ MariaDB에서 과거 데이터 조회
   ↓ split_date 이전의 모든 30분 단위 데이터

2. [Preprocess]
   ↓ 시간 특성 생성 (hour, dayofweek, sin/cos encoding)
   ↓ 공휴일 특성 생성 (한국 공휴일)
   ↓ 미래 48개 타임스탬프 생성

3. [Prediction - 1회 실행]
   ↓ TFT 모델로 30분 단위 48개 예측
   ↓ 정규화/역정규화 적용

4. [Hourly Aggregation]
   ↓ 30분 예측을 시간별로 집계 (24개)
   ↓ DB 저장 (UPSERT)

5. [Daily Aggregation]
   ↓ 30분 예측을 일별로 집계 (1개)
   ↓ DB 저장 (UPSERT)

6. [Response]
   ↓ API 응답 생성 (hourly 결과 반환)
```

---

## API 문서

FastAPI는 자동으로 API 문서를 생성합니다:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

인터랙티브하게 API를 테스트할 수 있습니다.

---

## 라이선스

이 프로젝트는 내부 사용을 위한 프로젝트입니다.

---

## 변경 이력

### v2.0 (2025-10-31)
- 모델 1회 실행으로 최적화
- UPSERT 방식으로 데이터 저장 변경
- 시간별 집계 로직 수정 (dt.ceil 적용)
- 로깅 최적화 (핵심 정보만 기록)
- SQLAlchemy Engine 통합

### v1.0 (2025-10-24)
- 초기 버전 릴리스
- TFT 모델 기반 예측
- FastAPI 구현

---

**최종 업데이트:** 2025-10-31
