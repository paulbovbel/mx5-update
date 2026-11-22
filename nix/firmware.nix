{
  lib,
  stdenvNoCC,
  fetchurl,
  python3,
  _7zz,
  source,
}:
stdenvNoCC.mkDerivation {
  pname = "mx5-firmware";
  version = "2.7.0";

  src = fetchurl {
    name = "headrush-mx5-2.7-windows-updater.zip";
    url = "https://cdn.inmusicbrands.com/HeadRush/FW/Aug24_Firmware_Updates/MX5%20v2.7/Windows%20Updater/HeadRush%20MX5%202.7%20Firmware%20Updater%20-%20Win.exe.zip";
    hash = "sha256-W1jODuBc59BUwhXM8qttPn+C5yx4ZN0mL+XywtSZlR4=";
  };

  dontUnpack = true;
  dontConfigure = true;
  dontBuild = true;
  nativeBuildInputs = [
    python3
    _7zz
  ];

  installPhase = ''
    runHook preInstall
    export PYTHONPATH=${source}
    python3 -m mx5_update "$src" --output "$out/share/mx5-update"
    python3 ${source}/tests/check_firmware_pins.py \
      ${source}/scripts/mx5-flash "$out/share/mx5-update"
    runHook postInstall
  '';

  # Fetch from the vendor and build locally; do not encourage redistribution
  # through binary caches without reviewing the vendor's license.
  preferLocalBuild = true;
  allowSubstitutes = false;

  meta = {
    description = "Official HeadRush MX5 v2.7 firmware, validated and extracted";
    homepage = "https://www.headrushfx.com/downloads.html";
    license = lib.licenses.unfree;
    platforms = lib.platforms.linux;
  };
}
