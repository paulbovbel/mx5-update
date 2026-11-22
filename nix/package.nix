{
  lib,
  python3Packages,
  makeWrapper,
  libusb1,
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

  doCheck = true;
  checkPhase = ''
    runHook preCheck
    python -m unittest discover -s tests -v
    "$out/bin/mx5-update" inspect > /dev/null
    "$out/bin/mx5-update" plan > /dev/null
    runHook postCheck
  '';
  pythonImportsCheck = [ "mx5_update" ];

  postFixup = ''
    wrapProgram "$out/bin/mx5-update" \
      --set MX5_LIBUSB "${lib.getLib libusb1}/lib/libusb-1.0.so" \
      --set-default MX5_FIRMWARE "${firmware}/share/mx5-update/Update.img" \
      --prefix PATH : "${lib.makeBinPath [ _7zz ]}"
  '';

  passthru = { inherit firmware; };

  meta = {
    description = "Linux updater for HeadRush MX5 with official v2.7 firmware";
    homepage = "https://github.com/paulbovbel/mx5-update";
    mainProgram = "mx5-update";
    platforms = lib.platforms.linux;
  };
}
