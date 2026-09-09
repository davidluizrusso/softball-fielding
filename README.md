# Softball Fielding Optimizer

A small web app that creates legal seven-inning slowpitch defensive
assignments, balances playing time, and limits positional churn. Select the
default Co-ed rules or an Open profile with no gender-based fielding minimums.
The application is team-neutral: different teams can use either rules profile
in independent browser sessions without replacing one another's game setup.
Optimization supports up to 15 available players per game.

## Live deployments

- [Softball Fielding Optimizer](https://softball-fielding-optimizer.streamlit.app/) —
  primary team-neutral deployment for Here For The Beer, Team Red, and future
  teams.
- [Here For The Beer](https://here-for-the-beer.streamlit.app/) — existing
  public team deployment. This address remains supported for current users.

The neutral deployment begins with an explicit choice: load Here For The Beer,
load Team Red, or start with an empty roster. Team Red loads its approved
13-player roster under locked Open rules and does not collect gender. Changing
setups requires confirmation and replaces only the current browser session;
it never modifies another team or another visitor's session.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/streamlit run app.py
```

Use `.venv/bin/streamlit run neutral_app.py` to exercise the first-load team
chooser locally. Direct `app.py` startup preserves the existing Here For The
Beer experience.

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
3. Use `app.py` for the existing deployment. To create a second deployment
   from the same branch without changing the existing app, use
   `neutral_app.py`; it executes the canonical `app.py` implementation without
   duplicating application logic.
4. Deploy the selected entrypoint.

No database or secrets are required. Each visitor's roster stays in their own
Streamlit session.

The initial roster, genders, and positional preferences are loaded from
`roster_positions.csv`. Everyone defaults to available unless the file includes
an `Available` column. The app accepts `Yes`, `Y`, `True`, `1`, or `X` as a
selected position.

Every successful solve displays one semantic seven-inning matrix. On narrow
screens, the matrix scrolls horizontally inside its own keyboard-accessible
region without widening the page. The complete lineup also remains available
as a CSV download. Explicit positions are preferred and hierarchy-derived
fallback assignments are minimized. A live phase indicator and a small
generic stick figure doing jumping jacks remain visible while the solver works.

The shared interactive solve budget is five seconds. A timed solve may remain
`FEASIBLE`, but a later continuity phase cannot replace an already legal
incumbent with a lexicographically worse lineup. Reproduce the published HFTB
latency and quality contract outside the ordinary test suite with:

```bash
.venv/bin/python scripts/benchmark_hftb.py \
  --processes 4 --runs-per-process 5 --budget 5 \
  --output benchmarks/hftb-5s-reference.json
```

The checked-in [reference artifact](benchmarks/hftb-5s-reference.json) records
all 20 qualifying runs and their environment, phase timing, status, and quality
vectors. Timed multi-worker search is nondeterministic: every reference run
must preserve the fairness/preference prefix, while the continuity vector is a
90%-minimum measured target rather than a hard feasibility guarantee.

See [SPEC.md](SPEC.md) for the lineup rules and optimization priorities.

## Documentation

[SPEC.md](SPEC.md) is the current normative description. The reviewed
[Open-rules optimization paper](docs/open_rules_fielding_optimization.pdf)
provides the formal model, Team Red case study, and verification evidence; its
[LaTeX source](docs/open_rules_fielding_optimization.tex) is checked in beside
it. The older papers in `docs/` are retained only as historical pre-hierarchy
examples and do not describe the current optimizer.
