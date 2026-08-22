# -*- coding: utf-8 -*-
"""
============================================================
  IFRS17 / K-ICS  원화 할인율 — 통합 자동화 실행 파일
============================================================

`ifrs17_krw_curve_auto.py`(기준곡선 산출 엔진)를 기초로,
`ifrs17_krw_curve_sensitivity.py`(민감도 4종 + DB import CSV)를
하나의 진입점에서 한 번에 실행한다.

■ 설계 방침
  - 계산 엔진 함수는 각 모듈에 그대로 두고 이 파일에서는 `import` 하여
    호출만 한다(코드 중복 없음).
  - ★ 매월 바뀌는 **주요 파라미터는 아래 [사용자 설정 구역] 에서만 수정**한다.
    이 값이 실행 직전에 auto / sensitivity 두 모듈에 모두 주입(override)되므로,
    더 이상 auto.py / sensitivity.py 를 직접 열 필요가 없다.
  - `BASE_DATE` 를 바꾸면 KOFIA 국고채 YTM 을 새 기준일로 **자동 재취득**한다.

■ 실행
    pip install numpy pandas scipy matplotlib openpyxl requests
    python ifrs17_krw_curve_all.py

■ 산출물 (모두 이 폴더에 저장)
    1) 원화_LP_금리기간구조_{YYYYMMDD}_auto.xlsx / _차트.png   ← 기준곡선 (auto)
    2) 원화_LP_금리기간구조_{YYYYMMDD}_민감도.xlsx / _차트.png ← 민감도 4종 (sensitivity)
    3) 위험경감_할인율_DB_import_{YYYYMM}.csv                   ← 회사 DB import (sensitivity)
"""

import sys

# Windows 콘솔(cp949)에서 유니코드 출력 보장
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── 모듈 import (엔진/함수는 각 모듈에서 관리) ──────────────────────
#    ※ 이 시점에 auto 가 KOFIA 를 1회 취득한다(기본 BASE_DATE 기준).
#       아래 apply_params() 에서 BASE_DATE 가 바뀌었으면 재취득한다.
import ifrs17_krw_curve_auto as auto
import ifrs17_krw_curve_sensitivity as sens


# ============================================================
# ★★★  사용자 설정 구역 — 매월 여기만 수정하세요  ★★★
# ============================================================

# ── [실행 토글] ──────────────────────────────────────────────
RUN_BASE        = True    # 기준곡선(auto) Excel/차트 산출
RUN_SENSITIVITY = True    # 민감도 4종 + DB import CSV 산출

# ── [1] 기준일 ───────────────────────────────────────────────
BASE_DATE = "2026-06-30"          # 'YYYY-MM-DD' (바꾸면 KOFIA 자동 재취득)

# ── [2] 유동성프리미엄 LP (%) ────────────────────────────────
LP_PCT = 0.414                    # FSS 홈페이지 매월 고시값 (예: 0.414 = 0.414%)

# ── [3] Smith-Wilson 파라미터 (감독원 고시) ──────────────────
LLP          = 23                 # 최종관찰만기 (년)
CP           = 60                 # 최초수렴시점 (년)
LTFR_PCT     = 4.30               # 장기선도금리 (%, 참고용)
UFR_SW2_PCT  = 4.30               # Step2 SmithWilson + Alpha 교정 UFR (%)
COUPON_FREQ  = 2                  # 이자지급횟수 (연 2회)
ALPHA_TOL    = 1e-4               # Alpha 수렴 허용오차
MAX_TENOR    = 100                # 출력 최대 만기 (년)

# ── [4] 민감도 시나리오 ──────────────────────────────────────
SHOCK_TENORS = [20.0, 30.0]       # 충격을 적용할 만기(년)
SCENARIOS    = [                  # (라벨, 차감 bp)   1bp = 0.01%p
    ("base",   0),
    ("-5bp",   5),
    ("-10bp",  10),
    ("-25bp",  25),
]

# ── [5] DB import CSV 고정값 (sensitivity.export_db_csv) ─────
DB_ECAST_VRBL_NM = "CREDR_BU_D_DISCR"   # ecast_vrbl_nm 고정값
DB_SCNO_DVVL     = "1"                  # scno_dvvl 고정값
DB_ECAST_KY      = "0"                  # ecast_ky 고정값
DB_INPP_CD       = "AUTO"               # inpp_cd 고정값
#   시나리오 라벨 → bz_dnm 접두어 (뒤4자리는 CLYM 으로 자동 결합)
DB_BZ_PREFIX     = {
    "base":  "IFRS17_RR",
    "-5bp":  "IFRS17_RR05DN",
    "-10bp": "IFRS17_RR10DN",
    "-25bp": "IFRS17_RR25DN",
}

