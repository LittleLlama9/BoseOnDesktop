# Bose on Desktop

Control your **Bose QuietComfort Ultra Headphones (1st gen)** from a Windows PC,
without the phone app. A small tray app with a windowed UI that mirrors the
settings side of the mobile app: noise modes, EQ, Immersive Audio, button
shortcut, battery, and device name, over Bluetooth or a USB-C data cable.

> **Unofficial.** Not affiliated with, endorsed by, or authorized by Bose.
> "Bose" and "QuietComfort" are trademarks of their respective owners and are
> used here only to describe hardware compatibility. This app reads and adjusts
> the same user settings the official app exposes. It does not modify or install
> firmware and makes no Bose cloud or account calls.

Built on the BMAP protocol work in
[aaronsb/bosectl](https://github.com/aaronsb/bosectl) (the vendored `pybmap`
layer under `ref-bosectl/`). This project adds a Windows transport, gen-1 device
config, and a desktop UI.

## Features

- **Windowed UI** mirroring the mobile app: noise modes (list, switch, rename,
  create, delete), per-mode noise level, Immersive Audio, and a Settings section
  (device name, shortcut button, technical info, voice prompts).
- **Tray app** showing battery and the current mode, with quick mode switching
  and a background reconnect poll.
- **EQ** read/write, with the level persisted locally and re-applied on
  reconnect (the headphones drop custom EQ to flat on a full reconnect; this
  restores it the way the phone app does).
- **Global hotkeys** for switching modes (Ctrl+Alt+Q / W / E, Ctrl+Alt+N to
  cycle).
- **Two transports**: Bluetooth (SPP virtual COM port) or USB-C (vendor HID),
  auto-selected. USB-C works while wired for analog audio and needs no pairing.

## Requirements

- Windows 10/11.
- Bose QuietComfort Ultra Headphones, 1st gen (product ID `0x4066`).
- Python 3.10+ (use the `py` launcher) if running from source.

Verified on firmware `1.6.7`. Other firmware may differ.

## Install (prebuilt)

Grab `BoseOnDesktop.exe` from the Releases page and run it. It lives in the
system tray; left-click opens the window.

## Run from source

```
py -m pip install -r requirements.txt
py -m pip install -e ref-bosectl/python      # pybmap protocol layer

py boseondesktop_tray.py                      # tray app + window
py -m bosewin.cli status                      # CLI (see below)
```

### Build the exe

```
py -m pip install pyinstaller
py -m PyInstaller --noconfirm BoseOnDesktop.spec
# result: dist\BoseOnDesktop.exe
```

## Connecting

Turn the headphones on and connect them to this PC over Bluetooth (paired is not
enough, they must be connected). Windows exposes an outgoing SPP virtual COM
port; the app finds it automatically by matching the Bose Bluetooth vendor ID in
the port's hardware ID. No manual COM-port setup is needed if the port exists.

If it does not exist: Settings > Bluetooth & devices > More Bluetooth options >
COM Ports > Add > Outgoing > pick the device's Serial Port service.

Over USB-C, connect the headphones with a **data** cable. The app prefers the
USB HID channel when a cable is present and otherwise falls back to Bluetooth.

## CLI

```
py -m bosewin.cli status              # full snapshot (default)
py -m bosewin.cli ports               # list discovered Bose SPP ports
py -m bosewin.cli battery
py -m bosewin.cli eq                  # read 3-band EQ
py -m bosewin.cli eq -- -3 0 2        # set Bass -3, Mid 0, Treble +2 (-10..+10)
py -m bosewin.cli cnc                 # read noise level (0-10, 0 = max ANC)
py -m bosewin.cli cnc 3               # set noise level (editable modes only)
py -m bosewin.cli modes               # list noise modes / custom profiles
py -m bosewin.cli mode Home           # switch to a mode by name
py -m bosewin.cli spatial motion      # Immersive Audio: off / still / motion
py -m bosewin.cli anc on              # ANC on/off
py -m bosewin.cli name "My Bose"      # rename
py -m bosewin.cli sidetone medium
py -m bosewin.cli multipoint on
py -m bosewin.cli buttons             # show shortcut-button mapping
```

(The `--` before negative EQ values stops argparse treating `-3` as a flag.)

## Library

```python
import bosewin
with bosewin.connect() as dev:        # auto-detects COM port + device type
    print(dev.battery())              # 50
    print(dev.eq())                   # [EqBand(Bass,-3), EqBand(Mid,0), ...]
    dev.set_eq(bass=-3, mid=0, treble=2)
```

## How gen-1 noise control differs

Gen-2 writes noise settings to `AudioModesSettingsConfig [31.10]`, which returns
`FuncNotSupp` on gen-1. Gen-1 carries the noise level, Immersive Audio, and ANC
**per mode**, in `ModeConfig [31.6]`. So the app sets the noise level by reading
the current mode's config, changing the field, and writing it back.

Because of that, noise settings only apply to **editable custom modes** (the ones
you create, e.g. Home / Focus). The locked presets Quiet / Aware / Immersion have
fixed levels and cannot be changed. Switch to a custom mode first.

## Scope and safety

- Reads and writes only the standard, unauthenticated settings operators. No
  credentials are extracted and no firmware is touched.
- Getters are verified before setters; the first EQ write test was a no-op.
- Out of scope: firmware updates, audio routing, spatial audio processing, and
  anything that touches Bose cloud services.

## Notes

- Development-only reverse-engineering material is not included in this
  repository.
- Compatibility beyond gen-1 QC Ultra on firmware 1.6.7 is untested.

## License

MIT. See [LICENSE](LICENSE). The vendored `pybmap` layer under `ref-bosectl/` is
MIT licensed by Aaron Bockelie; see `ref-bosectl/LICENSE`.
