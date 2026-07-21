# Bose on Desktop

A Windows clone of the settings side of the Bose Music app for the
**QuietComfort Ultra Headphones (1st gen)**. Adjust noise modes, EQ, Immersive
Audio, the shortcut button, and the device name from your PC, over **Bluetooth
or USB-C**. Built on the BMAP work in
[aaronsb/bosectl](https://github.com/aaronsb/bosectl).

> **Unofficial.** Not affiliated with or endorsed by Bose. It only reads and
> writes the same user settings the official app does. No firmware, no cloud, no
> account.

## Install

Download `BoseOnDesktop.exe` from [Releases](../../releases) and run it. It sits
in the system tray; left-click opens the window.

Or run from source:

```
py -m pip install -r requirements.txt
py -m pip install -e ref-bosectl/python
py boseondesktop_tray.py
```

## Caveats

- **1st-gen QC Ultra only**, tested on firmware 1.6.7. The 2nd-gen QC Ultra
  shares the same protocol family, so the CLI/library may work, but the app is
  built around 1st-gen noise handling and is untested there. Feel free to try it
  and report back.
- **Noise level only applies to custom modes** (Home / Focus / etc). The presets
  Quiet / Aware / Immersion are locked; switch to a custom mode to change it.
- **Bluetooth:** the headphones must be connected (not just paired); the app
  finds the Bose SPP COM port automatically.
- **USB-C:** use a data cable. The app prefers USB when a cable is present,
  otherwise Bluetooth.

## License

MIT. The vendored `pybmap` layer under `ref-bosectl/` is MIT by Aaron Bockelie.