# ============================================================
#  (아래는 수정 불필요) — 위 설정을 두 모듈에 주입
# ============================================================


def apply_params():
    """[사용자 설정 구역] 값을 auto / sensitivity 모듈 전역에 주입한다.

    sensitivity 는 `from auto import ...` 로 파라미터의 **복사본**을 갖기 때문에
    auto 만 바꿔서는 반영되지 않는다. 따라서 두 모듈 모두에 명시적으로 대입한다.
    """
    # BASE_DATE 변경 여부 판정 (import 시점 취득값 재사용 or 재취득)
    need_refetch = (BASE_DATE != auto.BASE_DATE)

    # 단위 변환 (% → 소수)
    ltfr_dec = LTFR_PCT / 100.0
    ufr_dec  = UFR_SW2_PCT / 100.0

    # 두 모듈에 공통 주입할 파라미터
    common = {
        "BASE_DATE":   BASE_DATE,
        "LP_PCT":      LP_PCT,
        "LLP":         LLP,
        "CP":          CP,
        "LTFR":        ltfr_dec,
        "UFR_SW2":     ufr_dec,
        "COUPON_FREQ": COUPON_FREQ,
        "ALPHA_TOL":   ALPHA_TOL,
        "MAX_TENOR":   MAX_TENOR,
    }
    for mod in (auto, sens):
        for k, v in common.items():
            if hasattr(mod, k):          # 모듈이 갖고 있는 이름만 덮어씀
                setattr(mod, k, v)

    # 민감도 전용 파라미터 (sensitivity 모듈)
    sens.SHOCK_TENORS = list(SHOCK_TENORS)
    sens.SCENARIOS    = list(SCENARIOS)

    # DB import CSV 규칙 (sensitivity 모듈)
    sens.DB_ECAST_VRBL_NM = DB_ECAST_VRBL_NM
    sens.DB_SCNO_DVVL     = DB_SCNO_DVVL
    sens.DB_ECAST_KY      = DB_ECAST_KY
    sens.DB_INPP_CD       = DB_INPP_CD
    sens.BZ_PREFIX        = dict(DB_BZ_PREFIX)

    # BASE_DATE 가 바뀐 경우에만 KOFIA 국고채 YTM 재취득
    if need_refetch:
        print(f"  [PARAM] BASE_DATE 변경 감지 ({BASE_DATE}) → KOFIA 재취득")
        auto.BOND_YIELDS_PCT = auto.fetch_bond_yields_pct(
            base_date=BASE_DATE, fallback=auto.BOND_YIELDS_PCT_FALLBACK)

    # 요약 출력
    print("  [PARAM] 적용된 주요 파라미터")
    print(f"          BASE_DATE={BASE_DATE}  LP={LP_PCT}%  "
          f"LLP={LLP}Y  CP={CP}Y  LTFR={LTFR_PCT}%  UFR_SW2={UFR_SW2_PCT}%")
    print(f"          COUPON_FREQ={COUPON_FREQ}  MAX_TENOR={MAX_TENOR}Y  "
          f"SHOCK={[int(t) for t in SHOCK_TENORS]}  "
          f"SCENARIOS={[s[0] for s in SCENARIOS]}")


def main():
    print("#" * 72)
    print("#  IFRS17 / K-ICS 원화 할인율 — 통합 자동화 실행")
    print(f"#  기준일: {BASE_DATE}   "
          f"(BASE={RUN_BASE}, SENSITIVITY={RUN_SENSITIVITY})")
    print("#" * 72)

    # ── 파라미터 주입 (두 모듈 동기화) ───────────────────────
    apply_params()

    # ── [1] 기준곡선 (auto) ──────────────────────────────────
    if RUN_BASE:
        print("\n" + "▶" * 3 + "  [1/2] 기준곡선 산출 (ifrs17_krw_curve_auto)\n")
        auto.run()

    # ── [2] 민감도 4종 + DB import CSV (sensitivity) ─────────
    if RUN_SENSITIVITY:
        print("\n" + "▶" * 3 + "  [2/2] 민감도 + DB CSV 산출 "
              "(ifrs17_krw_curve_sensitivity)\n")
        sens.run()

    print("\n" + "#" * 72)
    print("#  [완료] 통합 자동화 실행 종료")
    print("#" * 72)


if __name__ == "__main__":
    main()
