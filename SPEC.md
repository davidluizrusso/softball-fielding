# Softball Fielding Optimizer — MVP Specification

## Goal

Create a legal seven-inning defensive schedule for one game at a time. Among
legal schedules, balance playing time first and keep each player at no more
than two positions when possible.

## Inputs

- Roster name, entered in a player card
- Gender (`Woman` or `Man`)
- League rules profile (`Co-ed` or `Open`)
- Availability for the game, toggled from a tap-friendly player list
- Unranked positional preferences, selected from wrapping position buttons

The initial names, genders, and preferences come from `roster_positions.csv`.
All players default to available when the file has no availability column.

Preferences are hard eligibility rules: a player may not be assigned to an
unlisted position.

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

In an 8- or 9-player lineup under either profile, listing `RF` also makes the
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
3. Minimize one-inning state stints, including `Bench`.
4. Minimize fielding positions beyond two.
5. Minimize two-inning state stints, including `Bench`.
6. Minimize total distinct fielding positions.
7. Minimize adjacent state transitions, including field-to-Bench and
   Bench-to-field changes.

The two-position target is soft and may be exceeded to improve higher-priority
goals or produce a feasible schedule. State-stint targets are also soft.
`Bench` participates only in continuity: it is not a preference, fielding
position, inning played, or member of the reported positions-used set.
Consecutive Bench innings form one stint. `A → Bench → A` contains two A
stints and two adjacent transitions. Inning one does not itself count as a
transition.

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
