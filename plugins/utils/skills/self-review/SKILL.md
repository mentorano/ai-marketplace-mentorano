---
name: self-review
description: Use when you have just written or changed an output that someone else will act on, and before you commit it, hand it over or report it done — code (a diff), a fix of review findings, a spec, a plan, a doc, a handoff or handover prompt, a prompt file for another agent, a report. Also when a skill, a prompt or a rule asks for a self-review of your output (in captain: SV1), or the user says "self review", "check that nothing was missed", or is about to hand a branch over and wants it checked first.
---

# Self-review of an output you just wrote

One pass over your own output, in the same context that wrote it, before anyone acts on it.
You still hold the whole task in your window, so you can see what the output dropped. A fresh
reader cannot.

It is not a review. Where the process asks for a review by a fresh agent or a person, that
review still follows. A self-review never counts as a passed review.

## When not to use

- You wrote or changed nothing in this task.
- The user asks for an independent review of a branch or a pull request. Use a review skill or
  a fresh reviewer for that.

## Steps

1. **Name the output and its sources.** The output is every file you wrote or changed,
   read whole when it is a document (a handoff, a spec, a prompt file), wherever it lives,
   in the repository or outside it. For code it is also the diff: `git diff` (unstaged),
   `git diff --cached` (staged) and `git diff <base>..HEAD` once it is committed. The sources are what the output must agree with: the
   request or task text, the spec or plan, the recorded decisions, and for a handoff the
   conversation itself and the state files it summarizes.
2. **Read the whole output back** with `Read` or `git diff`. Read the text as it is on disk,
   not your memory of it, and read it as the one who gets only this output.
3. **Collect findings** as a numbered list, `F1`, `F2` …, each with the place and the claim.
   Use the row of the table that fits. Change nothing yet.
4. **Revalidate each finding against the source, one at a time.** Open the source again and
   decide one verdict:
   - `VALID`: the problem is real. Fix it now, only that.
   - `INVALID`: the output is right, or the claim is wrong. Change nothing; keep the reason.
   - `DECISION`: it needs a choice that is not yours (product, scope, a recorded decision).
     Change nothing; pass the question to the user or the coordinator.
5. **Read back what you changed** in step 4, once. A fix can break the line next to it.
6. **Report** every finding with its verdict in one line each, then the result line:
   `self-review: <n> findings, <m> fixed, <k> rejected, <d> decisions`.
   No findings: `self-review: 0 findings, 0 fixed, 0 rejected, 0 decisions` and what you read
   (the files or the diff range).

## What to check

| Output | Check |
|---|---|
| Code (a diff) | Every requirement of the task has a change. Nothing changed that the task did not ask for. Each edge case the task names is handled. The callers of what you changed still fit. A new test file is in the test runner. No debug leftover, no commented-out code. |
| A fix of review findings | Each finding in the list is closed. No unchanged line around a fix stopped working. |
| A spec or a plan | Every point of the request and every answer of the user is in it. No `TBD`, no `<...>` left. Every file, name and command it mentions exists or is marked as new. Each step can be checked when done. |
| A handoff, a handover prompt, a prompt file for another agent | The reader knows nothing else. It has the goal, what is done and the command that shows it, what is left, the open decisions and questions, the user's standing instructions in the user's own words, and the first step. Whatever lives only in this conversation is written down. Paths, branches and commands are exact text. |
| A doc or a report | Each claim points to a `file:line`, a command output or a log. Each number equals its source. Nothing is "done" without evidence. |

## Limits

- Same context only. Launch no subagent and invoke no other review skill or command.
- Run no test and no build for this pass. Verification is its own step, where the task or
  the process has one.
- Do not commit or push as part of it.
- Fix only `VALID` findings, and only what the finding names. A wider change is a `DECISION`.
- One pass plus step 5. Do not loop until nothing is found.

## Why

Review passes by fresh agents kept finding what the author could have seen: a requirement
with no change, a decision that never reached the handoff, a fix that broke the line next to
it. The author's own read-back costs one pass and leaves the fresh review for real defects.
The owner asked for it after every output of a session or an agent, the handoff first.
