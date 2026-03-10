class NttdGSInfo extends GSInfo {
    function GetAuthor()      { return "nttd"; }
    function GetName()        { return "nttd GameScript"; }
    function GetShortName()   { return "NTTD"; }
    function GetDescription() { return "GameScript bridge for nttd — handles queries and actions from the admin port."; }
    function GetVersion()     { return 1; }
    function GetDate()        { return "2026-03-10"; }
    function GetAPIVersion()  { return "15"; }
    function CreateInstance() { return "NttdGS"; }
    function GetURL()         { return ""; }
    function MinVersionToLoad() { return 1; }
}

RegisterGS(NttdGSInfo());
