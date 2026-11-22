{ lib, stdenvNoCC, fetchurl }:
stdenvNoCC.mkDerivation {
  pname = "mx-edit-source";
  version = "c2ef5344fb01a1a4b2ee3356c1b4d040b8af9688";
  src = fetchurl {
    name = "mx-edit-c2ef5344fb01a1a4b2ee3356c1b4d040b8af9688.tar.gz";
    url = "https://codeload.github.com/TicT4x/MX-Edit/tar.gz/c2ef5344fb01a1a4b2ee3356c1b4d040b8af9688";
    hash = "sha256-v93AHxgQHuE2u8ruYQpW+1ytoWdTSthGhVU3ggLD0zc=";
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
