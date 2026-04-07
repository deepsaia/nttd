class NttdIdle extends AIInfo {
    function GetAuthor()      { return "nttd"; }
    function GetName()        { return "nttd Idle"; }
    function GetDescription() { return "Does nothing. Placeholder company for nttd-controlled agents."; }
    function GetVersion()     { return 1; }
    function GetDate()        { return "2025-01-01"; }
    function CreateInstance() { return "NttdIdleAI"; }
    function GetShortName()   { return "IDLE"; }
    function GetAPIVersion()  { return "15"; }
}

RegisterAI(NttdIdle());
