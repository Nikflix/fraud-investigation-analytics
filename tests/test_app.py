from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from fraud_analytics.ingestion.paysim import load_paysim


ROOT = Path(__file__).resolve().parents[1]


def test_overview_filters_and_empty_selection(tmp_path, monkeypatch):
    database = tmp_path / "paysim.duckdb"
    load_paysim(ROOT / "data/sample/paysim.csv", database)
    monkeypatch.setenv("FRAUD_DATABASE_PATH", str(database))
    app = AppTest.from_file(ROOT / "app/overview.py", default_timeout=30).run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["6", "10.105M", "3", "1"]
    assert len(app.dataframe[0].value) == 6
    app.selectbox[0].select("Fraud labelled")
    app.button[0].click().run()
    assert not app.exception
    assert app.metric[0].value == "3"
    assert set(app.dataframe[0].value["is_fraud"]) == {"Fraud labelled"}
    app.selectbox[0].select("All labels")
    app.text_input[0].set_value("C001")
    app.button[0].click().run()
    assert not app.exception
    assert app.metric[0].value == "2"
    app.multiselect[0].set_value([])
    app.button[0].click().run()
    assert not app.exception
    assert app.metric[0].value == "0"
    assert "No transactions match" in app.info[0].value


def test_filter_change_resets_page(tmp_path, monkeypatch):
    header, *rows = (ROOT / "data/sample/paysim.csv").read_text().splitlines()
    source = tmp_path / "pagination.csv"
    source.write_text("\n".join([header, *(rows * 25)]) + "\n")
    database = tmp_path / "paysim.duckdb"
    load_paysim(source, database)
    monkeypatch.setenv("FRAUD_DATABASE_PATH", str(database))
    app = AppTest.from_file(ROOT / "app/overview.py", default_timeout=30).run()
    app.number_input[0].set_value(2).run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 50
    app.selectbox[0].select("Fraud labelled")
    app.button[0].click().run()
    assert not app.exception
    assert app.number_input[0].value == 1
    assert app.metric[0].value == "75"
    assert len(app.dataframe[0].value) == 75


def test_missing_database_shows_setup_instructions(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_DATABASE_PATH", str(tmp_path / "missing.duckdb"))
    app = AppTest.from_file(ROOT / "app/overview.py", default_timeout=30).run()
    assert not app.exception
    assert "Load a PaySim" in app.info[0].value
