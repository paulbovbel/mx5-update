{
  description = "HeadRush MX5 firmware extraction and Fastboot flashing runbook";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      eachSystem = nixpkgs.lib.genAttrs systems;
      forSystem =
        system:
        let
          pkgs = import nixpkgs {
            inherit system;
            # Only the explicitly requested vendor firmware is allowed.
            config.allowUnfreePredicate = pkg: nixpkgs.lib.getName pkg == "mx5-firmware";
          };
          source = pkgs.lib.cleanSourceWith {
            src = self;
            filter =
              path: type:
              let
                name = builtins.baseNameOf path;
              in
              pkgs.lib.cleanSourceFilter path type
              && !(builtins.elem name [
                ".venv"
                ".ruff_cache"
                "__pycache__"
                "build"
                "dist"
              ])
              && !(pkgs.lib.hasSuffix ".egg-info" name);
          };
          firmware = pkgs.callPackage ./nix/firmware.nix { inherit source; };
          bridgeSource = pkgs.callPackage ./nix/mods/bridge-source.nix { };
          namTool = pkgs.callPackage ./nix/mods/nam.nix { };
          composed =
            profile: instances:
            pkgs.callPackage ./nix/composed-firmware.nix {
              inherit source firmware bridgeSource namTool profile instances;
            };
          variants = {
            bridge = composed "bridge" 2;
          } // pkgs.lib.optionalAttrs (system == "x86_64-linux") {
            nam = composed "nam" 2;
            nam-bridge = composed "nam-bridge" 2;
            nam-4 = composed "nam" 4;
            nam-bridge-4 = composed "nam-bridge" 4;
          };
          modFirmware = pkgs.lib.mapAttrs' (
            name: firmware: pkgs.lib.nameValuePair "firmware-${name}" firmware
          ) variants;
          modApps = pkgs.lib.mapAttrs' (
            name: firmware: pkgs.lib.nameValuePair "flash-${name}" {
              type = "app";
              program = "${firmware}/bin/${firmware.flashCommand}";
              meta.description = "Flash experimental ${name} firmware";
            }
          ) variants;
          package = pkgs.callPackage ./nix/package.nix { inherit source firmware; };
        in
        {
          inherit pkgs firmware package modFirmware modApps;
        };
    in
    {
      packages = eachSystem (
        system:
        let
          env = forSystem system;
        in
        {
          default = env.package;
          mx5-update = env.package;
          firmware = env.firmware;
        } // env.modFirmware
      );

      apps = eachSystem (
        system:
        let
          env = forSystem system;
          app = {
            type = "app";
            program = "${env.package}/bin/mx5-extract-firmware";
            meta.description = "Validate and extract official HeadRush MX5 firmware";
          };
        in
        {
          default = app;
          extract-firmware = app;
          flash = {
            type = "app";
            program = "${env.package}/bin/mx5-flash";
            meta.description = "Run the MX5 v2.7 Fastboot flashing sequence";
          };
          fastboot = {
            type = "app";
            program = "${env.pkgs.android-tools}/bin/fastboot";
            meta.description = "Android Fastboot CLI for manual device checks";
          };
        } // env.modApps
      );

      checks = eachSystem (system: {
        package = self.packages.${system}.mx5-update;
        firmware = self.packages.${system}.firmware;
      } // (forSystem system).modFirmware);

      devShells = eachSystem (
        system:
        let
          env = forSystem system;
        in
        {
          default = env.pkgs.mkShell {
            packages = [
              env.pkgs.python3
              env.pkgs.android-tools
              env.pkgs._7zz
              env.pkgs.ruff
              env.pkgs.shellcheck
            ];
            # Deliberately do not depend on firmware: developing/testing the
            # source does not need to download proprietary artifacts.
          };
        }
      );
    };
}
