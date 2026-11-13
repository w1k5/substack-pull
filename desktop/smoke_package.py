"""Exercise the packaged engine using a fresh data directory and no credentials."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check_mcp(engine, env):
    params = StdioServerParameters(command=engine, args=["mcp"], env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert "publication_summary" in {tool.name for tool in tools.tools}


def main():
    engine = str(Path(sys.argv[1]).resolve(strict=True))
    internal = Path(engine).parent / "_internal"
    assert (internal / "substack_local/dashboard/static/index.html").is_file()
    with TemporaryDirectory() as directory:
        env = {**os.environ, "CLEARVIEW_DATA_DIR": directory}
        result = subprocess.check_output([engine, "connection", "current"], env=env, timeout=40)
        assert json.loads(result) == {"publication": None, "connected": False}
        subprocess.run([engine, "dashboard", "--help"], env=env, check=True, timeout=40)
        asyncio.run(asyncio.wait_for(check_mcp(engine, env), timeout=60))


if __name__ == "__main__":
    main()
