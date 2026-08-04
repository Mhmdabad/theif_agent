# Gmail API setup

The agent reports every finished match to the lecturer over the Gmail API
(FR-7.15, FR-7.17). Getting there is five ordered console steps from Appendix A,
and the rulebook is explicit that skipping one makes the flow fail **later and
more confusingly** than it would have failed at the time.

This file is the runbook. Each step says what to do, how to know it worked, and
what the step is actually for — because every one of them is a place where the
obvious shortcut costs an hour later.

> **None of these steps can be automated, and that is the point.** They bind a
> live mail account to code we are writing. The console asks a human each time
> on purpose.

---

## Step 1 — a Google Cloud project, with the Gmail API enabled

**Do this:**

1. Sign in to <https://console.cloud.google.com/> with the Google account that
   will send the reports. Whichever account this is, it is the one whose mail
   quota the agent will spend — pick deliberately.
2. Create a project, or select an existing one. Name it for the course, e.g.
   `uoh26-cops-and-robbers`, so it is obvious a year from now which project a
   stray credential belongs to.
3. Note the **project ID** shown in the picker. It is not the display name and
   it is what every later screen actually keys off.
4. Go to **APIs & Services → Library**, search for **Gmail API**, open it, and
   press **Enable**.

**Done when:** the Gmail API page for this project shows **API Enabled** with a
**Manage** button instead of **Enable**. Direct link, once the project is
selected:
<https://console.cloud.google.com/apis/library/gmail.googleapis.com>

### Why this is step 1

Enabling an API is Google's switch for *this project may call these endpoints*.
Until it is on, every later step still appears to work — the consent screen
saves, a client ID is issued, the browser flow completes — and then the first
real send fails with `accessNotConfigured`, an error that names the API rather
than the switch and reads as a code problem rather than a console one.

### The mistake worth naming

Enabling the API **on the wrong project**. Anyone with more than one project has
a picker at the top of the console that quietly persists across sessions, and
the Library page gives no hint that the project you are looking at is not the
project your `credentials.json` came from. If a send later fails with
`accessNotConfigured` against a project you are certain you enabled, check the
project ID in the credentials file against the one in the picker before checking
anything else.

### One account or two?

The cop and the thief are separate agents and each must report for itself
(FR-7.15 — one side reporting is not enough). They may share one Google Cloud
project: the reports differ by content, not by sender identity, and the
lecturer's address is the same for both. Two projects also work and cost only
the duplication of these five steps. What must **not** be shared is the
`token.json` file — see step 5.

---

## Steps 2–5

Not yet written up. They land with the issues that cover them:

| Step | What | Issue |
|---|---|---|
| 2 | OAuth Consent Screen, team members as Test Users | #94 |
| 3 | Scope restricted to `gmail.send` and nothing else | #95 |
| 4 | OAuth Client ID (Desktop Application) → `credentials.json` | #96 |
| 5 | First authorization flow → `token.json` | #97 |

---

## Before any of it: the two files that must never be committed

`credentials.json` and `token.json` are secrets, and FR-7.27 requires them
ignored **before the first commit** rather than after. Both are already listed
in [`.gitignore`](../.gitignore), along with `client_secret*.json`, which is the
name the console actually gives the file it hands you.

A secret pushed even once is compromised permanently. Deleting it from the
current tree does not remove it from history, and these repositories are public.
The remedy is not a revert; it is rotating the credential in the console.

See [`SECRETS.md`](SECRETS.md) for everything else this project keeps out of the
repository.
