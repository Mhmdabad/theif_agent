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

## Step 2 — the OAuth Consent Screen, and every team member as a Test User

**Do this:**

1. **APIs & Services → OAuth consent screen**, on the *same project* as step 1.
2. Choose a user type:
   - **Internal** if the account is on a Google Workspace domain and everyone
     who will authorize is inside it. No test-user list is needed and the app
     never has to be verified.
   - **External** otherwise — which is the case for ordinary `@gmail.com`
     accounts, so it is the likely answer here.
3. Fill the app information. App name, a support email, a developer contact
   email. All three are required; none of them are checked while the app stays
   in Testing.
4. Save, then find the **Test users** section and **add every email address
   that will ever run the authorization flow** — each team member, and the
   sending account itself if it differs.
5. Leave the publishing status as **Testing**. Do not press *Publish app*.

**Done when:** the consent screen page shows **Publishing status: Testing** and
every team member's address is listed under **Test users**.

### What a Test User actually is

While an External app is in Testing, Google will complete the authorization flow
**only for accounts on that list**. An account not on it gets

```
Error 403: access_denied
```

which does not mention test users, does not mention the consent screen, and
reads as though the account lacks permission for the Gmail API. It is the
rulebook's example of a step that fails "later and more confusingly" — the
missing configuration is on a page nobody is looking at, and the error names the
wrong thing.

The list is not a formality. Add people **before** they need it, because
discovering this at 2am on a match night means waiting for whoever owns the
console to wake up.

### Why Testing rather than Published

Publishing an External app that requests `gmail.send` puts it in front of
Google's verification process — a review with a turnaround measured in weeks,
requiring a privacy policy, a homepage and a recorded demonstration. None of
that is wanted for a course project.

The cost of staying in Testing is a **refresh token that expires after seven
days**. That is the trade, and it is the right way round: a week is a term-time
inconvenience, and verification is not a thing to start in week eleven. Practical
consequence — re-run the authorization flow (step 5) if the agent has not
reported in a week. FR-7.26's "reports autonomously for months" describes a
published app; ours is not one, and pretending otherwise would mean discovering
it during the tournament.

### The unverified-app warning is expected

Testing apps show a **"Google hasn't verified this app"** interstitial during the
flow. It is reached through *Advanced → Go to \<app name\> (unsafe)*. This is
normal for a project in Testing and not a sign anything is misconfigured.

---

## Steps 3–5

Not yet written up. They land with the issues that cover them:

| Step | What | Issue |
|---|---|---|
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
