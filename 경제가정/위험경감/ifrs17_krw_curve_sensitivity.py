"""
============================================================
  IFRS17 / K-ICS  원화 조정무위험 금리기간구조 — 민감도 분석판
  (Smith-Wilson 방법, 2026년 감독원 고시 기준)
  ★ 20년/30년 국채금리 충격 시나리오별 할인율 곡선 4종 생성
============================================================

이 파일은 `ifrs17_krw_curve_auto.py` 의 계산 엔진(Smith-Wilson 함수)과
파라미터, KOFIA 자동취득 결과(BOND_YIELDS_PCT)를 그대로 import 하여
재사용한다. Step 1~6 산출 파이프라인을 build_curve() 함수로 추출하여
임의의 국고채 YTM 입력에 대해 U(Spot)/V(Forward) 곡선을 계산한다.

[생성 시나리오 — 4종]
  1. base                : 원본 국고채 YTM 그대로
  2. 20Y/30Y  -5bp       : 20년·30년 YTM 에서 각각 5bp 차감
  3. 20Y/30Y  -10bp      : 20년·30년 YTM 에서 각각 10bp 차감
  4. 20Y/30Y  -25bp      : 20년·30년 YTM 에서 각각 25bp 차감

  ※ 1bp = 0.01%p.  20년·30년 만기 YTM 에만 충격을 주고 나머지 만기는 유지한다.
    (충격 후 전체 만기에 대해 Smith-Wilson 곡선을 재적합/재외삽 → 곡선 전 구간에 영향)

[의존 패키지]
  pip install numpy pandas scipy matplotlib openpyxl requests
"""

import os
import sys
from datetime import datetime
# Windows 콘솔(cp949)에서 em-dash 등 유니코드 출력 보장
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings("ignore")

# ── 기존 자동수집판에서 계산 엔진·파라미터·기준 YTM 재사용 ─────────────
#    (import 시 KOFIA 자동취득이 1회 수행되어 base.BOND_YIELDS_PCT 확보)
import ifrs17_krw_curve_auto as base
from ifrs17_krw_curve_auto import (
    smith_wilson_ytm,
    smith_wilson_from_spot,
    calibrate_alpha,
    _w_kernel_matrix,
    BASE_DATE, LLP, CP, LTFR, UFR_SW2, COUPON_FREQ,
    LP_PCT, ALPHA_TOL, MAX_TENOR, OUTPUT_DIR,
)


# ============================================================
# ★ 사용자 입력 구역 — 민감도 시나리오 정의
# ============================================================

# 충격을 적용할 만기(년)
SHOCK_TENORS = [20.0, 30.0]

# 시나리오 정의  (라벨, 차감 bp)   1bp = 0.01%p
#   base 는 0bp (충격 없음)
SCENARIOS = [
    ("base",   0),
    ("-5bp",   5),
    ("-10bp",  10),
    ("-25bp",  25),
]


# ============================================================
# Step 1~6 산출 파이프라인 (임의 YTM → U/V 곡선)
# ============================================================

