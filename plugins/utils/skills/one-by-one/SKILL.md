---
name: one-by-one
description: Use when the user asks to go through review findings, open points or any list of items one by one and to be asked about anything that changes behaviour, e.g. "go through them one by one", "ask me one at a time". The pass must close every decision before the final report.
---

# One-by-one pass

The user wants to go through a list (review findings, open points, TODO items) one item at a
time and to decide every point that changes behaviour. The goal of the pass is to close every
decision. When the pass ends, nothing should be left for a second round.

## How

1. Take the next item. Say what it is, what it changes and what you recommend.
2. If it changes behaviour, ask the user. Give 2–4 options, the recommended one first.
   If it does not change behaviour, fix it and say so in one line.
3. Fix the item as decided before you move to the next one.
4. **A new choice found while fixing is the next question.** Fixing one item often brings up a
   new decision: a new name in the ubiquitous language, a missing button, an unknown fact such
   as the phone model. Ask it right there, as the next one-by-one question. Do not collect such
   points into an "open points" list in the final report.
5. Keep each item's ID from the list in every question and in the report.

## The only exception

The user does not know the answer, or explicitly defers the choice. Then keep that question
with its ID in the final report, marked as deferred. Never invent the answer.

## Why

After one such pass the user asked, surprised, why there were still open points when the pass
was meant to close them. Leftover points force a second round that the user expected to be
unnecessary.
