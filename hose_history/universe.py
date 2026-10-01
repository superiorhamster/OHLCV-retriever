"""Evidence-backed universe discovery; completeness is deliberately not assumed."""
import hashlib
import io
import logging
import re
from pathlib import Path

import httpx
import pandas as pd
import pdfplumber

from .providers import KBSProvider, VCIProvider
from .schema import parse_date
from .storage import atomic_parquet
from .transport import ProviderError, atomic_json

log = logging.getLogger(__name__)
REPORTS = [
    (2020, "https://staticfile.hsx.vn/Uploads/UploadDocuments/1641898/Bao%20cao%20thuong%20nien%2020200.pdf"),
    (2022, "https://staticfile.hsx.vn/Uploads/UploadDocuments/1641900/Bao%20cao%20thuong%20nien%202022_tv.pdf"),
    (2023, "https://staticfile.hsx.vn/Uploads/UploadDocuments/1896430/B%C3%A1o%20c%C3%A1o%20th%C6%B0%E1%BB%9Dng%20ni%C3%AAn%202023.pdf"),
    (2024, "https://staticfile.hsx.vn/Uploads/UploadDocuments/1896445/B%C3%81O%20C%C3%81O%20TH%C6%AF%E1%BB%9CNG%20NI%C3%8AN%20%28ANUAL%20REPORT%29%202024.pdf"),
]


def extract_delistings(text, year, url, page):
    """Only parse explicitly delisted-company sections, never warrants/funds."""
    heading = re.search(r"DANH SÁCH HỦY NIÊM YẾT(?: NĂM)?\s*" + str(year), text, re.I)
    if not heading:
        return []
    block = text[heading.end():]
    stop = re.search(r"DANH SÁCH (?:NIÊM YẾT MỚI|CÁC|CHỨNG|CÔNG TY)", block, re.I)
    if stop:
        block = block[:stop.start()]
    records = []
    for line in block.splitlines():
        # Row numbers, ticker and a date must share a row; ambiguous layouts are reported.
        match = re.match(r"\s*\d+\s+([A-Z][A-Z0-9]{2})\s+(.+?)\s+(\d{1,2}/\d{1,2}/\d{4})\b", line)
        if not match:
            continue
        symbol, name, day = match.groups()
        try:
            parsed = parse_date(day)
        except ValueError:
            continue
        if parsed.year != year:
            continue
        records.append({"symbol": symbol, "company_name": name.strip(), "exchange": "HOSE",
            "listing_date": None, "delisting_date": str(parsed), "status": "historical",
            "previous_symbol": None, "source": "hose_annual_report", "evidence_url": url,
            "evidence_page": page, "evidence_text": line, "report_year": year})
    return records