def build_curve(bond_yields_pct):
    """
    국고채 YTM 딕셔너리 {tenor(년): YTM(%)} 를 입력받아
    Smith-Wilson Step 1~6 을 수행하고 월별 U(Spot)/V(Forward) 곡선을 반환.

    ifrs17_krw_curve_auto.run() 의 Step 1~6 로직과 완전 동일.

    Returns
    -------
    dict :
        uv_df      : DataFrame  (P(월), 만기(년), U_Spot_Disc(%), V_Fwd_Disc(%), 비고)
        alpha2     : float      Step3 산출 alpha
        fwd_inst   : float      CP 순간선도금리
        ok         : str        수렴여부 PASS/FAIL
        F_col      : ndarray    SW1 연속현물 (관찰만기)
        G_all      : ndarray    LP 가산 연속현물 (관찰만기)
        sw1_out_tenors : list
        ufr_sw1    : float
    """
    # ── 입력 데이터 준비 ─────────────────────────────────────
    obs_tenors = sorted(bond_yields_pct.keys())
    ytms       = [bond_yields_pct[t] / 100.0 for t in obs_tenors]
    ufr_sw1    = ytms[-1]    # 1단계 SW UFR = 50Y YTM

    sw1_out_tenors = sorted(set(obs_tenors) | {float(LLP)})
    sw2_obs_tenors = [t for t in sw1_out_tenors if t <= LLP + 1e-9]

    # ── [Step 1] SmithWilsonYTM  →  F 컬럼 ───────────────────
    k_spots_all = smith_wilson_ytm(
        obs_tenors, ytms, COUPON_FREQ,
        ufr_disc   = ufr_sw1,
        alpha      = 0.1,
        out_tenors = sw1_out_tenors,
    )
    F_col = k_spots_all

    sw1_arr = np.array(sw1_out_tenors)
    mask_lp = sw1_arr <= LLP + 1e-9
    k_spots_lp = k_spots_all[mask_lp]

    # ── [Step 2] LP 가산  →  G 컬럼 ──────────────────────────
    lp_dec = LP_PCT / 100.0
    G_sw2  = np.log(np.exp(k_spots_lp) + lp_dec)
    G_all  = np.where(mask_lp, np.log(np.exp(F_col) + lp_dec), np.nan)

    # ── [Step 3] Alpha 자동 산출 (UFR_SW2 기준) ───────────────
    alpha2 = calibrate_alpha(UFR_SW2, sw2_obs_tenors, G_sw2, CP, tol=ALPHA_TOL)

    # 수렴 검증
    _ltfr_c = np.log(1.0 + UFR_SW2)
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
    ok       = "PASS" if diff_bp <= 1.001 else "FAIL"

    # ── [Step 4] SmithWilson → 월단위 연속 현물금리 ───────────
    dt = 1.0 / 12
    n_months = MAX_TENOR * 12
    t0_tenors = np.concatenate([[1e-6], np.arange(1, n_months + 1) * dt])

    cont_all = smith_wilson_from_spot(
        sw2_obs_tenors, G_sw2, UFR_SW2, alpha2, t0_tenors
    )

    # ── [Step 5] Cont2Discrete  →  U 컬럼 ────────────────────
    U_all = np.exp(cont_all) - 1

    # ── [Step 6] Forward(Discrete)  →  V 컬럼 ────────────────
    P_idx = np.arange(len(t0_tenors))
    V_all = (1.0 + U_all[1:]) ** P_idx[1:] / (1.0 + U_all[:-1]) ** P_idx[:-1] - 1
    V_all = np.append(V_all, np.nan)

    # ── U/V 결과 DataFrame ───────────────────────────────────
    uv_rows = []
    for p in range(len(t0_tenors)):
        t = t0_tenors[p]
        uv_rows.append({
            "P(월)":          int(p),
            "만기(년)":       round(float(t), 6),
            "U_Spot_Disc(%)": round(float(U_all[p]) * 100, 8),
            "V_Fwd_Disc(%)":  (round(float(V_all[p]) * 100, 8)
                               if not np.isnan(V_all[p]) else np.nan),
            "비고":           ("LLP" if abs(t - LLP) < 1e-6 else
                               "CP"  if abs(t - CP)  < 1e-6 else ""),
        })
    uv_df = pd.DataFrame(uv_rows)

    return {
        "uv_df":          uv_df,
        "alpha2":         alpha2,
        "fwd_inst":       fwd_inst,
        "ok":             ok,
        "F_col":          F_col,
        "G_all":          G_all,
        "sw1_out_tenors": sw1_out_tenors,
        "ufr_sw1":        ufr_sw1,
    }


def make_shocked_yields(base_yields, shock_bp, shock_tenors=SHOCK_TENORS):
    """
    base_yields 딕셔너리를 복사한 뒤 shock_tenors 만기의 YTM 에서
    shock_bp(bp)를 차감한 새 딕셔너리 반환. (1bp = 0.01%p)
    """
    shocked = dict(base_yields)
    for t in shock_tenors:
        if t in shocked:
            shocked[t] = shocked[t] - shock_bp * 0.01
    return shocked


