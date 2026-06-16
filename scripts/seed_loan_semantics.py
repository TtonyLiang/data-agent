"""Compatibility entrypoint for the loan-risk semantic runtime seed."""

from scripts.seed_loan_semantic_runtime import (
    async_main,
    load_semantic_file,
    main,
    parse_args,
    seed_loan_semantic_runtime,
)


async def seed_loan_semantics(agent_id: int = 1, db=None):
    if db is not None:
        raise ValueError("seed_loan_semantics no longer supports the legacy table writer")
    return await seed_loan_semantic_runtime(agent_id=agent_id)


if __name__ == "__main__":
    main()
