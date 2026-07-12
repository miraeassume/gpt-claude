"""
============================================================
  K-ICS 원화 확률론적 할인율 시나리오 생성
  Hull-White 1 Factor 모형 (K-ICS 별표22 5-3.다.)
============================================================

[산출 흐름]
  결정론적 Excel 로드 + VA 가산 (초기 금리곡선)
    → Hull-White θ(t) 산출 (초기 곡선 exact fitting)
    → 스왑션 캘리브레이션 (a 단일, σ 6구간)
    → 시나리오 시뮬레이션 (Exact 이산화, 1,000개 × 1,440월)
    → 결과 출력 (단기금리 경로 + 마팅게일 테스트)

[K-ICS 규정]
  - 모형: Hull-White 1 factor  dr = a[θ(t)-r]dt + σdW
  - 시나리오: 최소 1,000개
  - 월단위 시나리오 원칙
  - 모수: 스왑션 36개 (옵션만기×스왑만기 각 6종)
  - σ 구간: 0~1, 1~2, 2~3, 3~5, 5~7, 7~10년
  - a 최저한도: 0.0001

[사용법]
  1. swaption_vol_input.xlsx 입력값 확인/수정
  2. python hw1f_krw_stochastic.py
  3. 출력 Excel / 차트 확인

  입력 템플릿 신규 생성:
    python hw1f_krw_stochastic.py --create-template

[의존 패키지]
  pip install numpy pandas scipy matplotlib openpyxl xlsxwriter
"""

import sys
import os
import warnings
import numpy as np
import pandas as pd
from scipy.optimize import minimize, brentq
from scipy.stats import norm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

# ============================================================
# ★ 사용자 설정 구역
# ============================================================

BASE_DATE = "2026-06-30"

# 결정론적 금리기간구조 파일 (ifrs17_krw_curve.py 산출물)
DET_CURVE_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "결정론적할인율생성",
    "원화_금리기간구조_20260630.xlsx"
))

# 스왑션 / VA / 파라미터 입력 파일
SWAPTION_INPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "swaption_vol_input.xlsx"
)

# 시나리오 설정 (K-ICS: 최소 1,000개, 월단위)
N_SCENARIOS = 1000
MAX_YEARS   = 120
N_STEPS     = MAX_YEARS * 12      # 1,440
DT          = 1.0 / 12            # 월단위 (년)

# K-ICS 모수 제약
A_MIN             = 0.0001
SIGMA_BREAKPOINTS = [0, 1, 2, 3, 5, 7, 10]   # 6구간 경계

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 초기 금리곡선
# ============================================================

def load_initial_curve(det_path: str, va_bps: float):
    """
    결정론적 Excel에서 Spot Rate 로드 후 VA 가산.
    VA는 전 만기 동일 적용 (K-ICS 변동성 조정).

    Returns:
      tenors_yr  : array (1~MAX_TENOR)
      df_annual  : P(0,T) array (연속복리 기준)
      spot_cont  : 연속복리 Spot Rate array (VA 포함)
      ltfr       : 장기선도금리 (파라미터 시트에서 로드)
    """
    if not os.path.exists(det_path):
        raise FileNotFoundError(
            f"결정론적 금리기간구조 파일이 없습니다:\n  {det_path}\n"
            f"ifrs17_krw_curve.py를 먼저 실행하세요."
        )
    df_sheet = pd.read_excel(det_path, sheet_name="금리기간구조")
    tenors_yr  = df_sheet["만기(년)"].values.astype(float)
    spot_pct   = df_sheet["Spot Rate(%)"].values

    # VA 가산 (연속복리 Spot Rate, decimal)
    spot_cont  = spot_pct / 100.0 + va_bps / 10000.0
    df_annual  = np.exp(-spot_cont * tenors_yr)

    # LTFR 로드 (120년 외삽에 사용)
    try:
        param_sheet = pd.read_excel(det_path, sheet_name="파라미터")
        ltfr_row    = param_sheet[param_sheet.iloc[:, 0].astype(str).str.contains("LTFR")]
        ltfr        = float(ltfr_row.iloc[0, 1]) / 100.0 if len(ltfr_row) > 0 else 0.043
    except Exception:
        ltfr = 0.043  # default LTFR 4.30%

    return tenors_yr, df_annual, spot_cont, ltfr


