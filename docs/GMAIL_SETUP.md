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

## Step 3 — one scope, and no other

**Do this:** on the consent screen, **Add or remove scopes**, and select exactly

```
https://www.googleapis.com/auth/gmail.send
```

Nothing else. Not `gmail.readonly`, not `gmail.modify`, not `mail.google.com`.

**Done when:** the scopes table lists that one entry, and
[`infra/gmail_auth.py`](../src/cop_agent/infra/gmail_auth.py) is still the only
file in the package containing a scope string — which
`test_only_the_send_scope_appears_anywhere_in_the_source` checks by reading the
source tree on every CI run.

### What the narrow scope actually buys

`token.json` lives on a laptop and grants exactly what the scope says. Assume it
leaks — a stray commit, a shared screen, a backup:

| Granted | What the leaked file does |
|---|---|
| `gmail.send` | sends mail as the account. Bad, loud, recoverable. |
| `+ gmail.readonly` | hands over years of correspondence. Silent, permanent. |

The second row is why FR-7.25 calls this the difference between a weapon and a
nearly harmless tool. Same file, same carelessness, entirely different day.

### Asking narrowly is not the same as receiving narrowly

Google returns the scopes **granted**, not the scopes requested. If the same
OAuth client was ever authorized more broadly, the grant can come back as the
union — and a token we did not ask for the power of is still a token that has
it.

`check_granted()` refuses such a token instead of trimming the list. Trimming
would describe the credential as narrow while the file on disk stayed wide, and
the file is what an attacker gets; it does not read our variables. The remedy is
to revoke at <https://myaccount.google.com/permissions> and authorize again.

---

## Step 4 — an OAuth Client ID of type **Desktop app**

**Do this:**

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type: **Desktop app**. Not *Web application*. Name it whatever
   you like.
3. **Download JSON** and save it in the repository root as `credentials.json`.
4. Confirm git is ignoring it *before* your next commit:

   ```bash
   git check-ignore -v credentials.json
   ```

   Silence means it is **not** ignored — stop and fix `.gitignore` first.

**Done when:** `credentials.json` sits in the repository root, the command above
names the `.gitignore` line that covers it, and `git status` does not mention it.

### Desktop app, and why the wrong choice hurts later

Every client type downloads as a file called `credentials.json` and they all
look plausible inside. The difference is one key: a Desktop client wraps its
fields in `"installed"`, a Web client in `"web"`.

Hand `InstalledAppFlow` a Web client and it proceeds normally — browser opens,
consent appears, you approve — and then dies at the redirect with

```
Error 400: redirect_uri_mismatch
```

which names a URI nobody configured. The natural response is an hour of adding
`http://localhost` to authorised redirect URIs in the console, and none of it
works, because the client is simply the wrong type.
[`infra/credentials.py`](../src/thief_agent/infra/credentials.py) says so at load
time instead.

### The check, not the promise

`.gitignore` containing a line and git actually ignoring a file are two
different facts. A pattern can be shadowed by a later negation, and a file that
is **already tracked** stays tracked no matter what the ignore file says.

`TestGitReallyIgnoresTheSecrets` asks git itself, in this repository, on every
CI run — `check-ignore` for each secret filename and `ls-files` to prove none is
tracked. It also asserts the rules are not *too* broad: a match log must stay
visible, since it is the evidence the Replay App verifies.

FR-7.27 is worth restating for the reason behind it. A secret pushed once is
compromised permanently: it stays in history, these repositories are public, and
the remedy is rotating the credential in the console rather than a revert.

---

## Step 5 — the first authorization flow

**Do this, once, from the repository root:**

```bash
python -m thief_agent.infra.authorize
```

A browser opens. Approve the consent screen — including the
**"Google hasn't verified this app"** interstitial, via *Advanced → Go to … (unsafe)*,
which is expected for an app in Testing. The command then writes `token_thief.json`
with mode `600`.

**Done when:** `token_thief.json` exists, a second run refreshes without asking again,
and `git check-ignore -v token_thief.json` names the `.gitignore` line covering it.

### The token file is named per agent on purpose

Not `token.json` in both repositories. The two agents authorize separately and
their credentials are not interchangeable — but two files with the same name in
sibling directories are an invitation to copy one across to skip the flow.
[`infra/token_store.py`](../src/thief_agent/infra/token_store.py) refuses a token
minted for a different `client_id` and says that copying is the usual cause.

Override with `GMAIL_TOKEN_PATH` if you want it somewhere else.

### What the command refuses, and why each refusal exists

| Refused | Because |
|---|---|
| an **over-scoped** grant | Google returns the scopes *granted*, which can exceed those requested if this client was ever authorized more broadly. Refused rather than trimmed — the file on disk is what an attacker gets, and it does not read our variables. |
| a grant with **no refresh token** | usable for an hour, then dead at whatever moment that hour ends. Google omits it when the client has been authorized before, so it appears exactly when somebody re-runs the flow to fix something else. Revoke at <https://myaccount.google.com/permissions> and run again. |
| a token from **another client** | it might work, and it is not ours. Usually a file copied between the two agents. |

Nothing is written when a grant is refused. Checking after the flow is not too
late: the file is what matters, and it does not get created.

The credentials file is checked **before** the browser opens, so nobody
approves a consent screen for a client that was never going to work.

### Sharing with a teammate

`credentials.json` identifies the **application**, so the same file works for
everyone on the team — hand it over directly. It is gitignored, so it is *not*
in a clone; a teammate who clones the repository gets no credentials at all.
They also need their address on the **Test Users** list from step 2.

`token_thief.json` is **personal**. Each person runs the flow for themselves.

### It expires after seven days

While the app is in Testing (step 2). Re-run this command if the agent has been
idle a week. Every error in the mail path ends by naming it, because every one
of them is fixed the same way.

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
