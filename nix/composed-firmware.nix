{
  lib,
  stdenvNoCC,
  python3,
  e2fsprogs,
  bash,
  coreutils,
  android-tools,
  makeWrapper,
  source,
  firmware,
  profile,
  bridgeSource ? null,
  namTool ? null,
  instances ? 2,
}:
let
  withBridge = builtins.elem profile [ "bridge" "nam-bridge" ];
  withNam = builtins.elem profile [ "nam" "nam-bridge" ];
  suffix = profile + lib.optionalString (withNam && instances == 4) "-4";
  command = "mx5-flash-${profile}";
in
assert !withBridge || bridgeSource != null;
assert !withNam || namTool != null;
stdenvNoCC.mkDerivation {
  pname = "mx5-firmware";
  version = "2.7.0-${suffix}";
  dontUnpack = true;
  dontConfigure = true;
  dontBuild = true;
  nativeBuildInputs = [ python3 e2fsprogs makeWrapper ];
  installPhase = ''
    runHook preInstall
    export PYTHONPATH=${source}
    python3 -m mx5_update.compose \
      --stock-bundle ${firmware}/share/mx5-update/Update.img \
      --flasher ${source}/scripts/mx5-flash \
      --profile ${profile} --instances ${toString instances} \
      ${lib.optionalString withBridge "--bridge-source ${bridgeSource}"} \
      ${lib.optionalString withNam "--nam-cli ${namTool}/bin/gui-core-cli"} \
      --output "$out/share/mx5-update"
    python3 ${source}/tests/check_firmware_pins.py \
      "$out/share/mx5-update/${command}" "$out/share/mx5-update"
    mkdir -p "$out/bin"
    cp "$out/share/mx5-update/${command}" "$out/bin/"
    substituteInPlace "$out/bin/${command}" \
      --replace-fail '#!/usr/bin/env bash' '#!${bash}/bin/bash'
    wrapProgram "$out/bin/${command}" \
      --set-default MX5_FIRMWARE_DIR "$out/share/mx5-update" \
      --prefix PATH : "${lib.makeBinPath [ android-tools coreutils ]}"
    "$out/bin/${command}" --help > /dev/null
    runHook postInstall
  '';
  preferLocalBuild = true;
  allowSubstitutes = false;
  passthru.flashCommand = command;
  meta = {
    description = "Locally composed MX5 2.7 firmware: ${suffix} (experimental)";
    license = lib.licenses.unfree;
    platforms = if withNam then [ "x86_64-linux" ] else lib.platforms.linux;
  };
}
