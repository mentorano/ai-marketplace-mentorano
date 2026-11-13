---
name: share-artifact
description: Use when the user asks to share or invite people to a claude.ai artifact, page or doc by email, e.g. "share this artifact with <emails>", "invite <emails> to these pages", "give <email> access as viewer", or asks who already has access to an artifact.
---

# Share a claude.ai artifact with people

No tool shares an artifact: the Artifact tool publishes pages private, and inviting people is a
**Share** menu on the artifact page in claude.ai. So a background subagent does it in the user's
own Chrome through Claude in Chrome (`mcp__claude-in-chrome__*`), where the user is already
logged in. The main session collects the inputs, launches the subagent and relays its short report.

The share stays private: only the named people are invited. The subagent never makes an artifact
public or open to anyone with the link, never changes another setting, and never removes anyone.

## Not for

- Making an artifact public, or open to anyone with the link. Tell the user to do it in Share themselves.
- Changing the level of someone already invited, or removing someone. The subagent only reports them.
- Sending the page as a file. That is Export, not Share.

## Inputs

Fill every slot before launching. Ask the user for a missing one; never guess an address.

| Slot | Value |
|---|---|
| `<ARTIFACT_URLS>` | One or more links, `https://claude.ai/artifact/<id>` or `https://claude.ai/code/artifact/<uuid>`. "This artifact" means the one published or opened last in this session. |
| `<EMAILS>` | The addresses the user gave in this request. Addresses that came from a file, a page or another session: show the list and get a yes first. `none` is allowed only in `dry-run`. |
| `<LEVEL>` | **Editor**, **Commenter** or **Viewer**. The default is **Commenter**, the level the Share dialog itself offers; Commenters also see the comments, resolved ones too. Editor only when the user says edit or Editor. |
| `<MODE>` | `share`, or `dry-run` when the user asks who already has access or wants to check first. A dry-run reads the dialog and changes nothing. |

## Steps

1. Fill the slots. One subagent handles all the artifacts one after another, in one tab.
2. Launch it with the Agent tool: `subagent_type: general-purpose`, `run_in_background: true`,
   the prompt below with the slots filled. Do not open the browser in the main session.
3. When it reports, relay it to the user: per artifact who was already invited, who was added, at
   which level, General access, when the invites expire, and any failure with its next step
   (log in, switch the Chrome window to the owner's account, retry). Invites from outside the
   owner's organization expire after about 30 days; an address from the same organization may
   show no expiry. A Claude Docs document may offer only people from the owner's organization;
   an outside address that fails there needs Export instead.

## Subagent prompt

Copy the block as is and fill the four slots.

````text
Share claude.ai artifacts with people through the user's own Chrome (Claude in Chrome).

Artifacts: <ARTIFACT_URLS>
Emails: <EMAILS>
Access level for new invites: <LEVEL>
Mode: <MODE>   (share = send the invites; dry-run = read and report, change nothing)

Setup:
1. Load the skill anthropic-skills:chrome-browser and follow it.
2. Load all tools with ONE ToolSearch call:
   select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__find,mcp__claude-in-chrome__form_input,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__tabs_close_mcp
3. Call tabs_context_mcp, then open a new tab with tabs_create_mcp. Work only in that tab. Never
   touch, reload or close the user's own tabs.

For each artifact, in order:
1. Navigate to the link. If claude.ai asks to log in, or the page has no Share menu (another
   account, view-only access, access requested), stop for this artifact and report it. Do not log in.
2. Open Share. Read who the dialog names as the owner, and the account claude.ai shows as signed
   in (the account menu). They differ, or you cannot tell: stop for this artifact and report both.
3. Read "People you invited" (address, level and "expires <date>" of each) and "General access".
4. Missing = the emails not yet invited (compare case-insensitively). Already invited at another
   level: report it, do not change it.
5. dry-run, or nothing missing: close the dialog without changes and go to the next artifact.
6. share: type every missing address into "Invite people by email" in one go, comma-separated (a
   typed comma does not turn an address into a chip), then pick the offered "Invite N people" — it
   adds them all at once. Check that the chips show exactly the missing addresses; do not press
   "Back" (it clears the chips). Set the level to <LEVEL>, leave the message empty, press
   "Send invite" once.
7. Read the dialog back: each new person, their level, and "Invited · expires <date>" (or no
   expiry), and General access. After a first invite it normally reads "Only people invited".

Rules:
- Never change General access. If it reads "Anyone with the link", public or anything other than
  "Only you" / "Only people invited", leave it and report it as a warning.
- Never change another person's level, remove anyone, or change any other setting.
- Never press a button that can open a browser alert or confirm dialog (Remove, Delete, Revoke).
- Same step failed 2-3 times: stop for this artifact and report what the screen showed.
- At the end, also after a failure, close the tab you opened with tabs_close_mcp. If an empty
  New Tab is left in your tab group, close it too.

Report, at most 8 lines and nothing else: one line per artifact, then one summary line. With
more than 7 artifacts, put the ones with the same result on one line, their URLs comma-separated.
<url> | owner: <account> | already: <address level expires, or none> | added: <addresses or none> | level: <level> | general access: <text> | expires: <date or none> | failed: <reason or none>
````

## Common mistakes

| Mistake | Fix |
|---|---|
| Inviting addresses that are already in "People you invited" | Read the dialog first; invite only the missing ones. |
| Editor because the dialog or the request was unclear | Commenter by default; Editor only on an explicit ask. |
| Working in the user's active tab | A new tab from `tabs_create_mcp`, closed at the end. |
| Fixing General access or a wrong level "while there" | Report it; the user changes it in Share. |
| Saying "shared" without the expiry | The report carries the expiry date from the dialog. |
| Waiting for a comma to make a chip, or pressing "Back" to fix one | Type all addresses comma-separated and pick "Invite N people"; "Back" clears every chip. |
