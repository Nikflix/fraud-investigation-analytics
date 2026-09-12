from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("sklearn")
from streamlit.testing.v1 import AppTest

from fraud_analytics.ingestion.paysim import load_paysim


ROOT = Path(__file__).resolve().parents[1]


def by_label(elements, label):
    return next(element for element in elements if element.label == label)


def data_overview():
    app = AppTest.from_file(ROOT / "app/overview.py", default_timeout=30).run()
    by_label(app.radio, "Workspace").set_value("Data overview").run()
    return app


def test_overview_filters_and_empty_selection(tmp_path, monkeypatch):
    database = tmp_path / "paysim.duckdb"
    load_paysim(ROOT / "data/sample/paysim.csv", database)
    monkeypatch.setenv("FRAUD_DATABASE_PATH", str(database))
    app = data_overview()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["6", "10.105M", "3", "1"]
    assert len(app.dataframe[0].value) == 6
    by_label(app.selectbox, "Dataset label").select("Fraud labelled")
    app.button[0].click().run()
    assert not app.exception
    assert app.metric[0].value == "3"
    assert set(app.dataframe[0].value["is_fraud"]) == {"Fraud labelled"}
    by_label(app.selectbox, "Dataset label").select("All labels")
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
    app = data_overview()
    app.number_input[0].set_value(2).run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 50
    by_label(app.selectbox, "Dataset label").select("Fraud labelled")
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


def test_build_queue_review_and_score_new_inputs(make_detection_database, monkeypatch):
    database = make_detection_database()
    monkeypatch.setenv("FRAUD_DATABASE_PATH", str(database))
    app = AppTest.from_file(ROOT / "app/overview.py", default_timeout=30).run()
    by_label(app.button, "Build review queue").click().run()
    assert not app.exception and not app.error
    assert by_label(app.metric, "Scored transactions").value == "180"
    by_label(app.selectbox, "Queue").select("All scored transactions").run()
    by_label(app.number_input, "Queue page").set_value(2).run()
    queue = next(frame.value for frame in app.dataframe if "review_status" in frame.value.columns)
    assert len(queue) == 80
    selected_row = by_label(app.selectbox, "Inspect transaction").value
    by_label(app.selectbox, "Review status").select("In review")
    by_label(app.text_area, "Review note").set_value("Checking this amount against the source balance.")
    by_label(app.button, "Save review").click().run()
    assert not app.exception and not app.error
    assert any("Review saved" in item.value for item in app.success)
    by_label(app.selectbox, "Status filter").select("In review").run()
    assert by_label(app.number_input, "Queue page").value == 1
    assert by_label(app.selectbox, "Inspect transaction").value == selected_row
    assert by_label(app.text_area, "Review note").value == "Checking this amount against the source balance."

    # A fresh session must read the saved status and note, rather than session-only state.
    app = AppTest.from_file(ROOT / "app/overview.py", default_timeout=30).run()
    by_label(app.selectbox, "Queue").select("All scored transactions").run()
    by_label(app.selectbox, "Status filter").select("In review").run()
    assert by_label(app.selectbox, "Review status").value == "In review"
    assert by_label(app.text_area, "Review note").value == "Checking this amount against the source balance."
    by_label(app.radio, "Workspace").set_value("Try a transaction").run()
    by_label(app.text_input, "Amount").set_value("100.00")
    by_label(app.button, "Score transaction").click().run()
    initial_score = by_label(app.metric, "Model score").value
    by_label(app.text_input, "Amount").set_value("950.00")
    by_label(app.button, "Score transaction").click().run()
    assert not app.exception and not app.error
    assert by_label(app.metric, "Model score").value != initial_score
    by_label(app.text_input, "Amount").set_value("1.001")
    by_label(app.button, "Score transaction").click().run()
    assert not app.exception
    assert "two decimal places" in app.error[0].value
    assert not app.metric


def test_demo_banner_and_switch_to_full_import(tmp_path, make_detection_database, monkeypatch):
    import shutil

    full = make_detection_database()
    folder = tmp_path / "data/processed"
    folder.mkdir(parents=True)
    selected = folder / "full.duckdb"
    shutil.copyfile(full, selected)
    demo = folder / "demo.duckdb"
    load_paysim(ROOT / "data/sample/paysim.csv", demo)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FRAUD_DATABASE_PATH", str(demo))
    app = AppTest.from_file(ROOT / "app/overview.py", default_timeout=30).run()
    assert any("Demo dataset" in item.value for item in app.warning)
    assert by_label(app.button, "Build review queue").disabled
    by_label(app.selectbox, "Dataset").set_value(selected).run()
    assert not app.exception and not app.error
    assert not any("Demo dataset" in item.value for item in app.warning)
    assert not by_label(app.button, "Build review queue").disabled
