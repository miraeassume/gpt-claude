"""
KOFIA 국고채권 시가평가 가중평균수익률 수집 (Playwright 네트워크 인터셉트 버전)
- 실제 KOFIA 채권 데이터 페이지를 Chromium으로 열고
  WebSquare가 자동으로 보내는 XMLSERVICES 응답을 가로채는 방식
- 설치: pip install playwright && python -m playwright install chromium
"""

import asyncio
import xml.etree.ElementTree as ET
import pandas as pd
from playwright.async_api import async_playwright

MATURITY_MAP = {
    "val1":  "1M",   "val2":  "3M",   "val3":  "6M",
    "val4":  "1Y",   "val5":  "1.5Y", "val6":  "2Y",
    "val7":  "2.5Y", "val8":  "3Y",   "val9":  "4Y",
    "val10": "5Y",   "val11": "7Y",   "val12": "10Y",
    "val13": "15Y",  "val14": "20Y",  "val15": "30Y",
}

BASE_URL  = "https://www.kofiabond.or.kr"
API_URL   = BASE_URL + "/XMLSERVICES/"

# WebSquare 채권금리 > 가중평균수익률 > 국고채권 페이지 XML 경로들
BOND_PAGES = [
    "/websquare/websquare.html?w2xPath=/xml/bndMrktInfo/srtPrcInfo/whtAvgYld/BISSrtPrcGovBndWhtAvgYldInq.xml",
    "/websquare/websquare.html?w2xPath=/xml/bndMrktInfoNew/srtPrcInfo/whtAvgYld/BISSrtPrcGovBndWhtAvgYldInq.xml",
    "/bndMrktInfoNew/srtPrcInfo/whtAvgYld/govBndWhtAvgYld.do",
]


def _parse_xml_to_df(xml_bytes: bytes, date: str) -> pd.DataFrame:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"  XML 파싱 오류: {e}")
        return pd.DataFrame()

    records = [
        {child.tag: child.text for child in item}
        for item in root.iter("BISSrtPrcEstMtrxWhtAvgDTO")
    ]
    if not records:
        print(f"  [{date}] BISSrtPrcEstMtrxWhtAvgDTO 태그 없음")
        return pd.DataFrame()

    df = pd.DataFrame(records)
    if "typeNmMrk" not in df.columns:
        return pd.DataFrame()

    df_gov = df[df["typeNmMrk"] == "국고채권"].copy()
    if df_gov.empty:
        return pd.DataFrame()

    row: dict = {"기준일": date}
    for col, mat in MATURITY_MAP.items():
        val = df_gov[col].values[0] if col in df_gov.columns else None
        row[mat] = float(val) if val and val != "0" else None
    return pd.DataFrame([row])


async def _intercept_fetch(date: str, headless: bool = True, timeout_sec: int = 30) -> pd.DataFrame:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
        )
        page = await context.new_page()

        captured_bodies: list[bytes] = []

        # XMLSERVICES 응답을 인터셉트
        async def handle_response(response):
            if "/XMLSERVICES/" in response.url:
                try:
                    body = await response.body()
                    ct = response.headers.get("content-type", "")
                    print(f"  [인터셉트] {response.url} status={response.status} ct={ct} len={len(body)}")
                    if b"BISSrtPrcEstMtrxWhtAvgDTO" in body:
                        captured_bodies.append(body)
                    else:
                        print(f"  [인터셉트] 예상 태그 없음, 미리보기: {body[:200]}")
                except Exception as e:
                    print(f"  [인터셉트 오류] {e}")

        page.on("response", handle_response)

        # 메인 → 채권 데이터 페이지 순서로 접근
        print("  [1] 메인 페이지 방문...")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1000)

        # 여러 경로 시도
        for bond_page in BOND_PAGES:
            url = BASE_URL + bond_page
            print(f"  [2] 채권 페이지 방문: {url[:80]}...")
            try:
                await page.goto(url, wait_until="networkidle", timeout=timeout_sec * 1000)
                await page.wait_for_timeout(3000)
                if captured_bodies:
                    break
            except Exception as e:
                print(f"      타임아웃/오류: {e}")

        # 인터셉트 실패 시: 페이지에서 날짜를 수동 설정 후 재조회 시도
        if not captured_bodies:
            print("  [3] 자동 인터셉트 실패 → 날짜 조건 수동 입력 시도...")
            # 날짜 입력 필드 찾아서 설정
            try:
                inputs = await page.query_selector_all("input[type='text'], input[type='date']")
                print(f"      입력 필드 수: {len(inputs)}")
                for inp in inputs:
                    placeholder = await inp.get_attribute("placeholder") or ""
                    name = await inp.get_attribute("name") or ""
                    if "date" in name.lower() or "dt" in name.lower() or "일" in placeholder:
                        await inp.fill(date)
                        print(f"      날짜 입력: {name or placeholder}")
                        break
                # 조회 버튼 클릭 시도
                buttons = await page.query_selector_all("button, input[type='button'], input[type='submit']")
                for btn in buttons[:5]:
                    text = await btn.inner_text()
                    if "조회" in text or "검색" in text or "search" in text.lower():
                        await btn.click()
                        await page.wait_for_timeout(3000)
                        print(f"      버튼 클릭: {text}")
                        break
            except Exception as e:
                print(f"      수동 입력 오류: {e}")

        await browser.close()

        if not captured_bodies:
            return pd.DataFrame()

        return _parse_xml_to_df(captured_bodies[-1], date)


def get_govbond_rate_playwright(date: str, headless: bool = True) -> pd.DataFrame:
    """
    Playwright 네트워크 인터셉트로 KOFIA 국고채권 금리 조회.

    Parameters
    ----------
    date     : 'YYYYMMDD' 형식 (예: '20260731')
    headless : True=창 없이, False=브라우저 창 표시 (디버깅용)
    """
    return asyncio.run(_intercept_fetch(date, headless=headless))


def get_govbond_rate_multi_playwright(dates: list[str], headless: bool = True) -> pd.DataFrame:
    """여러 날짜 일괄 조회."""
    frames = []
    for d in dates:
        print(f"\n=== {d} 조회 중 ===")
        df = get_govbond_rate_playwright(d, headless=headless)
        if not df.empty:
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── 직접 실행 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TARGET_DATE = "20260731"
    print(f"=== KOFIA 국고채권 금리 조회 (Playwright 인터셉트): {TARGET_DATE} ===\n")

    df = get_govbond_rate_playwright(TARGET_DATE, headless=True)

    if not df.empty:
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 200)
        print("\n[결과]")
        print(df.to_string(index=False))
        out_path = f"kofia_govbond_{TARGET_DATE}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"\n[저장 완료] {out_path}")
    else:
        print("\n데이터를 가져오지 못했습니다.")
        print("조치: headless=False 로 실행해서 브라우저에서 직접 확인해 보세요.")
        print("  df = get_govbond_rate_playwright('20260731', headless=False)")
