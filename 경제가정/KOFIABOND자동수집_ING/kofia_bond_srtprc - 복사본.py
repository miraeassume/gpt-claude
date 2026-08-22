"""
KOFIA 채권시가평가수익률 수집 모듈
화면 경로 : 시가평가 > 채권시가평가수익률
API     : BISBndSrtPrcSrchSO.selectDay
기관 설정: 평가사 평균('23.1.9~) + 5개 평가사 전체 선택

기관 코드 참고:
  A20000 : 평가사 평균('23.1.9~)  ← 기본값
  A10000 : 평가사 평균(~'23.1.8)
  A10002 : 나이스피앤아이
  A10003 : 한국자산평가
  A10004 : KIS자산평가
  A10005 : 에프앤자산평가
  A10006 : 이지자산평가

val 만기 매핑 (가중평균수익률 API와 다름):
  val1=3M, val2=6M, val3=9M, val4=1Y, val5=1.5Y,
  val6=2Y, val7=2.5Y, val8=3Y, val9=4Y, val10=5Y,
  val11=7Y, val12=10Y, val13=15Y, val14=20Y, val15=30Y, val16=50Y
"""

import requests
import xml.etree.ElementTree as ET
import pandas as pd

# ── 상수 ──────────────────────────────────────────────────────────────────
API_URL = "https://www.kofiabond.or.kr/proframeWeb/XMLSERVICES/"

MATURITY_MAP = {
    "val1":  "3M",   "val2":  "6M",   "val3":  "9M",
    "val4":  "1Y",   "val5":  "1.5Y", "val6":  "2Y",
    "val7":  "2.5Y", "val8":  "3Y",   "val9":  "4Y",
    "val10": "5Y",   "val11": "7Y",   "val12": "10Y",
    "val13": "15Y",  "val14": "20Y",  "val15": "30Y",
    "val16": "50Y",
}

# 기관 코드
ORG_AVG_NEW  = "A20000"   # 평가사 평균('23.1.9~)
ORG_AVG_OLD  = "A10000"   # 평가사 평균(~'23.1.8)
ORG_NICE     = "A10002"   # 나이스피앤아이
ORG_KAP      = "A10003"   # 한국자산평가
ORG_KIS      = "A10004"   # KIS자산평가
ORG_FN       = "A10005"   # 에프앤자산평가
ORG_EG       = "A10006"   # 이지자산평가 (EG자산평가)

_HEADERS = {
    "Content-Type": "application/xml; charset=utf-8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.kofiabond.or.kr/",
}


