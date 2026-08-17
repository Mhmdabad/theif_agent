from thief_agent.reference_v3 import Observation, PoliceSearchPolicy, ThiefSearchPolicy, _fallback
from thief_agent.strategy.police_search import DEPTH


def observation(role: str) -> Observation:
    return Observation(
        role=role,
        step=1,
        self_pos=(0, 0) if role == "police" else (3, 3),
        board_size=7,
        barriers=(),
        legal_moves=("MOVE:S", "MOVE:E", "STAY")
        if role == "police"
        else ("MOVE:N", "MOVE:S", "MOVE:W", "MOVE:E", "STAY"),
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


def test_thief_move_is_translated_instead_of_falling_back_to_north() -> None:
    import random

    action = ThiefSearchPolicy().decide(observation("thief"), random.Random(7))

    assert action.move == "MOVE:S"


def test_police_search_sees_three_of_its_own_decisions() -> None:
    assert DEPTH == 5


def test_police_search_uses_the_negotiated_barrier_budget() -> None:
    import random

    policy = PoliceSearchPolicy()
    obs = observation("police")
    policy.decide(obs, random.Random(7))

    assert policy.brain.max_barriers == obs.barriers_left + len(obs.barriers)


def test_police_fallback_closes_distance_instead_of_taking_first_move() -> None:
    obs = observation("police")
    obs = Observation(**{**obs.__dict__, "self_pos": (3, 3), "legal_moves": ("MOVE:E", "MOVE:W")})

    assert _fallback(obs, (3, 0)).move == "MOVE:W"
