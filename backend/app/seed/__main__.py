from app.seed import main
import asyncio, sys

raise SystemExit(asyncio.run(main(sys.argv[1:])))
