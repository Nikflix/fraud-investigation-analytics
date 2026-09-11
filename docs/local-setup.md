# Open the application on Windows

The Streamlit dashboard opens in your browser and reads a DuckDB file on your computer. Python installs both tools as project dependencies. You do not need to open MySQL Workbench.

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

Use the sidebar and click **Apply filters**. Try account `C099` to see three appearances, or `C001` to see two. An empty transaction-type selection returns no matches.

## 4. Load your full PaySim ZIP

Stop the app with Ctrl+C. If your uploaded file is in Downloads, use:

```powershell
.\.venv\Scripts\python.exe -m fraud_analytics ingest-paysim "$env:USERPROFILE\Downloads\archive (4).zip"
.\.venv\Scripts\python.exe -m fraud_analytics profile-paysim
$env:FRAUD_DATABASE_PATH = "data/processed/paysim.duckdb"
.\.venv\Scripts\python.exe -m streamlit run app/overview.py
```

Change the ZIP path if you saved it elsewhere. Keep the quotes around paths with spaces. An extracted `.csv` works with the same command. The ZIP must contain exactly one CSV with the [PaySim headers](paysim.md).

The import creates `data/processed/paysim.duckdb`, separate from the demo database. It copies the CSV to temporary storage, validates all records, then commits the complete snapshot. Allow disk space for the expanded CSV, staging data, and final database; the full import takes longer than the demo.

The recorded profile for the supplied dataset has **6,362,620 transactions**, **8,213 supplied fraud labels**, and **16 supplied existing-rule flags**. Your app reads the loaded file; it does not use hard-coded totals.

Reimporting the identical CSV reports `"already_loaded": true` and inserts zero rows. A different CSV is refused in an occupied database. Choose another `--database` path and set `FRAUD_DATABASE_PATH` to that same path for a separate snapshot.

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
| `No module named streamlit` or `fraud_analytics` | Rerun the installation command using the same `.venv` Python. |
| The app asks you to load PaySim | Check the import succeeded and `FRAUD_DATABASE_PATH` points to that database. |
| Only six transactions appear | The demo database is selected. Follow step 4 to switch to the full dataset. |
| File not found | Check the quoted ZIP path, filename, and current project folder. |
| Database file-lock error | Stop the app and close Python sessions using that file before importing. |
| Another snapshot is already loaded | Use a new database path; the loader deliberately preserves the existing snapshot. |
| Browser cannot connect | Keep the Streamlit command running and use the Local URL it prints. GitHub stores the code; it does not run this Python app. |

See the [DuckDB Python documentation](https://duckdb.org/docs/current/clients/python/overview) and [Streamlit run documentation](https://docs.streamlit.io/develop/api-reference/cli/run) for the underlying tools.
