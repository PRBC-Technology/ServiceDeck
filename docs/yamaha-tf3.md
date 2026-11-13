# Yamaha TF3 network control

ServiceDeck talks to the TF3 with Yamaha's SCP text protocol. This note is what that implementation is based on. Nothing in this file has been checked against the church's console; a power outage delayed that.

## Transport

- TCP, port **49280**. This is the mixer-control port in Yamaha's CL/QL/TF remote examples, not a Dante port.
- One command per line, ended with a newline (`\n`).
- The console replies with a line beginning `OK`, `OKm`, `NOTIFY`, or `ERROR`.
- `NOTIFY` is an unsolicited change (someone moved a fader on the console). ServiceDeck skips those while it is waiting for the reply to its own command, and polls the strips it is showing.
- A TF1 SCP log shows the console identifying itself with `OK devinfo productname "TF1"`. ServiceDeck sends `devinfo productname` and also reads the stereo on/off fader, so a test still works if the product-name command differs.

Give the console a fixed IP under **Network → Static IP** on the mixer-control interface. Put that address in ServiceDeck Settings → Sound.

## Levels and channel numbers

Fader values are decibels times 100.

| Position | Value |
| --- | --- |
| +10 dB | `1000` |
| 0 dB | `0` |
| −10 dB | `-1000` |
| Silence | `-32768` |

The on-screen fader uses silence at the bottom and then a straight line from −60 dB to +10 dB. Sends are throttled to about one every 80 ms while a finger is down, plus a final send on release.

Console channel 1 is protocol index 0. Yamaha's command list gives the TF3 and TF5 input indexes **0–39** (40 channels). TF1 and TF-Rack stop at 31. ServiceDeck allows 1–40 in the bank editor.

## Commands ServiceDeck sends

Input channel, DCA, and stereo master share one shape. `x` is the index. The second number is `0`.

```
get MIXER:Current/InCh/Fader/Level x 0
set MIXER:Current/InCh/Fader/Level x 0 <level>
get MIXER:Current/InCh/Fader/On x 0
set MIXER:Current/InCh/Fader/On x 0 <0|1>
```

DCA, index 0–7:

```
get MIXER:Current/DCA/Fader/Level x 0
set MIXER:Current/DCA/Fader/Level x 0 <level>
get MIXER:Current/DCA/Fader/On x 0
set MIXER:Current/DCA/Fader/On x 0 <0|1>
```

Stereo master:

```
get MIXER:Current/St/Fader/Level 0 0
set MIXER:Current/St/Fader/Level 0 0 <level>
get MIXER:Current/St/Fader/On 0 0
set MIXER:Current/St/Fader/On 0 0 <0|1>
```

Scribble-strip name, from a TF1 log (`Label/Name`, not `Fader/Name`):

```
get MIXER:Current/InCh/Label/Name x 0
```

Scene recall. TF scenes are two banks, A and B, numbers 0–99. Yamaha's TF examples use `ssrecall_ex scene_a 0` for scene A0 and `ssrecall_ex scene_b 1` for scene B1. CL/QL use a different command (`ssrecall_ex MIXER:Lib/Scene`). ServiceDeck uses the TF form only.

```
ssrecall_ex scene_a 0
ssrecall_ex scene_b 12
```

There is no confirmed command that returns the list of scene names. The buttons on the Sound tab are the labels stored in ServiceDeck. Recalling one always asks for confirmation.

## Banks

The Sound tab shows eight strips plus the stereo master. Settings decides which input indexes sit in which bank, in any order, with a custom label on each slot. A DCA view shows the eight DCA faders. The master stays on screen in both views.

## What is not confirmed on this TF3

- The DCA address `MIXER:Current/DCA/Fader` is the Yamaha RCP address used on the wider CL/QL/TF family. It has not been answered by this console.
- `MIXER:Current/St/Fader` is the stereo address in the TF-oriented RCP notes. Same caveat.
- `devinfo productname` is taken from a TF1 session log. The test connection does not depend on it alone.
- `Label/Name` is from that same TF1 log. Some write-ups use `Fader/Name` instead.
- Whether `NOTIFY` lines are reliable enough to skip polling. ServiceDeck polls the visible bank, the DCAs, and the master about every couple of seconds.
- Scene names, and whether `sscurrent_ex` (seen on QL) works on TF. Recall is send-only.
- Fader law at the very bottom of the physical fader (the −138 dB region versus −32768). The on-screen fader jumps to silence only at the bottom of the travel.

When the console is back, the first checks are: Test connection, move channel 1 a little and see it move on the desk, tap On, recall a spare scene, and confirm a DCA and the stereo master hit the right faders.
