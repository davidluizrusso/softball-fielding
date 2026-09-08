# Softball Fielding Optimizer — MVP Specification

## Goal

Create a legal seven-inning defensive schedule for one game at a time. Among
legal schedules, balance playing time first and keep each player at no more
than two positions when possible.

## Inputs

- Roster name, entered in a player card
- Gender (`Woman` or `Man`) for rosters that may use Co-ed rules; Team Red
  stores `Unspecified` and does not display or collect gender
- League rules profile (`Co-ed` or `Open`)
- Availability for the game, toggled from a tap-friendly player list
- Explicit positional preferences, selected from wrapping position buttons

The initial names, genders, and preferences come from `roster_positions.csv`.
All players default to available when the file has no availability column.

## Roster setups

The legacy entrypoint opens directly with the Here For The Beer CSV roster and
Co-ed as its default profile. The neutral entrypoint blocks all roster controls
until the user explicitly chooses Here For The Beer, Team Red, or an empty
roster. Team Red loads the published `team_red_roster.csv`, makes all players
available, and locks the profile to Open. An empty setup keeps the league
profile selectable and collects gender for newly added players.

Only one setup exists in a browser session. A setup change requires destructive
confirmation and atomically clears roster edits, availability widgets, open
drafts, results, errors, fingerprints, and timing before the
new setup is loaded. Canceling the confirmation preserves those values. Reset
restores the currently active roster template; it never changes teams. No
account, durable storage, or cross-session team state is implied.

Explicit preferences are first-choice assignments. The optimizer derives a
larger fallback-eligibility set from the universal hierarchy below, but it
minimizes fallback innings before considering any continuity objective.

- Everyone is eligible for `C` as a fallback.
- `SS` implies `3B` and `2B`; `3B` implies `2B`.
- `LC` implies `LF`, `RC`, and `RF`; `LF` implies `RC` and `RF`; `RC` implies
  `RF`.
- `P` and `1B` are opt-in only and are never inferred.

All inferred positions have the same fallback cost. The model does not invent
a comfort ranking among them. Explicit preferences remain stored separately
and unchanged.

## League profiles, positions, and lineup sizes

The full position set is `P`, `C`, `1B`, `2B`, `3B`, `SS`, `LF`, `LC`, `RC`,
and `RF`.

The `Co-ed` profile is the default and retains the original league rules:

| Fielders | Active positions | Minimum women |
| --- | --- | --- |
| 10 | All positions | 4 |
| 9 | All except `RF` | 3 |
| 8 | All except `RF` and `C` | 3 |

- Use 10 fielders whenever at least 10 players and at least 4 women are
  available.
- Otherwise use 9 fielders when at least 9 players and at least 3 women are
  available.
- Otherwise use 8 fielders when at least 8 players and at least 3 women are
  available.
- Fewer than 8 available players or fewer than 3 available women cannot form a
  legal lineup.

The `Open` profile removes gender-based fielding rules:

| Available players | Fielders | Active positions |
| --- | --- | --- |
| 10 or more | 10 | All positions |
| 9 | 9 | All except `RF` |
| 8 | 8 | All except `RF` and `C` |

Fewer than 8 available players cannot form an Open lineup. Gender remains a
stored roster attribute, but it does not affect Open lineup size, legality, or
optimization. A position-eligibility failure for a ten-player Open roster is
reported as an error; it does not silently reduce the lineup to nine.

The supported optimization input is 8–15 available players. A session may
retain more roster records, but at most 15 may be selected for one solve.

In an 8-player lineup under either profile, listing `RF` also makes the
player eligible at `RC` for that game.

## Per-inning legality

Every inning under either profile must:

- Fill every active position exactly once.
- Assign each player to at most one position.
- Assign every available player exactly one scheduling state: an active
  fielding position or `Bench`.

Every Co-ed inning must also meet the minimum number of women for the lineup
size and place at least one woman in the infield and one in the outfield. The
Open profile has neither gender constraint.

For this rule, the infield is `P`, `C`, `1B`, `2B`, `3B`, and `SS`. The
outfield is `LF`, `LC`, `RC`, and `RF`.

## Optimization priorities

After satisfying all hard rules, optimize in this order:

1. Minimize the spread between the most and least innings played.
2. Minimize total deviation from an equal share of the available innings.
3. Minimize innings assigned to hierarchy-derived fallback positions.
4. Minimize one-inning state stints, including `Bench`.
5. Minimize fielding positions beyond two.
6. Minimize two-inning state stints, including `Bench`.
7. Minimize total distinct fielding positions.
8. Minimize adjacent state transitions, including field-to-Bench and
   Bench-to-field changes.

The two-position target is soft and may be exceeded to improve higher-priority
goals or produce a feasible schedule. State-stint targets are also soft.
`Bench` participates only in continuity: it is not a preference, fielding
position, inning played, or member of the reported positions-used set.
Consecutive Bench innings form one stint. `A → Bench → A` contains two A
stints and two adjacent transitions. Inning one does not itself count as a
transition.

The solver uses a shared nominal five-second application budget while retaining
caller overrides. It first attempts to certify the arithmetic floor/ceiling
distribution for playing time, then uses up to a two-second fairness proof
budget when that slice is infeasible or cannot be established immediately. The
UI reports each active optimization phase. Before the final timed continuity
pass, the model bounds the weighted objective by the best legal incumbent and
the returned candidate is also compared using the documented lexicographic
vector. A worse timed candidate is discarded. `OPTIMAL` is reported only when
every higher-priority stage and the final weighted continuity objective are
proven; otherwise a legal incumbent is labeled `FEASIBLE`.

The opt-in HFTB reference benchmark runs 20 measured solves across at least
four fresh Python processes after one excluded warm-up per process. It records
the environment, phase boundaries, solver status, latency, and all eight
objective metrics for every run; this wall-clock check is intentionally not a
per-commit CI assertion.

## Output

- One semantic matrix with innings 1–7 as row headers and `P`, `C`, `1B`, `2B`,
  `3B`, `SS`, `LF`, `LC`, `RC`, `RF`, and `Bench` as column headers.
- All seven innings exist in the same table immediately after optimization;
  narrow screens scroll the matrix inside a keyboard-accessible region rather
  than using lineup-view or inning selectors.
- Inactive positions are shown as `—`.
- The CSV retains `Out` as its final header; each visible `Bench` cell contains
  the same available-but-unassigned player set.
- A playing-time summary showing innings played and positions used.
- A clear explanation when no feasible schedule exists.

## MVP scope

- Optimize one game at a time.
- Keep data in each browser session; do not require accounts or a database.
- Allow CSV download of results.
- Support deployment as a low-volume Streamlit Community Cloud app.
