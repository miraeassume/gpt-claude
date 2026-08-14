# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

IFRS17 및 K-ICS 규제 기준에 따른 **원화 할인율 곡선(Smith-Wilson)** 산출 도구. 금융감독원(FSS) 고시 방법론을 구현하며, KOFIA 국고채 YTM 데이터를 입력받아 최대 100년 만기 할인율 곡선을 계산하고 Excel 및 PNG 차트로 출력한다.

## 실행 방법

```bash
pip install numpy pandas scipy matplotlib openpyxl
python ifrs17_krw_curve.py
```

## 알고리즘 (FSS 간소화 xlsm VBA 완전 정합 버전 v4)

### 산출 흐름

```
BOND_YIELDS_PCT (국고채 YTM)
  → [Step 1] SmithWilsonYTM (Module2)
        UFR = 50Y YTM, alpha=0.1
        쿠폰행렬 직접 피팅: ZETA = (CWC')^-1 * (m - Cu)
        출력: F 컬럼 — 연속 현물금리 @ 관찰 만기 + LLP=23Y
  → [Step 2] LP 가산
        G = LN(EXP(F) + LP)  [≤ LLP 구간]
  → [Step 3] Alpha 자동 산출 (VBA SmithWilson_ALPHA_UB_LB)
        UFR_SW2 = 0.0 (Excel U7=0)
        이분탐색: CP=60Y에서 순간선도금리 → 0%
        결과: alpha ≈ 0.17453479 (2026년 7월)
  → [Step 4] SmithWilson (Module1)
        UFR = UFR_SW2 = 0.0, alpha = [Step 3 결과]
        ZETA = W^-1 * (P - M), 월 단위 외삽
        출력: 연속 현물금리 @ P=0~1200월
  → [Step 5] Cont2Discrete (Module3)
        U = EXP(cont_spot) - 1
  → [Step 6] Forward (V 컬럼)
        V(P=m) = (1+U(P=m+1))^(m+1) / (1+U(P=m))^m - 1
```

### 핵심 파라미터

| 변수 | 역할 | 값 |
|------|------|----|
| `LLP` | 최종관찰만기 | 23년 |
| `CP`  | 최초수렴시점 | 60년 |
| `LTFR` | 장기선도금리 (참고용) | 4.30% |
| `UFR_SW2` | **Step2/Alpha 교정 UFR** | **0.00%** (Excel U7=0) |
| `COUPON_FREQ` | 이자지급횟수 | 연 2회 |
| `LP_PCT` | 유동성프리미엄 | 매월 FSS 고시값 |
| `BOND_YIELDS_PCT` | 국고채 YTM | 매월 KOFIA 데이터 |

### VBA 정합 핵심 사항

1. **`_ytm_price`**: T가 dt(=1/freq)의 배수가 **아닌** 경우 (0.25Y, 0.75Y 등),
   DF = `1/(1+YTM*T)` (단순이자) 사용 — VBA의 `CInt(T/dt)` 판별과 동일

2. **UFR_SW2 = 0.0**: SmithWilson Step2 및 Alpha 교정 모두 UFR=0 사용
   - Excel 간소화 파일의 U7 셀 = 0 직접 대응
   - Alpha는 CP=60Y에서 순간선도금리 → 0%로 수렴

3. **F/G/U/V 컬럼**: Excel 간소화 파일 컬럼명과 동일
   - F: SW1 Spot(Cont) at 관찰 만기
   - G: Spot(Cont)+LP at 관찰 만기
   - U: 최종 Spot(Discrete) at 월별
   - V: 최종 Forward(Discrete) at 월별

### 출력 파일

| 파일 | 설명 |
|------|------|
| `원화_LP_금리기간구조_{YYYYMMDD}.xlsx` | 4개 시트: U_V_월별, F_G_관찰점, 파라미터, 비교_연단위 |
| `원화_LP_금리기간구조_{YYYYMMDD}_차트.png` | Spot/Forward 차트 |

## 참고 파일

| 파일 | 용도 |
|------|------|
| `FSS_IFRS17 및 K-ICS 금리기간구조(원화)_'26.1_간소화.xlsm` | **정답 기준** (VBA Module1/2/3 포함) |
| `FSS_IFRS17 및 K-ICS 금리기간구조(원화)_'26.1.xlsm` | 원본 FSS 파일 (Jan 2026) |
| `채권시가평가기준수익률_0731.xls` | KOFIA 국고채 YTM 원본 |
| `KOFIA_국고채권_금리_수집 (1).md` | API 데이터 수집 방법 |

## 데이터 교체 방법 (매월)

1. `BOND_YIELDS_PCT`: KOFIA 최신 국고채 YTM으로 교체
2. `LP_PCT`: FSS 홈페이지 고시 유동성프리미엄으로 교체
3. `BASE_DATE`: 기준일 교체
4. `UFR_SW2`: Excel 간소화 파일 U7 셀 값 확인 (통상 0.0 유지)
