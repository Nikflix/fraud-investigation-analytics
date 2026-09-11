# Run the project on Windows

The project currently runs from a terminal. There is no fraud dashboard yet.
DuckDB is installed as a Python dependency and stores transactions in a local
file. A database server and MySQL Workbench are not required.

## Get the code

Install Python 3.12 or newer and Git if they are not already installed. Open
PowerShell in the folder where you keep projects, then run:

```powershell
git clone https://github.com/Nikflix/fraud-investigation-analytics.git
cd fraud-investigation-analytics
```

If you already cloned the repository, open that folder and run `git pull`.

## Install the project

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

If Windows cannot find `python`, try `py` for the first two commands. Check that
the reported version is at least 3.12. Calling the environment's Python directly
means you do not need to activate it or change PowerShell execution policy.
Installing the project also installs DuckDB.

## Load the sample

Run these commands from the repository root:

```powershell
.\.venv\Scripts\python.exe -m fraud_analytics validate data/sample/transactions.csv
.\.venv\Scripts\python.exe -m fraud_analytics ingest data/sample/transactions.csv
```

The load should report `"inserted_rows": 6`. It creates
`data/processed/fraud.duckdb` with one `transactions` table. This file is ignored
by Git and stays on your computer.

Loading the same sample into that file again returns exit code `1` because its
transaction IDs already exist. The original six rows stay unchanged. To try a
separate database, pass a different path:

```powershell
.\.venv\Scripts\python.exe -m fraud_analytics ingest data/sample/transactions.csv --database data/processed/practice.duckdb
```

## See the data and run SQL

Start a Python session:

```powershell
.\.venv\Scripts\python.exe
```

At the `>>>` prompt, run:

```python
import duckdb
from pathlib import Path

con = duckdb.connect("data/processed/fraud.duckdb", read_only=True)
con.execute("SET TimeZone = 'UTC'")
con.sql("SELECT * FROM transactions ORDER BY timestamp").show()
con.sql(Path("sql/transaction_summary.sql").read_text()).show()
con.close()
exit()
```

The summary should show:

| transaction_type | transaction_count | total_amount | unknown_labels | negative_labels | positive_labels |
| --- | --- | --- | --- | --- | --- |
| PAYMENT | 3 | 60.50 | 3 | 0 | 0 |
| TRANSFER | 3 | 255.10 | 3 | 0 | 0 |

These are fictional sample transactions. Unknown labels do not mean legitimate
transactions. A browser dashboard using Streamlit is planned for a later stage.

Close database connections before running another process that writes to the
same file. If you see a file-lock error, exit the Python session and retry.

## Run the tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Tests use temporary databases; they do not change your local sample database.

See the [DuckDB Python documentation](https://duckdb.org/docs/current/clients/python/overview)
for the database client and connection options.
