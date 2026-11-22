{
  description = "Native Linux HeadRush MX5 updater and pinned v2.7 firmware";

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
          source = pkgs.lib.cleanSource self;
          firmware = pkgs.callPackage ./nix/firmware.nix { inherit source; };
          package = pkgs.callPackage ./nix/package.nix { inherit source firmware; };
        in
        {
          inherit pkgs firmware package;
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
        }
      );

      apps = eachSystem (
        system:
        let
          app = {
            type = "app";
            program = "${self.packages.${system}.mx5-update}/bin/mx5-update";
            meta.description = "Native Linux HeadRush MX5 updater";
          };
        in
        {
          default = app;
          mx5-update = app;
        }
      );

      checks = eachSystem (system: {
        package = self.packages.${system}.mx5-update;
        firmware = self.packages.${system}.firmware;
      });

      devShells = eachSystem (
        system:
        let
          env = forSystem system;
        in
        {
          default = env.pkgs.mkShell {
            packages = [
              env.pkgs.python3
              env.pkgs.libusb1
              env.pkgs._7zz
              env.pkgs.ruff
            ];
            MX5_LIBUSB = "${env.pkgs.lib.getLib env.pkgs.libusb1}/lib/libusb-1.0.so";
            # Deliberately do not depend on firmware: developing/testing the
            # source does not need to download proprietary artifacts.
          };
        }
      );
    };
}