def build_fine_curve(tenors_yr, df_annual, spot_cont, ltfr, n_steps, dt):
    """
    연단위 곡선을 월단위로 보간 + 최대 만기(120년) 이상 LTFR로 외삽.

    Returns:
      t_fine   : (n_steps,) 경과시간 배열 (년)
      df_fine  : (n_steps,) P(0,t) 배열
      f_fine   : (n_steps,) 순간 선도금리 f(0,t)
    """
    max_t      = n_steps * dt
    t_fine     = np.arange(1, n_steps + 1) * dt
    max_tenor  = tenors_yr.max()

    # log P(0,t) = -spot * t → 선형 보간 (연속복리 기준)
    # t=0 기점 (logP(0)=0) 포함: 0~1년 구간 선도금리가 0이 되는 버그 방지
    logP_known = -spot_cont * tenors_yr
    tenors_with_zero = np.concatenate([[0.0], tenors_yr])
    logP_with_zero   = np.concatenate([[0.0], logP_known])

    logP_fine = np.zeros(n_steps)
    for k, t in enumerate(t_fine):
        if t <= max_tenor:
            logP_fine[k] = np.interp(t, tenors_with_zero, logP_with_zero)
        else:
            # LTFR로 외삽: P(0,t) = P(0,max_tenor) * exp(-LTFR*(t-max_tenor))
            logP_fine[k] = logP_known[-1] + (-ltfr * (t - max_tenor))

    df_fine = np.exp(logP_fine)

    # 순간 선도금리 f(0,t) = -d/dt ln P(0,t)  (수치미분)
    f_fine       = np.zeros(n_steps)
    f_fine[0]    = -(logP_fine[1]  - logP_fine[0])  / dt
    f_fine[1:-1] = -(logP_fine[2:] - logP_fine[:-2]) / (2 * dt)
    f_fine[-1]   = -(logP_fine[-1] - logP_fine[-2]) / dt

    return t_fine, df_fine, f_fine


# ============================================================
# HW 모형 수식
# ============================================================

def hw_B(te: float, ti: float, a: float) -> float:
    """B(T_e, T_i) = (1 - e^{-a(T_i-T_e)}) / a"""
    return (1.0 - np.exp(-a * (ti - te))) / a


def _sigma_intervals(T, sigma_vals, bkpts=SIGMA_BREAKPOINTS):
    """
    T까지의 (lo, hi, sigma) 구간 리스트.
    bkpts 범위(0~10년) 이후는 마지막 σ로 연장.
    """
    intervals = []
    for i in range(len(sigma_vals)):
        lo = bkpts[i]
        if lo >= T:
            break
        hi = min(bkpts[i + 1], T)
        intervals.append((lo, hi, sigma_vals[i]))
    # bkpts[-1](=10년) 이후 구간: K-ICS 비관찰구간, 마지막 σ 값 연장 적용
    if T > bkpts[-1]:
        intervals.append((bkpts[-1], T, sigma_vals[-1]))
    return intervals


def compute_v2(T: float, a: float, sigma_vals, bkpts=SIGMA_BREAKPOINTS) -> float:
    """
    v²(T) = ∫₀ᵀ σ²(s)·e^{-2a(T-s)} ds
    Piecewise σ에 대한 해석해 (T > 10년 구간 포함).
    """
    if a < 1e-12:
        return sum(s ** 2 * (hi - lo) for lo, hi, s in _sigma_intervals(T, sigma_vals, bkpts))

    v2 = 0.0
    for lo, hi, sig in _sigma_intervals(T, sigma_vals, bkpts):
        v2 += sig ** 2 / (2.0 * a) * (
            np.exp(-2.0 * a * (T - hi)) - np.exp(-2.0 * a * (T - lo))
        )
    return v2


def sigma_at(t: float, sigma_vals, bkpts=SIGMA_BREAKPOINTS) -> float:
    """구간별 σ(t) 반환. t ≥ bkpts[-1](=10년) 이면 마지막 σ 사용."""
    for i in range(len(sigma_vals)):
        if t < bkpts[i + 1]:
            return sigma_vals[i]
    return sigma_vals[-1]  # t >= 10년: 비관찰구간, 마지막 σ 연장


