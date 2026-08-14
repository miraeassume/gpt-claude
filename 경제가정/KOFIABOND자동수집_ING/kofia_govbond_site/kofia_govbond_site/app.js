const MATURITY_MAP = {
  val1: "1M", val2: "3M", val3: "6M", val4: "1Y", val5: "1.5Y",
  val6: "2Y", val7: "2.5Y", val8: "3Y", val9: "4Y", val10: "5Y",
  val11: "7Y", val12: "10Y", val13: "15Y", val14: "20Y", val15: "30Y"
};

const sampleByDate = {
  "20260615": { 기준일: "20260615", "1M": 2.668, "3M": 2.781, "6M": 2.946, "1Y": 3.157, "1.5Y": null, "2Y": 3.538, "2.5Y": null, "3Y": 3.742, "4Y": null, "5Y": 3.928, "7Y": null, "10Y": 4.070, "15Y": null, "20Y": 4.089, "30Y": 4.001 }
};

function toYyyymmdd(dateValue) {
  return dateValue.replaceAll("-", "");
}

function buildXml(date) {
  return `<?xml version="1.0" encoding="utf-8"?>
<message>
  <proframeHeader>
    <pfmAppName>BIS-KOFIABOND</pfmAppName>
    <pfmSvcName>BISSrtPrcEstMtrxWhtAvgSrchSO</pfmSvcName>
    <pfmFnName>selectList</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
  <BISSrtPrcEstMtrxWhtAvgDTO>
    <standardDt>${date}</standardDt>
    <applyGbCd>C00</applyGbCd>
    <val20>1</val20>
  </BISSrtPrcEstMtrxWhtAvgDTO>
</message>`;
}

function getCurrentRow() {
  const date = toYyyymmdd(document.getElementById("standardDate").value);
  const base = sampleByDate["20260615"];
  return { ...base, 기준일: date };
}

function renderTable(row) {
  const columns = ["기준일", ...Object.values(MATURITY_MAP)];
  const thead = document.querySelector("#rateTable thead");
  const tbody = document.querySelector("#rateTable tbody");
  thead.innerHTML = `<tr>${columns.map(c => `<th>${c}</th>`).join("")}</tr>`;
  tbody.innerHTML = `<tr>${columns.map(c => `<td>${row[c] ?? "-"}</td>`).join("")}</tr>`;
}

function renderCurve(row) {
  const curve = document.getElementById("curve");
  const maturities = Object.values(MATURITY_MAP);
  const values = maturities.map(m => row[m]).filter(v => typeof v === "number");
  const max = Math.max(...values);
  curve.innerHTML = maturities.map(m => {
    const value = row[m];
    const height = value ? Math.max(8, Math.round((value / max) * 185)) : 0;
    return `<div class="bar-wrap">
      <div class="bar-value">${value ?? "-"}</div>
      <div class="bar" style="height:${height}px"></div>
      <div class="bar-label">${m}</div>
    </div>`;
  }).join("");
}

function renderMapping() {
  const grid = document.getElementById("mappingGrid");
  grid.innerHTML = Object.entries(MATURITY_MAP).map(([key, value]) =>
    `<div class="mapping-item"><strong>${key}</strong><span>${value}</span></div>`
  ).join("");
}

function downloadCsv(row) {
  const columns = ["기준일", ...Object.values(MATURITY_MAP)];
  const csv = [columns.join(","), columns.map(c => row[c] ?? "").join(",")].join("\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `kofia_govbond_rate_${row.기준일}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function refresh() {
  const row = getCurrentRow();
  document.getElementById("status").textContent = `${row.기준일} 샘플 데이터`;
  document.getElementById("xmlCode").textContent = buildXml(row.기준일);
  renderTable(row);
  renderCurve(row);
}

document.getElementById("queryBtn").addEventListener("click", refresh);
document.getElementById("xmlBtn").addEventListener("click", () => {
  document.getElementById("xmlPanel").classList.toggle("hidden");
  refresh();
});
document.getElementById("csvBtn").addEventListener("click", () => downloadCsv(getCurrentRow()));
document.getElementById("copyXmlBtn").addEventListener("click", async () => {
  await navigator.clipboard.writeText(document.getElementById("xmlCode").textContent);
  document.getElementById("copyXmlBtn").textContent = "복사됨";
  setTimeout(() => document.getElementById("copyXmlBtn").textContent = "복사", 1200);
});

renderMapping();
refresh();
