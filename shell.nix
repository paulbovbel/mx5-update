{ pkgs ? import <nixpkgs> { } }:
pkgs.mkShell {
  packages = [
    pkgs.python3
    pkgs.libusb1
    pkgs._7zz
  ];
  MX5_LIBUSB = "${pkgs.libusb1}/lib/libusb-1.0.so";
}