def compute_phi(T: float, a: float, sigma_vals, bkpts=SIGMA_BREAKPOINTS) -> float:
    """
    φ(T) = α(T) - f(0,T) : 시뮬레이션 드리프트 보정항.

    φ(T) = ∫₀ᵀ σ²(s)/a · (e^{-a(T-s)} - e^{-2a(T-s)}) ds
    상수 σ일 때: φ(T) = σ²·B(0,T)²/2 = σ²·(1-e^{-aT})²/(2a²)
    T > 10년 구간도 마지막 σ 값으로 연장 처리 (_sigma_intervals 사용).
    """
    if a < 1e-12:
        return sum(s ** 2 * 0.5 * (hi - lo) ** 2
                   for lo, hi, s in _sigma_intervals(T, sigma_vals, bkpts))

    phi = 0.0
    for lo, hi, sig in _sigma_intervals(T, sigma_vals, bkpts):
        sig2 = sig ** 2
        A_k  = (1.0 / a) * (np.exp(-a * (T - hi)) - np.exp(-a * (T - lo)))
        C_k  = (1.0 / (2 * a)) * (np.exp(-2 * a * (T - hi)) - np.exp(-2 * a * (T - lo)))
        phi += sig2 / a * (A_k - C_k)
    return phi


def hw_A_log(te, ti, P0te, P0ti, f0te, a, sigma_vals, bkpts=SIGMA_BREAKPOINTS):
    """ln A(T_e, T_i) (Jamshidian 분해에 사용)"""
    B   = hw_B(te, ti, a)
    v2  = compute_v2(te, a, sigma_vals, bkpts)
    return np.log(P0ti / P0te) + B * f0te - 0.5 * v2 * B ** 2


# ============================================================
# 스왑션 가격 (Jamshidian 분해)
# ============================================================

def _swaption_components(te, swap_tenor, K_swap, P0_func, f0te, a, sigma_vals,
                          bkpts=SIGMA_BREAKPOINTS, freq=1):
    """
    Jamshidian 분해에 필요한 사전 계산값 반환.
    Returns (pay_dates, cash_flows, P0ti_arr, A_arr, B_arr, v_te)
    """
    dt_swap    = 1.0 / freq
    n          = int(round(swap_tenor * freq))
    pay_dates  = [te + (i + 1) * dt_swap for i in range(n)]
    P0te       = P0_func(te)
    P0ti_arr   = np.array([P0_func(ti) for ti in pay_dates])
    A_log_arr  = np.array([
        hw_A_log(te, ti, P0te, P0ti, f0te, a, sigma_vals, bkpts)
        for ti, P0ti in zip(pay_dates, P0ti_arr)
    ])
    B_arr      = np.array([hw_B(te, ti, a) for ti in pay_dates])
    v2_te      = compute_v2(te, a, sigma_vals, bkpts)
    v_te       = np.sqrt(max(v2_te, 1e-16))

    cash_flows          = np.full(n, K_swap * dt_swap)
    cash_flows[-1]     += 1.0

    return pay_dates, cash_flows, P0te, P0ti_arr, A_log_arr, B_arr, v_te


def hw_swaption_price(te, swap_tenor, K_swap, P0_func, f0te, a, sigma_vals,
                       bkpts=SIGMA_BREAKPOINTS, freq=1):
    """
    Payer swaption 가격 (Jamshidian 분해, 명목원금 1 기준).
    Returns price (절대값, not normalized by annuity)
    """
    if te <= 0 or swap_tenor <= 0:
        return 0.0

    _, cash_flows, P0te, P0ti_arr, A_log_arr, B_arr, v_te = \
        _swaption_components(te, swap_tenor, K_swap, P0_func, f0te, a, sigma_vals, bkpts, freq)
    n = len(cash_flows)

    # r* 탐색: Σ cᵢ·A(T_e,Tᵢ)·e^{-B(T_e,Tᵢ)·r*} = 1
    def bond_val(r):
        return np.sum(cash_flows * np.exp(A_log_arr - B_arr * r)) - 1.0

    try:
        r_star = brentq(bond_val, -1.0, 3.0, xtol=1e-10, maxiter=200)
    except ValueError:
        return np.nan

    K_i_arr = np.exp(A_log_arr - B_arr * r_star)   # 각 원금옵션 행사가

    price = 0.0
    for i in range(n):
        sigma_p = B_arr[i] * v_te
        if sigma_p < 1e-12:
            price += cash_flows[i] * max(K_i_arr[i] * P0te - P0ti_arr[i], 0.0)
            continue
        h = (np.log(P0ti_arr[i] / (K_i_arr[i] * P0te)) / sigma_p) + sigma_p / 2.0
        # Put on ZCB (payer swaption 성분)
        zbo = K_i_arr[i] * P0te * norm.cdf(-h + sigma_p) - P0ti_arr[i] * norm.cdf(-h)
        price += cash_flows[i] * zbo

    return max(price, 0.0)


