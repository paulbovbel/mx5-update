{
  lib,
  stdenv,
  stdenvNoCC,
  fetchurl,
  cmake,
  patchelf,
  zlib,
  ncurses5,
  e2fsprogs,
  util-linux,
  curl,
  xz,
  python3,
}:
let
  pin = (builtins.fromJSON (builtins.readFile ../../mx5_update/mods/sources.json)).nam;
  toolchain = stdenvNoCC.mkDerivation {
    pname = "bootlin-armv7-toolchain";
    version = "2020.08-1";
    src = fetchurl {
      url = "https://toolchains.bootlin.com/downloads/releases/toolchains/armv7-eabihf/tarballs/armv7-eabihf--glibc--stable-2020.08-1.tar.bz2";
      hash = "sha256-e2aCYDr5qbXA5G/VcWVyNIO7aClegn0U0jjmPzOhR6g=";
    };
    nativeBuildInputs = [ patchelf ];
    dontConfigure = true;
    dontBuild = true;
    dontFixup = true;
    installPhase = ''
      mkdir -p "$out"
      cp -r . "$out/"
      chmod -R u+w "$out"
      # Retarget ONLY x86-64 host executables. Leave the ARM sysroot untouched:
      # its glibc 2.31 is the reason not to use a contemporary cross compiler.
      while IFS= read -r -d "" binary; do
        magic=$(od -An -tx1 -N20 "$binary" | tr -d ' \n')
        if [[ "$magic" == 7f454c46020101*3e00 ]]; then
          if patchelf --print-interpreter "$binary" >/dev/null 2>&1; then
            patchelf --set-interpreter "${stdenv.cc.bintools.dynamicLinker}" "$binary"
            patchelf --set-rpath "${lib.makeLibraryPath [ stdenv.cc.cc.lib zlib ncurses5 ]}:$out/lib" "$binary"
          fi
        fi
      done < <(find "$out/bin" "$out/libexec" "$out/arm-buildroot-linux-gnueabihf/bin" -type f -print0)
    '';
    meta.platforms = [ "x86_64-linux" ];
  };
  namCore = fetchurl {
    name = "nam-core-3cde95c354d5ba6da01316cad90b05cfc4855053.tar.gz";
    url = "https://codeload.github.com/sdatkinson/NeuralAmpModelerCore/tar.gz/3cde95c354d5ba6da01316cad90b05cfc4855053";
    hash = "sha256-vB5nHz4CaikQh5lm6XOtGVEypGmta8TDeu+EYywi1nc=";
  };
  eigen = fetchurl {
    url = "https://gitlab.com/libeigen/eigen/-/archive/bc3b39870ecb690a623a3f49149a358b95c5781d/eigen-bc3b39870ecb690a623a3f49149a358b95c5781d.tar.gz";
    hash = "sha256-X2VX0aym6VmkuVXFXyk1Jh/TDeWcDHnjW8bVy+HeItE=";
  };
in
stdenv.mkDerivation {
  pname = "headrush-nam-cli";
  version = pin.revision;
  src = fetchurl {
    name = "headrush-nam-${pin.revision}.tar.gz";
    url = "${pin.archive}/${pin.revision}";
    inherit (pin) hash;
  };
  nativeBuildInputs = [ cmake python3 ];
  buildInputs = [ e2fsprogs util-linux curl xz ];
  postPatch = ''
    mkdir -p nam_core/Dependencies/eigen
    tar xf ${namCore} -C nam_core --strip-components=1
    tar xf ${eigen} -C nam_core/Dependencies/eigen --strip-components=1
    # Packaging-only change in a private source copy: no Docker/network in builds.
    substituteInPlace CMakeLists.txt \
      --replace-fail 'COMMAND ''${CMAKE_SOURCE_DIR}/scripts/build_blobs.sh' \
        'COMMAND bash ''${CMAKE_SOURCE_DIR}/scripts/build_blobs_native.sh'
    export PATH="$PATH:${toolchain}/bin"
  '';
  preBuild = ''
    export PATH="$PATH:${toolchain}/bin"
    # Upstream's Makefile graph can race two rules producing the same blobs.
    # Build them once before CMake's parallel embedding/native compilation.
    (cd ..; bash scripts/build_blobs_native.sh)
  '';
  # Build only the patching CLI, not the GUI or unrelated developer tools.
  buildPhase = ''
    runHook preBuild
    cmake --build . --target gui-core-cli -j "$NIX_BUILD_CORES"
    runHook postBuild
  '';
  installPhase = ''
    mkdir -p "$out/bin" "$out/share/headrush-nam/blobs"
    cp gui-core-cli "$out/bin/"
    cp ../blobs/libnam_hook.so ../blobs/libnam_preload.so "$out/share/headrush-nam/blobs/"
  '';
  # Do not let host fixups touch the ARM payloads copied for provenance.
  dontPatchELF = true;
  dontStrip = true;
  meta = {
    description = "Pinned NAM firmware patcher and ARM payloads (no vendor firmware)";
    license = lib.licenses.gpl3Only;
    platforms = [ "x86_64-linux" ];
  };
}
