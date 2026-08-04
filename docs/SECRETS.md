# Secrets this project needs, and where they are not

## Step-0 signing key

The rulebook has the pre-game declaration **signed cryptographically with a key
supplied in advance** (Ch. 5.5). That key comes from the course and we do not
hold it yet.

Until it arrives, `declare()` produces a declaration whose signature reads
`"unsigned"` — explicitly, rather than as an empty string or a signature over an
empty key, both of which would *verify* and so claim an authenticity nobody
granted.

When the key is issued:

```bash
export STEP0_SIGNING_KEY=<the key the course supplies>
```

It is read from the environment and **never from a file in this repository**.
These repositories are public: a key committed beside the thing it signs can be
used by every other team in the cohort to forge our declaration, and Appendix C
makes "nothing sensitive anywhere in Git history" a submission gate — where a
leak is permanent regardless of any later deletion.

`verify_signature()` checks the opponent's declaration against the same key,
using `hmac.compare_digest`. That comparison is between a secret-keyed value
they produced and one we computed, which is the case where a timing channel is
real rather than theoretical.
