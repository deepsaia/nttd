class NttdIdleAI extends AIController {
    function Start() {
        // Sleep forever. This AI exists only to create a company slot
        // that nttd agents will control via the GameScript bridge.
        while (true) {
            this.Sleep(2147483647);
        }
    }
}
