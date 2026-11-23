{ lib, stdenvNoCC, fetchurl }:
let
  pin = (builtins.fromJSON (builtins.readFile ../../mx5_update/mods/sources.json)).bridge;
in
stdenvNoCC.mkDerivation {
  pname = "mx-edit-source";
  version = pin.revision;
  src = fetchurl {
    name = "mx-edit-${pin.revision}.tar.gz";
    url = "${pin.archive}/${pin.revision}";
    inherit (pin) hash;
  };
  dontConfigure = true;
  dontBuild = true;
  # Device scripts and ARM SQLite must never undergo host fixups.
  dontFixup = true;
  installPhase = ''
    mkdir -p "$out"
    cp -r . "$out/"
  '';
  meta.license = lib.licenses.mit;
}
