# K-ICS 원화 확률론적 할인율 생성 스크립트 설명

## 개요

**파일:** `hw1f_krw_stochastic.py`  
**목적:** K-ICS(보험자본기준) 별표22 5-3.다. 규정에 따른 원화 확률론적 할인율 시나리오 생성  
**모형:** Hull-White 1 Factor (HW1F)  
**기준일:** 2026-06-30  
**산출량:** 1,000개 시나리오 × 1,440월(120년)

---

## 산출 흐름

```
결정론적 금리기간구조 로드 (Excel)
  + VA(변동성 조정) 가산
       ↓
월단위 보간 + 120년 LTFR 외삽 → 초기 금리곡선 P(0,t), f(0,t)
       ↓
Hull-White θ(t) 산출 → 초기 곡선에 exact fitting
       ↓
스왑션 캘리브레이션 → a (단일), σ (6개 구간 구분)
       ↓
시뮬레이션 (Exact 이산화, Antithetic variates)
       ↓
결과 저장: Excel (4개 시트) + Fan Chart PNG
```

---

## K-ICS 규정 요약 (별표22 5-3.다.)

| 항목 | 규정 |
|------|------|
| 모형 | Hull-White 1 Factor |
| 시나리오 수 | 최소 1,000개 |
| 시간 단위 | 월단위 |
| 캘리브레이션 대상 | 스왑션 36개 (옵션만기×스왑만기 각 6종) |
| σ 구간 | 0~1, 1~2, 2~3, 3~5, 5~7, 7~10년 (6구간) |
| a 최저한도 | 0.0001 |

---

## 입력 파일

### 1. `결정론적할인율생성/원화_금리기간구조_20260630.xlsx`
- `ifrs17_krw_curve.py`의 산출물
- 시트: `금리기간구조` (만기(년), Spot Rate(%))
- 시트: `파라미터` (LTFR 값 포함)

**이 파일이 없으면 스크립트가 실행되지 않습니다.**  
`ifrs17_krw_curve.py`를 먼저 실행해야 합니다.

### 2. `swaption_vol_input.xlsx`
- 시트: `스왑션변동성` — ATM Normal vol (bp 단위), 6×6 행렬
  - 행: 옵션만기 (1, 2, 3, 5, 7, 10년)
  - 열: 스왑만기 (1, 2, 3, 5, 7, 10년)
- 시트: `파라미터입력`
  - `VA(bp)`: 변동성 조정 (감독원 공시값)
  - `시드(Seed)`: 난수 시드 (기본 42)

> **주의:** 현재 `스왑션변동성` 시트는 더미 데이터입니다.  
> 실제 시장 데이터(Bloomberg/Reuters ATM Normal vol)로 교체 후 재실행해야 합니다.

---

## 사용법

### 최초 실행: 입력 템플릿 생성
```bash
python hw1f_krw_stochastic.py --create-template
```
`swaption_vol_input.xlsx` 파일이 생성됩니다.

### 정상 실행
```bash
python hw1f_krw_stochastic.py
```

### 실행 전 체크리스트
1. `swaption_vol_input.xlsx` → `스왑션변동성` 시트에 실제 ATM Normal vol(bp) 입력
2. `swaption_vol_input.xlsx` → `파라미터입력` 시트에 감독원 공시 VA(bp) 값 입력
3. `결정론적할인율생성/원화_금리기간구조_20260630.xlsx` 파일 존재 확인

### 의존 패키지 설치
```bash
pip install numpy pandas scipy matplotlib openpyxl xlsxwriter
```

---

## 주요 함수 설명

### 금리곡선 구성

#### `load_initial_curve(det_path, va_bps)`
- 결정론적 Excel에서 Spot Rate 로드
- VA(bp)를 전 만기에 균등 가산
- LTFR(장기선도금리) 로드
- **반환:** `tenors_yr`, `df_annual`, `spot_cont`, `ltfr`

#### `build_fine_curve(tenors_yr, df_annual, spot_cont, ltfr, n_steps, dt)`
- 연단위 곡선을 월단위(1/12년)로 보간
- t=0 기점(logP(0)=0) 포함하여 1년 이내 선도금리 오류 방지
- 최대 만기(통상 60~100년) 초과 구간은 LTFR로 외삽
- **반환:** `t_fine`, `df_fine`, `f_fine`

### HW1F 모형 수식

#### `compute_v2(T, a, sigma_vals)`
$$v^2(T) = \int_0^T \sigma^2(s) e^{-2a(T-s)} \, ds$$
- 구간별 σ에 대한 해석해 계산
- T > 10년 구간도 마지막 σ값으로 연장 처리

