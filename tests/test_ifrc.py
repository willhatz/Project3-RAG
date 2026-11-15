from ingest import ifrc
from ingest.config import Source

EVENT = {
    "id": 7713,
    "name": "Sri Lanka - Tropical Cyclone Ditwah, 2025 ",
    "summary": "<p>Cyclone Ditwah made landfall.</p><ul><li>Heavy rain</li><li>Landslides</li></ul>",
    "updated_at": "2026-02-12T08:43:54Z",
    "field_reports": [
        {"id": 18014, "report_date": "2025-11-28T00:00:00Z", "summary": "Situation update",
         "description": "<p>56 confirmed deaths.</p>", "num_dead": 56, "num_displaced": 1575, "num_missing": None},
        {"id": 1, "report_date": "2025-11-20T00:00:00Z", "summary": "", "description": ""},  # empty -> skipped
    ],
    "appeals": [],
}


def _source():
    return Source(id="ifrc_ditwah", method="ifrc_go", region="sri_lanka", event="cyclone_ditwah",
                  options={"event_id": 7713})


def test_parse_event_builds_overview_and_field_reports():
    docs = ifrc.parse_event(EVENT, _source())
    assert len(docs) == 2

    overview, report = docs
    assert overview.url == "https://go.ifrc.org/emergencies/7713"
    assert overview.title == "Sri Lanka - Tropical Cyclone Ditwah, 2025 - IFRC emergency overview"
    assert overview.published == "2026-02-12"
    assert "- Heavy rain" in overview.text and "<" not in overview.text

    assert report.url == "https://go.ifrc.org/field-reports/18014"
    assert report.published == "2025-11-28"
    assert "Dead: 56" in report.text and "Displaced: 1,575" in report.text
    assert "Missing" not in report.text  # None figures are omitted
    assert report.method == "ifrc_go" and report.language == "en"
