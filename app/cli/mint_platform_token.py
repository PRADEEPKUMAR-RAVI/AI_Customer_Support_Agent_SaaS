"""Mint a ``scope=platform`` JWT for M10 ops. The operator identity is a separate principal,
never a tenant-scoped staff JWT [IMP-SEC-9] — this repo has no self-serve login or table for it
(the M10 gotcha explicitly says "keep it tiny"), so an out-of-band CLI mint is the POC story.

Usage: ``python -m app.cli.mint_platform_token [--actor-id UUID] [--ttl-seconds N]``
"""

from __future__ import annotations

import argparse
import uuid

from app.core.security import create_token

_DEFAULT_TTL_SECONDS = 24 * 3600


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--actor-id", default=None,
        help="UUID identifying this operator in platform_audit_log (random if omitted)",
    )
    parser.add_argument("--ttl-seconds", type=int, default=_DEFAULT_TTL_SECONDS)
    args = parser.parse_args()

    actor_id = args.actor_id or str(uuid.uuid4())
    token = create_token({"scope": "platform", "sub": actor_id}, args.ttl_seconds)
    print(f"actor_id={actor_id}")
    print(f"token={token}")


if __name__ == "__main__":
    main()
