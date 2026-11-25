import json
import os
import platform
import subprocess
import time
import requests
import config

BOT_TOKEN = os.getenv("POE_LICENSE_BOT_TOKEN", "")
AVAILABLE_CHANNEL_ID = os.getenv("POE_LICENSE_AVAILABLE_CHANNEL_ID", "")
ACTIVATED_CHANNEL_ID = os.getenv("POE_LICENSE_ACTIVATED_CHANNEL_ID", "")

API_BASE = "https://discord.com/api/v10"
HEADERS = {"Authorization": f"Bot {BOT_TOKEN}"}

LICENSE_FILE = config.data_file("license.json")
OFFLINE_GRACE_SECONDS = 7 * 24 * 3600
TRIAL_DURATION_SECONDS = 24 * 3600


def get_hwid():
    """Stable machine ID. Prefer Windows MachineGuid so hostname / reinstall
    of the app cannot mint a new identity. Hostname is last-resort only."""
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
            )
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            if guid and str(guid).strip():
                return str(guid).strip()
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                [
                    "powershell", "-NoProfile", "-Command",
                    "(Get-CimInstance Win32_ComputerSystemProduct).UUID",
                ],
                stderr=subprocess.DEVNULL,
                timeout=8,
            ).decode(errors="ignore").strip()
            if out and "error" not in out.lower() and out.upper() != "UUID":
                return out
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                "wmic csproduct get uuid", shell=True, stderr=subprocess.DEVNULL
            ).decode(errors="ignore")
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            if len(lines) >= 2 and lines[1]:
                return lines[1]
        except Exception:
            pass
    return platform.node() or "UNKNOWN_HWID"


def _same_machine(stored_hwid, hwid=None):
    """True if *stored_hwid* looks like this PC (new MachineGuid or older hostname)."""
    stored = str(stored_hwid or "")
    if not stored:
        return False
    checks = [hwid, get_hwid(), platform.node()]
    for candidate in checks:
        if candidate and (candidate in stored or stored in str(candidate)):
            return True
    return False


def is_trial_key(key):
    return key.strip().upper().startswith("TRIAL")


def _parse_activated(content):
    """Parse 'key | hwid | date [| expires_unix]' lines from #activated-keys."""
    parts = [p.strip() for p in content.split("|")]
    if len(parts) < 2:
        return None
    parsed = {"key": parts[0], "hwid": parts[1], "date": parts[2] if len(parts) > 2 else ""}
    if len(parts) >= 4 and parts[3]:
        try:
            parsed["expires_at"] = float(parts[3])
        except ValueError:
            parsed["expires_at"] = None
    else:
        parsed["expires_at"] = None
    return parsed


