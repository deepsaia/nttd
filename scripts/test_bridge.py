"""Quick test to verify bridge connects to a running OpenTTD server."""
import asyncio
import logging

from nttd.bridge.admin_client import AdminClient
from nttd.bridge.bridge import Bridge
from nttd.state.world import WorldState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


async def main() -> None:
    world = WorldState()
    client = AdminClient(host="127.0.0.1", port=3977)

    ok = await client.connect(password="nttd", name="nttd-test")
    if not ok:
        print("FAILED to connect. Is OpenTTD running with admin_password=nttd?")
        return

    bridge = Bridge(world, client)
    if client.welcome:
        bridge.apply_welcome(client.welcome)
    await client.subscribe_defaults()

    print(f"Connected! Map: {world.game.map_width}x{world.game.map_height}")
    print(f"Game date: {world.game.game_date}")
    print("Listening for 5 seconds...")

    # Run poll loop for a few seconds to collect data
    poll_task = asyncio.create_task(client.poll_loop())
    await asyncio.sleep(5)
    await client.disconnect()
    poll_task.cancel()

    snapshot = world.snapshot()
    print(f"\nFinal state:")
    print(f"  Game date: {snapshot.game.game_date}")
    print(f"  Companies: {len(snapshot.companies)}")
    for c in snapshot.companies:
        print(f"    [{c.id}] {c.name} - money={c.money}, loan={c.loan}")
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