def fwd_swap_rate_annuity(te, swap_tenor, P0_func, freq=1):
    """ATM forward swap rate K와 annuity 반환"""
    dt_swap  = 1.0 / freq
    n        = int(round(swap_tenor * freq))
    pay_dates = [te + (i + 1) * dt_swap for i in range(n)]
    annuity  = sum(P0_func(ti) * dt_swap for ti in pay_dates)
    K        = (P0_func(te) - P0_func(te + swap_tenor)) / annuity if annuity > 1e-12 else 0.0
    return K, annuity


def normal_vol_to_price(te, swap_tenor, normal_vol_bps, P0_func):
    """
    ATM Normal(Bachelier) swaption price (명목 1 기준).
    normal_vol_bps: Normal vol (bp 단위)
    """
    nv = normal_vol_bps / 10000.0
    K, annuity = fwd_swap_rate_annuity(te, swap_tenor, P0_func)
    # ATM Bachelier: Price = A · σ_N · √(T_e/(2π))
    return annuity * nv * np.sqrt(te / (2.0 * np.pi))


def price_to_normal_vol_bps(price, te, swap_tenor, P0_func):
    """모형 가격 → Normal IV (bp)"""
    K, annuity = fwd_swap_rate_annuity(te, swap_tenor, P0_func)
    if annuity < 1e-12 or te <= 0:
        return np.nan
    nv = price / (annuity * np.sqrt(te / (2.0 * np.pi)))
    return nv * 10000.0


# ============================================================
# 캘리브레이션
# ============================================================

def calibrate_hw(swaption_data, P0_func, f0_interp,
                 bkpts=SIGMA_BREAKPOINTS, a_min=A_MIN, verbose=True):
    """
    (a, σ_1,...,σ_6) 최적화.
    목적함수: Σ (모형 Normal IV - 시장 Normal IV)² [bps² 단위]
    swaption_data: list of {'option_expiry', 'swap_tenor', 'normal_vol_bps'}
    """
    def objective(params):
        a         = max(params[0], a_min)
        sig_vals  = np.abs(params[1:])
        total_err = 0.0

        for d in swaption_data:
            te, ts, nv_mkt = d['option_expiry'], d['swap_tenor'], d['normal_vol_bps']
            f0te  = float(f0_interp(te))
            K, _  = fwd_swap_rate_annuity(te, ts, P0_func)
            mkt_p = normal_vol_to_price(te, ts, nv_mkt, P0_func)
            mdl_p = hw_swaption_price(te, ts, K, P0_func, f0te, a, sig_vals, bkpts)

            if np.isnan(mdl_p) or mkt_p < 1e-15:
                total_err += 1e4
                continue
            nv_mdl = price_to_normal_vol_bps(mdl_p, te, ts, P0_func)
            if np.isnan(nv_mdl):
                total_err += 1e4
                continue
            total_err += (nv_mdl - nv_mkt) ** 2

        return total_err

    x0     = np.array([0.05] + [0.01] * 6)
    bounds = [(a_min, 2.0)] + [(1e-6, 0.30)] * 6

    res = minimize(objective, x0, method='L-BFGS-B', bounds=bounds,
                   options={'maxiter': 1000, 'ftol': 1e-14, 'gtol': 1e-9})

    a_cal    = max(float(res.x[0]), a_min)
    sig_cal  = np.abs(res.x[1:])

    if verbose:
        print(f"    최적화 목적함수값: {res.fun:.4f} bp²")
        print(f"    수렴 여부: {'성공' if res.success else '경고: 미수렴 - 결과 검토 필요'}")

    return a_cal, sig_cal, res


# ============================================================
# 시뮬레이션
# ============================================================

