# core/data_processor.py
import pandas as pd
import numpy as np
import joblib
from typing import Dict, Any
import os

from app.core.config import settings, ModelConfig
import logging
from app.core.exceptions import DataProcessingError

logger = logging.getLogger(__name__)

class DataProcessor:
    """데이터 전처리 클래스"""
    
    def __init__(self):
        self.solar_scaler_A = None
        self.solar_scaler_B = None
        self.solar_scaler_C = None
        self.weather_scaler = None

        # scaler에서 feature names 추출 (config7.json 대신 scaler 사용)
        self.solar_features_from_scaler = None
        self.weather_features_from_scaler = None

        self.load_scaler()
    
    def load_scaler(self):
        """저장된 스케일러 로드 - 공장별 태양광 스케일러 포함"""
        try:
            # 스케일러 설정 정의
            scaler_configs = {
                'solar_A': {
                    'attr': 'solar_scaler_A',
                    'path_attr': 'SOLAR_SCALER_A_PATH',
                    'name': '공장 A 태양광'
                },
                'solar_B': {
                    'attr': 'solar_scaler_B',
                    'path_attr': 'SOLAR_SCALER_B_PATH',
                    'name': '공장 B 태양광'
                },
                'solar_C': {
                    'attr': 'solar_scaler_C',
                    'path_attr': 'SOLAR_SCALER_C_PATH',
                    'name': '공장 C 태양광'
                },
                'solar_T': {
                    'attr': 'solar_scaler_T',
                    'path_attr': 'SOLAR_SCALER_T_PATH',
                    'name': '공장 Total 태양광'
                },
                'weather': {
                    'attr': 'weather_scaler',
                    'path_attr': 'WEATHER_SCALER_PATH',
                    'name': '기상'
                }
            }

            # 통합 로드 로직
            for scaler_key, config in scaler_configs.items():
                self._load_single_scaler(
                    attr_name=config['attr'],
                    path_attr=config['path_attr'],
                    scaler_name=config['name']
                )

            # ===== scaler에서 feature names 추출 =====
            # Solar features 추출 (Total 스케일러 기준)
            if self.solar_scaler_T and hasattr(self.solar_scaler_T, 'feature_names_in_'):
                self.solar_features_from_scaler = self.solar_scaler_T.feature_names_in_.tolist()
                logger.info(f"📊 Scaler에서 추출한 Solar features: {self.solar_features_from_scaler}")
            else:
                logger.warning("⚠️ Solar scaler에서 feature_names_in_ 속성을 찾을 수 없습니다")

            # Weather features 추출
            if self.weather_scaler and hasattr(self.weather_scaler, 'feature_names_in_'):
                self.weather_features_from_scaler = self.weather_scaler.feature_names_in_.tolist()
                logger.info(f"📊 Scaler에서 추출한 Weather features: {self.weather_features_from_scaler}")
            else:
                logger.warning("⚠️ Weather scaler에서 feature_names_in_ 속성을 찾을 수 없습니다")

        except Exception as e:
            logger.error(f"❌ 스케일러 로드 실패: {str(e)}")
            raise

    def _load_single_scaler(self, attr_name: str, path_attr: str, scaler_name: str):
        """
        단일 스케일러 로드 헬퍼 함수

        Args:
            attr_name: 저장할 속성명 (예: 'solar_scaler_A')
            path_attr: settings의 경로 속성명 (예: 'SOLAR_SCALER_A_PATH')
            scaler_name: 로깅용 스케일러 이름 (예: '공장 A 태양광')
        """
        if not hasattr(settings, path_attr):
            error_msg = f"{path_attr}가 설정되지 않았습니다"
            logger.error(f"❌ {error_msg}")
            raise ValueError(error_msg)

        path = getattr(settings, path_attr)
        logger.info(f"🔍 {scaler_name} 스케일러 경로: {path}")

        if not os.path.exists(path):
            error_msg = f"{scaler_name} 스케일러 파일이 없습니다: {path}"
            logger.error(f"❌ {error_msg}")
            raise FileNotFoundError(error_msg)

        # 스케일러 로드
        scaler = joblib.load(path)
        setattr(self, attr_name, scaler)
        logger.info(f"✅ {scaler_name} 스케일러 로드 완료")

    @staticmethod
    def aggregate_daily_solar_data(df):
        if df.empty:
            return pd.DataFrame()

        df = df.copy()
        df['ymdhms'] = pd.to_datetime(df['ymdhms'])

        logger.info(f"📊 집계 전 데이터: {len(df)}건, 시간 범위: {df['ymdhms'].min()} ~ {df['ymdhms'].max()}")

        # 집계할 컬럼만 선택하고 존재하는 것만 매핑
        agg_map = {}
        potential_agg = {
            'PV_Volt': 'mean',
            'PV_Amp': 'mean',
            'Volt_R': 'mean',
            'Volt_S': 'mean',
            'Volt_T': 'mean',
            'Ampe_R': 'mean',  
            'Ampe_S': 'mean', 
            'Ampe_T': 'mean', 
            'Frequency': 'mean',
            'Today_Generation': 'sum',
            'generate_gap': 'sum',
            'Accum_Generation': 'mean',
        }

        # 존재하는 컬럼만 집계 맵에 추가
        for col, agg_func in potential_agg.items():
            if col in df.columns:
                agg_map[col] = agg_func
            else:
                logger.warning(f"⚠️ 컬럼 '{col}'이 데이터프레임에 없습니다.")

        logger.info(f"📊 실제 집계할 컬럼: {list(agg_map.keys())}")

        daily_df = df.groupby(['ymdhms']).agg(agg_map).reset_index()
        logger.info(f"📊 집계 후 데이터: {len(daily_df)}건")

        return daily_df
    
    def preprocess_solar_data(self, solar_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """
        태양광 데이터 전처리 - 단계별 처리

        Args:
            solar_df: solar_hour 테이블에서 가져온 태양광 데이터

        Returns:
            Dict[str, pd.DataFrame]: 공장별 집계된 데이터 {"FactoryA": df_A, "FactoryB": df_B, "FactoryC": df_C}
        """
        try:
            if solar_df.empty:
                raise DataProcessingError("입력 데이터가 비어있습니다.")

            # 1단계: 데이터 타입 변환 및 검증
            solar_df = self._validate_and_convert_types(solar_df)

            # 2단계: 이상치 처리
            solar_df = self._handle_outliers(solar_df)

            # 3단계: 공장별 분류
            factory_data = self._classify_by_factory(solar_df)

            # 4단계: 공장별 집계
            aggregated_data = self._aggregate_by_factory(factory_data)

            # 5단계: 품질 체크
            self._check_data_quality(solar_df, "태양광 데이터")

            # 결과 로깅
            for factory_name, df in aggregated_data.items():
                logger.info(f"{factory_name} 전처리 완료: {len(df)}건")

            return aggregated_data

        except Exception as e:
            logger.error(f"태양광 데이터 전처리 실패: {str(e)}")
            raise DataProcessingError(f"태양광 데이터 전처리 실패: {str(e)}")

    def _validate_and_convert_types(self, solar_df: pd.DataFrame) -> pd.DataFrame:
        """
        1단계: 데이터 타입 검증 및 변환

        Args:
            solar_df: 원본 태양광 데이터

        Returns:
            pd.DataFrame: 타입 변환된 데이터
        """
        # 데이터 복사
        solar_df = solar_df.copy()

        # config에서 solar_features 가져오기
        solar_features = ModelConfig.FEATURES.get("solar_features", [])

        # 숫자형 컬럼 데이터 타입 변환
        for col in solar_features:
            if col in solar_df.columns:
                s = solar_df[col].astype(str).str.strip().str.replace(',', '', regex=False)
                solar_df[col] = pd.to_numeric(s.replace({'': None, '-': None, 'NaN': None}), errors='coerce')

        logger.info(f"숫자형 컬럼 데이터 타입 변환 완료: {solar_features}")

        # 시간 컬럼을 datetime으로 변환
        solar_df['ymdhms'] = pd.to_datetime(solar_df['ymdhms'])
        solar_df['HOUR'] = solar_df['ymdhms'].dt.hour

        return solar_df

    def _handle_outliers(self, solar_df: pd.DataFrame) -> pd.DataFrame:
        """
        2단계: 이상치 처리

        Args:
            solar_df: 타입 변환된 태양광 데이터

        Returns:
            pd.DataFrame: 이상치 처리된 데이터
        """
        # 음수값을 0으로 처리
        if 'generate_gap' in solar_df.columns:
            negative_count = (solar_df['generate_gap'] < 0).sum()
            if negative_count > 0:
                logger.info(f"⚠️ generate_gap 음수값 {negative_count}건 발견, 0으로 처리")
                solar_df.loc[solar_df['generate_gap'] < 0, 'generate_gap'] = 0

        return solar_df

    def _classify_by_factory(self, solar_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """
        3단계: ID별 공장 분류

        Args:
            solar_df: 이상치 처리된 태양광 데이터

        Returns:
            Dict[str, pd.DataFrame]: 공장별 분류된 데이터
        """
        # 공장별 ID 범위 정의
        factory_id_ranges = {
            'FactoryA': range(1, 13),    # ID 1-12
            'FactoryB': range(13, 16),   # ID 13-15
            'FactoryC': range(16, 19),   # ID 16-18
            'Factory_Total': range(1, 19) # ID 1-18 전체
        }

        classified_data = {}
        logger.info(f"🏭 ID별 공장 분류 결과:")

        for factory_name, id_range in factory_id_ranges.items():
            factory_df = solar_df[solar_df['id'].isin(id_range)].copy()
            classified_data[factory_name] = factory_df

            # 로깅
            unique_ids = sorted(factory_df['id'].unique()) if not factory_df.empty else []
            logger.info(f"  {factory_name}: {len(factory_df)}건, 고유 ID: {unique_ids}")

            # Factory_Total의 경우 추가 통계 로깅
            if factory_name == 'Factory_Total' and not factory_df.empty:
                logger.info(f"   📊 {factory_name} 상세 정보:")
                logger.info(f"     ID 범위: {factory_df['id'].min()} ~ {factory_df['id'].max()}")
                logger.info(f"     시간 범위: {factory_df['ymdhms'].min()} ~ {factory_df['ymdhms'].max()}")

                # 주요 feature 통계
                solar_features = ModelConfig.FEATURES.get("solar_features", [])
                for feature in solar_features:
                    if feature in factory_df.columns:
                        logger.info(
                            f"     {feature}: "
                            f"min={factory_df[feature].min():.4f}, "
                            f"max={factory_df[feature].max():.4f}, "
                            f"mean={factory_df[feature].mean():.4f}, "
                            f"count={factory_df[feature].notna().sum()}"
                        )

        return classified_data

    def _aggregate_by_factory(self, factory_data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """
        4단계: 공장별 집계

        Args:
            factory_data: 공장별 분류된 데이터

        Returns:
            Dict[str, pd.DataFrame]: 공장별 집계된 데이터
        """
        aggregated_data = {}

        for factory_name, factory_df in factory_data.items():
            if factory_df.empty:
                aggregated_data[factory_name] = pd.DataFrame()
                logger.warning(f"⚠️ {factory_name} 데이터가 비어있습니다")
            else:
                aggregated_df = self.aggregate_daily_solar_data(factory_df)
                aggregated_df = aggregated_df.fillna(0)
                aggregated_data[factory_name] = aggregated_df

        logger.info("✅ 공장별 집계 완료")
        return aggregated_data

    

    def _get_solar_scaler_by_factory(self, factory_name: str):
        """공장명에 따라 해당하는 태양광 스케일러 반환"""
        scaler_map = {
            'FactoryA': self.solar_scaler_A,
            'FactoryB': self.solar_scaler_B,
            'FactoryC': self.solar_scaler_C,
            'Factory_Total': self.solar_scaler_T
        }
        return scaler_map.get(factory_name)

    @staticmethod
    def add_time_cyclic_features(df, date_col='tm'):
        """
        시간/날짜 관련 파생 변수 만들기 - 기상 데이터

        입력 df에 다음 컬럼을 추가:
        - hour     : 시간 (0-23)
        - hour_sin : 시간의 주기형 인코딩 (24시간 주기)
        - hour_cos : 시간의 주기형 인코딩 (24시간 주기)
        - sin_week : 요일의 주기형 인코딩 (7일 주기)
        - cos_week : 요일의 주기형 인코딩 (7일 주기)
        - sin_day  : 연중일(DOY)의 주기형 인코딩 (365/366일 주기)
        - cos_day  : 연중일(DOY)의 주기형 인코딩 (365/366일 주기)
        - peak_hours : 피크 시간대 (10-14시, 1/0)
        - is_daylight : 일광 시간대 (6-18시, 1/0)
        """
        out = df.copy()

        # datetime 변환
        out[date_col] = pd.to_datetime(out[date_col], errors='coerce')
        # 1. 기본 시간 특성
        out['hour'] = out[date_col].dt.hour
        out['day_of_week'] = out[date_col].dt.dayofweek
        out['month'] = out[date_col].dt.month
        out['is_weekend'] = (out[date_col].dt.dayofweek >= 5).astype(int)
        
        # 2. 순환 인코딩 (태양광에 중요!)
        out['hour_sin'] = np.sin(2 * np.pi * out['hour'] / 24)
        out['hour_cos'] = np.cos(2 * np.pi * out['hour'] / 24)
        out['day_sin'] = np.sin(2 * np.pi * out['day_of_week'] / 7)
        out['day_cos'] = np.cos(2 * np.pi * out['day_of_week'] / 7)
        out['month_sin'] = np.sin(2 * np.pi * out['month'] / 12)
        out['month_cos'] = np.cos(2 * np.pi * out['month'] / 12)
        
        # 3. 태양광 특화 시간 특성
        out['is_daylight'] = ((out['hour'] >= 6) & (out['hour'] <= 18)).astype(int)
        out['peak_hours'] = ((out['hour'] >= 10) & (out['hour'] <= 14)).astype(int)
        out['morning_hours'] = ((out['hour'] >= 6) & (out['hour'] <= 10)).astype(int)
        out['evening_hours'] = ((out['hour'] >= 14) & (out['hour'] <= 18)).astype(int)
    
        
        # 4. 라마단 특성 (여름철 피크 발전 시간)
        summer_months = [6, 7, 8]
        out['summer_peak'] = ((out['month'].isin(summer_months)) & 
                            (out['peak_hours'] == 1)).astype(int)

        return out

    def preprocess_weather_data(self, weather_df: pd.DataFrame) -> pd.DataFrame:
        """
        기상 데이터 전처리

        Args:
            weather_df: tb_weather_info 테이블에서 가져온 기상 데이터

        Returns:
            pd.DataFrame: 전처리된 기상 데이터
        """
        try:
            if weather_df.empty:
                raise DataProcessingError("기상 데이터가 비어있습니다.")

            weather_df = weather_df.copy()

            # 영어 컬럼명을 한국어로 변환 (모델 학습 시 사용된 컬럼명)
            column_mapping = {
                'tmp': '1시간기온',
                'pop': '강수확률',
                'reh': '습도',
                'wsd': '풍속',
                'sky': '하늘상태',
                'pty': '강수형태',
                'pcp': '1시간강수량',
                'sno': '1시간신적설',
                'tmn': '일최저기온',
                'tmx': '일최고기온',
                'uuu': '동서바람성분',
                'vvv': '남북바람성분',
                'wav': '파고',
                'vec': '풍향'
            }

            # 숫자형 컬럼 데이터 타입 변환 (문자열로 저장된 숫자 처리)
            # config에서 weather_features 가져와서 DB 원본 컬럼(영문)만 추출
            weather_features = ModelConfig.FEATURES.get("weather_features", [])

            # 한국어 feature를 영어 DB 컬럼으로 역매핑 + apparent_elevation 추가
            reverse_mapping = {v: k for k, v in column_mapping.items()}
            base_db_columns = []
            for feature in weather_features:
                if feature in reverse_mapping:
                    base_db_columns.append(reverse_mapping[feature])
                elif feature == 'apparent_elevation':  # 이미 영어로 된 컬럼
                    base_db_columns.append('apparent_elevation')
                # hour_cos, peak_hours, is_daylight는 파생 feature이므로 제외

            # 중복 제거
            base_db_columns = list(set(base_db_columns))

            for c in base_db_columns:
                if c in weather_df.columns:
                    s = weather_df[c].astype(str).str.strip().str.replace(',', '', regex=False)
                    weather_df[c] = pd.to_numeric(s.replace({'': None, '-': None, 'NaN': None}), errors='coerce')

            logger.info(f"기상 데이터 숫자형 컬럼 타입 변환 완료: {base_db_columns}")

            # 시간 컬럼을 datetime으로 변환
            weather_df['tm'] = pd.to_datetime(weather_df['tm'])

            for eng_col, kor_col in column_mapping.items():
                if eng_col in weather_df.columns:
                    weather_df[kor_col] = weather_df[eng_col]

            # apparent_elevation은 이미 영어로 되어 있으므로 그대로 사용

            logger.info(f"컬럼명 매핑 완료: {list(column_mapping.keys())} → {list(column_mapping.values())}")

            # 파생 변수 생성
            weather_df = self.add_time_cyclic_features(weather_df, 'tm')

            # 결측치 처리
            weather_df = weather_df.fillna(0)

            # 전처리 결과 샘플 로깅
            logger.info(f"📊 전처리된 기상 데이터 샘플 (처음 5개):")
            logger.info(f"기상 데이터 전처리 완료: {len(weather_df)}건")
            logger.info(f"기상 데이터 전처리 완료: {weather_df.shape}")
            logger.info(f"전처리 후 컬럼: {list(weather_df.columns)}")
            return weather_df

        except Exception as e:
            logger.error(f"기상 데이터 전처리 실패: {str(e)}")
            raise DataProcessingError(f"기상 데이터 전처리 실패: {str(e)}")

    def create_separate_sequences(self, solar_df: pd.DataFrame, weather_df: pd.DataFrame,
                                  solar_scaler, weather_scaler,
                                  past_history: int = 168, future_target: int = 24) -> Dict[str, np.ndarray]:
        """
        Solar와 Weather 데이터를 별도로 시퀀스 생성 (Merge 없이)

        Args:
            solar_df: 태양광 데이터 (과거 데이터, ymdhms 포함)
            weather_df: 기상 데이터 (미래 데이터, tm 포함)
            solar_scaler: 태양광 스케일러
            weather_scaler: 기상 스케일러
            past_history: 과거 입력 길이 (168시간)
            future_target: 미래 예측 길이 (24시간)

        Returns:
            Dict with X_solar (N, 168, 2), X_weather (N, 24, 10), timestamps (N, 24)
        """
        logger.info(f"🔍 개별 시퀀스 생성 시작")

        # Solar features 추출 및 스케일링
        solar_features = [col for col in ModelConfig.FEATURES['solar_features'] if col in solar_df.columns]
        X_solar = solar_df[solar_features].fillna(0)
        Scaled_X_solar = solar_scaler.transform(X_solar)

        logger.info(f"   Solar 데이터: {len(Scaled_X_solar)}건, features: {solar_features}")
        logger.info(f"   Solar 범위: {solar_df['ymdhms'].min()} ~ {solar_df['ymdhms'].max()}")

        # Solar 데이터 통계 (Factory_Total이면 상세 로깅)
        for feature in solar_features:
            if feature in solar_df.columns:
                logger.info(f"   📊 {feature}: min={solar_df[feature].min():.4f}, max={solar_df[feature].max():.4f}, mean={solar_df[feature].mean():.4f}")

        # Weather features 추출 및 스케일링
        # scaler에서 추출한 weather features 사용
        if self.weather_features_from_scaler:
            # scaler에서 추출한 features가 있으면 그것 사용
            weather_features = [col for col in self.weather_features_from_scaler if col in weather_df.columns]
            logger.info(f"   Scaler에서 추출한 Weather features 사용: {weather_features}")
        else:
            # scaler에서 feature names을 찾을 수 없으면 config에서 사용
            weather_features = [col for col in ModelConfig.FEATURES['weather_features'] if col in weather_df.columns]
            logger.info(f"   Config에서 Weather features 추출: {weather_features}")

        X_weather = weather_df[weather_features].fillna(0)
        logger.info(f"   Weather DataFrame columns: {X_weather.columns.tolist()}")

        # scaler의 feature names 순서로 정렬
        if hasattr(weather_scaler, 'feature_names_in_'):
            scaler_feature_names = weather_scaler.feature_names_in_.tolist()
            logger.info(f"   Scaler feature names: {scaler_feature_names}")
            # scaler의 순서와 일치하도록 재정렬
            X_weather = X_weather[scaler_feature_names]
            logger.info(f"   Scaler 순서에 맞춰 정렬된 X_weather columns: {X_weather.columns.tolist()}")

        Scaled_X_weather = weather_scaler.transform(X_weather)

        logger.info(f"   Weather 데이터: {len(Scaled_X_weather)}건, features: {weather_features}")
        logger.info(f"   Weather 범위: {weather_df['tm'].min()} ~ {weather_df['tm'].max()}")

        # 시퀀스 생성 가능 개수 계산
        # Solar에서 168개씩, Weather에서 24개씩 슬라이딩
        max_solar_sequences = len(Scaled_X_solar) - past_history + 1
        max_weather_sequences = len(Scaled_X_weather) - future_target + 1
        num_sequences = min(max_solar_sequences, max_weather_sequences)

        logger.info(f"   Solar 최대 시퀀스: {max_solar_sequences}개")
        logger.info(f"   Weather 최대 시퀀스: {max_weather_sequences}개")
        logger.info(f"   생성 가능 시퀀스: {num_sequences}개")

        if num_sequences <= 0:
            logger.error(f"   ❌ 시퀀스 생성 불가!")
            return {
                'X_solar': np.array([]),
                'X_weather': np.array([]),
                'timestamps': np.array([])
            }

        # 시퀀스 생성
        dataset_X_solar = []
        dataset_X_weather = []
        dataset_time = []

        weather_times = weather_df['tm'].values

        for i in range(num_sequences):
            # Solar 과거 168h (슬라이딩)
            solar_seq = Scaled_X_solar[i:i + past_history]

            # Weather 미래 24h (슬라이딩)
            weather_seq = Scaled_X_weather[i:i + future_target]

            # 미래 시간 (Weather의 timestamp)
            future_time = weather_times[i:i + future_target]

            dataset_X_solar.append(solar_seq)
            dataset_X_weather.append(weather_seq)
            dataset_time.append(future_time)

        X_solar_array = np.array(dataset_X_solar)
        X_weather_array = np.array(dataset_X_weather)
        T_array = np.array(dataset_time)

        logger.info(f"   ✅ 시퀀스 생성 완료: {num_sequences}개")
        logger.info(f"   X_solar shape: {X_solar_array.shape}")
        logger.info(f"   X_weather shape: {X_weather_array.shape}")

        return {
            'X_solar': X_solar_array,
            'X_weather': X_weather_array,
            'timestamps': T_array
        }


    def _check_data_quality(self, df: pd.DataFrame, data_type: str):
        """데이터 품질 체크"""
        total_rows = len(df)
        
        if total_rows == 0:
            raise DataProcessingError(f"{data_type}가 비어있습니다.")
        
        # 결측치 비율 체크
        missing_ratio = df.isnull().sum().sum() / (total_rows * len(df.columns))
        if missing_ratio > settings.MISSING_VALUE_THRESHOLD:
            logger.warning(f"{data_type} 결측치 비율이 높습니다: {missing_ratio:.2%}")
        
        # 수치형 컬럼의 무한값 체크
        numeric_columns = df.select_dtypes(include=[np.number]).columns
        for col in numeric_columns:
            if np.isinf(df[col]).any():
                logger.warning(f"{data_type}의 {col} 컬럼에 무한값이 있습니다.")
        
        logger.info(f"{data_type} 품질 체크 완료 - 총 {total_rows}건, 결측치 비율: {missing_ratio:.2%}")


# 전역 데이터 프로세서 인스턴스
_data_processor = None

def get_data_processor() -> DataProcessor:
    """데이터 프로세서 의존성 주입"""
    global _data_processor
    if _data_processor is None:
        _data_processor = DataProcessor()
    return _data_processor