#### `compute_phi(T, a, sigma_vals)`
$$\varphi(T) = \frac{\sigma^2}{a^2}(1-e^{-aT})^2 / 2 \quad \text{(상수 σ일 때)}$$
- 시뮬레이션 드리프트 보정항: α(t) = f(0,t) + φ(t)
- 구간별 σ에 대한 해석해 (T > 10년 구간 포함)

#### `hw_swaption_price(te, swap_tenor, K_swap, P0_func, f0te, a, sigma_vals)`
- **Jamshidian 분해**를 이용한 Payer swaption 가격 계산
- r* 탐색 → 각 만기별 ZCB 옵션 합산

### 캘리브레이션

#### `calibrate_hw(swaption_data, P0_func, f0_interp)`
- 목적함수: Σ(모형 Normal IV - 시장 Normal IV)² [bp²]
- 최적화: L-BFGS-B
- **최적화 변수:** a (1개) + σ (6개) = 7개 파라미터

### 시뮬레이션

#### `simulate_hw(a, sigma_vals, t_fine, df_fine, f_fine, ...)`
**Exact 이산화 공식:**
$$x(t+\Delta t) = x(t) \cdot e^{-a\Delta t} + \sigma(t)\sqrt{\frac{1-e^{-2a\Delta t}}{2a}} \cdot Z$$

$$r(t) = x(t) + \alpha(t), \quad \alpha(t) = f(0,t) + \varphi(t)$$

- **Antithetic variates:** 500개 난수 + 부호반전 500개 → 분산 감소

### 마팅게일 테스트

#### `martingale_test(r_paths, df_fine, dt)`
**검증 조건:** $E\left[e^{-\int_0^T r(s)ds}\right] = P(0,T)$

- 허용 오차: |E[DF]/P(0,t) - 1| < 1%
- 결과가 1%를 초과하면 a 파라미터 또는 시드 재검토 필요

---

## 출력 파일

### `원화_확률론적할인율_20260630.xlsx`
| 시트 | 내용 |
|------|------|
| `단기금리_경로` | (1440 × 1002) — 경과월, 경과년, S0001~S1000 시나리오 별 연복리 단기금리(%) |
| `마팅게일_테스트` | (1440 × 11) — 초기할인계수, 시나리오평균 누적DF, 비율, 퍼센타일 |
| `파라미터` | 기준일, VA, a, σ 6개, 시나리오 수, RMSE, 마팅게일 최대오차 |
| `스왑션_캘리브레이션` | 시장 NV vs 모형 NV 비교표 |

### `원화_확률론적할인율_20260630_차트.png`
- 좌: 단기금리 시나리오 Fan Chart (P1~P99)
- 우: 마팅게일 테스트 결과 (E[DF]/P(0,t))

---

## 핵심 버그 수정 이력

### Bug 1: 1년 이내 선도금리 0 오류
- **원인:** `build_fine_curve`에서 logP(0)=0 앵커 미포함 → 1년 이내 구간 보간 시 잘못된 기울기
- **수정:** `np.interp` 호출 시 t=0, logP=0 기점을 명시적으로 추가

### Bug 2: T > 10년 구간 σ 미계산
- **원인:** `_sigma_intervals`가 `SIGMA_BREAKPOINTS` 범위(0~10년) 이후를 처리하지 않음
- **수정:** bkpts[-1](=10년) 초과 시 마지막 σ값으로 구간 연장

### Bug 3: compute_phi 수식 오류
- **원인:** `simulate_hw`에서 `compute_v2(T)/2`를 드리프트 보정으로 사용 (수식 불일치)
- **수정:** `compute_phi(T)`를 직접 계산하는 별도 함수로 분리 및 대체

---

## GPT에서 이어서 작업 시 참고사항

1. **모형 수정 후 반드시 마팅게일 테스트로 검증** (허용: |비율-1| < 1%)
2. **`_sigma_intervals` 함수가 T > 10년 처리의 핵심** — 이 함수를 수정하면 `compute_v2`, `compute_phi`, `sigma_at` 전부 영향
3. **`build_fine_curve`의 t=0 앵커** — 제거하면 1년 이내 선도금리가 0이 되는 버그 재발
4. **캘리브레이션 수렴 실패 시:** 초기값 `x0` 또는 bounds 조정, 또는 최적화 method를 `Nelder-Mead`로 변경 시도
5. **메모리 이슈:** 단기금리 경로 행렬이 (1440 × 1000) × float64 = 약 11MB, Excel 저장 시 수 분 소요 정상

---

## 다음 단계

- [ ] `swaption_vol_input.xlsx` → 실제 ATM Normal vol(bp) 입력 (Bloomberg KRW swaption 기준)
- [ ] 감독원 공시 VA(bp) 값 입력
- [ ] `python hw1f_krw_stochastic.py` 재실행
- [ ] 마팅게일 테스트 결과 확인 (|오차| < 1%)
- [ ] 캘리브레이션 RMSE 확인 (목표: < 5bp)
