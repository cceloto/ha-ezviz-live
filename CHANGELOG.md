# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.0.2] - 2026-11-01

### Added

- Integration logo (`logo.png`, `dark_logo.png` and @2x variants) for Home Assistant's integration pages.
- README banner (also shown on the HACS repository page) and a GitHub social preview image for link previews.
- `tools/make_brand.py`, which regenerates every brand image.
- Issue forms for bug reports, feature requests, and documentation/texts/translations, next to the device report;
  blank issues are disabled.
- README: tested hardware, a clearer compatibility matrix (device types, features, how to check a device),
  how Home Assistant picks the language, how to contribute, and a "Built with Claude Code" disclosure.

### Fixed

- Device model now shows the commercial name (e.g. `DP2C`, as the EZVIZ app and the core integration show it);
  the full product code moved to `model_id`, and the firmware version is filled in.
- Device linking on Home Assistant 2026.8+, where every integration owns its own device: the camera's device
  shares the core EZVIZ identifier and MAC address, so it is listed as a linked device, and it gets the core
  device's area once when it is created.
- The motion-picture fallback for thumbnails now looks up the core device unambiguously.

### Changed

- New integration icon: cloud camera lens with a live dot on a blue gradient, legible down to 32 px.

## [0.0.1] - 2026-11-01

### Added

- Cloud live view (video and audio) for EZVIZ cameras over the VTM/VTDU stream servers, with ECDH-encrypted
  commands and media, served to Home Assistant's `stream` component as HLS.
- Session reuse from the core EZVIZ integration: no credentials asked for or stored.
- On-demand sessions shared by all viewers, closed 5 s after the last one leaves.
- Thumbnails that never wake the device: last frame of the previous session, or the core integration's last
  motion picture.
- HLS-only by default; optional WebRTC through go2rtc.
- One camera entity per live-capable channel, attached to the existing EZVIZ device.
- Experimental support for devices with image encryption (verification code from the core integration) and a
  repair issue when the code is missing.
- Diagnostics with masked serials.
- English and Brazilian Portuguese translations.
- Integration icon (original artwork, not the EZVIZ logo).

Tested with: EZVIZ DP2C (CS-DP2C-R100-6E2WPFB-GD, firmware V5.3.3 build 250911), Home Assistant 2026.10.4.

[Unreleased]: https://github.com/cceloto/ha-ezviz-live/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/cceloto/ha-ezviz-live/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/cceloto/ha-ezviz-live/releases/tag/v0.0.1
