# ServiceDeck

ServiceDeck is the Sunday control dashboard for the PRBC booth. One computer on the church network runs it. The volunteer on the sound desk, and an iPad on the same Wi-Fi, open it in a browser and run the service from big touch tiles.

The screen is a set of tabs sized for an 11-inch iPad (about 1194×834 landscape and 834×1194 portrait) and a desktop browser. Each tab is one screen: Stream, Cameras, Sound, Service, and Settings. Tiles can be moved between the first four tabs. That layout is saved on the booth PC.

What the tabs control:

- **Stream** — OBS Studio: program scenes, Go Live / End Stream, recording, and a stream timer. The Facebook stream uses the stream key already saved in OBS.
- **Cameras** — PTZ cameras over VISCA over IP (Sony / BirdDog style, UDP port 52381): labelled presets, press-and-hold pan/tilt, zoom, speed, and home.
- **Sound** — Yamaha TF3 over SCP on TCP port 49280: eight channel faders at a time, custom banks, DCA faders, the stereo master, and scene recall.
- **Service** — today's Planning Center plan (read-only) and Proclaim remote control.

## Sunday, for the volunteer

1. On the booth PC, open the **ServiceDeck** shortcut (or double-click `Run-ServiceDeck.bat`).
2. Leave that window open. Closing it stops the dashboard. It does not, by itself, stop a stream that OBS has already started.
3. On this PC a browser opens. On the iPad, open Safari to the **Other devices** address printed in the window, for example `http://192.168.1.20:8080`.
4. Enter the passcode. The first time, it is `0000`. Change it before the next Sunday.
5. Use the tabs along the top. **Go Live** asks you to confirm, then tells OBS to start the stream it is already set up to send. **End Stream** asks you to confirm too.
6. Scene buttons switch the program scene. Camera preset buttons recall a saved shot. Hold an arrow to move the camera; let go and it stops.
7. On **Sound**, drag a fader or tap On. Scene buttons ask before they recall. On **Service**, the plan is read-only. If Planning Center is live, the current item is highlighted. If it is not, Previous and Next step through the order.
8. Press **Lock** when you walk away. The stream keeps running.

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
- Planning Center application id and secret
- Proclaim host and remote password
- TF3 address, channel banks, DCA labels, and scene buttons
- which tiles are visible, which tab they sit on, and their order

`config/servicedeck.example.json` is a commented example with sample addresses and no passcode. Keys that start with `_` are ignored if you copy the example over the real file.

## Security

This is a trusted-LAN tool, not a website.

- The first passcode is `0000`, and the lock screen says so until you change it. Pick 4 to 8 digits. `0000` cannot be saved again.
- Only a salted PBKDF2-HMAC-SHA256 hash is stored. Each install gets its own salt.
- After unlock, the browser gets an HttpOnly session cookie. Restarting ServiceDeck logs every device out. Sessions last 12 hours and refresh while the dashboard is in use.
- Five wrong passcodes lock that device out for 30 seconds. Further groups of five wait longer, up to 10 minutes.
- Every control under `/api/` requires the session. The lock screen is the only page that works without it.
- There is no HTTPS. Do not put this on the public internet, and do not port-forward it. Anyone on the church Wi-Fi who knows the passcode can switch scenes, go live, and move cameras.
- `config/servicedeck.json` contains the OBS password, the Planning Center secret, and the Proclaim remote password. It is git-ignored. After a secret is saved, Settings does not send it back to the browser.
- Press **Lock** when the desk is unattended. Locking the screen does not stop an active stream.

## Planning Center

In Settings → Service, enter a [Personal Access Token](https://api.planningcenteronline.com/docs/overview/authentication) application id and secret. They are stored only in `config/servicedeck.json`. Load the service types, pick the Sunday service, and save.

The Service tab shows that service type's plan for today, or the next plan if today has none: title, date, ordered items (songs, headers, and other items, with lengths), and who is scheduled. If a Planning Center Live session is running, its current item is highlighted. Otherwise Previous and Next walk the order on this dashboard only. They do not change Planning Center.

The last successful plan is cached in `config/planning_center_cache.json`. If the internet drops mid-service, the tile keeps showing that copy and says so.

## Proclaim

Proclaim's documented remote is HTTP on port **52195**, which cannot be changed. In Proclaim: **Settings → Remote → Enable**, and set a network control password if ServiceDeck is not running on the Proclaim computer.

The tile can send:

| Control | Command | Confirmed in Proclaim's public article |
| --- | --- | --- |
| Next slide | `nextSlide` | Yes |
| Pre-service, warm-up, service, post-service | `StartPreService`, `StartWarmUp`, `StartService`, `StartPostService` | Yes |
| On air / off air | `GET /onair/session` | Yes. This is the only documented status. Proclaim does not report the current slide or item. |
| Previous slide, previous item, next item | `previousSlide`, `previousServiceItem`, `nextServiceItem` | Not in the article's command list we could retrieve. These are the names Bitfocus Companion uses. Treat them as unverified until someone presses them on the real Proclaim. |

## Yamaha TF3

The mixer is controlled with Yamaha's SCP text protocol on TCP **49280**. Details, including what is confirmed and what still needs the console, are in [docs/yamaha-tf3.md](docs/yamaha-tf3.md).

Settings → Sound stores the mixer IP, up to eight channels per bank in any order, DCA labels, and the scene buttons. The Sound tab keeps the stereo master on screen, shows one bank or the DCAs, and asks before recalling a scene. Fader moves are throttled while a finger is down. Levels are polled back from the console when it answers.

## iPad layout

Tabs stay on screen. A tab's tiles fill the space under them, and a long service order scrolls inside its tile rather than pushing the page. Buttons are at least 44 pixels. Settings is split into General, OBS, Cameras, Sound, Service, and Tabs so each section is one screen, with a long camera list scrolling inside that section only.

In Settings → Tabs, show or hide a tile, choose its tab, and move it up or down. That choice is stored with the other settings and is the same on every device.

## Tests

Unit tests do not need OBS, cameras, or a network. From the project folder:

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

On macOS or Linux the same commands work with `python3` and `source .venv/bin/activate`.

Covered without hardware: config load and save, passcode hashing and lockout, the session cookie, VISCA packet bytes, Planning Center plan selection and the offline cache, Proclaim command URLs, and TF3 SCP command lines and reply parsing. Before a Sunday, still check the real devices once. The power outage means none of the network devices have been exercised from this build.

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

- DMX lighting
- A presentation control other than Proclaim, if the booth adds one

## License

MIT. See [LICENSE](LICENSE).
