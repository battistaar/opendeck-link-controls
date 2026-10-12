# Link Controls for OpenDeck

An [OpenDeck](https://github.com/nekename/OpenDeck) plugin for Insta360 Link webcams on
Linux. It drives the camera through [linkctl](https://github.com/battistaar/insta360_link_control),
so it needs no other dependencies.

## Actions

| Action | Settings |
| --- | --- |
| **Pan / Tilt** | Direction; step in degrees, or continuous movement while the key is held, with a speed from 1 (about 2.5°/s) to 10 (about 26°/s) |
| **Zoom** | In or out; step, or continuous zoom while held |
| **AI Tracking** | Toggles tracking. The key shows whether tracking is on. |
| **Preset** | Preset number, and whether it is stored on this computer or in the camera (slots 1–6) |

Presets are saved from the Link Control GUI or with `linkctl preset save N [--camera]`.

## Only talks to the camera when it has to

- Movement and zoom keys only act while an application is streaming the camera's video,
  because the gimbal does not move otherwise. They show an alert instead.
- The tracking key's state is refreshed every 2 s, but only while a tracking key is on the
  deck and some application has the camera open. Whether the camera is open is read from
  `/proc`, without touching the camera. While idle, the key shows the mode linkctl last set.
- If an application holds the camera open without streaming (the linkctl GUI with the
  preview off, for example), the plugin asks the camera whether video is flowing every 2 s.

## Install

1. Install linkctl with pipx (`pipx install .` in a checkout of insta360_link_control).
2. Run `./install.sh`. It copies the plugin into `~/.config/opendeck/plugins` and restarts
   OpenDeck. Run it again after changing the plugin.
3. Drag the actions from the **Link Controls** category onto your keys.

The plugin runs on linkctl's own Python interpreter, found from the `linkctl` command.
It logs to `~/.local/state/opendeck-link-controls/plugin.log`; set `LINKCONTROLS_DEBUG=1`
in OpenDeck's environment for every camera access.

## Development

- `tools/make_icons.py` redraws the icons (needs Pillow).
- `tests/hardware_test.py` runs the plugin against a fake OpenDeck and a real camera. It
  moves the camera and needs computer preset 1 and camera preset 6 saved. Quit OpenDeck first:
  its own copy of the plugin holds the camera open, which the test would see as an
  application using it.

  ```bash
  "$(head -1 "$(readlink -f "$(command -v linkctl)")" | cut -c3-)" tests/hardware_test.py
  ```

## License

MIT
