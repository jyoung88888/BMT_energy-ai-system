# Solar Energy Prediction API

태양광 발전량 예측을 위한 FastAPI 기반 REST API 서비스입니다.

## 📋 목차
- [주요 기능](#주요-기능)
- [시스템 아키텍처](#시스템-아키텍처)
- [API 엔드포인트](#api-엔드포인트)
- [데이터 파이프라인](#데이터-파이프라인)
- [공장별 모델 구조](#공장별-모델-구조)
- [설치 및 실행](#설치-및-실행)
- [사용 예시](#사용-예시)
- [디렉토리 구조](#디렉토리-구조)

---

## 🌟 주요 기능

- **공장별 AI 모델 기반 태양광 발전량 예측** (A, B, C 공장)
  - 각 공장 특성에 최적화된 멀티모달 LSTM 모델
  - 공장별 독립 스케일러로 데이터 분포 정규화

- **멀티모달 입력 시스템**
  - 과거 태양광 데이터 168시간 (PV_Amp, generate_gap)
  - 미래 기상 데이터 24시간 (기온, 습도, 풍속, 태양고도 등 10개 피처)

- **앙상블 예측 (Ensemble Prediction)**
  - 슬라이딩 윈도우로 25개 독립 시퀀스 생성
  - 각 시간대별로 여러 예측값 평균 → 안정적이고 신뢰도 높은 예측

- **실시간 데이터 조회**
  - MariaDB 비동기 조회 (태양광 + 기상 데이터)
  - 범위 기반 정확한 데이터 추출 (SQL BETWEEN)

- **자동 전처리 파이프라인**
  - 공장별 데이터 분리 및 집계 (ID 매핑)
  - 시간 주기성 피처 엔지니어링 (cos/sin, 태양고도각 등)
  - 정규화 및 슬라이딩 윈도우 시퀀스 생성

- **스마트 후처리**
  - 앙상블 평균 (시간대별 다중 예측값 평균)
  - 물리적 제약 적용 (음수 → 0, 야간 → 0)
  - 데이터 연속성 자동 검증 및 상세 로깅

---

## 🏗️ 시스템 아키텍처

```
┌─────────────────────────┐
│   FastAPI Server        │
│   (main.py)             │
└──────────┬──────────────┘
           │
           │ POST /predict/solar/ensemble
           │
           ▼
┌──────────────────────────┐
│   1. Data Layer          │
│   (database.py)          │
│   - MariaDB 조회         │
│   - 태양광/기상 데이터   │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│ 2. Preprocessing         │
│  (preprocess.py)         │
│  - 공장별 분리            │
│  - 정규화 (Scaler)       │
│  - 슬라이딩 윈도우        │
│  - 시퀀스 생성            │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│ 3. AI Prediction         │
│  (predictor.py)          │
│  - Model A/B/C           │
│  - 배치 예측 (N개 시퀀스)│
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│ 4. Postprocessing        │
│ (postprocess.py)         │
│  - 앙상블 평균            │
│  - 음수값 제거            │
│  - 야간 0 처리            │
│  - 역정규화               │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│   JSON Response          │
└──────────────────────────┘
```

---

## 📡 API 엔드포인트

### **POST /predict/solar/ensemble** - 앙상블 예측

여러 시퀀스를 생성하여 각각 예측한 후 평균을 내는 앙상블 방식입니다.

**Request:**
```bash
POST /predict/solar/ensemble?target_date=20250820
```

**Response:**
```json
{
  "status": "success",
  "target_date": "20250820",
  "target_range": "2025-08-20 23:00:00 ~ 2025-08-21 22:00:00",
  "data_info": {
    "solar_records": 1920,
    "weather_records": 48
  },
  "ensemble_info": {
    "factories": ["FactoryA", "FactoryB", "FactoryC"],
    "sequences_per_factory": {
      "FactoryA": 25,
      "FactoryB": 25,
      "FactoryC": 25
    }
  },
  "results": {
    "FactoryA": {
      "predictions": [0.0, 0.0, 125.3, 138.7, ...],
      "timestamps": ["2025-08-20 23:00:00", "2025-08-21 00:00:00", ...],
      "num_sequences_used": 25,
      "num_predictions_averaged": [1, 2, 3, ..., 25, 24, 23, ...]
    },
    "FactoryB": { ... },
    "FactoryC": { ... }
  }
}
```

**Pipeline Flow:**
```
1. 날짜 변환: 20250820 → 2025-08-20 00:00:00 (base_dt)
2. 목표 시간대 계산: base_dt + 23h ~ base_dt + 46h (24시간, 미래 시점)
3. 데이터 조회 범위 계산:
   - Solar: base_dt - 168h ~ base_dt + 45h (192시간, 모든 공장 ID)
   - Weather: base_dt ~ base_dt + 46h (47시간)
4. 슬라이딩 윈도우로 25개 시퀀스 생성 (168h 과거 + 24h 미래)
5. 각 시퀀스별 독립 예측 (공장별 전용 모델 사용)
6. 목표 시간대에 대해 앙상블 평균
7. 야간 시간대(22:00~05:00) 자동 0 처리
```

**앙상블 예측 장점:**
- 여러 시점에서 바라본 예측을 평균하여 더 안정적
- 이상치(outlier)의 영향 감소
- 모델 예측의 불확실성 완화

---

### **GET /health** - 헬스 체크

```json
{
  "status": "healthy",
  "service": "Solar Prediction API",
  "version": "1.0.0"
}
```

---

### **GET /info** - API 정보

```json
{
  "title": "Solar Energy Prediction API",
  "version": "1.0.0",
  "description": "태양광 발전량 예측 API 서비스",
  "endpoints": {
    "predict_ensemble": "/predict/solar/ensemble",
    "health": "/health",
    "docs": "/docs"
  }
}
```

---

## 🔄 데이터 파이프라인

### 1단계: 데이터 수집 (database.py)

**MariaDB 데이터베이스:**

- **solar_mokup.solar_hour**: 태양광 발전 데이터
  - `id`: 공장 ID (1~3 → A, 4~8 → B, 9~10 → C)
  - `ymdhms`: 시간 (YYYY-MM-DD HH:00:00)
  - `generate_gap`: 발전량 (kWh)
  - `PV_Amp`: 전류 (A)
  - `PV_Volt`, `Volt_R/S/T`, `Amp_R/S/T`, `Frequency` 등

- **vilagefcst.tb_weather_info**: 기상 예보 데이터
  - `tm`: 예보 시간
  - `1시간기온`, `강수확률`, `습도`, `풍속`, `하늘상태`: 기상 변수

**데이터 조회 (범위 기반):**
```python
# 앙상블 예측용 데이터 조회
ensemble_data = await fetch_ensemble_data(
    solar_start="2025-08-13 00:00:00",
    solar_end="2025-08-21 21:00:00",      # 192시간 범위
    weather_start="2025-08-20 00:00:00",
    weather_end="2025-08-21 22:00:00"     # 47시간 범위
)
solar_df = ensemble_data['solar_df']      # 모든 공장 ID 포함
weather_df = ensemble_data['weather_df']
```

---

### 2단계: 전처리 (preprocess.py)

**태양광 데이터 전처리:**
```python
# 1. 공장별 분리 및 집계
FactoryA: id=[1,2,3] → 시간당 합계
FactoryB: id=[4,5,6,7,8] → 시간당 합계
FactoryC: id=[9,10] → 시간당 합계

# 2. 공장별 스케일러로 정규화
scaler_A.transform(FactoryA_df)
scaler_B.transform(FactoryB_df)
scaler_C.transform(FactoryC_df)

# 3. 시퀀스 데이터 생성
X_solar = [과거 168시간] → Shape: (N, 168, 2)
```

**기상 데이터 전처리:**
```python
# 1. 피처 엔지니어링
hour_cos = cos(2π * hour / 24)  # 시간 주기성
peak_hours = 1 if hour in [17-21] else 0
altitude_deg = 태양 고도각
is_daylight = 1 if 일출~일몰 else 0

# 2. 정규화 및 시퀀스 생성
X_weather = [미래 24시간] → Shape: (N, 24, 10)
```

**슬라이딩 윈도우 (앙상블용):**
```
예시: target_date = 2025-08-20

Solar 데이터: 2025-08-13 00:00 ~ 2025-08-21 21:00 (192시간, 10개 ID)
Weather 데이터: 2025-08-20 00:00 ~ 2025-08-21 22:00 (47시간)

시퀀스 생성 (25개):
시퀀스 0: Solar[0:168] + Weather[0:24]   → 예측: 2025-08-20 23:00 ~ 2025-08-21 22:00
시퀀스 1: Solar[1:169] + Weather[1:25]   → 예측: 2025-08-21 00:00 ~ 2025-08-21 23:00
...
시퀀스 24: Solar[24:192] + Weather[24:48] → 예측: 2025-08-21 23:00 ~ 2025-08-22 22:00

→ 목표 시간대(2025-08-20 23:00 ~ 2025-08-21 22:00)가 여러 시퀀스에서 예측됨
→ 각 시간대별로 평균을 내어 최종 예측값 산출 (앙상블 평균)
→ 예: 2025-08-21 10:00은 시퀀스 0~11에서 예측됨 → 12개 값 평균
```

---

### 3단계: AI 예측 (predictor.py)

**공장별 모델:**

```python
# 멀티모달 LSTM 모델
Input 1: X_solar (N, 168, 2)   # 과거 태양광
Input 2: X_weather (N, 24, 10)  # 미래 기상

Model A: A_multimodal_solar_model_e500_b8_p100_v6.keras
Model B: B_multimodal_solar_model_e500_b8_p100_v6.keras
Model C: C_multimodal_solar_model_e500_b8_p100_v6.keras

Output: y_pred (N, 24, 1)  # 24시간 발전량 예측
```

**모델 선택:**
```python
predict(X_solar, X_weather, factory_name='A')  # Model A 사용
predict(X_solar, X_weather, factory_name='B')  # Model B 사용
predict(X_solar, X_weather, factory_name='C')  # Model C 사용
```

---

### 4단계: 후처리 (postprocess.py)

**앙상블 평균 및 후처리:**
```python
1. 각 시간대별로 여러 시퀀스의 예측값 수집
   - 예: 2025-08-21 10:00
     → 시퀀스 0,1,2,...,11에서 예측된 12개 값 수집
2. 시간대별 평균 계산
   - 예: [125.3, 130.1, 128.7, ...] → 평균 128.0 kWh
3. 음수값 제거 (물리적 제약)
4. 야간 시간대(22:00~05:00) → 0 설정
5. 목표 시간대(23:00~22:00)만 필터링하여 반환
6. 역정규화는 모델 내부에서 수행 (target_scaler 사용)
```

**앙상블 평균 효과:**
- 초기 시간대(23:00~01:00): 1~3개 시퀀스 평균 (적음)
- 중간 시간대(02:00~20:00): 최대 25개 시퀀스 평균 (많음, 안정적)
- 후기 시간대(21:00~22:00): 24~23개 시퀀스 평균 (감소)
```

---

## 🏭 공장별 모델 구조

### 모델 파일 (config.py)

```python
# 공장별 AI 모델
MODEL_A_PATH = './weights/A_multimodal_solar_model_e500_b8_p100_v6.keras'
MODEL_B_PATH = './weights/B_multimodal_solar_model_e500_b8_p100_v6.keras'
MODEL_C_PATH = './weights/C_multimodal_solar_model_e500_b8_p100_v6.keras'

# 공장별 스케일러
SOLAR_SCALER_A_PATH = './weights/A_solar_scaler_e500_b8_p100_v6.pkl'
SOLAR_SCALER_B_PATH = './weights/B_solar_scaler_e500_b8_p100_v6.pkl'
SOLAR_SCALER_C_PATH = './weights/C_solar_scaler_e500_b8_p100_v6.pkl'

# 공통 기상 스케일러
WEATHER_SCALER_PATH = './weights/A_weather_scaler_e500_b8_p10_v6.pkl'

# 공장별 타겟 스케일러
A_TARGET_SCALER_PATH = './weights/A_target_scaler_e500_b8_p100_v6.pkl'
B_TARGET_SCALER_PATH = './weights/B_target_scaler_e500_b8_p100_v6.pkl'
C_TARGET_SCALER_PATH = './weights/C_target_scaler_e500_b8_p100_v6.pkl'
```

### 공장별 ID 매핑

```python
FactoryA: 1 ~ 12          
FactoryB: 12 ~ 14   
FactoryC: 14 ~ 16    
```

---

## ⚙️ 설치 및 실행

### 1. 환경 설정

```bash
# Python 3.12+ 필요
pip install -r requirements.txt
```

**requirements.txt:**
```
fastapi==0.104.1
uvicorn==0.24.0
pydantic==2.5.0
pandas==2.1.3
numpy==1.24.3
tensorflow==2.14.0
scikit-learn==1.3.2
pymysql==1.1.0
aiomysql==0.2.0
```

### 2. 데이터베이스 설정

**config.py** 수정:

```python
solar_database_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'your_password',
    'database': 'solar_mokup',
    'charset': 'utf8mb4'
}

weather_database_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'your_password',
    'database': 'vilagefcst',
    'charset': 'utf8mb4'
}
```

### 3. 모델 파일 준비

`weights/` 디렉토리에 다음 파일 배치:

```
weights/
├── A_multimodal_solar_model_e500_b8_p100_v6.keras
├── B_multimodal_solar_model_e500_b8_p100_v6.keras
├── C_multimodal_solar_model_e500_b8_p100_v6.keras # 예측 모델 
├── A_solar_scaler_e500_b8_p100_v6.pkl
├── B_solar_scaler_e500_b8_p100_v6.pkl
├── C_solar_scaler_e500_b8_p100_v6.pkl # 태양광 컬럼 스케일러 
├── A_target_scaler_e500_b8_p10_v6.pkl
├── B_target_scaler_e500_b8_p100_v6.pkl
├── C_target_scaler_e500_b8_p100_v6.pkl
└── weather_scaler_e500_b8_p10_v6.pkl # 타겟 스케일러 
```

### 4. 서버 실행

```bash
cd app
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

서버 실행 후:
- API 문서: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Health Check: http://localhost:8000/health

---

## 💡 사용 예시

### cURL

**앙상블 예측:**
```bash
curl -X POST "http://localhost:8000/predict/solar/ensemble?target_date=20250820"
```

### Python

```python
import requests

# 앙상블 예측
response = requests.post(
    "http://localhost:8000/predict/solar/ensemble?target_date=20250820"
)
result = response.json()

print(f"Status: {result['status']}")
print(f"Target Range: {result['target_range']}")
print(f"Sequences per factory: {result['ensemble_info']['sequences_per_factory']}")

# 공장별 예측 결과 출력
for factory in ['FactoryA', 'FactoryB', 'FactoryC']:
    predictions = result['results'][factory]['predictions']
    timestamps = result['results'][factory]['timestamps']
    print(f"\n{factory} 예측 (처음 5개):")
    for i in range(5):
        print(f"  {timestamps[i]}: {predictions[i]:.2f} kWh")
```

### 응답 예시 해석

```python
# num_predictions_averaged: 각 시간대별로 평균에 사용된 시퀀스 개수
# - 초기: [1, 2, 3, ...] → 앙상블 효과 약함
# - 중간: [23, 24, 25, 25, ...] → 앙상블 효과 강함 (가장 안정적)
# - 후기: [..., 25, 24, 23] → 앙상블 효과 감소

result = {
    "FactoryA": {
        "predictions": [0.0, 0.0, 8.5, 125.3, ..., 85.2, 0.0],  # 24시간
        "timestamps": ["2025-08-20 23:00:00", ..., "2025-08-21 22:00:00"],
        "num_sequences_used": 25,
        "num_predictions_averaged": [1, 2, 3, ..., 25, 25, ..., 24, 23]
    }
}
```

---

## 📂 디렉토리 구조

```
solar_api/
├── app/
│   ├── main.py                      # FastAPI 엔드포인트
│   ├── core/
│   │   ├── config.py                # 설정 관리
│   │   ├── database.py              # MariaDB 연결 및 조회
│   │   ├── preprocess.py            # 데이터 전처리
│   │   ├── postprocess.py           # 예측 후처리
│   │   └── exceptions.py            # 커스텀 예외
│   ├── models/
│   │   └── predictor.py             # AI 모델 관리
│   └── utils/
│       └── Solar_data_preprocessing.py
├── weights/                         # 모델 및 스케일러
├── logs/                            # 로그 파일
└── README.md                        # 이 문서
```

---

## 🔍 주요 특징

### 1. 비동기 I/O 처리
- FastAPI 비동기 엔드포인트
- DB 조회 비동기 처리 (`asyncio`)
- 모델 A, B, C 병렬 로딩 (서버 시작 시)

### 2. 공장별 독립 모델
- 각 공장(A/B/C) 전용 AI 모델 (멀티모달 LSTM)
- 공장별 Solar/Target 스케일러로 데이터 분포 최적화
- 공통 Weather 스케일러 사용

### 3. 멀티모달 입력
- **Input 1**: 과거 168시간 태양광 데이터 (PV_Amp, generate_gap)
- **Input 2**: 미래 24시간 기상 데이터 (기온, 습도, 풍속, 태양고도 등 10개 피처)
- 두 입력을 동시에 활용하여 예측 정확도 향상

### 4. 앙상블 평균 (Ensemble Prediction)
- 슬라이딩 윈도우로 25개 시퀀스 생성
- 각 시퀀스 독립 예측 후 시간대별 평균
- 예측 안정성 향상 및 이상치 영향 감소
- 중간 시간대(낮 시간) 최대 25개 예측값 평균 → 높은 신뢰도

### 5. 자동 후처리
- 물리적 제약 조건: 음수 → 0
- 야간 시간대(22:00~05:00) 자동 0 처리
- 목표 시간대 필터링 (24시간)
- 데이터 연속성 자동 검증 및 로깅

### 6. 범위 기반 데이터 조회
- 명시적 시작/종료 시각으로 정확한 데이터 조회
- 태양광: 192시간 범위 (168h 과거 + 24h 미래)
- 기상: 47시간 범위 (목표 시작 ~ 종료 + 여유)
- SQL BETWEEN 절로 정확한 범위 제어

---