def discover_universe(transport, config, store, *, refresh=False, evidence_file=None):
    path = config.data_dir / "metadata" / "symbols.parquet"
    if path.exists() and not refresh and evidence_file is None:
        return pd.read_parquet(path)
    observations = []
    for cls in (KBSProvider, VCIProvider):
        try:
            observations.extend(cls(transport, config).get_symbols())
        except (ProviderError, KeyError, TypeError) as exc:
            store.report("universe_issues", [{"source": cls.name, "error": str(exc)}])
    if not observations:
        if path.exists():
            log.warning("Listing endpoints failed; using saved universe snapshot")
            return pd.read_parquet(path)
        raise ProviderError("Cannot discover any current symbols")
    listed = pd.DataFrame(observations).drop_duplicates("symbol", keep="first")
    current = listed[listed.exchange == "HOSE"].copy()
    current["evidence_url"] = current.source.map({"kbs": "https://kbbuddywts.kbsec.com.vn/iis-server/investment/stock/search/data",
        "vci": "https://trading.vietcap.com.vn/api/price/symbols/getAll"})
    atomic_parquet(pd.DataFrame(observations), config.data_dir / "metadata" / "listing_observations.parquet")
    historical, report_manifest = [], []
    # Small sourced extraction snapshot, not a manually invented ticker universe.
    # Read successfully from PDF page 47 (printed page 97) on 2026-09-26 before
    # later requests were rejected. Preserve this evidence when the archive is offline.
    snapshot = Path(__file__).parent / "resources" / "hose_2023_delistings.txt"
    snapshot_text = snapshot.read_text(encoding="utf-8")
    historical.extend(extract_delistings(snapshot_text, 2023, REPORTS[2][1], 47))
    report_manifest.append({"year": 2023, "url": REPORTS[2][1], "status": "bundled_verified_extraction",
        "evidence_page": 47, "extracted_rows": 13, "observed_at": "2026-09-26",
        "extraction_sha256": hashlib.sha256(snapshot_text.encode()).hexdigest()})
    for year, url in REPORTS:
        pdf = config.data_dir / "raw" / "metadata" / f"hose_annual_{year}.pdf"
        try:
            if pdf.exists():
                content = pdf.read_bytes()
            else:
                response = transport.client.get(url, timeout=config.request_timeout)
                response.raise_for_status()
                content = response.content
                if not content.startswith(b"%PDF"):
                    atomic_json(config.data_dir / "raw" / "metadata" / f"hose_annual_{year}.error.json",
                        {"url": url, "status": response.status_code, "body": response.text,
                         "observed_at": config.end})
                    raise ValueError("Source did not return a PDF")
                pdf.parent.mkdir(parents=True, exist_ok=True)
                pdf.write_bytes(content)
            found, headings = [], 0
            with pdfplumber.open(io.BytesIO(content)) as doc:
                for n, page in enumerate(doc.pages, 1):
                    # Annual reports often put two printed pages on one PDF page.
                    # Crop before extracting so fund rows cannot interleave with delistings.
                    sections = [page]
                    if page.width > 1.3 * page.height:
                        sections = [page.crop((0, 0, page.width / 2, page.height)),
                                    page.crop((page.width / 2, 0, page.width, page.height))]
                    for section in sections:
                        text = section.extract_text() or ""
                        if re.search(r"DANH SÁCH HỦY NIÊM YẾT", text, re.I):
                            headings += 1
                            found.extend(extract_delistings(text, year, url, n))
            historical.extend(found)
            report_manifest.append({"year": year, "url": url, "sha256": hashlib.sha256(content).hexdigest(),
                                    "delisting_sections": headings, "extracted_rows": len(found),
                                    "status": "partial_extraction" if found else "unparsed"})
            if not found:
                store.report("universe_issues", [{"source": url, "error": "No confidently parsed delisting rows; report coverage incomplete"}])
        except (httpx.HTTPError, ValueError, OSError) as exc:
            store.report("universe_issues", [{"source": url, "error": str(exc)}])
            report_manifest.append({"year": year, "url": url, "status": "failed"})
    if evidence_file:
        evidence = pd.read_parquet(evidence_file) if str(evidence_file).endswith(".parquet") else pd.read_csv(evidence_file)
        required = {"symbol", "exchange", "evidence_url"}
        if not required <= set(evidence) or evidence[list(required)].isna().any().any():
            raise ValueError("Universe evidence requires symbol, exchange, evidence_url")
        historical.extend(evidence[evidence.exchange.isin(["HOSE", "HSX"])].assign(status="historical").to_dict("records"))
    # Never lose previously discovered delisted securities on a refresh.
    if path.exists():
        previous = pd.read_parquet(path)
        historical.extend(previous[~previous.symbol.isin(current.symbol)].assign(status="historical").to_dict("records"))
    evidence = pd.DataFrame(historical).drop_duplicates(["symbol", "delisting_date", "source"]) if historical else pd.DataFrame()
    if not evidence.empty:
        atomic_parquet(evidence, config.data_dir / "metadata" / "historical_evidence.parquet")
    universe = pd.concat([current, evidence], ignore_index=True).drop_duplicates("symbol", keep="first")
    for c in ["listing_date", "delisting_date", "previous_symbol"]:
        if c not in universe:
            universe[c] = None
    universe["security_id"] = "unresolved:" + universe.symbol
    universe["observed_at"] = config.end
    universe["membership_confidence"] = "current_snapshot_only"
    universe.loc[universe.status != "current", "membership_confidence"] = "historical_evidence_partial"
    atomic_parquet(universe, path)
    memberships = universe[["symbol", "security_id", "exchange", "listing_date", "delisting_date", "evidence_url", "membership_confidence"]].copy()
    memberships = memberships.rename(columns={"listing_date": "valid_from", "delisting_date": "valid_until"})
    atomic_parquet(memberships, config.data_dir / "metadata" / "exchange_memberships.parquet")
    aliases_path = config.data_dir / "metadata" / "aliases.parquet"
    alias_cols = ["security_id", "symbol", "previous_symbol", "valid_from", "valid_until", "evidence_url"]
    aliases = universe[universe.previous_symbol.notna()][["security_id", "symbol", "previous_symbol", "evidence_url"]].copy()
    aliases["valid_from"], aliases["valid_until"] = None, None
    if aliases_path.exists():
        aliases = pd.concat([pd.read_parquet(aliases_path), aliases], ignore_index=True).drop_duplicates()
    atomic_parquet(aliases.reindex(columns=alias_cols), aliases_path)
    atomic_json(config.data_dir / "metadata" / "universe_manifest.json", {
        "historical_universe_complete": False, "observed_at": config.end, "reports": report_manifest,
        "uncovered_report_years": sorted(set(range(2000, int(config.end[:4]) + 1)) - {y for y, _ in REPORTS}),
        "limitations": ["Historical report coverage is partial", "Ticker reuse and rename identity unresolved unless evidenced",
                        "Current exchange snapshots do not establish historical membership intervals"]})
    return universe
