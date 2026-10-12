"""Entry point so the worker can run with `python -m app.worker`."""

from app.worker import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
