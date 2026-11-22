{
  lib,
  python3Packages,
  makeWrapper,
  android-tools,
  bash,
  coreutils,
  shellcheck,
  _7zz,
  source,
  firmware,
}:
python3Packages.buildPythonApplication {
  pname = "mx5-update";
  version = "0.1.0";
  src = source;
  pyproject = true;

  build-system = [ python3Packages.setuptools ];
  nativeBuildInputs = [ makeWrapper ];
  nativeCheckInputs = [ shellcheck ];

  doCheck = true;
  checkPhase = ''
    runHook preCheck
    python -m unittest discover -s tests -v
    bash -n scripts/mx5-flash
    shellcheck scripts/mx5-flash
    "$out/bin/mx5-extract-firmware" --help > /dev/null
    "$out/bin/mx5-flash" --help > /dev/null
    "$out/bin/mx5-extract-firmware" "${firmware}/share/mx5-update/Update.img" \
      --output "$TMPDIR/installed-firmware"
    python tests/check_firmware_pins.py scripts/mx5-flash "$TMPDIR/installed-firmware"
    runHook postCheck
  '';
  pythonImportsCheck = [ "mx5_update" ];

  postFixup = ''
    substituteInPlace "$out/bin/mx5-flash" \
      --replace-fail '#!/usr/bin/env bash' '#!${bash}/bin/bash'
    wrapProgram "$out/bin/mx5-extract-firmware" \
      --prefix PATH : "${lib.makeBinPath [ _7zz ]}"
    wrapProgram "$out/bin/mx5-flash" \
      --set-default MX5_FIRMWARE_DIR "${firmware}/share/mx5-update" \
      --prefix PATH : "${lib.makeBinPath [ android-tools coreutils ]}"
  '';

  passthru = { inherit firmware; };

  meta = {
    description = "MX5 firmware preparation and fail-fast Fastboot flashing script";
    homepage = "https://github.com/paulbovbel/mx5-update";
    mainProgram = "mx5-extract-firmware";
    platforms = lib.platforms.linux;
  };
}