def simulate_hw(a, sigma_vals, t_fine, df_fine, f_fine,
                n_scenarios, n_steps, dt,
                seed=42, bkpts=SIGMA_BREAKPOINTS):
    """
    Hull-White 1F Exact 이산화.

    x(t+dt) = x(t)·e^{-a·dt} + σ(t)·√{(1-e^{-2a·dt})/(2a)}·Z
    r(t)    = x(t) + α(t)
    α(t)    = f(0,t) + v²(t)/2

    Antithetic variates: 상위 500개 난수 + 하위 부호반전 500개

    Returns:
      r_paths   : (n_scenarios, n_steps)  연속복리 단기금리
      alpha_arr : (n_steps,)              드리프트 조정항
    """
    print("    α(t) 사전 계산 중 ...")
    alpha_arr = np.zeros(n_steps)
    std_arr   = np.zeros(n_steps)
    decay     = np.exp(-a * dt)

    var_step  = (1.0 - np.exp(-2.0 * a * dt)) / (2.0 * a) if a > 1e-12 else dt

    for k in range(n_steps):
        t            = t_fine[k]
        alpha_arr[k] = f_fine[k] + compute_phi(t, a, sigma_vals, bkpts)
        std_arr[k]   = sigma_at(t, sigma_vals, bkpts) * np.sqrt(var_step)

    print(f"    시뮬레이션 ({n_scenarios} × {n_steps}) 중 ...")
    rng    = np.random.default_rng(seed)
    half   = n_scenarios // 2
    Z      = rng.standard_normal((half, n_steps))
    Z_full = np.concatenate([Z, -Z], axis=0)   # antithetic

    x        = np.zeros((n_scenarios, n_steps))
    x_prev   = np.zeros(n_scenarios)

    for k in range(n_steps):
        x_new    = x_prev * decay + std_arr[k] * Z_full[:, k]
        x[:, k]  = x_new
        x_prev   = x_new

    r_paths = x + alpha_arr[np.newaxis, :]
    return r_paths, alpha_arr


# ============================================================
# 마팅게일 테스트  (K-ICS 결과적정성 검증)
# ============================================================

def martingale_test(r_paths, df_fine, dt):
    """
    마팅게일 조건: E[exp(-∫₀ᵀ r(s)ds)] = P(0,T)

    Returns:
      avg_cum_df  : (n_steps,)  시나리오 평균 누적할인계수
      ratio       : (n_steps,)  마팅게일 비율 = avg_cum_df / P(0,t)
      pctiles     : dict  각 퍼센타일별 누적할인계수 경로
    """
    cum_log = np.cumsum(r_paths * dt, axis=1)

    # overflow 방지: exp 계산 전 극단값 경고 후 nan 처리
    with np.errstate(over='ignore', invalid='ignore'):
        cum_df = np.exp(-cum_log)
    cum_df = np.where(np.isinf(cum_df) | np.isnan(cum_df), np.nan, cum_df)

    avg_cum_df = np.nanmean(cum_df, axis=0)
    ratio      = np.where(df_fine > 1e-15, avg_cum_df / df_fine, np.nan)

    pctiles = {}
    for p in [1, 5, 50, 95, 99]:
        pctiles[f"P{p:02d}"] = np.nanpercentile(cum_df, p, axis=0)

    return avg_cum_df, ratio, pctiles


# ============================================================
# 입력 템플릿 생성
# ============================================================

def create_template(path):
    """
    swaption_vol_input.xlsx 템플릿 생성.
    실제 스왑션 데이터로 교체 후 사용.
    """
    # 스왑션 변동성 (Normal vol, bp) - 더미 데이터
    # 행: 옵션만기, 열: 스왑만기
    option_expiries = [1, 2, 3, 5, 7, 10]
    swap_tenors     = [1, 2, 3, 5, 7, 10]

    # 2026-06-30 기준 원화 ATM 스왑션 Normal vol 더미 (실제값으로 교체 필요)
    dummy_vols = np.array([
        # 스왑 1Y  2Y   3Y   5Y   7Y  10Y
        [  50,  55,  60,  65,  68,  70],   # 옵션 1Y
        [  55,  58,  63,  68,  70,  72],   # 옵션 2Y
        [  58,  62,  66,  71,  73,  74],   # 옵션 3Y
        [  62,  65,  70,  74,  76,  77],   # 옵션 5Y
        [  63,  67,  71,  75,  77,  78],   # 옵션 7Y
        [  65,  68,  72,  76,  78,  79],   # 옵션 10Y
    ], dtype=float)

    sw_vol_df = pd.DataFrame(
        dummy_vols,
        index=pd.Index(option_expiries, name="옵션만기(Y)"),
        columns=pd.Index(swap_tenors,   name="스왑만기(Y)")
    )

    params_df = pd.DataFrame([
        ["VA(bp)",       0.0,  "변동성 조정 (감독원 공시, bp 단위)"],
        ["시드(Seed)",   42,   "난수 시드 (정수)"],
    ], columns=["항목", "값", "설명"])

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        sw_vol_df.to_excel(writer, sheet_name="스왑션변동성")
        params_df.to_excel(writer, index=False, sheet_name="파라미터입력")

    print(f"  [OK] 템플릿 생성 완료: {path}")
    print("  [*] 스왑션변동성 시트의 값을 실제 시장 데이터(Normal vol, bp)로 교체하세요.")


