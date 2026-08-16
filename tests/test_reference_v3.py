from thief_agent.reference_v3 import Observation, PoliceSearchPolicy, ThiefSearchPolicy


def observation(role: str) -> Observation:
    return Observation(
        role=role,
        step=1,
        self_pos=(0, 0) if role == "police" else (3, 3),
        board_size=7,
        barriers=(),
        legal_moves=("S", "E", "STAY") if role == "police" else ("N", "S", "E", "W", "STAY"),
        barrier_targets=((0, 0), (0, 1), (1, 0)) if role == "police" else (),
        barriers_left=14,
        steps_left=34,
        rival_scent={"3,3": 0.9} if role == "police" else {"0,0": 0.9},
    )


def test_search_policies_only_return_kit_legal_actions() -> None:
    import random

    for policy, role in ((PoliceSearchPolicy(), "police"), (ThiefSearchPolicy(), "thief")):
        obs = observation(role)
        action = policy.decide(obs, random.Random(7))
        assert action.move in obs.legal_moves
        assert action.barrier is None or action.barrier in obs.barrier_targets