def _build_payload(
    date: str,
    report_comp_cd: str = ORG_AVG_NEW,
    eval_cds: list[str] | None = None,
) -> bytes:
    """
    selectDay 요청 XML 생성.

    Parameters
    ----------
    date           : 조회 기준일 'YYYYMMDD'
    report_comp_cd : 기관 코드 (기본: 평가사 평균 '23.1.9~)
    eval_cds       : 체크박스로 선택할 평가사 코드 리스트
                     None 이면 5개 전체 선택
    """
    if eval_cds is None:
        eval_cds = [ORG_NICE, ORG_KAP, ORG_KIS, ORG_FN, ORG_EG]

    # val1~val5 채우기 (최대 5개, 빈 슬롯은 빈 태그)
    checkbox_tags = ""
    for i in range(1, 6):
        code = eval_cds[i - 1] if i <= len(eval_cds) else ""
        checkbox_tags += f"    <val{i}>{code}</val{i}>\n"

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<message>
  <proframeHeader>
    <pfmAppName>BIS-KOFIABOND</pfmAppName>
    <pfmSvcName>BISBndSrtPrcSrchSO</pfmSvcName>
    <pfmFnName>selectDay</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
  <BISBndSrtPrcDayDTO>
    <standardDt>{date}</standardDt>
    <reportCompCd>{report_comp_cd}</reportCompCd>
    <applyGbCd>C00</applyGbCd>
{checkbox_tags}  </BISBndSrtPrcDayDTO>
</message>"""
    return xml.encode("utf-8")


def _parse_response(content: bytes, date: str, bond_type: str = "국고채권") -> pd.DataFrame:
    """XML 응답 → 지정 채권 종류 1행 DataFrame."""
    root = ET.fromstring(content)
    records = [
        {child.tag: child.text for child in item}
        for item in root.iter("BISBndSrtPrcDayDTO")
    ]

    if not records:
        print(f"[{date}] 응답 데이터 없음 (휴일 또는 미영업일)")
        return pd.DataFrame()

    df = pd.DataFrame(records)

    if "typeNmMrk" not in df.columns:
        print(f"[{date}] 예상 외 응답 구조: {df.columns.tolist()[:5]}")
        return pd.DataFrame()

    df_target = df[df["typeNmMrk"] == bond_type].copy()
    if df_target.empty:
        available = df["typeNmMrk"].dropna().unique().tolist()
        print(f"[{date}] '{bond_type}' 없음. 가능한 종류: {available[:5]}")
        return pd.DataFrame()

    row: dict = {"기준일": date, "기관": df_target["koreanShotNm"].values[0]}
    for val_col, maturity in MATURITY_MAP.items():
        val = df_target[val_col].values[0] if val_col in df_target.columns else None
        row[maturity] = float(val) if val and val != "0" else None

    return pd.DataFrame([row])


def get_srtprc_rate(
    date: str,
    bond_type: str = "국고채권",
    report_comp_cd: str = ORG_AVG_NEW,
    eval_cds: list[str] | None = None,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """
    KOFIA 채권시가평가수익률 단일 날짜 조회.

    Parameters
    ----------
    date           : 조회 기준일 'YYYYMMDD' (예: '20260731')
    bond_type      : 채권 종류명 (기본: '국고채권')
    report_comp_cd : 기관 코드   (기본: 평가사 평균 '23.1.9~, A20000)
    eval_cds       : 체크박스 평가사 코드 리스트 (None=5개 전체)
    session        : 재사용할 requests.Session (None이면 자동 생성)

    Returns
    -------
    pd.DataFrame  기준일 + 기관 + 만기별 수익률 1행
    """
    s = session or requests.Session()

    response = s.post(
        API_URL,
        data=_build_payload(date, report_comp_cd, eval_cds),
        headers=_HEADERS,
        timeout=15,
    )
    response.raise_for_status()

    ct = response.headers.get("Content-Type", "")
    if "html" in ct or response.content.strip().startswith(b"<!DOCTYPE"):
        raise RuntimeError(
            f"[{date}] 서버가 HTML을 반환했습니다. 네트워크/IP 접근 문제일 수 있습니다.\n"
            f"응답: {response.content[:200].decode('utf-8', errors='replace')}"
        )

    return _parse_response(response.content, date, bond_type)


def get_srtprc_rate_multi(
    dates: list[str],
    bond_type: str = "국고채권",
    report_comp_cd: str = ORG_AVG_NEW,
    eval_cds: list[str] | None = None,
) -> pd.DataFrame:
    """
    여러 날짜 일괄 조회 (세션 재사용).

    Parameters
    ----------
    dates          : ['YYYYMMDD', ...] 리스트
    bond_type      : 채권 종류명 (기본: '국고채권')
    report_comp_cd : 기관 코드
    eval_cds       : 체크박스 평가사 코드 리스트

    Returns
    -------
    pd.DataFrame  날짜별 수익률 누적 DataFrame
    """
    s = requests.Session()
    frames = []
    for d in dates:
        try:
            df = get_srtprc_rate(d, bond_type, report_comp_cd, eval_cds, session=s)
            if not df.empty:
                frames.append(df)
                print(f"[{d}] 수집 완료")
        except Exception as e:
            print(f"[{d}] 오류: {e}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── 직접 실행 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TARGET_DATE   = "20260731"
    BOND_TYPE     = "국고채권"
    ORG           = ORG_AVG_NEW                              # 평가사 평균('23.1.9~)
    EVAL_CDS      = [ORG_NICE, ORG_KAP, ORG_KIS, ORG_FN, ORG_EG]  # 5개 전체

    print(f"=== KOFIA 채권시가평가수익률 조회 ===")
    print(f"  날짜   : {TARGET_DATE}")
    print(f"  기관   : 평가사 평균('23.1.9~) [A20000]")
    print(f"  평가사 : 나이스피앤아이 / 한국자산평가 / KIS / 에프앤 / 이지")
    print(f"  종류   : {BOND_TYPE}\n")

    try:
        df = get_srtprc_rate(TARGET_DATE, BOND_TYPE, ORG, EVAL_CDS)
    except RuntimeError as e:
        print(e)
        df = pd.DataFrame()

    if not df.empty:
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 200)
        print(df.to_string(index=False))

        out_path = f"kofia_srtprc_{TARGET_DATE}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"\n[저장 완료] {out_path}")
    else:
        print("데이터를 가져오지 못했습니다.")
