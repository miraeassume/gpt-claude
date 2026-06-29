# KOFIA 국고채권 금리 수집 가이드

**대상 사이트:** [금융투자협회 채권정보센터](https://www.kofiabond.or.kr/)  
**데이터:** 채권금리 > 가중평균수익률 > 시가평가 가중평균수익률 (국고채권)  
**작성일:** 2026-06-15

---

## 1. API 엔드포인트 정보

| 항목 | 값 |
|------|-----|
| URL | `https://www.kofiabond.or.kr/XMLSERVICES/` |
| Method | POST |
| Content-Type | `application/xml; charset=utf-8` |
| pfmAppName | `BIS-KOFIABOND` |
| pfmSvcName | `BISSrtPrcEstMtrxWhtAvgSrchSO` |
| pfmFnName | `selectList` |

---

## 2. 요청 XML (Request Payload)

```xml
<?xml version="1.0" encoding="utf-8"?>
<message>
  <proframeHeader>
    <pfmAppName>BIS-KOFIABOND</pfmAppName>
    <pfmSvcName>BISSrtPrcEstMtrxWhtAvgSrchSO</pfmSvcName>
    <pfmFnName>selectList</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
  <BISSrtPrcEstMtrxWhtAvgDTO>
    <standardDt>20260615</standardDt>  <!-- 조회 날짜: YYYYMMDD -->
    <applyGbCd>C00</applyGbCd>
    <val20>1</val20>
  </BISSrtPrcEstMtrxWhtAvgDTO>
</message>
```

---

## 3. 응답 구조 (Response)

- 루트 태그: `BISSrtPrcEstMtrxWhtAvgListDTO`
- 반복 태그: `BISSrtPrcEstMtrxWhtAvgDTO` (총 43건, 채권 종류별)
- **국고채권 필터 조건:** `typeNmMrk == "국고채권"`

### 주요 필드

| 필드명 | 설명 |
|--------|------|
| `largeCategoryMrk` | 대분류 (예: 국채) |
| `typeNmMrk` | 채권 종류 (예: 국고채권) |
| `creditRnkMrk` | 신용등급 (예: 양곡,외평,재정) |
| `val1` ~ `val15` | 잔존만기별 수익률 |

### 만기 매핑 (val1 ~ val15)

| 필드 | 만기 | 필드 | 만기 | 필드 | 만기 |
|------|------|------|------|------|------|
| val1 | 1M | val6 | 2Y | val11 | 7Y |
| val2 | 3M | val7 | 2.5Y | val12 | 10Y |
| val3 | 6M | val8 | 3Y | val13 | 15Y |
| val4 | 1Y | val9 | 4Y | val14 | 20Y |
| val5 | 1.5Y | val10 | 5Y | val15 | 30Y |

---

## 4. Python 코드

```python
import requests
import xml.etree.ElementTree as ET
import pandas as pd

# val1~val15 → 잔존만기 매핑
MATURITY_MAP = {
    "val1": "1M", "val2": "3M", "val3": "6M",
    "val4": "1Y", "val5": "1.5Y", "val6": "2Y",
    "val7": "2.5Y", "val8": "3Y", "val9": "4Y",
    "val10": "5Y", "val11": "7Y", "val12": "10Y",
    "val13": "15Y", "val14": "20Y", "val15": "30Y"
}

def get_govbond_rate(date: str) -> pd.DataFrame:
    """
    국고채권 시가평가 가중평균수익률 조회
    date: 'YYYYMMDD' (예: '20260615')
    """
    url = "https://www.kofiabond.or.kr/XMLSERVICES/"

    payload = f"""<?xml version="1.0" encoding="utf-8"?>
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

    headers = {
        "Content-Type": "application/xml; charset=utf-8",
        "Referer": "https://www.kofiabond.or.kr/",
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.post(url, data=payload.encode("utf-8"), headers=headers)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    records = []
    for item in root.iter("BISSrtPrcEstMtrxWhtAvgDTO"):
        d = {child.tag: child.text for child in item}
        records.append(d)

    df = pd.DataFrame(records)

    # 국고채권만 필터링
    df_gov = df[df["typeNmMrk"] == "국고채권"].copy()

    # 만기별 컬럼으로 변환
    result = {"기준일": date}
    for val_col, maturity in MATURITY_MAP.items():
        val = df_gov[val_col].values[0] if not df_gov.empty else None
        result[maturity] = float(val) if val and val != "0" else None

    return pd.DataFrame([result])


# 단일 날짜 조회
df = get_govbond_rate("20260615")
print(df.to_string(index=False))

# 여러 날짜 조회 (예: 최근 5 영업일)
dates = ["20260609", "20260610", "20260611", "20260612", "20260615"]
df_all = pd.concat([get_govbond_rate(d) for d in dates], ignore_index=True)
print(df_all.to_string(index=False))
```

---

## 5. 샘플 출력 (2026-06-15 기준)

| 기준일 | 1M | 3M | 6M | 1Y | 2Y | 3Y | 5Y | 10Y | 20Y | 30Y |
|--------|-----|-----|-----|-----|-----|-----|-----|------|------|------|
| 20260615 | 2.668 | 2.781 | 2.946 | 3.157 | 3.538 | 3.742 | 3.928 | 4.070 | 4.089 | 4.001 |

---

## 6. 참고 사항

- **0 값 처리:** 해당 만기에 거래가 없으면 `0`으로 반환됨 → 코드에서 `None`으로 변환
- **휴일 조회:** 영업일이 아닌 날짜는 데이터 없음 (빈 응답 또는 전일 데이터)
- **applyGbCd:** `C00` = 수익률 기준 (변경 불필요)
- **사내 인트라넷 환경:** 외부 URL 접근 가능 여부 사전 확인 필요