def _fetch_messages(channel_id, limit=100):
    """Fetch every message in the channel (Discord caps each request at 100)."""
    messages = []
    before = None
    while True:
        params = {"limit": min(limit, 100)}
        if before:
            params["before"] = before
        resp = requests.get(
            f"{API_BASE}/channels/{channel_id}/messages",
            headers=HEADERS, params=params, timeout=15
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        messages.extend(batch)
        if len(batch) < params["limit"]:
            break
        before = batch[-1]["id"]
        if len(messages) >= 5000:
            break
        time.sleep(0.15)
    return messages


def _delete_message(channel_id, message_id):
    resp = requests.delete(
        f"{API_BASE}/channels/{channel_id}/messages/{message_id}",
        headers=HEADERS, timeout=10
    )
    if resp.status_code not in (204, 200):
        resp.raise_for_status()


def _post_message(channel_id, content):
    resp = requests.post(
        f"{API_BASE}/channels/{channel_id}/messages",
        headers=HEADERS, json={"content": content}, timeout=10
    )
    resp.raise_for_status()
    return resp.json()


def _activation_line(key, hwid, expires_at=None):
    line = f"{key} | {hwid} | {time.strftime('%Y-%m-%d')}"
    if expires_at is not None:
        line += f" | {expires_at}"
    return line


def _find_activated(activated_messages, key, hwid=None):
    """Return (message, parsed) if *key* appears in #activated-keys."""
    key_lower = key.strip().lower()
    for msg in activated_messages:
        parsed = _parse_activated(msg["content"])
        if not parsed:
            continue
        if parsed["key"].lower() != key_lower:
            continue
        if hwid is not None and not _same_machine(parsed["hwid"], hwid):
            continue
        return msg, parsed
    return None, None


def _trial_already_used(activated_messages, hwid):
    for msg in activated_messages:
        parsed = _parse_activated(msg["content"])
        if parsed and is_trial_key(parsed["key"]) and _same_machine(parsed["hwid"], hwid):
            return parsed
    return None


def _is_expired(parsed):
    expires_at = parsed.get("expires_at")
    return expires_at is not None and time.time() > expires_at


def redeem_key(key):
    """First-time activation: consumes an unused key and binds it to this machine.
    Returns (success: bool, message: str)."""
    if not all((BOT_TOKEN, AVAILABLE_CHANNEL_ID, ACTIVATED_CHANNEL_ID)):
        return False, "Configure the three POE_LICENSE environment variables and restart the app."
    key = key.strip()
    if not key:
        return False, "Enter a key."

    hwid = get_hwid()

    try:
        activated = _fetch_messages(ACTIVATED_CHANNEL_ID)

        existing_msg, existing = _find_activated(activated, key)
        if existing:
            if _is_expired(existing):
                return False, "This trial key has expired."
            if _same_machine(existing["hwid"], hwid):
                _save_local(key, hwid, existing.get("expires_at"))
                if is_trial_key(key):
                    _mark_trial_used(hwid)
                return True, "Already activated on this machine."
            return False, "This key has already been used on another machine."

        available = _fetch_messages(AVAILABLE_CHANNEL_ID)
        match = next(
            (m for m in available if m["content"].strip().lower() == key.lower()),
            None
        )
        if not match:
            return False, "Invalid or already-used key."

        if is_trial_key(key):
            blocked, reason = _trial_blocked(activated, hwid)
            if blocked:
                return False, reason
            expires_at = time.time() + TRIAL_DURATION_SECONDS
        else:
            expires_at = None

        # Post to activated first so a failed delete doesn't lose the key entirely.
        _post_message(ACTIVATED_CHANNEL_ID, _activation_line(key, hwid, expires_at))
        _delete_message(AVAILABLE_CHANNEL_ID, match["id"])

        _save_local(key, hwid, expires_at)
        if expires_at:
            _mark_trial_used(hwid)
        if expires_at:
            return True, "Trial license activated (24 hours)."
        return True, "License activated."

    except requests.RequestException as e:
        return False, f"Could not reach license server: {e}"


def start_trial():
    """Disabled: trials are issued as TRIAL- keys in #available-keys only."""
    return False, "Free trial requires a trial key. Enter it above."


def _trial_data_paths():
    programdata = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
    return os.path.join(programdata, "AutoCrafter", ".trial")


def _mark_trial_used(hwid):
    """Survive AppData wipes / reinstalls. Best-effort; Discord is primary."""
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\AutoCrafter")
        winreg.SetValueEx(key, "TrialUsed", 0, winreg.REG_SZ, "1")
        winreg.SetValueEx(key, "TrialHwid", 0, winreg.REG_SZ, hwid)
        winreg.CloseKey(key)
    except Exception:
        pass
    try:
        path = _trial_data_paths()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(hwid)
        if platform.system() == "Windows":
            subprocess.run(
                ["attrib", "+h", "+s", path],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
    except Exception:
        pass


def _local_trial_used(hwid):
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\AutoCrafter")
        used, _ = winreg.QueryValueEx(key, "TrialUsed")
        stored, _ = winreg.QueryValueEx(key, "TrialHwid")
        winreg.CloseKey(key)
        if str(used) == "1" and stored and _same_machine(stored, hwid):
            return True
    except Exception:
        pass
    try:
        path = _trial_data_paths()
        if os.path.exists(path):
            with open(path, "r") as f:
                stored = f.read().strip()
            if stored and _same_machine(stored, hwid):
                return True
    except Exception:
        pass
    return False


def _trial_blocked(activated_messages, hwid):
    prior = _trial_already_used(activated_messages, hwid)
    if prior:
        if _is_expired(prior):
            return True, "Your free trial has already been used on this PC."
        return True, "A trial is already active on this PC. Enter that trial key to resume."
    if _local_trial_used(hwid):
        return True, "Your free trial has already been used on this PC."
    return False, ""


def verify_saved_license():
    """Called on every launch. Confirms the locally-saved key hasn't been revoked.
    Returns (success: bool, message: str)."""
    if not os.path.exists(LICENSE_FILE):
        return False, "No saved license."

    try:
        with open(LICENSE_FILE, "r") as f:
            data = json.load(f)
        key, hwid = data.get("key"), data.get("hwid")
        expires_at = data.get("expires_at")
        if not key or not hwid:
            return False, "Corrupt license file."
    except Exception:
        return False, "Corrupt license file."

    if expires_at is not None and time.time() > expires_at:
        return False, "Your trial has expired. Please purchase a license."

    if not _same_machine(hwid):
        return False, "This license is bound to another PC."

    try:
        activated = _fetch_messages(ACTIVATED_CHANNEL_ID)
        _, parsed = _find_activated(activated, key, hwid=hwid)
        if parsed:
            if _is_expired(parsed):
                return False, "Your trial has expired. Please purchase a license."
            _save_local(key, hwid, parsed.get("expires_at"))
            if is_trial_key(key):
                _mark_trial_used(get_hwid())
            return True, "OK"
        return False, "License revoked or not found."
    except requests.RequestException:
        cached_at = data.get("cached_at", 0)
        if expires_at is not None and time.time() > expires_at:
            return False, "Your trial has expired. Please purchase a license."
        if time.time() - cached_at < OFFLINE_GRACE_SECONDS:
            return True, "OK (offline grace period)"
        return False, "Could not reach the license server and the offline grace period expired."


def _save_local(key, hwid, expires_at=None):
    payload = {"key": key, "hwid": hwid, "cached_at": time.time()}
    if expires_at is not None:
        payload["expires_at"] = expires_at
    with open(LICENSE_FILE, "w") as f:
        json.dump(payload, f)


def read_local_license():
    if not os.path.exists(LICENSE_FILE):
        return None
    try:
        with open(LICENSE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def trial_time_left():
    """Seconds remaining on the local trial, or None if this is a paid / unlimited license."""
    data = read_local_license()
    if not data:
        return None
    expires_at = data.get("expires_at")
    key = data.get("key") or ""
    if expires_at is None and not is_trial_key(key):
        return None
    if expires_at is None:
        return 0.0
    return float(expires_at) - time.time()


def format_trial_remaining(seconds):
    if seconds is None:
        return None
    if seconds <= 0:
        return "Trial ended"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"Trial · {days}d {hours}h left"
    if hours > 0:
        return f"Trial · {hours}h {minutes:02d}m left"
    return f"Trial · {minutes}m {secs:02d}s left"
