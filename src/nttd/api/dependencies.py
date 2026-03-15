from nttd.actions.tracker import ActionTracker
from nttd.bridge.admin_client import AdminClient
from nttd.bridge.bridge import Bridge
from nttd.logging.event_logger import EventLogger
from nttd.runtime.orchestrator import Orchestrator
from nttd.state.agent_registry import AgentRegistry
from nttd.state.snapshot_broker import AgentSnapshotBroker
from nttd.state.world import WorldState

world = WorldState()
agent_registry = AgentRegistry()
action_tracker = ActionTracker()
admin_client = AdminClient()
bridge = Bridge(world, admin_client)
orchestrator = Orchestrator(world, admin_client)
event_logger = EventLogger()

snapshot_broker_registry: dict[str, AgentSnapshotBroker] = {}
