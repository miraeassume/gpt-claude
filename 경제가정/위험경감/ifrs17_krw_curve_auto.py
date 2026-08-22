"""
============================================================
  IFRS17 / K-ICS  원화 조정무위험 금리기간구조 산출
  (Smith-Wilson 방법, 2026년 감독원 고시 기준)
  ★ 자동수집판 : BOND_YIELDS_PCT 를 KOFIA에서 인터넷으로 자동 취득
============================================================

이 파일은 `ifrs17_krw_curve.py` 를 기반으로,
국고채 YTM(BOND_YIELDS_PCT)을 손으로 입력하는 대신
KOFIA 채권시가평가수익률 API(kofia_bond_srtprc.py)에서
BASE_DATE 기준으로 자동으로 내려받도록 수정한 버전입니다.

[KOFIA 만기 ↔ 곡선 tenor 매핑]
  3M→0.25, 6M→0.50, 9M→0.75, 1Y→1.00, 1.5Y→1.50, 2Y→2.00,
  2.5Y→2.50, 3Y→3.00, 4Y→4.00, 5Y→5.00, 7Y→7.00, 10Y→10.00,
  15Y→15.00, 20Y→20.00, 30Y→30.00, 50Y→50.00   (16개 완전 대응)

[의존 패키지]
  pip install numpy pandas scipy matplotlib openpyxl requests

[원본 알고리즘 설명은 ifrs17_krw_curve.py 상단 docstring 참조]
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os
import sys
import warnings
warnings.filterwarnings("ignore")

# ── KOFIA 자동수집 모듈 import ───────────────────────────────
#   ../KOFIABOND자동수집_ING/kofia_bond_srtprc.py 를 경로에 추가
_KOFIA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "KOFIABOND자동수집_ING")
)
if _KOFIA_DIR not in sys.path:
    sys.path.insert(0, _KOFIA_DIR)

from kofia_bond_srtprc import get_srtprc_rate, ORG_AVG_NEW  # noqa: E402


# ============================================================
# ★ 사용자 입력 구역  (이 블록만 수정하세요)
# ============================================================

# [1] 기준일
BASE_DATE = "2026-06-30"

# [2] 국고채 YTM  ← KOFIA API에서 자동 취득 (수동 입력 불필요)
#     아래 KOFIA_TO_TENOR 매핑으로 API 응답을 tenor(년) 딕셔너리로 변환합니다.
#     - 채권 종류 : 국고채권
#     - 기관     : 평가사 평균('23.1.9~, A20000)
#     ※ 50Y YTM은 1단계 SW의 UFR로도 사용 (FSS xlsm E23 셀 역할)
BOND_TYPE   = "국고채권"
REPORT_COMP = ORG_AVG_NEW      # 평가사 평균('23.1.9~)

# KOFIA 응답 만기명(str) → 곡선 tenor(년, float) 매핑
KOFIA_TO_TENOR = {
    "3M":   0.25,   # 3개월
    "6M":   0.50,   # 6개월
    "9M":   0.75,   # 9개월
    "1Y":   1.00,   # 1년
    "1.5Y": 1.50,   # 1년6개월
    "2Y":   2.00,   # 2년
    "2.5Y": 2.50,   # 2년6개월
    "3Y":   3.00,   # 3년
    "4Y":   4.00,   # 4년
    "5Y":   5.00,   # 5년
    "7Y":   7.00,   # 7년
    "10Y": 10.00,   # 10년
    "15Y": 15.00,   # 15년
    "20Y": 20.00,   # 20년
    "30Y": 30.00,   # 30년
    "50Y": 50.00,   # 50년  ← 1단계 SW UFR로도 사용
}

# [2-fallback] API 실패 시 사용할 수동 백업값 (원본 ifrs17_krw_curve.py 값)
#     인터넷/휴일/서버 오류로 자동수집이 안 될 때만 사용됩니다.
BOND_YIELDS_PCT_FALLBACK = {
    0.25:  2.831 ,   # 3개월
    0.50:  3.093 ,   # 6개월
    0.75:  3.316 ,   # 9개월
    1.00:  3.394 ,   # 1년
    1.50:  3.535 ,   # 1년6개월
    2.00:  3.655 ,   # 2년
    2.50:  3.700 ,   # 2년6개월
    3.00:  3.760 ,   # 3년
    4.00:  3.905 ,   # 4년
    5.00:  4.020 ,   # 5년
    7.00:  4.149 ,   # 7년
   10.00:  4.262 ,   # 10년
   15.00:  4.384 ,   # 15년
   20.00:  4.470 ,   # 20년
   30.00:  4.508 ,   # 30년
   50.00:  4.409 ,   # 50년  ← 1단계 SW UFR로도 사용
}

# [3] Smith-Wilson 파라미터 (감독원 고시)
LLP      = 23      # 최종관찰만기
CP       = 60      # 최초수렴시점
LTFR     = 4.30/100  # 장기선도금리 4.30% (참고용 — SW Step2에서는 UFR_SW2 사용)
UFR_SW2  = 4.30/100     # Step2 SmithWilson + Alpha 교정 UFR (Excel U7=0)
COUPON_FREQ = 2    # 이자지급횟수 (연 2회, 반기)

# [4] 유동성프리미엄 LP (단위: %, 감독원 홈페이지 매월 게시)
#     VBA V11 셀 = 0.00434 → 0.434%
LP_PCT = 0.414    # 2026년 7월 FSS 고시값 (감독원 홈페이지 매월 교체)

# [5] Alpha 수렴 허용오차 (bp 단위 아님, 이산율 스케일)
ALPHA_TOL = 1e-4   # VBA CONVERGE_TOLERANCE (≈ 1bp 이산 환산)

# [6] 출력 최대 만기 (년)
MAX_TENOR = 100

# [7] 결과 파일 저장 경로
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# 국고채 YTM 자동 취득 (KOFIA)
# ============================================================

def fetch_bond_yields_pct(base_date=BASE_DATE,
                          bond_type=BOND_TYPE,
                          report_comp=REPORT_COMP,
                          fallback=None):
    """
    KOFIA 채권시가평가수익률 API에서 국고채 YTM을 자동 취득하여
    {tenor(년): YTM(%)} 딕셔너리(BOND_YIELDS_PCT)로 반환.

    Parameters
    ----------
    base_date   : 기준일 'YYYY-MM-DD' (내부에서 'YYYYMMDD'로 변환)
    bond_type   : 채권 종류명 (기본 '국고채권')
    report_comp : 기관 코드 (기본 평가사 평균 A20000)
    fallback    : 취득 실패 시 사용할 백업 dict (None이면 예외 발생)

    Returns
    -------
    dict  {0.25: 2.831, 0.50: 3.093, ...}
    """
    date_yyyymmdd = base_date.replace("-", "")
    print(f"  [KOFIA] {date_yyyymmdd} 국고채 YTM 자동 취득 중...")

    try:
        df = get_srtprc_rate(date_yyyymmdd, bond_type, report_comp)
    except Exception as e:
        print(f"  [KOFIA] API 오류: {e}")
        df = pd.DataFrame()

    if df is None or df.empty:
        if fallback is not None:
            print("  [KOFIA] 취득 실패 → 백업값(BOND_YIELDS_PCT_FALLBACK) 사용")
            return dict(fallback)
        raise RuntimeError(
            f"KOFIA에서 {date_yyyymmdd} 국고채 YTM을 가져오지 못했습니다. "
            f"(휴일/미영업일/네트워크 문제) — fallback을 지정하거나 날짜를 확인하세요."
        )

    row = df.iloc[0]
    yields = {}
    missing = []
    for kofia_mat, tenor in KOFIA_TO_TENOR.items():
        val = row.get(kofia_mat)
        if val is None or pd.isna(val):
            missing.append(kofia_mat)
            continue
        yields[tenor] = float(val)

    if missing:
        print(f"  [KOFIA] 경고: 결측 만기 {missing}")

    # 필수 만기(50Y = 1단계 UFR) 검증 및 결측 보완
    if not yields or 50.00 not in yields:
        if fallback is not None:
            print("  [KOFIA] 필수 만기 결측 → 백업값 사용")
            return dict(fallback)
        raise RuntimeError("KOFIA 응답에 50Y(1단계 UFR용) 값이 없습니다.")

    # 결측 만기가 있으면 fallback으로 개별 보완
    if fallback is not None:
        for tenor, v in fallback.items():
            yields.setdefault(tenor, v)

    print(f"  [KOFIA] 취득 완료 (기관: {row.get('기관', '-')}, "
          f"{len(yields)}개 만기)")
    return dict(sorted(yields.items()))


# 모듈 로드 시 자동 취득 (실패하면 백업값)
BOND_YIELDS_PCT = fetch_bond_yields_pct(fallback=BOND_YIELDS_PCT_FALLBACK)


# ============================================================
# 계산 엔진 — VBA Module1 / Module2 Python 복제
# ============================================================

def _w_kernel_matrix(t1_arr, t2_arr, alpha, ltfr):
    """
    Wilson 커널 행렬 W[i,j] = W(t1_arr[i], t2_arr[j]) 벡터화 산출
    VBA: Exp(-UFR*(T(i)+T(j)))*(ALPHA*Min - 0.5*Exp(-ALPHA*Max)*(Exp(ALPHA*Min)-Exp(-ALPHA*Min)))
    """
    t1 = np.asarray(t1_arr, dtype=float).reshape(-1, 1)
    t2 = np.asarray(t2_arr, dtype=float).reshape(1, -1)
    mn = np.minimum(t1, t2)
    mx = np.maximum(t1, t2)
    return (np.exp(-ltfr * (t1 + t2)) *
            (alpha * mn - 0.5 * np.exp(-alpha * mx) *
             (np.exp(alpha * mn) - np.exp(-alpha * mn))))


def _ytm_price(tenor, ytm, freq):
    """
    VBA YTMPrice 정확 복제: 쿠폰채 가격 계산
    - T가 dt의 배수인 경우 (쿠폰 지급일): DF = (1+YTM/freq)^(-T*freq) [복리]
    - T가 dt의 배수가 아닌 경우 (0.25Y, 0.75Y 등): DF = 1/(1+YTM*T) [단순이자]
      (VBA: Abs(T/dt - CInt(T/dt)) < 1e-7 판별)
    """
    dt = 1.0 / freq
    T  = round(tenor, 10)
    P  = 0.0
    while T > 1e-10:
        CF = (1.0 + ytm / freq) if abs(T - tenor) < 1e-9 else ytm / freq
        T_over_dt = T / dt
        if abs(T_over_dt - round(T_over_dt)) < 1e-7:   # 쿠폰 지급일 → 복리
            DF = (1.0 + ytm / freq) ** (-T * freq)
        else:                                            # 비쿠폰 날짜 → 단순이자 (VBA)
            DF = 1.0 / (1.0 + ytm * T)
        P += CF * DF
        T  = round(T - dt, 10)
    return P


def smith_wilson_ytm(tenors, ytms, freq, ufr_disc, alpha, out_tenors):
    """
    VBA Module2 SmithWilsonYTM 복제
    - YTM 쿠폰행렬 직접 피팅 (bootstrap 불필요)
    - ZETA = (C W C')^-1 * (m - Cu)
    - UFR: discrete 입력 → ln(1+UFR) 내부 변환

    Parameters
    ----------
    tenors     : list[float]  관찰 만기 (년)
    ytms       : list[float]  YTM (소수, 예: 0.03)
    freq       : int          이자지급횟수
    ufr_disc   : float        1단계 SW UFR (이산율, 예: 0.034 for 3.4%)
    alpha      : float        수렴속도
    out_tenors : list[float]  출력 만기

    Returns
    -------
    spots : ndarray  연속 현물금리
    """
    ltfr = np.log(1.0 + ufr_disc)          # VBA: UFR = Log(1+UFR)
    n    = len(tenors)
    dt   = 1.0 / freq

    # ── 1. 모든 쿠폰 지급 시점 수집 (unique, sorted) ──────
    coupon_set = set()
    for tenor in tenors:
        T = round(tenor, 10)
        while T > 1e-10:
            coupon_set.add(round(T, 10))
            T = round(T - dt, 10)
    T_arr = np.array(sorted(coupon_set))
    N2    = len(T_arr)

    # ── 2. 쿠폰 행렬 C (n × N2) ───────────────────────────
    C = np.zeros((n, N2))
    for i, (tenor, ytm) in enumerate(zip(tenors, ytms)):
        for j, t in enumerate(T_arr):
            if t > tenor + 1e-9:
                C[i, j] = 0.0
            elif abs(t - tenor) < 1e-9:
                C[i, j] = 1.0 + ytm / freq          # 원금 + 최종쿠폰
            else:
                r = (tenor - t) * freq
                if abs(r - round(r)) < 1e-6:
                    C[i, j] = ytm / freq             # 중간 쿠폰

    # ── 3. u, m 벡터 ──────────────────────────────────────
    u = np.exp(-ltfr * T_arr)                        # (N2,)
    m = np.array([_ytm_price(t, y, freq) for t, y in zip(tenors, ytms)])  # (n,)

    # ── 4. W 행렬 (N2 × N2) ───────────────────────────────
    W = _w_kernel_matrix(T_arr, T_arr, alpha, ltfr)  # 대칭행렬

    # ── 5. ZETA 산출 ──────────────────────────────────────
    #   ZETA = (C W C')^-1 * (m - C u)
    CWCt      = C @ W @ C.T
    m_Cu      = m - C @ u
    zeta_bond = np.linalg.solve(CWCt, m_Cu)          # (n,)
    zeta2     = C.T @ zeta_bond                      # (N2,)  = ZETA2

    # ── 6. 출력 테너별 연속 현물금리 (벡터화) ──────────────
    out = np.maximum(np.asarray(out_tenors, dtype=float), 1e-6)
    W2  = _w_kernel_matrix(out, T_arr, alpha, ltfr)  # (Nout, N2)
    tmp = np.exp(-ltfr * out) + W2 @ zeta2
    return -np.log(tmp) / out


def smith_wilson_from_spot(obs_tenors, cont_spots, ufr_disc, alpha, out_tenors):
    """
    VBA Module1 SmithWilson 복제
    - 연속 현물금리에서 SW 피팅 후 외삽
    - ZETA = W^-1 * (P - M)

    Parameters
    ----------
    obs_tenors  : list[float]  관찰 만기
    cont_spots  : ndarray      연속 현물금리 (소수)
    ufr_disc    : float        LTFR (이산율)
    alpha       : float        수렴속도
    out_tenors  : list[float]  출력 만기

    Returns
    -------
    spots : ndarray  연속 현물금리
    """
    ltfr = np.log(1.0 + ufr_disc)                   # VBA: UFR = Log(1+UFR)
    u    = np.asarray(obs_tenors, dtype=float)
    P    = np.exp(-cont_spots * u)                   # DF
    M    = np.exp(-ltfr * u)
    P_M  = P - M

    W    = _w_kernel_matrix(u, u, alpha, ltfr)
    zeta = np.linalg.solve(W, P_M)                  # (n,)

    out  = np.maximum(np.asarray(out_tenors, dtype=float), 1e-6)
    W2   = _w_kernel_matrix(out, u, alpha, ltfr)    # (Nout, n)
    tmp  = np.exp(-ltfr * out) + W2 @ zeta
    return -np.log(tmp) / out


def calibrate_alpha(ufr_disc, obs_tenors, cont_spots, cp, tol=1e-4):
    """
    VBA SmithWilson_ALPHA_UB_LB 복제
    CP에서 순간 선도금리 ≈ UFR_SW2 가 되도록 alpha 이분탐색

    ※ Excel 간소화 파일: UFR_SW2=0 사용 → CP에서 순간 선도금리 → 0%

    Parameters
    ----------
    ufr_disc   : float  UFR (이산율) — UFR_SW2=0.0 전달
    obs_tenors : array  관찰 만기 (≤ LLP)
    cont_spots : array  LP 가산 연속 현물금리
    cp         : float  최초수렴시점
    tol        : float  허용오차 |exp(fwd)-exp(ltfr)| ≤ tol

    Returns
    -------
    alpha : float
    """
    ltfr = np.log(1.0 + ufr_disc)                # UFR_SW2=0 → ltfr=0
    u    = np.asarray(obs_tenors, dtype=float)
    P    = np.exp(-cont_spots * u)
    M    = np.exp(-ltfr * u)
    P_M  = P - M

    def _fwd_at_cp(alpha):
        W    = _w_kernel_matrix(u, u, alpha, ltfr)
        zeta = np.linalg.solve(W, P_M)
        su   = np.sinh(alpha * u)
        X    = np.dot(u  * M, zeta)
        Y    = np.dot(su * M, zeta)
        PP   = np.exp(-ltfr * cp) * (1.0 + alpha * X
                                     - np.exp(-alpha * cp) * Y)
        dPP  = (-ltfr * PP
                + np.exp(-ltfr * cp) * alpha * np.exp(-alpha * cp) * Y)
        return -dPP / PP

    ALPHA_LB  = 0.001
    ALPHA_UB  = 1.0
    alpha     = ALPHA_LB
    d_alpha   = ALPHA_UB + ALPHA_LB   # = 1.001  (VBA 동일)

    for itr in range(52):
        fwd = _fwd_at_cp(alpha)
        if itr == 0 and abs(np.exp(fwd) - np.exp(ltfr)) <= tol:
            return alpha
        d_alpha /= 2.0
        if abs(np.exp(fwd) - np.exp(ltfr)) > tol:
            alpha += d_alpha
        else:
            alpha -= d_alpha

    return alpha


# ============================================================
# 메인 실행
# ============================================================

def run():
    print("=" * 72)
    print("  IFRS17 / K-ICS  원화 조정무위험 금리기간구조 (LP 가산) [자동수집판]")
    print(f"  기준일: {BASE_DATE}  LLP={LLP}Y  CP={CP}Y  "
          f"UFR_SW2={UFR_SW2*100:.2f}%  LP={LP_PCT}%")
    print("=" * 72)

    # ── 입력 데이터 준비 ─────────────────────────────────────
    obs_tenors = sorted(BOND_YIELDS_PCT.keys())
    ytms       = [BOND_YIELDS_PCT[t] / 100.0 for t in obs_tenors]
    ufr_sw1    = ytms[-1]    # 1단계 SW UFR = 50Y YTM

    # SW1 출력 만기: 입력 테너 ∪ {LLP}
    sw1_out_tenors = sorted(set(obs_tenors) | {float(LLP)})

    # SW2 관찰 만기: ≤ LLP 구간
    sw2_obs_tenors = [t for t in sw1_out_tenors if t <= LLP + 1e-9]

    # ── [Step 1] SmithWilsonYTM  →  F 컬럼 ───────────────────
    print(f"\n  [Step 1] SmithWilsonYTM  UFR1={ufr_sw1*100:.3f}%  α=0.1")
    k_spots_all = smith_wilson_ytm(
        obs_tenors, ytms, COUPON_FREQ,
        ufr_disc   = ufr_sw1,
        alpha      = 0.1,
        out_tenors = sw1_out_tenors,
    )
    # F 컬럼: 관찰 테너별 연속 현물금리 (Excel F 컬럼)
    F_col = k_spots_all  # 전체 sw1_out_tenors 기준

    sw1_arr = np.array(sw1_out_tenors)
    mask_lp = sw1_arr <= LLP + 1e-9
    k_spots_lp = k_spots_all[mask_lp]   # ≤ LLP 구간 (SW2 입력용)

    # ── [Step 2] LP 가산  →  G 컬럼 ──────────────────────────
    lp_dec  = LP_PCT / 100.0
    G_sw2   = np.log(np.exp(k_spots_lp) + lp_dec)   # SW2 입력 (≤LLP)
    G_all   = np.where(mask_lp,
                       np.log(np.exp(F_col) + lp_dec),
                       np.nan)                         # 전체 (Excel G 컬럼)
    print(f"  [Step 2] LP 가산  LP={LP_PCT}%  G=LN(EXP(F)+{lp_dec:.5f})")

    # ── [Step 3] Alpha 자동 산출 (UFR_SW2 기준) ───────────────
    alpha2 = calibrate_alpha(UFR_SW2, sw2_obs_tenors, G_sw2, CP, tol=ALPHA_TOL)

    # 수렴 검증
    _ltfr_c = np.log(1.0 + UFR_SW2)    # UFR_SW2=0 → ltfr=0
    _u      = np.asarray(sw2_obs_tenors, float)
    _P      = np.exp(-G_sw2 * _u)
    _M      = np.exp(-_ltfr_c * _u)
    _W      = _w_kernel_matrix(_u, _u, alpha2, _ltfr_c)
    _zeta   = np.linalg.solve(_W, _P - _M)
    _su     = np.sinh(alpha2 * _u)
    _X      = np.dot(_u  * _M, _zeta)
    _Y      = np.dot(_su * _M, _zeta)
    _PP     = np.exp(-_ltfr_c * CP) * (1 + alpha2 * _X - np.exp(-alpha2 * CP) * _Y)
    _dPP    = (-_ltfr_c * _PP
               + np.exp(-_ltfr_c * CP) * alpha2 * np.exp(-alpha2 * CP) * _Y)
    fwd_inst = -_dPP / _PP
    diff_bp  = abs(np.exp(fwd_inst) - np.exp(_ltfr_c)) * 10000
    ok       = "PASS" if diff_bp <= 1.001 else "FAIL"   # 1bp + FP margin
    print(f"  [Step 3] Alpha={alpha2:.8f}  CP={CP}Y 순간선도={fwd_inst*100:.4f}%  "
          f"(UFR_SW2 대비 {diff_bp:.2f}bp  {ok})")

    # ── [Step 4] SmithWilson → 월단위 연속 현물금리 ───────────
    dt = 1.0 / 12
    # P=0 (t=1e-6) ~ P=N (t=N/12) 포함 — Excel 구조 일치
    n_months = MAX_TENOR * 12
    t0_tenors  = np.concatenate([[1e-6], np.arange(1, n_months + 1) * dt])  # P=0..N

    cont_all = smith_wilson_from_spot(
        sw2_obs_tenors, G_sw2, UFR_SW2, alpha2, t0_tenors
    )

    # ── [Step 5] Cont2Discrete  →  U 컬럼 ────────────────────
    U_all = np.exp(cont_all) - 1     # EXP(cont) - 1

    # ── [Step 6] Forward(Discrete)  →  V 컬럼 ────────────────
    #   V(P=m) = (1+U(P=m+1))^(m+1) / (1+U(P=m))^m - 1  (Excel 수식)
    #   여기서 P=0..N, t=P/12 년
    P_idx = np.arange(len(t0_tenors))          # 0, 1, 2, ..., N
    # V at P=m  = (1+U[m+1])^(m+1)/(1+U[m])^m - 1  for m = 0..N-1
    V_all = (1.0 + U_all[1:]) ** P_idx[1:] / (1.0 + U_all[:-1]) ** P_idx[:-1] - 1
    # V 마지막(P=N)은 NaN 처리
    V_all = np.append(V_all, np.nan)

    # ── U/V 결과 DataFrame (Excel P=0..N 구조) ───────────────
    uv_rows = []
    for p in range(len(t0_tenors)):
        t = t0_tenors[p]
        uv_rows.append({
            "P(월)":            int(p),
            "만기(년)":         round(float(t), 6),
            "U_Spot_Disc(%)":   round(float(U_all[p]) , 6),
            "V_Fwd_Disc(%)":    (round(float(V_all[p]) , 6)
                                 if not np.isnan(V_all[p]) else np.nan),
            "비고":             ("LLP" if abs(t - LLP) < 1e-6 else
                                 "CP"  if abs(t - CP)  < 1e-6 else ""),
        })
    uv_df = pd.DataFrame(uv_rows)

    # ── 콘솔 출력 (주요 P 포인트) ────────────────────────────
    key_months = {int(round(y * 12)) for y in
                  [1/12, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, LLP, 30, 40, 50, CP, 70, 100]}
    print(f"\n  {'P(월)':>6}  {'만기(년)':>8}  {'U_Spot(%)':>12}  {'V_Fwd(%)':>12}")
    print("  " + "-" * 50)
    for _, r in uv_df.iterrows():
        p = int(r["P(월)"])
        if p in key_months:
            note = f"  [{r['비고']}]" if r["비고"] else ""
            v_str = (f"{r['V_Fwd_Disc(%)']:>12.5f}"
                     if not pd.isna(r["V_Fwd_Disc(%)"]) else f"{'NaN':>12}")
            print(f"  {p:>6}  {r['만기(년)']:>8.4f}"
                  f"  {r['U_Spot_Disc(%)']:>12.5f}"
                  f"  {v_str}{note}")

    # ── Excel 저장 ────────────────────────────────────────────
    date_str   = BASE_DATE.replace("-", "")
    excel_path = os.path.join(OUTPUT_DIR, f"원화_LP_금리기간구조_{date_str}_auto.xlsx")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        # 메인 시트: U/V 컬럼 (Excel 간소화 파일 U/V 컬럼 대응)
        uv_df.to_excel(writer, index=False, sheet_name="U_V_월별")

        # F/G 컬럼 시트 (관찰 만기별 SW1 결과)
        fg_df = pd.DataFrame({
            "Tenor(년)":          sw1_out_tenors,
            "YTM(%)":             [BOND_YIELDS_PCT.get(t, np.nan) for t in sw1_out_tenors],
            "F_Spot_Cont(%)":     F_col * 100,
            "G_Spot_Cont+LP(%)":  G_all * 100,
            "SW2_입력여부":       ["O" if t <= LLP + 1e-9 else "X"
                                   for t in sw1_out_tenors],
        })
        fg_df.to_excel(writer, index=False, sheet_name="F_G_관찰점")

        # 파라미터 시트
        params = pd.DataFrame([
            ["기준일",        BASE_DATE],
            ["YTM 출처",      f"KOFIA API 자동취득 ({BOND_TYPE}, {REPORT_COMP})"],
            ["LLP (년)",      LLP],
            ["CP  (년)",      CP],
            ["UFR_SW2 (%)",   UFR_SW2 * 100],
            ["LTFR (참고, %)", LTFR * 100],
            ["Alpha (산출)",  round(alpha2, 8)],
            ["수렴여부",      ok],
            ["이자지급횟수",  COUPON_FREQ],
            ["LP (%)",        LP_PCT],
            ["1단계 UFR",     f"{ufr_sw1*100:.4f}% (50Y YTM)"],
            ["U 정의",        "EXP(cont_spot)-1  (Cont2Discrete)"],
            ["V 정의",        "(1+U(P+1))^(P+1)/(1+U(P))^P-1  (Excel 수식)"],
        ], columns=["항목", "값"])
        params.to_excel(writer, index=False, sheet_name="파라미터")

        # 국고채 YTM 입력
        ytm_in = pd.DataFrame([
            {"Tenor(년)": t, "YTM입력(%)": BOND_YIELDS_PCT[t]}
            for t in sorted(BOND_YIELDS_PCT)
        ])
        ytm_in.to_excel(writer, index=False, sheet_name="국고채YTM입력")

        # 비교용 연단위 요약 (P=12,24,...,1200)
        annual_idx = [p for p in range(len(t0_tenors)) if p > 0 and p % 12 == 0]
        ann_rows = []
        for p in annual_idx:
            ann_rows.append({
                "P(월)":            p,
                "만기(년)":         p // 12,
                "U_Spot_Disc(%)":   uv_df.at[p, "U_Spot_Disc(%)"],
                "V_Fwd_Disc(%)":    uv_df.at[p, "V_Fwd_Disc(%)"],
                "FSS_Spot(%)":      "",
                "FSS_Fwd(%)":       "",
                "Spot_차이(bp)":    "",
                "Fwd_차이(bp)":     "",
            })
        pd.DataFrame(ann_rows).to_excel(writer, index=False, sheet_name="비교_연단위")

    print(f"\n  [OK] Excel 저장: {excel_path}")

    # ── 차트 ──────────────────────────────────────────────────
    p_arr    = uv_df["만기(년)"].values
    spot_arr = uv_df["U_Spot_Disc(%)"].values
    fwd_arr  = uv_df["V_Fwd_Disc(%)"].values

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    fig.suptitle(
        f"조정무위험 금리기간구조 (LP={LP_PCT}% 가산)  {BASE_DATE}",
        fontsize=13, fontweight="bold")

    for ax, y_arr, label, color in [
        (ax1, spot_arr, "U: Spot(Discrete)",    "steelblue"),
        (ax2, fwd_arr,  "V: Forward(Discrete)", "darkorchid"),
    ]:
        ax.plot(p_arr, y_arr, color=color, lw=1.5, label=label)
        ax.axhline(LTFR * 100, color="red",    ls="--", lw=1.2,
                   label=f"LTFR {LTFR*100:.2f}%")
        ax.axvline(LLP,        color="green",  ls=":",  lw=1.2,
                   label=f"LLP {LLP}Y")
        ax.axvline(CP,         color="orange", ls=":",  lw=1.2,
                   label=f"CP {CP}Y")
        ax.set_ylabel("금리 (%)")
        ax.set_title(label, fontsize=11)
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
        ax.set_xlim(0, MAX_TENOR)

    ax2.set_xlabel("만기 (년)")
    plt.tight_layout()

    chart_path = os.path.join(OUTPUT_DIR, f"원화_LP_금리기간구조_{date_str}_auto_차트.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  [OK] 차트 저장: {chart_path}")
    print()

    return uv_df


if __name__ == "__main__":
    run()
