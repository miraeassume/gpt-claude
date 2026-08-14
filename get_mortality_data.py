#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
KOSIS API에서 연령별, 성별 사망률 데이터 추출
"""

import requests
import pandas as pd
import json
from urllib3.exceptions import InsecureRequestWarning

# SSL 경고 억제
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# ============================================================================
# 설정
# ============================================================================
API_KEY = "Zjg5NjBmYWQ5ZTMzNmRjOWZmMDc5YmYyNWY5YzVjYTE="
API_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"

PARAMS = {
    "method": "getList",
    "apiKey": API_KEY,
    "itmId": "T1 T5",
    "objL1": "0 1 2 3 4 5 6 7 8 9 A B C D E F G H I J",
    "objL2": "ALL",
    "objL3": "ALL",
    "format": "json",
    "jsonVD": "Y",
    "prdSe": "Y",
    "newEstPrdCnt": 5,
    "orgId": "101",
    "tblId": "DT_1B34E01"
}

# ============================================================================
# 함수
# ============================================================================

def fetch_mortality_data():
    """KOSIS API에서 사망률 데이터 조회"""
    print("🔄 KOSIS API에서 데이터를 가져오는 중...")

    try:
        response = requests.get(API_URL, params=PARAMS, timeout=60, verify=False)
        response.encoding = 'utf-8'
        response.raise_for_status()

        data = response.json()
        print(f"✅ 데이터 조회 성공! (상태코드: {response.status_code})")
        print(f"📊 총 {len(data):,}개 레코드 확인됨")

        return data

    except requests.exceptions.Timeout:
        print("❌ 타임아웃: 서버 응답 시간 초과")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ 요청 오류: {e}")
        return None
    except json.JSONDecodeError:
        print("❌ JSON 파싱 오류")
        return None


def process_mortality_data(data):
    """
    API 응답 데이터를 처리하여 연령별, 성별 사망률만 추출
    """
    if not data or len(data) == 0:
        print("❌ 데이터 없음")
        return None

    print("\n🔍 연령별, 성별 사망률 데이터 필터링 중...")

    # DataFrame 생성
    df = pd.DataFrame(data)

    print(f"   원본 레코드: {len(df):,}개")

    # ========================================================================
    # 필터링: 사망률 데이터만 추출 (ITM_NM == '사망률')
    # ========================================================================

    # 먼저 어떤 항목들이 있는지 확인
    print(f"\n   📋 포함된 항목명:")
    for item in df['ITM_NM'].unique():
        count = len(df[df['ITM_NM'] == item])
        print(f"      - {item}: {count:,}개")

    # 사망률 데이터만 필터링
    df_mortality = df[df['ITM_NM'] == '사망률'].copy()
    print(f"\n   ✅ 사망률 데이터: {len(df_mortality):,}개")

    if len(df_mortality) == 0:
        print("❌ 사망률 데이터를 찾을 수 없습니다")
        return None

    # ========================================================================
    # 연령별, 성별 필터링
    # ========================================================================
    print(f"\n   📊 성별 분포:")
    for sex in df_mortality['C2_NM'].unique():
        count = len(df_mortality[df_mortality['C2_NM'] == sex])
        print(f"      - {sex}: {count:,}개")

    print(f"\n   📊 연령대 분포:")
    for age in sorted(df_mortality['C3_NM'].unique()):
        count = len(df_mortality[df_mortality['C3_NM'] == age])
        print(f"      - {age}: {count:,}개")

    print(f"\n   📅 연도 분포:")
    for year in sorted(df_mortality['PRD_DE'].unique()):
        count = len(df_mortality[df_mortality['PRD_DE'] == year])
        print(f"      - {year}: {count:,}개")

    # ========================================================================
    # 필요한 컬럼만 선택 및 이름 변경
    # ========================================================================
    df_result = df_mortality[[
        'PRD_DE',      # 연도
        'C2_NM',       # 성별
        'C3_NM',       # 연령대
        'DT',          # 데이터값
        'UNIT_NM',     # 단위
        'ITM_NM'       # 항목명
    ]].copy()

    df_result.columns = ['연도', '성별', '연령대', '사망률', '단위', '항목명']

    return df_result


def clean_and_format_data(df):
    """데이터 정제 및 포맷팅"""
    if df is None or df.empty:
        return None

    df_clean = df.copy()

    print("\n🧹 데이터 정제 중...")
    print(f"   정제 전: {len(df_clean):,}개 행")

    # ========================================================================
    # 1. 성별 필터링: '계' 제거 (남, 여만 유지)
    # ========================================================================
    print(f"\n   성별 종류: {df_clean['성별'].unique().tolist()}")
    df_clean = df_clean[df_clean['성별'] != '계'].copy()
    print(f"   ✅ '계' 제거 후: {len(df_clean):,}개 행")

    # ========================================================================
    # 2. 연령대 필터링: '계' 제거 (구체적 연령만 유지)
    # ========================================================================
    print(f"\n   연령대 종류 (샘플): {df_clean['연령대'].unique()[:10].tolist()}")
    df_clean = df_clean[df_clean['연령대'] != '계'].copy()
    print(f"   ✅ 연령대 '계' 제거 후: {len(df_clean):,}개 행")

    # ========================================================================
    # 3. 사망률을 숫자로 변환
    # ========================================================================
    df_clean['사망률'] = pd.to_numeric(df_clean['사망률'], errors='coerce')

    # ========================================================================
    # 4. 빈 행 제거
    # ========================================================================
    df_clean = df_clean.dropna(subset=['사망률'])
    print(f"   ✅ 빈 행 제거 후: {len(df_clean):,}개 행")

    # ========================================================================
    # 5. 중복 제거 (연도, 성별, 연령대가 같은 행 제거)
    # ========================================================================
    duplicates_before = len(df_clean)
    df_clean = df_clean.drop_duplicates(subset=['연도', '성별', '연령대'], keep='first')
    duplicates_removed = duplicates_before - len(df_clean)
    if duplicates_removed > 0:
        print(f"   ✅ 중복 행 제거: {duplicates_removed:,}개 제거됨")

    # ========================================================================
    # 6. 연도를 정수로 변환
    # ========================================================================
    df_clean['연도'] = df_clean['연도'].astype(int)

    # ========================================================================
    # 7. 정렬
    # ========================================================================
    df_clean = df_clean.sort_values(['연도', '성별', '연령대'], ascending=[False, True, True])

    print(f"   ✅ 최종: {len(df_clean):,}개 행\n")

    return df_clean


def save_to_excel(df, filename='사망률데이터.xlsx'):
    """Excel로 저장"""
    if df is None or df.empty:
        print("❌ 저장할 데이터가 없습니다")
        return False

    try:
        filepath = f"C:\\Users\\isu0627\\Desktop\\claude\\{filename}"

        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='사망률', index=False)

            # 워크시트 포맷팅
            worksheet = writer.sheets['사망률']
            worksheet.column_dimensions['A'].width = 10
            worksheet.column_dimensions['B'].width = 12
            worksheet.column_dimensions['C'].width = 15
            worksheet.column_dimensions['D'].width = 12
            worksheet.column_dimensions['E'].width = 10
            worksheet.column_dimensions['F'].width = 15

        print(f"\n✅ 데이터가 저장되었습니다:")
        print(f"   📁 {filepath}")
        return True

    except Exception as e:
        print(f"❌ Excel 저장 오류: {e}")
        return False


def print_summary(df):
    """데이터 요약 출력"""
    if df is None or df.empty:
        print("❌ 출력할 데이터가 없습니다")
        return

    print("\n" + "="*80)
    print("📈 연령별, 성별 사망률 요약")
    print("="*80)

    # 연도별 요약
    print("\n📅 연도별 통계:")
    year_summary = df.groupby('연도')['사망률'].agg(['count', 'mean', 'min', 'max']).round(2)
    year_summary.columns = ['레코드수', '평균사망률', '최소', '최대']
    print(year_summary)

    # 성별별 요약
    print("\n👥 성별별 평균 사망률:")
    sex_summary = df.groupby('성별')['사망률'].mean().round(2)
    for sex, rate in sex_summary.items():
        print(f"   {sex:4} : {rate:6.2f} (십만명당)")

    # 연령별 요약 (전체 평균)
    print("\n📊 연령별 평균 사망률 (전체 5개년):")
    age_summary = df.groupby('연령대')['사망률'].mean().sort_values(ascending=False).round(2)
    print(age_summary)

    # 최신 연도 상세 데이터
    latest_year = df['연도'].max()
    print(f"\n📋 {latest_year}년 상세 데이터 (성별 × 연령대):")
    latest_data = df[df['연도'] == latest_year].sort_values(['성별', '연령대']).reset_index(drop=True)

    # 깔끔한 형식으로 표시
    for sex in sorted(latest_data['성별'].unique()):
        sex_data = latest_data[latest_data['성별'] == sex]
        print(f"\n   【{sex}】")
        for _, row in sex_data.iterrows():
            print(f"      {row['연령대']:8} : {row['사망률']:7.2f} {row['단위']}")

    print("\n" + "="*80)


# ============================================================================
# 메인
# ============================================================================

def main():
    print("="*70)
    print("🏥 KOSIS 연령별·성별 사망률 데이터 추출 도구")
    print("="*70 + "\n")

    # 1. 데이터 조회
    raw_data = fetch_mortality_data()

    if raw_data is None:
        print("\n⚠️  데이터 조회 실패. 스크립트를 종료합니다.")
        return

    # 2. 데이터 처리
    df_processed = process_mortality_data(raw_data)

    if df_processed is None:
        print("\n⚠️  데이터 처리 실패. 스크립트를 종료합니다.")
        return

    # 3. 데이터 정제
    df_clean = clean_and_format_data(df_processed)

    if df_clean is None or df_clean.empty:
        print("\n⚠️  정제된 데이터가 없습니다.")
        return

    # 4. 요약 출력
    print_summary(df_clean)

    # 5. Excel로 저장
    save_to_excel(df_clean)

    print("\n✨ 작업 완료!")


if __name__ == "__main__":
    main()
