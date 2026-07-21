# Softball Fielding Optimizer — MVP Specification

## Goal

Create a legal seven-inning defensive schedule for one game at a time. Among
legal schedules, balance playing time first and keep each player at no more
than two positions when possible.

## Inputs

- Roster name, entered in a player card
- Gender (`Woman` or `Man`)
- Availability for the game, toggled from a tap-friendly player list
- Unranked positional preferences, selected from wrapping position buttons

The initial names, genders, and preferences come from `roster_positions.csv`.
All players default to available when the file has no availability column.

Preferences are hard eligibility rules: a player may not be assigned to an
unlisted position.

## Positions and lineup sizes

The full position set is `P`, `C`, `1B`, `2B`, `3B`, `SS`, `LF`, `LC`, `RC`,
and `RF`.

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
- In an 8- or 9-player lineup, listing `RF` also makes the player eligible at
  `RC` for that game.

## Per-inning legality

Every inning must:

- Fill every active position exactly once.
- Assign each player to at most one position.
- Meet the minimum number of women for the lineup size.
- Place at least one woman in the infield and at least one in the outfield.

For this rule, the infield is `P`, `C`, `1B`, `2B`, `3B`, and `SS`. The
outfield is `LF`, `LC`, `RC`, and `RF`.

## Optimization priorities

After satisfying all hard rules, optimize in this order:

1. Minimize the spread between the most and least innings played.
2. Minimize total deviation from an equal share of the available innings.
3. Strongly discourage one-inning position stints.
4. Minimize distinct positions, with an additional penalty beyond two.
5. Prefer stints of at least three innings over two-inning stints.
6. Minimize position starts so longer continuous runs win remaining ties.

The two-position target is soft and may be exceeded to improve higher-priority
goals or produce a feasible schedule. Position-stint targets are also soft. A
stint is a run of consecutive innings at one position; sitting out ends the
stint, even when the player later returns to the same position.

## Output

- A matrix with innings 1–7 as rows and all ten positions as columns.
- Inactive positions are shown as `—`.
- A playing-time summary showing innings played and positions used.
- A clear explanation when no feasible schedule exists.

## MVP scope

- Optimize one game at a time.
- Keep data in each browser session; do not require accounts or a database.
- Allow CSV download of results.
- Support deployment as a low-volume Streamlit Community Cloud app.
