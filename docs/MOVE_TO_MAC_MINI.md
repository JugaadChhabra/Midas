# Moving Midas to the Mac mini

Two scripts do the whole move: `move-out.ps1` on the Windows office machine and `move-in.sh` on the Mac mini.
Each runs in one go and stops at the first problem, before anything that can't be undone. Each one writes a log
(`logs\move-out.txt` / `logs/move-in.txt`); if a script stops, send that log to Claude.

Plan for about 1–2 hours. Most of that is the database restore on the Mac, which needs no attention.

## Before you start

- [ ] The Mac mini is on the **office network** (same network as the NAS), signed in, and you know its password.
- [ ] Have a USB stick ready, or use AirDrop, to carry one zip file from Windows to the Mac. The zip holds the
      passwords and API keys, so keep it off chat if you can.
- [ ] Pick a quiet time. Midas is off from step 1 until the Mac finishes. Don't do it around midnight IST, when
      the nightly backup runs.

## On the Windows machine

1. Copy these three files from the repo into `D:\My Data\Desktop\midas`, next to `start.bat`:
   - `move-out.ps1`
   - `move-out.bat`
   - `move-in.sh`
2. Make sure Docker Desktop is running.
3. Double-click **`move-out.bat`**. It:
   1. checks the files the Mac needs are all there
   2. waits for Shorts cuts in progress to finish (at most 20 minutes)
   3. stops the app, so nothing writes to the database or YouTube any more
   4. records row counts for 10 tables, then publishes a **final NAS snapshot**. This takes 10–30 minutes. If it
      fails, the script restarts Midas on this machine and stops, so nothing is lost.
   5. stops every container
   6. writes **`midas-move-<date>.zip`** to the Desktop
   7. renames `.env` to `.env.moved-<date>`, so `start.bat` can't start Midas here again by accident
4. When it says **DONE**, copy the zip to the Mac mini.
5. Leave this machine off, or at least **never run `start.bat` on it again**. If two machines run Midas, both write
   to YouTube, and the old one's midnight backup would overwrite the NAS snapshot with stale data.

## On the Mac mini

1. Unzip `midas-move-<date>.zip` and move the `midas-move-<date>` folder somewhere permanent, for example your
   home folder renamed to `~/midas`. **This folder is Midas from now on**: the database, logs and Shorts cache
   live in it.
2. Open **Terminal** in that folder (right-click the folder in Finder > New Terminal at Folder) and run:

   ```bash
   bash move-in.sh
   ```

3. When asked, type your **Mac password** (once). Nothing shows while you type; that's normal.
4. If **Docker Desktop** opens a window, accept its terms. If Docker isn't installed and Homebrew isn't either,
   the script stops and tells you to install Docker Desktop for Mac (Apple chip) first. Install it, open it once,
   then run `bash move-in.sh` again.
5. If macOS asks whether Terminal or Docker may **find devices on the local network**, or accept
   **incoming connections**, click **Allow**.
6. Wait. The script:
   1. removes Windows line endings from the config files
   2. installs Rosetta and pins the app to `linux/amd64`. The app image is built for Intel/AMD only, so it runs
      emulated on the Mac's Apple chip.
   3. checks the NAS is reachable
   4. pulls the images and starts everything
   5. lets the app restore the database from the NAS. This is the long part: up to 2 hours, with a progress line
      every 2 minutes.
   6. compares row counts with the Windows machine's. It stops if any differ.
   7. turns off sleep, makes the Mac restart after a power cut, and adds Docker to the login items
7. When it says **DONE**, it prints the new address for the team, `http://<mac-ip>:8000`.

## After the move

- [ ] Open `http://localhost:8000` on the Mac and sign in.
- [ ] Send the team the new address. Everyone has to sign in again.
- [ ] Keep the Mac **on and signed in**. Docker only runs while a user is logged in.
- [ ] Tell Claude the Mac is live, so `STATE.md`, the office runbook and the memory notes get updated. The
      runbook's PowerShell commands become Terminal commands.

## Everyday commands on the Mac

Run these in Terminal, in the Midas folder:

| What | Command |
|---|---|
| Stop Midas | `docker compose down` |
| Start Midas (pulls the latest image) | `docker compose up -d` |
| Watch the live log | `docker compose logs -f midas` |
| NAS snapshot (after a DB change) | `docker compose exec -T midas python -c "from app.backup import snapshot_to_nas; print(snapshot_to_nas())"` |

## If something goes wrong

- **`move-out` stopped before "App stopped"**: nothing changed. Fix what it says and run it again.
- **`move-out` snapshot failed**: Midas is running again on Windows; nothing moved. Send `logs\move-out.txt`.
- **`move-in` can't reach the NAS**: check the Mac is on the office network, and allow Local Network access
  (System Settings > Privacy & Security > Local Network) for Terminal and Docker. Then run it again.
- **`move-in` says the app crashed during the restore**: it has already stopped the app. Send `logs/move-in.txt`.
  Once the cause is fixed: `docker compose down && rm -rf pgdata`, then `bash move-in.sh` again.
- **`move-in` reports a row-count MISMATCH**: run `docker compose stop midas` and send the log. Don't let it run.
- **The Mac fails and you need Windows back**: on Windows, rename `.env.moved-<date>` back to `.env` and
  double-click `start.bat`. Its database still holds exactly what the snapshot holds.
