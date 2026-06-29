"""
============================================================
  IFRS17 / K-ICS  원화 조정무위험 금리기간구조 산출
  (Smith-Wilson 방법, 2026년 감독원 고시 기준)
============================================================

[산출 흐름]
  국고채 YTM 입력
    → 선형보간 (정수 만기 채움)
    → Bootstrapping (YTM → Spot Rate)
    → LP 가산 (LLP까지)
    → Smith-Wilson 피팅 (관찰 구간 보간 + LLP 이후 외삽)
    → LTFR 수렴 확인 (CP=60년)
    → 결과 출력 (Excel + 차트)

[2026년 파라미터]
  LLP (최종관찰만기) : 23년
  CP  (최초수렴시점) : 60년
  LTFR (장기선도금리): 4.30%

[사용법]
  1. 아래 ★ 사용자 입력 구역의 값을 수정
  2. python ifrs17_krw_curve.py 실행
  3. Excel 및 차트 파일 확인

[의존 패키지]
  pip install numpy pandas scipy matplotlib openpyxl
"""

import numpy as np
import pandas as pd
from scipy.optimize import brentq
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os
import warnings
warnings.filterwarnings("ignore")

# ============================================================
# ★ 사용자 입력 구역  (이 블록만 수정하세요)
# ============================================================

# [1] 기준일
BASE_DATE = "2026-06-30"

# [2] 국고채 YTM  (KOFIA 시가평가 가중평균수익률, 단위: %)
#     실제 운영 시 KOFIA에서 조회한 값으로 교체
#     지원 만기: 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 15Y, 20Y, 30Y
BOND_YIELDS_PCT = {
     1:  3.15,   # 더미 데이터 (실제값으로 교체 필요)
     2:  3.20,
     3:  3.25,
     5:  3.30,
     7:  3.35,
    10:  3.40,
    15:  3.50,
    20:  3.55,
    30:  3.60,
}

# [3] Smith-Wilson 파라미터 (감독원 고시)
LLP  = 23       # 최종관찰만기 (2026년: 23년, 단계적 확대 중)
CP   = 60       # 최초수렴시점
LTFR = 0.0430   # 장기선도금리 (4.30%)

# Alpha: None이면 CP 수렴 조건(1bp 이내)으로 자동산출,
#        숫자 입력 시 고정값 사용 (예: ALPHA = 0.1)
ALPHA = None

# [4] 유동성프리미엄 (LP, 단위: %)
#     감독원 매월 홈페이지 게시값으로 교체
#     None으로 설정하면 LP 미적용
LP_TABLE_PCT = {
     1:  0.10,
     2:  0.13,
     3:  0.16,
     5:  0.18,
     7:  0.20,
    10:  0.22,
    15:  0.25,
    20:  0.28,
    23:  0.30,
}

# [5] 출력 최대 만기 (년)
MAX_TENOR = 100

# [6] 결과 파일 저장 경로
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 계산 엔진 (수정 불필요)
# ============================================================

def interp_yields(obs_tenors: list, obs_yields_pct: list, max_t: int) -> dict:
    """
    관찰 만기 사이 수익률 선형 보간 → {1: y1%, 2: y2%, ...} 반환
    """
    all_t = np.arange(1, max_t + 1)
    y_interp = np.interp(all_t, obs_tenors, obs_yields_pct)
    return dict(zip(all_t.tolist(), y_interp.tolist()))


def bootstrap(yields_pct: dict) -> dict:
    """
    Par yield(%) → Discount Factor  부트스트랩 (연 1회 쿠폰 가정)

    수식:  P(T) = (1 - c_T * Σ_{t=1}^{T-1} P(t)) / (1 + c_T)
    단, 비연속 만기(예: 4Y가 없고 3Y→5Y 점프) 처리는
    선형보간 후 순차 계산하므로 사전에 모든 정수 만기가 채워져야 함
    """
    tenors = sorted(yields_pct.keys())
    df = {}
    for T in tenors:
        c = yields_pct[T] / 100.0
        pv_coupons = sum(df.get(t, 0.0) for t in range(1, T))
        df[T] = (1.0 - c * pv_coupons) / (1.0 + c)
    return df


