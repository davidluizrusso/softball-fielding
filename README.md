# Softball Fielding Optimizer

A small web app that creates legal seven-inning slowpitch defensive
assignments, balances playing time, and limits positional churn. Select the
default Co-ed rules or an Open profile with no gender-based fielding minimums.
The deployment is team-neutral: different teams can use either rules profile
in independent browser sessions without replacing one another's game setup.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/streamlit run app.py
```

Run the automated tests with:

```bash
.venv/bin/python -m pytest
```

The real-browser regression suite covers mobile touch and desktop mouse input:

```bash
npm ci
npx playwright install chromium
npm run test:browser
```

## Deploy

1. Put this directory in its own GitHub repository.
2. In Streamlit Community Cloud, create an app from the repository.
3. Choose `app.py` as the entrypoint and deploy.

No database or secrets are required. Each visitor's roster stays in their own
Streamlit session.

The initial roster, genders, and positional preferences are loaded from
`roster_positions.csv`. Everyone defaults to available unless the file includes
an `Available` column. The app accepts `Yes`, `Y`, `True`, `1`, or `X` as a
selected position.

The default inning view is a semantic two-column table for screen-reader and
mobile access. The complete seven-inning matrix remains available on screen and
as a CSV download.

See [SPEC.md](SPEC.md) for the lineup rules and optimization priorities.

## Technical paper

The optimization formulation and deployment notes are available as
[LaTeX source](docs/softball_fielding_optimization.tex) and a
[compiled PDF](docs/softball_fielding_optimization.pdf).

The lineup rules are also memorialized in the substantially more ominous
[Defensive Lineup Compliance Code](docs/defensive_lineup_compliance_code.pdf),
with its corresponding [LaTeX source](docs/defensive_lineup_compliance_code.tex).
