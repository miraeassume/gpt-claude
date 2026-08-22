# -*- coding: utf-8 -*-
"""
민감도 결과(V_Fwd 4종)를 회사 DB import 용 long-format CSV 로 변환.

입력 : 원화_LP_금리기간구조_{YYYYMMDD}_민감도.xlsx  (시트: Fwd_비교_월별)
출력 : 위험경감_할인율_DB_import_{CLYM}.csv

DB 칼럼 정의
  clym          : base_date 앞 6자리        (예: 2026-06-30 → '202606')
  ecast_vrbl_nm : 'CREDR_BU_D_DISCR' 고정
  bz_dnm        : 변수별 명칭 (아래 매핑)     ※ 뒤4자리 = CLYM 뒤4자리
  scno_dvvl     : '1'  고정
  ecast_ky      : '0'  고정
  seq           : 변수별 1부터 시작하는 순번
  sysdate       : 생성 시점 현재일시 'YYYY-MM-DD HH:MM:SS'
  inpp_cd       : 'AUTO' 고정
  ecast_data    : 예측 데이터 = V_Fwd 값(소수, 6자리 반올림)
"""
import os
from datetime import datetime
import pandas as pd

BASE_DATE = "2026-06-30"
CLYM  = BASE_DATE.replace("-", "")[:6]     # '202606'
CLYM4 = CLYM[-4:]                          # '2606'
DATE_STR = BASE_DATE.replace("-", "")      # '20260630'

XLSX = f"원화_LP_금리기간구조_{DATE_STR}_민감도.xlsx"
OUT  = f"위험경감_할인율_DB_import_{CLYM}.csv"

# 원본 컬럼 → bz_dnm 매핑
VAR_MAP = {
    "V_Fwd_base(%)":  f"IFRS17_RR_{CLYM4}",
    "V_Fwd_-5bp(%)":  f"IFRS17_RR05DN_{CLYM4}",
    "V_Fwd_-10bp(%)": f"IFRS17_RR10DN_{CLYM4}",
    "V_Fwd_-25bp(%)": f"IFRS17_RR25DN_{CLYM4}",
}

# ── 고정값 ────────────────────────────────────────────────────
SCNO_DVVL = "1"       # 시나리오 구분값 고정
ECAST_KY  = "0"       # 예측 키 고정
INPP_CD   = "AUTO"    # 입력자 코드 고정
SYSDATE   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 생성 시점 현재일시

COLS = ["clym", "ecast_vrbl_nm", "bz_dnm", "scno_dvvl",
        "ecast_ky", "seq", "sysdate", "inpp_cd", "ecast_data"]


def main():
    src = pd.read_excel(XLSX, sheet_name="Fwd_비교_월별")
    p_col = [c for c in src.columns if c.startswith("P")][0]  # 'P(월)'

    rows = []
    for orig_col, bz in VAR_MAP.items():
        seq = 0
        for _, r in src.iterrows():
            val = r[orig_col]
            if pd.isna(val):          # P=1200 등 Forward 미정의 행 제외
                continue
            seq += 1                  # 변수별 1부터 시작
            rows.append({
                "clym":          CLYM,
                "ecast_vrbl_nm": "CREDR_BU_D_DISCR",
                "bz_dnm":        bz,
                "scno_dvvl":     SCNO_DVVL,
                "ecast_ky":      ECAST_KY,
                "seq":           seq,
                "sysdate":       SYSDATE,
                "inpp_cd":       INPP_CD,
                "ecast_data":    round(float(val) / 100.0, 6),  # % → 소수, 6자리 반올림
            })

    out = pd.DataFrame(rows, columns=COLS)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    print(f"[OK] {OUT}  ({len(out)} rows)")
    print(f"  clym={CLYM}  bz_dnm 4종:")
    for c, b in VAR_MAP.items():
        print(f"    {c:>16} -> {b}")
    print(f"  sysdate={SYSDATE}")
    print("\n[미리보기]")
    print(out.head(3).to_string(index=False))
    print("  ...")
    print(out.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()