# ============================================================
# 회사 DB import 용 CSV 생성 (long-format)
# ============================================================
#
# DB 칼럼 정의
#   clym          : base_date 앞 6자리        (예: 2026-06-30 → '202606')
#   ecast_vrbl_nm : 'CREDR_BU_D_DISCR' 고정
#   bz_dnm        : 변수별 명칭 (VAR_MAP)      ※ 뒤4자리 = CLYM 뒤4자리
#   scno_dvvl     : '1'  고정
#   ecast_ky      : '0'  고정
#   seq           : 변수별 1부터 시작하는 순번
#   sysdate       : 생성 시점 현재일시 'YYYY-MM-DD HH:MM:SS'
#   inpp_cd       : 'AUTO' 고정
#   ecast_data    : 예측 데이터 = V_Fwd 값(소수, 6자리 반올림)

# 고정값
DB_SCNO_DVVL = "1"
DB_ECAST_KY  = "0"
DB_INPP_CD   = "AUTO"
DB_ECAST_VRBL_NM = "CREDR_BU_D_DISCR"
DB_CSV_COLS = ["clym", "ecast_vrbl_nm", "bz_dnm", "scno_dvvl",
               "ecast_ky", "seq", "sysdate", "inpp_cd", "ecast_data"]

# 시나리오 라벨 → bz_dnm 접두어 매핑 (뒤4자리는 실행 시 CLYM 으로 결합)
BZ_PREFIX = {
    "base":  "IFRS17_RR",
    "-5bp":  "IFRS17_RR05DN",
    "-10bp": "IFRS17_RR10DN",
    "-25bp": "IFRS17_RR25DN",
}


def export_db_csv(fwd_cmp):
    """
    fwd_cmp (시나리오별 V_Fwd(%) 월별 비교표)를 long-format DB import CSV 로 저장.

    Parameters
    ----------
    fwd_cmp : DataFrame
        컬럼: P(월), 만기(년), 비고, V_Fwd_{label}(%) ...
    """
    clym  = BASE_DATE.replace("-", "")[:6]   # '202606'
    clym4 = clym[-4:]                        # '2606'
    sysdate = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for label, _ in SCENARIOS:
        col = f"V_Fwd_{label}(%)"
        bz  = f"{BZ_PREFIX[label]}_{clym4}"
        seq = 0
        for _, r in fwd_cmp.iterrows():
            val = r[col]
            if pd.isna(val):        # P=1200 등 Forward 미정의 행 제외
                continue
            seq += 1                # 변수별 1부터 시작
            rows.append({
                "clym":          clym,
                "ecast_vrbl_nm": DB_ECAST_VRBL_NM,
                "bz_dnm":        bz,
                "scno_dvvl":     DB_SCNO_DVVL,
                "ecast_ky":      DB_ECAST_KY,
                "seq":           seq,
                "sysdate":       sysdate,
                "inpp_cd":       DB_INPP_CD,
                "ecast_data":    round(float(val) / 100.0, 6),  # % → 소수, 6자리 반올림
            })

    out = pd.DataFrame(rows, columns=DB_CSV_COLS)
    csv_path = os.path.join(
        OUTPUT_DIR, f"위험경감_할인율_DB_import_{clym}.csv")
    out.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"  [OK] DB import CSV 저장: {csv_path}  ({len(out)} rows)")
    for label, _ in SCENARIOS:
        print(f"        V_Fwd_{label}(%) -> {BZ_PREFIX[label]}_{clym4}")
    return csv_path


# ============================================================
# 메인 실행
# ============================================================

