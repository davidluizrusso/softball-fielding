# Softball Fielding Optimizer

A small web app that creates legal seven-inning co-ed slowpitch defensive
assignments, balances playing time, and limits positional churn.

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

See [SPEC.md](SPEC.md) for the lineup rules and optimization priorities.

## Technical paper

The optimization formulation and deployment notes are available as
[LaTeX source](docs/softball_fielding_optimization.tex) and a
[compiled PDF](docs/softball_fielding_optimization.pdf).
