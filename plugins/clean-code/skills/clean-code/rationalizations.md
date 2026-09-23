# Rationalizations

Read this when tempted to skip a rule. The left column is the thought; the
right column is the answer.

| Excuse | Answer |
|---|---|
| "No time to split this now." | The split takes minutes. The next reader pays hours. Measure, split, measure. |
| "Match the existing style." | Match the formatting; that is the team rule. A 500-line neighbour is not a style, it is a smell with tenure. Leave it cleaner than you found it. |
| "It's just a script." | Scripts outlive the project. The one-off becomes the pipeline. |
| "We'll clean it up later." | Later equals never. Later is where this file came from. There is no refactor task on the board. |
| "The linter passes." | Ruff and ESLint defaults do not check function length or nesting; ruff needs `--select PLR0915,C901` and ESLint's `max-lines-per-function` is not in `recommended`. Pylint's defaults do, at 50 statements and 5 blocks, looser than this skill. No linter here checks layer boundaries unless the project turned on `import-linter` or `dependency-cruiser`. `measure.py` measures length, complexity, parameters and nesting every run; `boundaries.py` counts the imports that cross a boundary the wrong way. |
| "The tests pass." | Tests prove behaviour, not shape. Both are the deliverable. |
| "Don't gold-plate it." | A function under 20 lines is not gold. Uncle Bob: functions "should hardly ever be 20 lines long", and Kent Beck's Sparkle functions were two to four. 20 is where he stops, not where he aims. |
| "The user just wants it working." | The user wants it working next month too. |
| "Adding a `# noqa` is faster." | A suppression is a safety the code overrode on purpose. Write the reason on the line or fix the finding. |
| "This function is complex because the domain is complex." | Then the complexity is a type, not a branch: polymorphism, a strategy, or a lookup table. Not nested `if`s. |
| "One more parameter won't hurt." | The fourth parameter is a missing object. Name it. |
| "I'll put the rule in the handler, it's only used here." | Only-used-here is how a rule ends up in a second handler. Put it in the domain, call it from the handler. |
| "LGTM, ship it." | Three passes, findings revalidated, outcomes reported. Then ship it. |
| "The user scoped the edit narrowly." | Then the report names what stays over threshold, why, and what the follow-up split would be. Silence is the violation, not the scope. |
