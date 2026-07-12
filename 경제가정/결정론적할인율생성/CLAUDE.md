# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

IFRS17 및 K-ICS 규제 기준에 따른 **원화 할인율 곡선(Smith-Wilson)** 산출 도구. 금융감독원(FSS) 고시 방법론을 구현하며, KOFIA 국고채 YTM 데이터를 입력받아 최대 100년 만기 할인율 곡선을 계산하고 Excel 및 PNG 차트로 출력한다.

## 실행 방법

```bash
# 의존 패키지 설치
pip install numpy pandas scipy matplotlib openpyxl

# 스크립트 실행 (출력: .xlsx + .png)
python ifrs17_krw_curve.py
```

별도 빌드, 테스트 프레임워크, 린트 설정 없음.

## 주요 파라미터 (스크립트 상단 하드코딩)

| 변수 | 의미 | 현재값 |
|------|------|--------|
| `LLP` | Last Liquid Point (최종유동점) | 23년 |
| `CP`  | Convergence Point (수렴점) | 60년 |
| `LTFR` | Long-Term Forward Rate (장기선도금리) | 4.30% |
| `LP`  | Liquidity Premium (유동성 프리미엄) | 0 bp |
| `BOND_YIELDS_PCT` | 만기별 국고채 YTM (%) | 더미 데이터 — 실사용 시 교체 필요 |

## 데이터 파이프라인

```
BOND_YIELDS_PCT (국고채 YTM dict)
  → interp_yields()   선형 보간 (1~23년 공백 채움)
  → bootstrap()       YTM → 할인계수 (par yield 부트스트랩)
  → df_to_spot()      할인계수 → 현물금리 (연속복리)
  → add_lp()          유동성 프리미엄 가산 (≤ LLP 구간)
  → calibrate_alpha() alpha 자동 탐색 (CP에서 LTFR ±1bp 수렴)
  → sw_fit()          Smith-Wilson 계수(ζ) 행렬 계산
  → [1~100년 루프]
      sw_df()         할인계수
      sw_fwd()        순간선도금리 (수치 미분)
  → DataFrame → Excel(.xlsx) + 차트(.png)
```

## 핵심 함수 역할

- `W(t, u, alpha)` — Wilson 커널 함수 (알고리즘의 수학적 핵심)
- `sw_fit()` — ζ 계수 행렬 풀기 (선형대수)
- `calibrate_alpha()` — `scipy.optimize.brentq`로 alpha 자동 탐색
- `run()` — 전체 파이프라인 오케스트레이션 + 파일 출력

## KOFIA 데이터 수집

실데이터 입력 방법은 저장소 내 `KOFIA_국고채권_금리_수집 (1).md` 참조.
API 응답의 `val1`~`val15` 필드가 각 만기(1M~30Y)에 해당한다.

## 참고 자료 (저장소 내)

- FSS 공시 할인율 곡선 Excel (2026년 1~5월)
- IFRS17 경제가정·K-ICS 할인율 기준 PDF 문서
