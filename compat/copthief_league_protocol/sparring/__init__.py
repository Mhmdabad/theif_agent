"""A practice opponent for the Cop-Thief league — the full rulebook, no mail, simple brains.

Run it locally to rehearse a complete six-sub-game series before you contact another team.

Three things this package is deliberately NOT:

* **Not a league entry.** A sparring game is an uncounted warm-up (book App. E rule 52), so no
  report is owed by either side, and none can be produced — see ``sparring.guards.no_mail``.
* **Not tuned.** The policies here are the public-knowledge kind (random, greedy) and carry no
  learned weights. A practice peer that answered with a tuned brain would hand a future opponent
  a free sample of the thing being graded.
* **Not an independent implementation of the crypto.** The game layer — rules, engine, state
  machine, wire, receiver contract, artifacts — is written from ``SPEC.md`` and the book. The
  byte-level constructions are the kit's own, imported through ``sparring.kitref``. So this peer
  cannot catch a bug *inside* ``verify_vectors.py``; playing a real team remains the true test.
"""

__version__ = "0.1.0"

# Reported in the sealed step-0 record as `code_version`, the way the book asks a real peer to
# declare the commit it played. A practice peer has no commit to declare, so it declares this.
CODE_VERSION = f"copthief-sparring/{__version__}"

# The group id every sparring peer uses unless told otherwise. `game_id` is built from the two
# group ids, so this prefix is what makes a practice artifact impossible to mistake for a league
# pairing at a glance — see sparring.artifacts.
GROUP_PREFIX = "sparring-"
DEFAULT_GROUP_ID = "sparring-local"

# The repos a sparring peer truthfully declares (identity block, declaration artifact, and the
# result's rule-49 `links.github`): its cop and its thief both live in this kit. A real team
# declares two implementation repos here; the sparring peer has exactly one, twice.
KIT_REPO_URL = "https://github.com/Imreec/copthief-league-protocol"
