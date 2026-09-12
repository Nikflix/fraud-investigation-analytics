# Open the application on Windows

The Streamlit dashboard opens in your browser and reads a DuckDB file on your computer. Python installs both tools as project dependencies. You do not need to open MySQL Workbench.

## Update an existing installation

Stop the running app with **Ctrl+C**. In PowerShell, from your existing project folder:

```powershell
git pull
.\.venv\Scripts\python.exe -m pip install -e ".[dev,app]"
$env:FRAUD_DATABASE_PATH = "data/processed/paysim.duckdb"
.\.venv\Scripts\python.exe -m streamlit run app/overview.py
```

In **Dataset**, select the full database showing **6,362,620 records**. Open **Review queue** and click **Build review queue**. If only the six-record demo is available, follow step 4 below to import your full ZIP first.

Git updates the code. Your database and fitted model stay on your computer, so the first analysis must run locally. Reopening the app after analysis loads the saved model and reviews.

## 1. Get the code

Install Python 3.12 or newer and Git if needed. Open PowerShell in the folder where you keep projects:

```powershell
git clone https://github.com/Nikflix/fraud-investigation-analytics.git
cd fraud-investigation-analytics
```

If you already cloned the repository, open that project folder and run `git pull`.

## 2. Install the project

Run these commands from the repository root:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,app]"
```

If Windows cannot find `python`, try `py` for the first two commands. Check that the reported version is at least 3.12. Calling the environment's Python directly avoids changing PowerShell execution policy.

## 3. Open a small demo

```powershell
.\.venv\Scripts\python.exe -m fraud_analytics ingest-paysim data/sample/paysim.csv --database data/processed/paysim-demo.duckdb
$env:FRAUD_DATABASE_PATH = "data/processed/paysim-demo.duckdb"
.\.venv\Scripts\python.exe -m streamlit run app/overview.py
```

Streamlit should open your browser. If it does not, open the **Local URL** printed in PowerShell, normally [http://localhost:8501](http://localhost:8501). That address works on your computer after the command starts. Keep PowerShell open; Ctrl+C stops the app.

The demo contains **six hand-written test records**, including three fraud labels and one existing-rule flag. It is for checking the interface and does not represent the full dataset.

Choose **Data overview** under **Workspace**, use the sidebar filters, and click **Apply filters**. Try account `C099` to see three appearances, or `C001` to see two. An empty transaction-type selection returns no matches. Model training is disabled for this tiny fixture.

## 4. Load your full PaySim ZIP

Stop the app with Ctrl+C. If your uploaded file is in Downloads, use:

```powershell
.\.venv\Scripts\python.exe -m fraud_analytics ingest-paysim "$env:USERPROFILE\Downloads\archive (4).zip"
.\.venv\Scripts\python.exe -m fraud_analytics profile-paysim
$env:FRAUD_DATABASE_PATH = "data/processed/paysim.duckdb"
.\.venv\Scripts\python.exe -m streamlit run app/overview.py
```

Change the ZIP path if you saved it elsewhere. If the file is named `archive (4)(1).zip`, use that exact filename in the command. Keep the quotes around paths with spaces. An extracted `.csv` works with the same command. The ZIP must contain exactly one CSV with the [PaySim headers](paysim.md).

The import creates `data/processed/paysim.duckdb`, separate from the demo database. It copies the CSV to temporary storage, validates all records, then commits the complete snapshot. Allow disk space for the expanded CSV, staging data, and final database; the full import takes longer than the demo.

The recorded profile for the supplied dataset has **6,362,620 transactions**, **8,213 supplied fraud labels**, and **16 supplied existing-rule flags**. Your app reads the loaded file; it does not use hard-coded totals.

Reimporting the identical CSV reports `"already_loaded": true` and inserts zero rows. A different CSV is refused in an occupied database. Choose another `--database` path and set `FRAUD_DATABASE_PATH` to that same path for a separate snapshot.

## 5. Build and use the review queue

Select the full dataset in the app, open **Review queue**, and click **Build review queue**. Progress messages show training, threshold selection, test scoring, and saving. Keep the app running until the queue is ready. Training uses several million rows in memory and takes longer than opening the overview.

For the supplied CSV, the finished view shows **918,617 scored transactions**, **11,316 model alerts**, and **182,750 rule alerts**. The queue covers later test hours 379–743; earlier records were used for training and validation. The **Measured performance** expander explains the evaluation.

Choose **Model alerts**, **Rule alerts**, or **All scored transactions**. Select a transaction under **Inspect transaction** to see its score, rule reasons, model factors, and earlier account activity. Enter a note, choose **New**, **In review**, or **Closed**, and click **Save review**. The status and timestamped history are saved in your DuckDB file.

For a fresh calculation, open **Try a transaction**:

1. Select **TRANSFER**, enter amount `10.00` and source balance `1000.00`, then click **Score transaction**.
2. Change the amount to `900.00` and score again.
3. The score changes, and the second input triggers the rule for requesting at least 80% of the source balance. On the recorded baseline, both examples remain below the model alert threshold; model and rule results are independent.

This form checks entered values with the saved model. It does not ingest a live feed. Supplied labels can be revealed separately for learning; saving a review does not change them or retrain the model.

For command-line analysis, stop Streamlit first and run:

```powershell
.\.venv\Scripts\python.exe -m fraud_analytics analyze-paysim --database data/processed/paysim.duckdb --config configs/detection.toml
.\.venv\Scripts\python.exe -m streamlit run app/overview.py
```

Repeating the same analysis returns `"reused": true` and retains reviews. If you deliberately change `configs/detection.toml`, rerun the CLI analysis to create a separate saved run. The app displays the most recently created run for the selected dataset. See the [model card](model-card.md) before comparing experiments.

## SQL and tests

To query PaySim directly, start Python:

```powershell
.\.venv\Scripts\python.exe
```

At the `>>>` prompt:

```python
import duckdb

with duckdb.connect("data/processed/paysim.duckdb", read_only=True) as con:
    con.sql("""
        SELECT transaction_type, count(*) AS transactions,
               count_if(is_fraud) AS fraud_labels, sum(amount) AS recorded_amount
        FROM paysim_transactions
        GROUP BY transaction_type
        ORDER BY transaction_type
    """).show()
exit()
```

Run tests from PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Tests use temporary databases and small fixtures. They do not change your local dataset.

## If something does not open

| Symptom | What to check |
| --- | --- |
| `No module named streamlit`, `sklearn`, or `fraud_analytics` | Rerun the installation command using the same `.venv` Python. |
| The app asks you to load PaySim | Check the import succeeded and `FRAUD_DATABASE_PATH` points to that database. |
| Only six transactions appear | The demo database is selected. Import the full ZIP in step 4, then select its database in the sidebar. |
| Only the old charts appear | Stop the app, run the update commands above, and restart it from the updated project folder. The new sidebar has a Workspace selector. |
| File not found | Check the quoted ZIP path, filename, and current project folder. |
| Database file-lock error | Stop the app and close Python sessions using that file before importing or running CLI analysis. |
| Another snapshot is already loaded | Use a new database path; the loader deliberately preserves the existing snapshot. |
| Browser cannot connect | Keep the Streamlit command running and use the Local URL it prints. GitHub stores the code; it does not run this Python app. |

See the [DuckDB Python documentation](https://duckdb.org/docs/current/clients/python/overview) and [Streamlit run documentation](https://docs.streamlit.io/develop/api-reference/cli/run) for the underlying tools.
