# <project> - <role/session> handoff, <date> <part of day>

Self-contained: everything from earlier handoffs that still stands is carried into §1-§4 below,
shortened. Earlier files (<paths>) are for lookup only; read one only where a line here points to it.

**Nothing here is status.** Re-derive at the point of use:

```sh
<skill dir>/scripts/derive-state.sh <repo> --fetch
<skill dir>/scripts/measure-context.py <repo> 24
<any extra command: container, CI run, board read>
```

**Name swap:** <who renames what, or "none">.

## 1. Owner decisions taken (text in <amendments path>)
- **<id> - <title>.** <one or two lines; what it binds, which lanes it touches>.

## 2. Coord rulings (for ratification unless listed under 1)
- **<ruling>.** <reasoning in one line>. <withdrawn earlier ruling, if any, and why>.

## 3. Open threads (verify each against git before acting)
1. **Expected КАЦНА:** <branch + what it carries; exact sha if a lane withdrew later commits>. Verify with `git log origin/<branch>`.
2. **OPEN for the owner:** <question - recommendation - deadline>.
3. **Sessions:** <who should be woken/cleared at its next boundary - as intent, not status>.

## 4. Lessons
- **<lesson>.** <the incident in one line, the rule>. Memory: `<memory file>` if saved.
