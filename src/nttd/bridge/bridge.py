import logging

from pyopenttdadmin.enums import PacketType
from pyopenttdadmin.packet import (
    CompanyEconomyPacket,
    CompanyInfoPacket,
    CompanyRemovePacket,
    DatePacket,
    WelcomePacket,
)

from nttd.bridge.admin_client import AdminClient
from nttd.schemas.company import Company
from nttd.state.world import WorldState

logger = logging.getLogger(__name__)


class Bridge:
    """Connects AdminClient events to WorldState updates."""

    def __init__(self, world: WorldState, client: AdminClient) -> None:
        self.world = world
        self.client = client
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.client.on(PacketType.SERVER_DATE, self._on_date)
        self.client.on(PacketType.SERVER_COMPANY_INFO, self._on_company_info)
        self.client.on(PacketType.SERVER_COMPANY_ECONOMY, self._on_company_economy)
        self.client.on(PacketType.SERVER_COMPANY_REMOVE, self._on_company_remove)

    def _on_date(self, packet: DatePacket) -> None:
        self.world.game.game_date = packet.date
        self.world.game.tick += 1

    def _on_company_info(self, packet: CompanyInfoPacket) -> None:
        company = self.world.companies.get(packet.id)
        if company is None:
            company = Company(id=packet.id)
        company.name = packet.name
        company.manager = packet.manager_name
        company.color = packet.color.value
        company.is_ai = packet.is_ai
        company.is_active = True
        self.world.update_company(company)
        logger.info("Company %d: %s (manager=%s, ai=%s)", packet.id, packet.name, packet.manager_name, packet.is_ai)

    def _on_company_economy(self, packet: CompanyEconomyPacket) -> None:
        company = self.world.companies.get(packet.id)
        if company is None:
            company = Company(id=packet.id)
        company.money = packet.money
        company.loan = packet.current_loan
        company.income = packet.income
        if packet.quarterly_info and len(packet.quarterly_info) > 0:
            company.value = packet.quarterly_info[0].get("company_value", 0)
        if packet.quarterly_info and len(packet.quarterly_info) > 1:
            company.profit_last_year = packet.quarterly_info[1].get("income", 0)
        self.world.update_company(company)

    def _on_company_remove(self, packet: CompanyRemovePacket) -> None:
        company = self.world.companies.get(packet.id)
        if company is not None:
            company.is_active = False
            logger.info("Company %d removed: %s", packet.id, packet.admin_remove_reason)

    def apply_welcome(self, welcome: WelcomePacket) -> None:
        self.world.game.map_width = welcome.mapwidth
        self.world.game.map_height = welcome.mapheight
        self.world.game.landscape = str(welcome.landscape)
        self.world.game.game_date = welcome.startdate