def df_to_spot(discount_factors: dict) -> dict:
    """Discount Factor → 연속복리 Spot Rate  s(T) = -ln(P(T)) / T"""
    return {T: -np.log(B) / T for T, B in discount_factors.items() if B > 0}


def add_lp(spot_rates: dict, lp_table_pct: dict, llp: int) -> dict:
    """
    LLP까지의 Spot Rate에 LP 가산 (LP는 Tenor 간 선형 보간)
    LLP 초과 구간은 원래 Spot 유지 (Smith-Wilson 외삽 영역)
    """
    lp_t = sorted(lp_table_pct.keys())
    lp_v = [lp_table_pct[t] / 100.0 for t in lp_t]
    adjusted = {}
    for T, s in spot_rates.items():
        if T <= llp:
            lp = float(np.interp(T, lp_t, lp_v))
            adjusted[T] = s + lp
        else:
            adjusted[T] = s
    return adjusted


# ── Smith-Wilson 커널 ──────────────────────────────────────

def W(t: float, u: float, alpha: float, ltfr: float) -> float:
    """
    Wilson kernel:
      W(t,u) = exp(-LTFR*(t+u)) * [α·min(t,u) - exp(-α·max(t,u))·sinh(α·min(t,u))]
    """
    a = min(t, u)
    b = max(t, u)
    return np.exp(-ltfr * (t + u)) * (alpha * a - np.exp(-alpha * b) * np.sinh(alpha * a))


def sw_fit(tenors: list, df_obs: dict, alpha: float, ltfr: float) -> np.ndarray:
    """
    Smith-Wilson ζ 계수 산출
      행렬 방정식: [W(t_i, t_j)] · ζ = P_obs - exp(-LTFR·t)
    """
    N = len(tenors)
    Wmat = np.array([[W(tenors[i], tenors[j], alpha, ltfr) for j in range(N)]
                     for i in range(N)])
    rhs = np.array([df_obs[t] - np.exp(-ltfr * t) for t in tenors])
    return np.linalg.solve(Wmat, rhs)


def sw_df(t: float, tenors: list, zeta: np.ndarray,
          alpha: float, ltfr: float) -> float:
    """시점 t의 Discount Factor 산출"""
    P = np.exp(-ltfr * t)
    for j, tj in enumerate(tenors):
        P += zeta[j] * W(t, tj, alpha, ltfr)
    return P


def sw_fwd(t: float, tenors: list, zeta: np.ndarray,
           alpha: float, ltfr: float, dt: float = 1 / 252) -> float:
    """시점 t의 순간 forward rate (수치미분)"""
    P0 = sw_df(t,      tenors, zeta, alpha, ltfr)
    P1 = sw_df(t + dt, tenors, zeta, alpha, ltfr)
    return -np.log(P1 / P0) / dt if P0 > 0 and P1 > 0 else np.nan


def calibrate_alpha(tenors: list, df_obs: dict, cp: int,
                    ltfr: float, tol: float = 0.0001) -> float:
    """
    CP에서 forward rate가 LTFR ±1bp 이내로 수렴하는 최소 α 탐색
    |f(CP) / LTFR - 1| ≤ tol
    """
    def gap(alpha):
        zeta = sw_fit(tenors, df_obs, alpha, ltfr)
        f_cp = sw_fwd(cp, tenors, zeta, alpha, ltfr)
        return abs(f_cp / ltfr - 1.0) - tol

    # α 후보군 탐색 (0.01 ~ 2.0)
    for a in np.arange(0.01, 2.01, 0.005):
        if gap(a) <= 0:
            # 최소값 정밀 탐색
            try:
                lo = max(0.001, a - 0.01)
                return round(brentq(gap, lo, a + 0.01), 5)
            except Exception:
                return round(a, 5)
    return 0.1  # fallback


# ============================================================
# 메인 실행
# ============================================================

