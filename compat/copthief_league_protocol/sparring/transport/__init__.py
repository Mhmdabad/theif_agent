"""How messages get from one peer to the other.

``loopback`` runs both peers in one process and is what puts a full six-sub-game series in the
zero-dependency test tier — no fastmcp, no sockets, no sleeping. ``faults`` wraps it to inject
exactly the hazards SPEC section 7.1 describes, so the receiver contract is proven against the
conditions it exists for rather than against a calm network.

``server``/``client`` are the real thing and are the only modules in the package that import
fastmcp or open a socket (``guards/no_mail.py`` rule NM-5 enforces that).
"""
