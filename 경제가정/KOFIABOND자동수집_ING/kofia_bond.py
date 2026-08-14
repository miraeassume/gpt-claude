"""
KOFIA 국고채권 시가평가 가중평균수익률 수집 모듈
- 엔드포인트: https://www.kofiabond.or.kr/XMLSERVICES/
- 방식: XML POST (세션 쿠키 자동 처리)
"""

import requests
import xml.etree.ElementTree as ET
import pandas as pd

MATURITY_MAP = {
    "val1":  "1M",   "val2":  "3M",   "val3":  "6M",
    "val4":  "1Y",   "val5":  "1.5Y", "val6":  "2Y",
    "val7":  "2.5Y", "val8":  "3Y",   "val9":  "4Y",
    "val10": "5Y",   "val11": "7Y",   "val12": "10Y",
    "val13": "15Y",  "val14": "20Y",  "val15": "30Y",
}

API_URL  = "https://www.kofiabond.or.kr/proframeWeb/XMLSERVICES/"  # 실제 WebSquare 호출 URL
BASE_URL = "https://www.kofiabond.or.kr/"
DATA_PAGE = "https://www.kofiabond.or.kr/websquare/websquare.html?w2xPath=/xml/main.xml"

_COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}


def _make_session() -> requests.Session:
    """브라우저처럼 세션 초기화 (쿠키 획득)."""
    s = requests.Session()
    s.headers.update(_COMMON_HEADERS)
    s.get(BASE_URL, timeout=10)   # 메인 → 쿠키 세팅
    s.get(DATA_PAGE, timeout=10)  # 데이터 페이지 방문
    return s


def _build_payload(date: str) -> bytes:
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<message>
  <proframeHeader>
    <pfmAppName>BIS-KOFIABOND</pfmAppName>
    <pfmSvcName>BISSrtPrcEstMtrxWhtAvgSrchSO</pfmSvcName>
    <pfmFnName>selectList</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
  <BISSrtPrcEstMtrxWhtAvgDTO>
    <standardDt>{date}</standardDt>
    <applyGbCd>C00</applyGbCd>
    <val20>1</val20>
  </BISSrtPrcEstMtrxWhtAvgDTO>
</message>"""
    return xml.encode("utf-8")


def _parse_response(content: bytes, date: str) -> pd.DataFrame:
    """XML 응답 → 국고채권 1행 DataFrame."""
    root = ET.fromstring(content)
    records = [
        {child.tag: child.text for child in item}
        for item in root.iter("BISSrtPrcEstMtrxWhtAvgDTO")
    ]

    if not records:
        print(f"[{date}] 응답 데이터 없음 (휴일 또는 미영업일)")
        return pd.DataFrame()

    df = pd.DataFrame(records)

    if "typeNmMrk" not in df.columns:
        print(f"[{date}] 예상 외 응답 구조")
        return pd.DataFrame()

    df_gov = df[df["typeNmMrk"] == "국고채권"].copy()
    if df_gov.empty:
        print(f"[{date}] 국고채권 row 없음")
        return pd.DataFrame()

    row: dict = {"기준일": date}
    for val_col, maturity in MATURITY_MAP.items():
        val = df_gov[val_col].values[0] if val_col in df_gov.columns else None
        row[maturity] = float(val) if val and val != "0" else None

    return pd.DataFrame([row])


def get_govbond_rate(date: str, session: requests.Session | None = None) -> pd.DataFrame:
    """
    KOFIA 국고채권 시가평가 가중평균수익률 단일 날짜 조회.

    Parameters
    ----------
    date    : 'YYYYMMDD' 형식  (예: '20260731')
    session : 재사용할 세션 객체 (None 이면 자동 생성)

    Returns
    -------
    pd.DataFrame  기준일 + 만기별 수익률 1행 / 데이터 없으면 빈 DataFrame
    """
    s = session or _make_session()

    response = s.post(
        API_URL,
        data=_build_payload(date),
        headers={
            "Content-Type": "application/xml; charset=utf-8",
            "Referer":      DATA_PAGE,
            "Origin":       BASE_URL.rstrip("/"),
        },
        timeout=15,
    )
    response.raise_for_status()

    # 서버가 에러 HTML을 200으로 반환하는 경우 감지
    ct = response.headers.get("Content-Type", "")
    if "html" in ct or response.content.strip().startswith(b"<!DOCTYPE"):
        body_preview = response.content[:300].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"[{date}] 서버가 XML 대신 HTML을 반환했습니다.\n"
            "  가능한 원인:\n"
            "  1) 네트워크/IP 차단 (사내망 미접속, WAF 등)\n"
            "  2) 세션/쿠키 만료\n"
            f"  응답 미리보기:\n{body_preview}"
        )

    return _parse_response(response.content, date)


def get_govbond_rate_multi(dates: list[str]) -> pd.DataFrame:
    """
    여러 날짜 일괄 조회 (세션 재사용으로 속도 개선).

    Parameters
    ----------
    dates : ['YYYYMMDD', ...] 리스트

    Returns
    -------
    pd.DataFrame  날짜별 수익률 누적 DataFrame
    """
    s = _make_session()
    frames = []
    for d in dates:
        try:
            df = get_govbond_rate(d, session=s)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            print(f"[{d}] 수집 실패: {e}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── 직접 실행 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TARGET_DATE = "20260731"
    print(f"=== KOFIA 국고채권 금리 조회: {TARGET_DATE} ===\n")

    try:
        df = get_govbond_rate(TARGET_DATE)
    except RuntimeError as e:
        print(e)
        df = pd.DataFrame()

    if not df.empty:
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 200)
        print(df.to_string(index=False))

        out_path = f"kofia_govbond_{TARGET_DATE}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"\n[저장 완료] {out_path}")
    else:
        print("데이터를 가져오지 못했습니다.")