def run():
    print("=" * 62)
    print("  IFRS17 / K-ICS  원화 조정무위험 금리기간구조 산출")
    print(f"  기준일: {BASE_DATE}")
    print("=" * 62)
    print(f"  LLP={LLP}년  |  CP={CP}년  |  LTFR={LTFR*100:.2f}%")
    print()

    # ── 1. 수익률 보간 ─────────────────────────────────────
    obs_t = sorted(BOND_YIELDS_PCT.keys())
    obs_y = [BOND_YIELDS_PCT[t] for t in obs_t]

    # LLP 이하 만기만 관찰값으로 사용 (+ LLP 보간 추가)
    # LLP가 관찰 만기 사이에 있으면 선형보간값 추가
    obs_t_llp = [t for t in obs_t if t <= LLP]
    obs_y_llp = [BOND_YIELDS_PCT[t] for t in obs_t_llp]
    if LLP not in obs_t_llp:
        y_llp = float(np.interp(LLP, obs_t, obs_y))
        obs_t_llp.append(LLP)
        obs_y_llp.append(y_llp)
        obs_t_llp = sorted(obs_t_llp)
        obs_y_llp = [obs_y_llp[sorted(obs_t_llp).index(t)] for t in obs_t_llp]

    # 정수 만기로 보간
    yield_map = interp_yields(obs_t_llp, obs_y_llp, LLP)

    # ── 2. 부트스트랩 ──────────────────────────────────────
    df_boot = bootstrap(yield_map)

    # ── 3. Spot Rate 변환 ──────────────────────────────────
    spot_raw = df_to_spot(df_boot)

    # ── 4. LP 적용 ─────────────────────────────────────────
    if LP_TABLE_PCT:
        spot_adj = add_lp(spot_raw, LP_TABLE_PCT, LLP)
        lp_at_llp = float(np.interp(LLP,
                                    sorted(LP_TABLE_PCT.keys()),
                                    [LP_TABLE_PCT[t] / 100 for t in sorted(LP_TABLE_PCT.keys())]))
        print(f"  [LP 적용]  LLP({LLP}Y) LP = {lp_at_llp*100:.4f}%")
    else:
        spot_adj = spot_raw.copy()
        print("  [LP 미적용]")

    # LP 적용 후 Discount Factor (Smith-Wilson 관찰값)
    df_obs_sw = {T: np.exp(-spot_adj[T] * T) for T in sorted(spot_adj.keys())}
    sw_tenors = sorted(df_obs_sw.keys())

    # ── 5. Alpha 산출 ──────────────────────────────────────
    if ALPHA is None:
        alpha = calibrate_alpha(sw_tenors, df_obs_sw, CP, LTFR)
        print(f"  [Alpha]    자동산출 = {alpha}")
    else:
        alpha = float(ALPHA)
        print(f"  [Alpha]    고정값   = {alpha}")

    # ── 6. Smith-Wilson 피팅 ───────────────────────────────
    zeta = sw_fit(sw_tenors, df_obs_sw, alpha, LTFR)

    # ── 7. 전 구간 Curve 산출 ─────────────────────────────
    rows = []
    for T in range(1, MAX_TENOR + 1):
        P = sw_df(T, sw_tenors, zeta, alpha, LTFR)
        spot = -np.log(P) / T if P > 0 else np.nan

        if T == 1:
            fwd = spot
        else:
            P_prev = sw_df(T - 1, sw_tenors, zeta, alpha, LTFR)
            fwd = -np.log(P / P_prev) if (P > 0 and P_prev > 0) else np.nan

        rows.append({
            "만기(년)": T,
            "Discount Factor": P,
            "Spot Rate(%)":    spot * 100 if not np.isnan(spot) else np.nan,
            "Forward Rate(%)": fwd  * 100 if not np.isnan(fwd)  else np.nan,
        })

    result = pd.DataFrame(rows)

    # ── 8. 수렴 검증 ───────────────────────────────────────
    fwd_cp = sw_fwd(CP, sw_tenors, zeta, alpha, LTFR)
    diff_bp = abs(fwd_cp - LTFR) * 10000
    print(f"\n  [수렴 검증] CP={CP}Y forward = {fwd_cp*100:.4f}%  "
          f"(LTFR 대비 {diff_bp:.2f}bp {'✓' if diff_bp <= 1 else '✗ 기준 초과'})")

    # ── 9. 콘솔 출력 ───────────────────────────────────────
    key_tenors = {1, 2, 3, 5, 7, 10, 15, 20, 23, 30, 40, 50, 60, 70, 80, 100}
    print()
    print(f"  {'만기':>6}  {'Spot(%)':>10}  {'Forward(%)':>11}  {'DiscFactor':>12}")
    print("  " + "-" * 46)
    for _, r in result.iterrows():
        T = int(r["만기(년)"])
        if T in key_tenors:
            marker = " ◀ LLP" if T == LLP else (" ◀ CP" if T == CP else "")
            print(f"  {T:>6}  {r['Spot Rate(%)']:>10.5f}  "
                  f"{r['Forward Rate(%)']:>11.5f}  {r['Discount Factor']:>12.8f}{marker}")

    # ── 10. Excel 저장 ─────────────────────────────────────
    date_str = BASE_DATE.replace("-", "")
    excel_path = os.path.join(OUTPUT_DIR, f"원화_금리기간구조_{date_str}.xlsx")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        # 금리기간구조 (소수점 정리)
        out_df = result.copy()
        out_df["Discount Factor"] = out_df["Discount Factor"].round(8)
        out_df["Spot Rate(%)"]    = out_df["Spot Rate(%)"].round(6)
        out_df["Forward Rate(%)"] = out_df["Forward Rate(%)"].round(6)
        out_df.to_excel(writer, index=False, sheet_name="금리기간구조")

        # 파라미터
        params = pd.DataFrame([
            ["기준일",             BASE_DATE],
            ["LLP (최종관찰만기)", LLP],
            ["CP  (최초수렴시점)", CP],
            ["LTFR (%)",          LTFR * 100],
            ["Alpha",             alpha],
            ["LP 적용여부",        "Y" if LP_TABLE_PCT else "N"],
        ], columns=["항목", "값"])
        params.to_excel(writer, index=False, sheet_name="파라미터")

        # 국고채 YTM 입력값
        ytm_in = pd.DataFrame(
            [{"만기(년)": t, "YTM입력(%)": v} for t, v in sorted(BOND_YIELDS_PCT.items())]
        )
        ytm_in.to_excel(writer, index=False, sheet_name="국고채YTM입력")

        # LP 입력값
        if LP_TABLE_PCT:
            lp_in = pd.DataFrame(
                [{"만기(년)": t, "LP(%)": v} for t, v in sorted(LP_TABLE_PCT.items())]
            )
            lp_in.to_excel(writer, index=False, sheet_name="LP입력")

    print(f"\n  ✓ Excel 저장 완료: {excel_path}")

    # ── 11. 차트 ───────────────────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(15, 5))
    fig.suptitle(f"원화 조정무위험 금리기간구조  ({BASE_DATE})", fontsize=13, fontweight="bold")

    t_arr = result["만기(년)"].values
    s_arr = result["Spot Rate(%)"].values
    f_arr = result["Forward Rate(%)"].values

    for ax, y_arr, label, color in [
        (axes[0], s_arr,   "Spot Rate",    "steelblue"),
        (axes[1], f_arr, "Forward Rate", "darkorchid"),
    ]:
        ax.plot(t_arr, y_arr, color=color, lw=2, label=label)
        ax.axhline(LTFR * 100, color="red",    ls="--", lw=1.2, label=f"LTFR {LTFR*100:.2f}%")
        ax.axvline(LLP,         color="green",  ls=":",  lw=1.2, label=f"LLP {LLP}Y")
        ax.axvline(CP,          color="orange", ls=":",  lw=1.2, label=f"CP {CP}Y")
        ax.set_xlabel("만기 (년)", fontsize=11)
        ax.set_ylabel("금리 (%)", fontsize=11)
        ax.set_title(f"{label} Curve", fontsize=11)
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
        ax.set_xlim(0, MAX_TENOR)

    plt.tight_layout()
    chart_path = os.path.join(OUTPUT_DIR, f"원화_금리기간구조_{date_str}_차트.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  ✓ 차트 저장 완료: {chart_path}")
    print()

    return result


if __name__ == "__main__":
    run()