def run():
    print("=" * 72)
    print("  IFRS17 / K-ICS  원화 조정무위험 금리기간구조 — 민감도 분석판")
    print(f"  기준일: {BASE_DATE}  LLP={LLP}Y  CP={CP}Y  "
          f"UFR_SW2={UFR_SW2*100:.2f}%  LP={LP_PCT}%")
    print(f"  충격 만기: {[int(t) for t in SHOCK_TENORS]}년"
          f"  시나리오: {[s[0] for s in SCENARIOS]}")
    print("=" * 72)

    base_yields = dict(base.BOND_YIELDS_PCT)

    # 기준 YTM 요약 출력
    print("\n  [기준 국고채 YTM (%)]")
    for t in sorted(base_yields):
        star = "  ← 충격대상" if t in SHOCK_TENORS else ""
        print(f"    {t:>6.2f}Y : {base_yields[t]:.4f}{star}")

    # ── 시나리오별 곡선 산출 ─────────────────────────────────
    results = {}
    for label, bp in SCENARIOS:
        yields = make_shocked_yields(base_yields, bp)
        res    = build_curve(yields)
        results[label] = res
        y20 = yields.get(20.0, np.nan)
        y30 = yields.get(30.0, np.nan)
        print(f"\n  [{label:>6}]  20Y={y20:.4f}%  30Y={y30:.4f}%  "
              f"alpha={res['alpha2']:.6f}  수렴={res['ok']}")

    # ── 통합 비교 DataFrame (월별) ───────────────────────────
    #    기준 uv_df 의 P/만기 골격에 각 시나리오 U/V 를 컬럼으로 병합
    base_uv = results["base"]["uv_df"]
    spot_cmp = base_uv[["P(월)", "만기(년)", "비고"]].copy()
    fwd_cmp  = base_uv[["P(월)", "만기(년)", "비고"]].copy()
    for label, _ in SCENARIOS:
        spot_cmp[f"U_Spot_{label}(%)"] = results[label]["uv_df"]["U_Spot_Disc(%)"]
        fwd_cmp [f"V_Fwd_{label}(%)"]  = results[label]["uv_df"]["V_Fwd_Disc(%)"]

    # 차이(bp) 컬럼 추가 (base 대비)
    for label, bp in SCENARIOS:
        if bp == 0:
            continue
        spot_cmp[f"Δ_{label}(bp)"] = (
            (spot_cmp[f"U_Spot_{label}(%)"] - spot_cmp["U_Spot_base(%)"]) * 100
        ).round(4)
        fwd_cmp[f"Δ_{label}(bp)"] = (
            (fwd_cmp[f"V_Fwd_{label}(%)"] - fwd_cmp["V_Fwd_base(%)"]) * 100
        ).round(4)

    # ── 콘솔: 주요 만기 Spot 비교 ────────────────────────────
    key_months = {int(round(y * 12)) for y in
                  [1, 3, 5, 10, 15, 20, LLP, 30, 40, 50, CP, 70, 100]}
    print("\n  [주요 만기 Spot(Discrete) 비교 (%)]")
    header = "  " + f"{'만기(년)':>8}" + "".join(
        f"{lbl:>12}" for lbl, _ in SCENARIOS)
    print(header)
    print("  " + "-" * (8 + 12 * len(SCENARIOS)))
    for _, r in spot_cmp.iterrows():
        p = int(r["P(월)"])
        if p in key_months:
            row = "  " + f"{r['만기(년)']:>8.2f}"
            for lbl, _ in SCENARIOS:
                row += f"{r[f'U_Spot_{lbl}(%)']:>12.5f}"
            print(row)

    # ── 회사 DB import 용 CSV 생성 (매월 자동, Excel 저장과 독립) ──
    export_db_csv(fwd_cmp)

    # ── Excel 저장 ────────────────────────────────────────────
    date_str   = BASE_DATE.replace("-", "")
    excel_path = os.path.join(
        OUTPUT_DIR, f"원화_LP_금리기간구조_{date_str}_민감도.xlsx")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        # 1) Spot 비교 (전 시나리오)
        spot_cmp.to_excel(writer, index=False, sheet_name="Spot_비교_월별")
        # 2) Forward 비교 (전 시나리오)
        fwd_cmp.to_excel(writer, index=False, sheet_name="Fwd_비교_월별")

        # 3) 연단위 요약 (P=12,24,...)
        annual_idx = [p for p in base_uv["P(월)"]
                      if p > 0 and p % 12 == 0]
        ann = spot_cmp[spot_cmp["P(월)"].isin(annual_idx)].copy()
        ann.to_excel(writer, index=False, sheet_name="Spot_비교_연단위")

        # 4) 시나리오별 개별 U/V 시트
        for label, _ in SCENARIOS:
            sheet = f"UV_{label}".replace("-", "m")  # 시트명에 '-' 회피
            results[label]["uv_df"].to_excel(
                writer, index=False, sheet_name=sheet[:31])

        # 5) 파라미터 / 시나리오 정보
        param_rows = [
            ["기준일",        BASE_DATE],
            ["YTM 출처",      "KOFIA API 자동취득 (base) + 20Y/30Y 충격"],
            ["충격 만기",     ", ".join(f"{int(t)}Y" for t in SHOCK_TENORS)],
            ["LLP (년)",      LLP],
            ["CP  (년)",      CP],
            ["UFR_SW2 (%)",   UFR_SW2 * 100],
            ["LTFR (참고, %)", LTFR * 100],
            ["이자지급횟수",  COUPON_FREQ],
            ["LP (%)",        LP_PCT],
        ]
        for label, bp in SCENARIOS:
            r = results[label]
            param_rows.append(
                [f"[{label}] 차감bp / alpha / 수렴",
                 f"{bp}bp / {r['alpha2']:.8f} / {r['ok']}"])
        pd.DataFrame(param_rows, columns=["항목", "값"]).to_excel(
            writer, index=False, sheet_name="파라미터")

        # 6) 시나리오별 입력 YTM
        ytm_rows = []
        for t in sorted(base_yields):
            row = {"Tenor(년)": t}
            for label, bp in SCENARIOS:
                row[f"YTM_{label}(%)"] = make_shocked_yields(base_yields, bp)[t]
            ytm_rows.append(row)
        pd.DataFrame(ytm_rows).to_excel(
            writer, index=False, sheet_name="국고채YTM입력")

    print(f"\n  [OK] Excel 저장: {excel_path}")

    # ── 차트 (Spot / Forward 4곡선 비교) ─────────────────────
    colors = {"base": "black", "-5bp": "steelblue",
              "-10bp": "darkorange", "-25bp": "crimson"}

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    fig.suptitle(
        f"민감도 분석 — 조정무위험 금리기간구조 (20Y/30Y 국채금리 충격)  {BASE_DATE}",
        fontsize=13, fontweight="bold")

    x = base_uv["만기(년)"].values
    for label, _ in SCENARIOS:
        c  = colors.get(label, None)
        ls = "-" if label == "base" else "--"
        lw = 1.8 if label == "base" else 1.3
        ax1.plot(x, results[label]["uv_df"]["U_Spot_Disc(%)"].values,
                 color=c, ls=ls, lw=lw, label=f"Spot {label}")
        ax2.plot(x, results[label]["uv_df"]["V_Fwd_Disc(%)"].values,
                 color=c, ls=ls, lw=lw, label=f"Fwd {label}")

    for ax, ttl in [(ax1, "U: Spot (Discrete)"), (ax2, "V: Forward (Discrete)")]:
        ax.axvline(LLP, color="green",  ls=":", lw=1.0, label=f"LLP {LLP}Y")
        ax.axvline(CP,  color="gray",   ls=":", lw=1.0, label=f"CP {CP}Y")
        ax.set_ylabel("금리 (%)")
        ax.set_title(ttl, fontsize=11)
        ax.legend(fontsize=8, ncol=2)
        ax.grid(alpha=0.3)
        ax.set_xlim(0, MAX_TENOR)
    ax2.set_xlabel("만기 (년)")
    plt.tight_layout()

    chart_path = os.path.join(
        OUTPUT_DIR, f"원화_LP_금리기간구조_{date_str}_민감도_차트.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  [OK] 차트 저장: {chart_path}")
    print()

    return results


if __name__ == "__main__":
    run()
