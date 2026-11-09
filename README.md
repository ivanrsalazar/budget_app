# TrueNorth Budget

A private, local-first cash-flow planner. TrueNorth stores data in SQLite and projects recurring income, recurring expenses, and one-time items week by week so you can see what is actually available before the next payday.

## Run it

Requires Python 3.10 or newer. There are no third-party packages.

```bash
python3 server.py
```

Open <http://127.0.0.1:8000>. The database is created at `data/budget.db` and is intentionally ignored by Git.

### Run in the background on a custom port

From the project directory, this example starts the app on port `8123`, writes output to `budget.log`, and saves the process ID to `budget.pid`:

```bash
BUDGET_PORT=8123 nohup python3 server.py > budget.log 2>&1 & echo $! > budget.pid
```

Open <http://127.0.0.1:8123>. Change `8123` to any available port. The default host remains `127.0.0.1`, so the app is only accessible from your computer.

Check whether the process is running:

```bash
ps -p "$(cat budget.pid)"
```

Follow the application logs:

```bash
tail -f budget.log
```

Stop the background process and remove the saved process ID:

```bash
kill "$(cat budget.pid)"
rm budget.pid
```

On the first run, if `resources/Finances - Winter '26_'27.csv` exists, its dated expense rows are imported once as planned one-time items. The starting balance is initialized from the first week's calculated `Left` amount (or its opening amount if no remainder exists). The CSV itself is ignored because it contains private financial data.

## Features

- Set a current cash balance and an “as of” date.
- Add recurring income and expenses by interval, every selected weekday, or an ordinal weekday such as the third Thursday of each month.
- Add one-time planned or posted items.
- See a 12-week running cash-flow forecast and the lowest projected balance.
- Browse a monthly calendar of recurring and one-time activity with projected end-of-day Checking balances.
- Track credit-card balances, limits, APRs, due days, and minimum payments.
- Assign recurring or one-time expenses to Checking or a saved credit line.
- Direct one-time or recurring card payments to a saved credit line to reduce its projected debt.
- See exactly how much remains immediately before the next expected income.
- Edit, pause, or delete recurring rules and one-time items.
- Switch between light and dark themes; the preference is remembered locally.
- Keep all information locally in SQLite.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Data and backups

Stop the app before copying `data/budget.db` as a backup. To start over, move that file elsewhere and restart the server. Never commit the database, CSV exports, `.env`, or other account exports to a public repository.

