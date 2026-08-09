#!/usr/bin/env python3
"""Fail if a shared module has drifted from the sibling repository.

The cop and thief may not share a live-state module — doing so disqualifies the
solution — so the logic they both need is **deliberately duplicated** and must
be kept in lockstep by hand. That is a rule with no compiler behind it, and it
has already been broken three times: placement-reach validation existed only in
the cop repo, so this agent would have accepted a barrier on any cell of the
board; ``domain/search.py`` was simply absent here; and the Appendix F accessor
landed on the cop side only, leaving book values hard-coded here, where a
*fixed* parameter drifting is a disqualification discovered at audit.

All three were found by using the code, not by reviewing it. This turns the
next one into a build failure at the moment it appears.

The manifest is explicit rather than a glob. Some divergence is intentional —
role names, role-specific framing, the brains themselves — so a check that
guessed would either miss real drift or cry wolf about the deliberate kind.
Each intentional divergence carries its reason, making the list a statement
about the design rather than a suppression.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SIBLING_URL = "https://github.com/Mhmdabad/police_agent"
SIBLING_PACKAGE = "cop_agent"
OUR_PACKAGE = "thief_agent"

SHARED: tuple[str, ...] = (
    "domain/axes.py",
    "domain/board.py",
    "domain/crypto.py",
    "domain/crypto_record.py",
    "domain/rules.py",
    "domain/search.py",
    "domain/actions.py",
    "domain/scoring.py",
    "domain/scent.py",
    "domain/scent_falloff.py",
    "domain/scent_audit.py",
    "domain/scent_audit_disagreement.py",
    "domain/scent_audit_replay.py",
    "domain/turn_order.py",
    "domain/scent_audit_wire.py",
    "domain/trail.py",
    "domain/memory.py",
    "domain/fixture.py",
    "domain/lock.py",
    "domain/lock_model.py",
    "domain/belief.py",
    "domain/belief_readout.py",
    "domain/inference.py",
    "domain/credibility.py",
    "domain/credibility_verdict.py",
    "domain/foci.py",
    "domain/foci_clusters.py",
    "domain/hints.py",
    "domain/hints_lexicon.py",
    "domain/bluff.py",
    "domain/bluff_vetting.py",
    "domain/bluff_intent.py",
    "domain/bluff_decoy.py",
    "domain/bluff_phrasing.py",
    "domain/providers.py",
    "domain/budgeting.py",
    "infra/artefacts.py",
    "infra/artefacts_coherence.py",
    "infra/ceremony.py",
    "infra/ceremony_verdict.py",
    "infra/ceremony_match.py",
    "infra/ceremony_final.py",
    "infra/ceremony_step.py",
    "infra/ceremony_step_lock.py",
    "infra/ceremony_step_state.py",
    "infra/ceremony_reveal.py",
    "infra/ceremony_ack.py",
    "infra/ceremony_commit.py",
    "infra/ceremony_errors.py",
    "infra/report_reload.py",
    "infra/match_ledger.py",
    "runtime/match.py",
    "runtime/match_play.py",
    "runtime/match_agreement.py",
    "runtime/match_state.py",
    "runtime/match_outcome.py",
    "runtime/orchestrator_result.py",
    "runtime/peer.py",
    "runtime/peer_records.py",
    "runtime/peer_mailbox.py",
    "runtime/peer_types.py",
    "runtime/subgame.py",
    "runtime/subgame_audit.py",
    "runtime/subgame_commit.py",
    "runtime/subgame_scent.py",
    "runtime/subgame_hint.py",
    "runtime/subgame_moves.py",
    "runtime/subgame_state.py",
    "runtime/subgame_types.py",
    "infra/mcp_transport.py",
    "infra/mcp_transport_session.py",
    "infra/mcp_transport_loop.py",
    "infra/mcp_transport_failures.py",
    "infra/config_file.py",
    "infra/config_file_record.py",
    "infra/credentials.py",
    "infra/declaration.py",
    "infra/declaration_record.py",
    "infra/declaration_parties.py",
    "infra/dos_detector.py",
    "infra/dos_detector_cadence.py",
    "infra/gatekeeper.py",
    "infra/gatekeeper_429.py",
    "infra/mailer.py",
    "infra/mailer_provider.py",
    "infra/quota.py",
    "infra/quota_ledger.py",
    "infra/report.py",
    "infra/report_document.py",
    "infra/report_parts.py",
    "infra/token_bucket.py",
    "infra/token_bucket_core.py",
    "infra/token_store.py",
    "infra/token_store_refresh.py",
    "infra/token_store_read.py",
    "infra/token_store_record.py",
    "infra/token_store_file.py",
    "infra/gmail_auth.py",
    "infra/handshake.py",
    "infra/handshake_book.py",
    "infra/handshake_peering.py",
    "infra/handshake_greeting.py",
    "infra/inboxes.py",
    "infra/inboxes_negotiate.py",
    "infra/inboxes_turns.py",
    "infra/inboxes_gate.py",
    "infra/inboxes_state.py",
    "infra/inboxes_keys.py",
    "infra/latency.py",
    "infra/latency_samples.py",
    "infra/tunnel.py",
    "infra/tunnel_ngrok.py",
    "infra/tunnel_address.py",
    "infra/match_log.py",
    "infra/match_log_slots.py",
    "infra/match_log_entry.py",
    "infra/mcp_client.py",
    "infra/mcp_client_retry.py",
    "infra/mcp_client_settings.py",
    "infra/mcp_client_faults.py",
    "infra/mcp_server.py",
    "infra/protocol.py",
    "infra/protocol_control.py",
    "infra/protocol_roles.py",
    "infra/step_zero.py",
    "infra/step_zero_signing.py",
    "infra/step_zero_provenance.py",
    "infra/step_zero_hardware.py",
    "infra/transport_log.py",
    "infra/token_ledger.py",
    "infra/validation.py",
    "infra/validation_shapes.py",
    "infra/validation_primitives.py",
    "runtime/orchestrator_book.py",
    "runtime/orchestrator_core.py",
    "runtime/orchestrator_greeting.py",
    "runtime/orchestrator_agreements.py",
    "runtime/orchestrator_rotation.py",
    "runtime/orchestrator_config.py",
    "runtime/orchestrator_config_digest.py",
    "runtime/orchestrator_scent.py",
    "runtime/orchestrator_scent_lock.py",
    "runtime/deadline.py",
    "runtime/driver_startup.py",
    "runtime/driver_declaration.py",
    "runtime/driver_config.py",
    "runtime/scheduler.py",
    "runtime/state_machine.py",
    "runtime/watchdog.py",
    "ui/banner.py",
    "ui/app.py",
    "ui/paint.py",
    "ui/replay.py",
    "ui/replay_check.py",
    "ui/replay_model.py",
    "ui/verdict.py",
    "ui/verdict_stamp.py",
    "ui/view.py",
    "ui/view_heat.py",
    "strategy/base_types.py",
    "strategy/voice.py",
    "strategy/voice_config.py",
    "domain/providers_backends.py",
    "cli_config.py",
    "cli_announce.py",
    "cli_failures.py",
    "cli_play.py",
    "cli_report.py",
    "cli_report_send.py",
    "cli_arguments.py",
    "ui/app_painter.py",
    "ui/app_frames.py",
    "ui/app_windows.py",
    "shared/appendix_f.py",
    "shared/config.py",
    "shared/config_validation.py",
    "shared/naming.py",
    "shared/result_claim.py",
    "shared/terms.py",
)
"""Modules that must be identical once the package name is normalised."""

DIVERGENT: dict[str, str] = {
    "runtime/driver.py": "names this role and its private config path",
    "cli_identity.py": "holds this role, its private config path and its package name",
    "__main__.py": "names this role, its private config path and its default port",
    "infra/authorize.py": "stamps the role into the token; both agents share one OAuth client",
    "__init__.py": "package docstring names the role this repo implements",
    "domain/outcome.py": "capture-claim framing differs: who is obliged, and to whom",
    "runtime/orchestrator.py": "role default, and the duplicate-role failure differs by side",
    "strategy/base.py": "notes which hooks this role overrides",
    "strategy/loader.py": "reads police_class vs thief_class",
    "domain/barrier_audit.py": "cop-only; the thief has no barriers to replay",
    "strategy/barriers.py": "cop-only; the thief places no barriers",
    "strategy/containment.py": "thief-only; the cop builds the trap rather than reading it",
    "strategy/police_brain.py": "the cop's policy; no counterpart here",
    "strategy/thief_brain_geometry.py": "thief-only; the cop has no counterpart policy",
    "strategy/thief_brain_ranking.py": "thief-only; the cop has no counterpart policy",
    "strategy/thief_brain.py": "the thief's policy; no counterpart there",
}
"""Files that differ on purpose, each with the reason. Not a suppression list."""

_PACKAGE_RE = re.compile(rf"\b({SIBLING_PACKAGE}|{OUR_PACKAGE})\b")


def normalise(text: str) -> str:
    """Erase the package name, which is the one difference we expect."""
    return _PACKAGE_RE.sub("AGENT", text)


def current_branch() -> str | None:
    """The branch this check is running on, if it is not the default one.

    CI does not check out a branch name for a pull request, so the environment
    is consulted first: ``GITHUB_HEAD_REF`` is the PR's source branch and is
    empty for a push, where ``GITHUB_REF_NAME`` carries it instead.
    """
    for variable in ("GITHUB_HEAD_REF", "GITHUB_REF_NAME"):
        name = os.environ.get(variable, "").strip()
        if name and name != "main":
            return name
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    name = result.stdout.strip()
    return name if name and name not in ("main", "HEAD") else None


def _try_clone(destination: Path, ref: str) -> bool:
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, SIBLING_URL, str(destination)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def clone_sibling(destination: Path, ref: str, prefer: str | None = None) -> tuple[Path, str]:
    """Shallow-clone the sibling, preferring a branch of the same name.

    A change to a shared module has to land in both repositories, and until it
    has, each side's branch disagrees with the other's ``main``. Comparing
    against ``main`` therefore turns every paired change red on both sides at
    once, with no merge order that resolves it — which used to be worked
    around by parking the module as an exemption for the duration.

    Preferring a sibling branch of the same name removes the need for that.
    Paired PRs share a branch name, so they are compared against each other;
    once both merge, ``main`` and ``main`` agree and nothing changes. The
    fallback is exact rather than fuzzy: a branch either exists over there or
    the comparison is against ``main``.
    """
    if prefer and _try_clone(destination, prefer):
        return destination / "src" / SIBLING_PACKAGE, prefer
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, SIBLING_URL, str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    return destination / "src" / SIBLING_PACKAGE, ref


def compare(ours: Path, theirs: Path) -> list[str]:
    """Report every shared module that differs, or is missing on either side."""
    problems: list[str] = []
    for relative in SHARED:
        mine, sibling = ours / relative, theirs / relative
        if not mine.exists():
            problems.append(f"{relative}: missing here")
            continue
        if not sibling.exists():
            problems.append(f"{relative}: missing in the sibling repository")
            continue
        if normalise(mine.read_text()) != normalise(sibling.read_text()):
            problems.append(f"{relative}: drifted")
    return problems


def unlisted(ours: Path) -> list[str]:
    """Report modules that are in neither list.

    A new shared module that nobody added to the manifest is unchecked, and
    unchecked is how the last three gaps happened.
    """
    known = set(SHARED) | set(DIVERGENT)
    found = {str(p.relative_to(ours)) for p in ours.rglob("*.py")}
    return sorted(f for f in found - known if not f.endswith("__init__.py"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="main", help="sibling branch to compare against")
    parser.add_argument("--src", default=f"src/{OUR_PACKAGE}", help="our package root")
    parser.add_argument(
        "--no-pair",
        action="store_true",
        help="always compare against --ref, never a sibling branch of the same name",
    )
    args = parser.parse_args()

    ours = Path(args.src)
    workspace = Path(tempfile.mkdtemp(prefix="drift-"))
    compared_against = args.ref
    try:
        theirs, compared_against = clone_sibling(
            workspace / "sibling", args.ref, prefer=None if args.no_pair else current_branch()
        )
        problems = compare(ours, theirs)
        stray = unlisted(ours)
    except subprocess.CalledProcessError as exc:
        print(f"could not clone {SIBLING_URL}: {exc.stderr.strip()}", file=sys.stderr)
        return 2
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    if stray:
        print("modules in neither SHARED nor DIVERGENT (add them to the manifest):")
        for name in stray:
            print(f"  {name}")
    if problems:
        print(f"\nshared modules out of lockstep with {SIBLING_URL}@{compared_against}:")
        for problem in problems:
            print(f"  {problem}")
        print(
            "\nThe two agents duplicate this logic deliberately — sharing a live-state\n"
            "module disqualifies the solution — so a change to one must land in both."
        )
    if problems or stray:
        return 1
    print(f"{len(SHARED)} shared modules in lockstep with {SIBLING_URL}@{compared_against}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