# ============================================================
# 메인 실행
# ============================================================

def run():
    print("=" * 62)
    print("  K-ICS 원화 확률론적 할인율 시나리오 생성")
    print(f"  기준일: {BASE_DATE}")
    print("=" * 62)

    # ── 1. 입력 데이터 로드 ────────────────────────────────
    if not os.path.exists(SWAPTION_INPUT_PATH):
        print(f"\n  [!!] 입력 파일 없음: {SWAPTION_INPUT_PATH}")
        print("    python hw1f_krw_stochastic.py --create-template 으로 템플릿 생성 후 재실행하세요.")
        return

    params_df  = pd.read_excel(SWAPTION_INPUT_PATH, sheet_name="파라미터입력", header=0)
    params_map = dict(zip(params_df.iloc[:, 0].astype(str), params_df.iloc[:, 1]))
    va_bps     = float(params_map.get("VA(bp)", 0))
    seed       = int(params_map.get("시드(Seed)", 42))
    print(f"\n  [파라미터]  VA = {va_bps:.1f}bp  |  Seed = {seed}")

    # 결정론적 금리기간구조
    tenors_yr, df_annual, spot_cont, ltfr = load_initial_curve(DET_CURVE_PATH, va_bps)
    print(f"  [초기곡선]  만기범위: 1~{int(tenors_yr.max())}년  |  LTFR: {ltfr*100:.2f}%")

    # 월단위 보간 + 120년 외삽
    t_fine, df_fine, f_fine = build_fine_curve(
        tenors_yr, df_annual, spot_cont, ltfr, N_STEPS, DT
    )

    def P0_func(t):
        if t <= 0:
            return 1.0
        if t <= tenors_yr.max():
            s = np.interp(t, tenors_yr, spot_cont)
        else:
            s = spot_cont[-1] + ltfr * ((t - tenors_yr.max()) / t)
            # 외삽: P(0,t) = P(0,Tmax) * exp(-LTFR*(t-Tmax))
            return float(df_annual[-1] * np.exp(-ltfr * (t - tenors_yr.max())))
        return float(np.exp(-s * t))

    def f0_interp(t):
        return float(np.interp(t, t_fine, f_fine))

    # 스왑션 데이터
    sw_raw = pd.read_excel(SWAPTION_INPUT_PATH, sheet_name="스왑션변동성", index_col=0)
    option_expiries = [float(x) for x in sw_raw.index]
    swap_tenors_lst = [float(x) for x in sw_raw.columns]

    swaption_data = []
    for te in option_expiries:
        for ts in swap_tenors_lst:
            nv = sw_raw.loc[te, ts]
            if pd.notna(nv) and float(nv) > 0:
                swaption_data.append({
                    'option_expiry':  te,
                    'swap_tenor':     ts,
                    'normal_vol_bps': float(nv)
                })
    print(f"  [스왑션]    유효 데이터 {len(swaption_data)}개 로드")

    # ── 2. 캘리브레이션 ────────────────────────────────────
    print("\n  [캘리브레이션]")
    a_cal, sigma_cal, res = calibrate_hw(swaption_data, P0_func, f0_interp)

    print(f"  a = {a_cal:.6f}  (최저한도 {A_MIN})")
    for i, (lo, hi) in enumerate(zip(SIGMA_BREAKPOINTS[:-1], SIGMA_BREAKPOINTS[1:])):
        print(f"  σ [{lo:2d}~{hi:2d}Y] = {sigma_cal[i]*10000:.2f} bp  ({sigma_cal[i]*100:.5f}%)")

    # 캘리브레이션 검증표
    cal_rows = []
    for d in swaption_data:
        te, ts   = d['option_expiry'], d['swap_tenor']
        nv_mkt   = d['normal_vol_bps']
        f0te     = f0_interp(te)
        K, _     = fwd_swap_rate_annuity(te, ts, P0_func)
        mdl_p    = hw_swaption_price(te, ts, K, P0_func, f0te, a_cal, sigma_cal)
        nv_mdl   = price_to_normal_vol_bps(mdl_p, te, ts, P0_func)
        cal_rows.append({
            '옵션만기(Y)': te, '스왑만기(Y)': ts,
            '시장NV(bp)':  nv_mkt,
            '모형NV(bp)':  round(nv_mdl, 2) if not np.isnan(nv_mdl) else np.nan,
            '오차(bp)':    round(nv_mdl - nv_mkt, 2) if not np.isnan(nv_mdl) else np.nan,
        })
    cal_df = pd.DataFrame(cal_rows)
    rmse   = np.sqrt(np.nanmean(cal_df['오차(bp)'].values.astype(float) ** 2))
    print(f"  캘리브레이션 RMSE = {rmse:.4f} bp")
    if abs(a_cal - A_MIN) < 1e-7:
        print(f"  [!!] a가 최저한도({A_MIN})에 고착. 실제 스왑션 데이터 입력 후 재실행 필요.")

    # ── 3. 시뮬레이션 ─────────────────────────────────────
    print(f"\n  [시뮬레이션]  {N_SCENARIOS}개 × {N_STEPS}월 ...")
    r_paths, alpha_arr = simulate_hw(
        a_cal, sigma_cal, t_fine, df_fine, f_fine,
        N_SCENARIOS, N_STEPS, DT, seed=seed
    )
    # 연복리 단기금리 R = e^r - 1
    R_paths_pct = (np.exp(r_paths) - 1.0) * 100.0   # % 단위

    rmin = R_paths_pct.min()
    rmax = R_paths_pct.max()
    rmdn = np.median(R_paths_pct[:, -1])
    print(f"  완료.  범위: [{rmin:.2f}%, {rmax:.2f}%]  |  120년 중앙값: {rmdn:.2f}%")

    # ── 4. 마팅게일 테스트 ─────────────────────────────────
    print("\n  [마팅게일 테스트]")
    avg_cum_df, ratio, pctiles = martingale_test(r_paths, df_fine, DT)
    valid_ratio = ratio[np.isfinite(ratio)]
    max_err = np.max(np.abs(valid_ratio - 1.0)) if len(valid_ratio) > 0 else np.nan
    if np.isnan(max_err):
        print("  [!!] 마팅게일 테스트: 수치 overflow (a 너무 작음 - 실제 스왑션 데이터 입력 필요)")
    else:
        print(f"  최대 오차 |E[DF]/P(0,t)-1| = {max_err*100:.4f}%  "
              f"({'[OK] 1% 이내' if max_err < 0.01 else '[!!] 1% 초과 - 시드 재검토'})")

    # ── 5. Excel 저장 ──────────────────────────────────────
    date_str   = BASE_DATE.replace("-", "")
    excel_path = os.path.join(OUTPUT_DIR, f"원화_확률론적할인율_{date_str}.xlsx")
    print(f"\n  [Excel 저장]  (대용량 파일, 수 분 소요될 수 있습니다)")
    print(f"  경로: {excel_path}")

    months    = np.arange(1, N_STEPS + 1)
    years_arr = months / 12.0
    scen_cols = [f"S{i+1:04d}" for i in range(N_SCENARIOS)]

    # xlsxwriter 시도 → 없으면 openpyxl
    try:
        import xlsxwriter
        engine = "xlsxwriter"
    except ImportError:
        engine = "openpyxl"

    with pd.ExcelWriter(excel_path, engine=engine) as writer:
        # 시트1: 단기금리 경로  (1440 × 1002)
        rate_df = pd.DataFrame(
            np.round(R_paths_pct.T, 6),   # (1440, 1000)
            columns=scen_cols
        )
        rate_df.insert(0, "경과월", months)
        rate_df.insert(1, "경과년", np.round(years_arr, 6))
        rate_df.to_excel(writer, index=False, sheet_name="단기금리_경로")
        print("    [OK] 시트1: 단기금리_경로")

        # 시트2: 마팅게일 테스트  (1440 × 11)
        mg_df = pd.DataFrame({
            "경과월":               months,
            "경과년":               np.round(years_arr, 6),
            "초기할인계수_P(0,t)":   np.round(df_fine, 8),
            "시나리오평균_누적DF":   np.round(avg_cum_df, 8),
            "마팅게일비율":          np.round(ratio, 8),
            "오차(비율-1)":         np.round(ratio - 1.0, 8),
            "P01":                  np.round(pctiles["P01"], 8),
            "P05":                  np.round(pctiles["P05"], 8),
            "P50(중앙값)":          np.round(pctiles["P50"], 8),
            "P95":                  np.round(pctiles["P95"], 8),
            "P99":                  np.round(pctiles["P99"], 8),
        })
        mg_df.to_excel(writer, index=False, sheet_name="마팅게일_테스트")
        print("    [OK] 시트2: 마팅게일_테스트")

        # 시트3: 파라미터
        param_rows = [
            ["기준일",            BASE_DATE],
            ["VA(bp)",           va_bps],
            ["수렴속도 a",        round(a_cal, 6)],
        ]
        for i, (lo, hi) in enumerate(zip(SIGMA_BREAKPOINTS[:-1], SIGMA_BREAKPOINTS[1:])):
            param_rows.append([f"σ [{lo}~{hi}Y] (bp)", round(sigma_cal[i] * 10000, 4)])
        param_rows += [
            ["시나리오수",         N_SCENARIOS],
            ["최대경과기간(년)",   MAX_YEARS],
            ["시간단위(년)",       DT],
            ["난수시드",          seed],
            ["RMSE(bp)",         round(rmse, 4)],
            ["캘리브레이션수렴",   "Y" if res.success else "N"],
            ["마팅게일최대오차(%)", round(max_err * 100, 4)],
        ]
        pd.DataFrame(param_rows, columns=["항목", "값"]).to_excel(
            writer, index=False, sheet_name="파라미터"
        )
        print("    [OK] 시트3: 파라미터")

        # 시트4: 스왑션 캘리브레이션
        cal_df.to_excel(writer, index=False, sheet_name="스왑션_캘리브레이션")
        print("    [OK] 시트4: 스왑션_캘리브레이션")

    print(f"  [OK] Excel 저장 완료")

    # ── 6. 차트 ───────────────────────────────────────────
    pct_list  = [1, 10, 25, 50, 75, 90, 99]
    pct_vals  = np.percentile(R_paths_pct, pct_list, axis=0)   # (7, 1440)
    yr_axis   = t_fine

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle(
        f"원화 확률론적 할인율 (Hull-White 1F)  |  {BASE_DATE}  |  "
        f"a={a_cal:.4f}, RMSE={rmse:.1f}bp",
        fontsize=12, fontweight="bold"
    )

    # Fan chart
    ax = axes[0]
    fill_pairs = [(0, 6, 0.12), (1, 5, 0.18), (2, 4, 0.25)]
    palette    = ["#4575b4", "#74add1", "#abd9e9"]
    for (lo_i, hi_i, alpha_v), col in zip(fill_pairs, palette):
        ax.fill_between(yr_axis, pct_vals[lo_i], pct_vals[hi_i],
                        alpha=alpha_v, color=col, label=f"P{pct_list[lo_i]}~P{pct_list[hi_i]}")
    ax.plot(yr_axis, pct_vals[3], color="#d73027", lw=1.8, label="P50(중앙값)")
    ax.set_xlabel("경과년", fontsize=10)
    ax.set_ylabel("단기금리 (%)", fontsize=10)
    ax.set_title("단기금리 시나리오 Fan Chart", fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    ax.set_xlim(0, MAX_YEARS)

    # 마팅게일 테스트
    ax2 = axes[1]
    ax2.plot(yr_axis, ratio, color="steelblue", lw=1.5, label="마팅게일 비율 E[DF]/P(0,t)")
    ax2.axhline(1.00, color="red",    ls="--", lw=1.5, label="기준값 1.0")
    ax2.axhline(1.01, color="orange", ls=":",  lw=1.0, label="±1% 허용선")
    ax2.axhline(0.99, color="orange", ls=":",  lw=1.0)
    ax2.set_xlabel("경과년", fontsize=10)
    ax2.set_ylabel("E[DF] / P(0,t)", fontsize=10)
    ax2.set_title("마팅게일 테스트 (K-ICS 결과적정성)", fontsize=11)
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.3)
    ax2.set_xlim(0, MAX_YEARS)
    ax2.set_ylim(0.90, 1.10)

    plt.tight_layout()
    chart_path = os.path.join(OUTPUT_DIR, f"원화_확률론적할인율_{date_str}_차트.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  [OK] 차트 저장 완료: {chart_path}")
    print()


if __name__ == "__main__":
    if "--create-template" in sys.argv:
        create_template(SWAPTION_INPUT_PATH)
    else:
        run()
