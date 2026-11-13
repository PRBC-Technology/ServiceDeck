# ServiceDeck

ServiceDeck is the Sunday control dashboard for the PRBC booth. One computer on the church network runs it. The volunteer on the sound desk, and an iPad on the same Wi-Fi, open it in a browser and run the service from big touch tiles.

Version 1 controls:

- **OBS Studio** — program scenes, Go Live / End Stream, recording, and a stream timer. The Facebook stream uses the stream key already saved in OBS.
- **PTZ cameras** — several cameras, labelled preset buttons, press-and-hold pan/tilt, zoom, speed, and home. The camera protocol is VISCA over IP (Sony / BirdDog style, UDP port 52381).

Planning Center, Proclaim, and the Yamaha TF3 are on the dashboard as tiles you can turn on later. They do not control those systems yet. See [Roadmap](#roadmap).

## Sunday, for the volunteer

1. On the booth PC, open the **ServiceDeck** shortcut (or double-click `Run-ServiceDeck.bat`).
2. Leave that window open. Closing it stops the dashboard. It does not, by itself, stop a stream that OBS has already started.
3. On this PC a browser opens. On the iPad, open Safari to the **Other devices** address printed in the window, for example `http://192.168.1.20:8080`.
4. Enter the passcode. The first time, it is `0000`. Change it before the next Sunday.
5. **Go Live** asks you to confirm, then tells OBS to start the stream it is already set up to send. **End Stream** asks you to confirm too.
6. Scene buttons switch the program scene. Camera preset buttons recall a saved shot. Hold an arrow to move the camera; let go and it stops.
7. Press **Lock** when you walk away. The stream keeps running.

## Set up the booth PC (Windows)

You need Windows 10 or 11 and [Python 3.11 or newer](https://www.python.org/downloads/). During the Python install, tick **Add python.exe to PATH**.

1. Copy this folder onto the booth PC, for example `C:\ServiceDeck`.
2. Double-click `Run-ServiceDeck.bat`.

The first launch creates a `.venv` folder, installs the Python packages, starts the server, and opens a browser. Later launches reuse that environment and check the packages again. Device settings and the passcode are saved in `config\servicedeck.json`. That file stays on this PC.

To start it from a command prompt instead:

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m servicedeck --open-browser
```

The server listens on `0.0.0.0` and port **8080** unless you change the port in Settings. Restart ServiceDeck after a port change. The window prints a link for this computer and one for every other device on the LAN.

### Desktop shortcut

Double-click `Create-Desktop-Shortcut.bat`. It puts **ServiceDeck** on the desktop. The shortcut runs `Run-ServiceDeck.bat`.

If that script is blocked, make the shortcut by hand:

1. Right-click `Run-ServiceDeck.bat`.
2. Choose **Show more options** if you see it, then **Create shortcut**.
3. Drag the shortcut onto the desktop and rename it ServiceDeck.

### iPad on the church Wi-Fi

The iPad and the booth PC have to be on the same network. Cellular data will not reach the PC.

1. Start ServiceDeck and read the **Other devices** line.
2. On the iPad, open Safari and type that address, including `http://` and the port. Safari will not assume a port.
3. Optional: Share → Add to Home Screen. The passcode is still required.

The layout you save in Settings is stored on the booth PC, so the iPad and the PC show the same tiles.

### Windows Firewall

The first time Python listens on the network, Windows may ask for permission. Allow it on **private** networks. Do not allow it on a public network, and do not forward this port from the church router.

If the iPad cannot connect, open **Command Prompt as Administrator** and allow the port (change `8080` if you changed it in Settings):

```bat
netsh advfirewall firewall add rule name="ServiceDeck" dir=in action=allow protocol=TCP localport=8080
```

To remove that rule later:

```bat
netsh advfirewall firewall delete rule name="ServiceDeck"
```

Also set the booth PC not to sleep during the service. A sleeping PC drops the dashboard and the iPad.

## OBS

OBS 28 or newer already includes the WebSocket server.

1. In OBS: **Tools → WebSocket Server Settings**.
2. Enable the WebSocket server.
3. Note the port (usually **4455**) and set a password. **Show Connect Info** shows the current password.
4. In ServiceDeck **Settings**, enter the OBS computer's IP, that port, and that password. Use `127.0.0.1` when OBS is on the same PC as ServiceDeck.
5. Press **Test OBS**. A good result names the OBS version.

Scene buttons are the scenes in OBS. **Go Live** can switch to a start scene first: in Settings, tick **Switch to the start scene when going live** and type the scene name exactly.

### Facebook stream key

Set this once in OBS. ServiceDeck never asks for the key, never stores it, and never sends it. **Go Live** only tells OBS to start the stream it is already configured to send.

1. In Meta's Live Producer, copy the **persistent** stream key for the church page (a one-off key changes and will surprise you next week).
2. In OBS: **Settings → Stream**.
3. Service: **Facebook Live**. Paste the key and apply.
4. Confirm a short test stream from OBS itself before relying on the dashboard.

## Cameras

In **Settings → Cameras**, add each camera:

| Field | Typical value |
| --- | --- |
| Name | What the volunteer should read, such as Main |
| IP address | The camera's fixed address |
| Port | `52381` |
| Protocol | VISCA over IP |

Preset **button** numbers match the camera: button 1 is memory 1. **Save preset…** asks which button, then asks you to confirm, because it overwrites that memory with wherever the camera is pointing now.

Hold an arrow or a zoom button. Releasing it sends stop. **Stop** in the middle of the pad stops pan, tilt, and zoom. **Home** returns the camera to its home position. The speed slider runs from 1 to 24.

The status light is **Connected** when the camera answers a VISCA version inquiry, and **No reply** when it does not. Some cameras answer movement commands even when they ignore inquiries; you can still try the controls. **Test connection** in Settings is the explicit check.

VISCA over IP fixes the camera address at 1, which is the factory address. The packet layer is separate from the tile (`servicedeck/visca.py` builds packets, `servicedeck/drivers/visca_ip.py` sends them). An HTTP/CGI driver can be added later as `servicedeck/drivers/http_cgi.py` without changing the tile. That driver is only a placeholder in v1.

## Settings that stick

`config/servicedeck.json` is created on first launch and is not part of git. It holds:

- the salted passcode hash (not the passcode)
- the bind address and port
- OBS host, port, and WebSocket password
- cameras, protocols, and preset labels
- which tiles are visible, and their order

`config/servicedeck.example.json` is a commented example with sample addresses and no passcode. Keys that start with `_` are ignored if you copy the example over the real file.

## Security

This is a trusted-LAN tool, not a website.

- The first passcode is `0000`, and the lock screen says so until you change it. Pick 4 to 8 digits. `0000` cannot be saved again.
- Only a salted PBKDF2-HMAC-SHA256 hash is stored. Each install gets its own salt.
- After unlock, the browser gets an HttpOnly session cookie. Restarting ServiceDeck logs every device out. Sessions last 12 hours and refresh while the dashboard is in use.
- Five wrong passcodes lock that device out for 30 seconds. Further groups of five wait longer, up to 10 minutes.
- Every control under `/api/` requires the session. The lock screen is the only page that works without it.
- There is no HTTPS. Do not put this on the public internet, and do not port-forward it. Anyone on the church Wi-Fi who knows the passcode can switch scenes, go live, and move cameras.
- `config/servicedeck.json` contains the OBS WebSocket password. It is git-ignored. The settings page does not send that password back to the browser after it is saved.
- Press **Lock** when the desk is unattended. Locking the screen does not stop an active stream.

## Tests

Unit tests do not need OBS, cameras, or a network. From the project folder:

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

On macOS or Linux the same commands work with `python3` and `source .venv/bin/activate`.

Covered without hardware: config load and save, passcode hashing and lockout, the session cookie, and VISCA packet bytes (header, sequence reset, presets, pan/tilt, zoom, home). Before a Sunday, still check the real devices once: OBS test connection, a scene change, a short test stream, a preset recall, and a pan that stops when you let go.

## Adding a tile

Each system is a module under `servicedeck/integrations/` with the same interface:

- `config_schema()` — settings fields
- `status()` — what the tile shows; this must not raise
- `actions()` — commands the tile can send
- `handle_action(action, payload)` — run one command
- `test_connection(payload)` — the Settings test button

Register it in `servicedeck/integrations/registry.py` and `servicedeck/catalog.py`, then render the tile in `servicedeck/static/app.js`. The HTTP routes are already generic: `POST /api/integrations/<id>/actions/<action>`.

Camera protocols implement `servicedeck/drivers/base.py` and are chosen with the camera's `protocol` field. v1 ships `visca_ip` only.

## Roadmap

Not built yet:

- **Planning Center** — today's service order on a tile
- **Proclaim** — current slide and next slide
- **Yamaha TF3** — scene recall and mute groups through Mixing Station
- **Later:** DMX lighting
- **Later:** a presentation-app control beyond Proclaim, if the booth adds one

The three church systems above have placeholder modules and hidden tiles so the layout file already knows their ids. Turning a placeholder tile on shows "Not in this version". It does not pretend to work.

## License

MIT. See [LICENSE](LICENSE).
