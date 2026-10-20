"""
Resolve recorded key names to pynput Key/KeyCode and handle special keys
(e.g. Ctrl+Alt+Delete on Windows).
"""
import sys
from pynput.keyboard import Key


# All pynput Key enum names (with and without "Key." prefix) for reliable lookup
_KEY_NAMES = [
    "alt", "alt_l", "alt_r", "alt_gr", "backspace", "caps_lock",
    "cmd", "cmd_l", "cmd_r", "ctrl", "ctrl_l", "ctrl_r",
    "delete", "down", "end", "enter", "esc",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10",
    "f11", "f12", "f13", "f14", "f15", "f16", "f17", "f18", "f19", "f20",
    "home", "insert", "left", "menu", "num_lock",
    "page_down", "page_up", "pause", "print_screen", "right",
    "scroll_lock", "shift", "shift_l", "shift_r", "space", "tab", "up",
    "media_play_pause", "media_volume_mute", "media_volume_down", "media_volume_up",
    "media_previous", "media_next",
]

# Map: normalized name (no "Key." prefix) -> Key member
KEY_MAP = {}
for name in _KEY_NAMES:
    member = getattr(Key, name, None)
    if member is not None:
        KEY_MAP[name] = member

# Special key that cannot be sent via normal APIs (Windows Secure Attention Sequence)
CTRL_ALT_DELETE_ALIASES = ("ctrl_alt_delete", "ctrl+alt+delete", "ctrl_alt_del", "Key.ctrl_alt_delete")


def resolve_paste_key(paste_key) -> Key:
    """Resolve a paste_key string/Key to a pynput Key. Used by both recorders."""
    if paste_key is None:
        return Key.f8
    if isinstance(paste_key, Key):
        return paste_key
    name = str(paste_key).replace("Key.", "").strip().lower()
    return KEY_MAP.get(name, Key.f8)


def resolve_button(btn_str: str):
    """Resolve a recorded button string (e.g. 'Button.left') to a pynput Button."""
    from pynput.mouse import Button
    if "left" in btn_str:
        return Button.left
    if "right" in btn_str:
        return Button.right
    if "middle" in btn_str:
        return Button.middle
    return None


def resolve_key(key_value):
    """
    Resolve a recorded key value (str from JSON) to something pynput can press/release.

    Returns:
        tuple: (resolved, is_ctrl_alt_delete)
        - resolved: a single character (str), a Key member, or a KeyCode; or None to skip
        - is_ctrl_alt_delete: if True, caller should call send_ctrl_alt_delete() instead
    """
    if not isinstance(key_value, str):
        return None, False

    key_str = key_value.strip()

    # Special: Ctrl+Alt+Delete (handled by OS on Windows, not by pynput)
    if key_str.lower() in CTRL_ALT_DELETE_ALIASES:
        return None, True

    # Single character (including Unicode from JSON e.g. "\u0003" -> one char)
    if len(key_str) == 1:
        return key_str, False

    # "Key.xxx" or "xxx" -> look up in Key enum
    normalized = key_str.replace("Key.", "").strip().lower()
    if normalized in KEY_MAP:
        return KEY_MAP[normalized], False

    # Try direct attribute name (e.g. "ctrl_l")
    member = getattr(Key, normalized, None)
    if member is not None:
        return member, False

    return None, False


def send_ctrl_alt_delete():
    """
    Send Ctrl+Alt+Delete (Secure Attention Sequence) on Windows.
    On other platforms, or if the OS blocks it, does nothing and returns False.

    Note: Windows blocks normal key simulation for this combination. We try
    the SendSAS API when available (e.g. some Windows versions); otherwise
    playback will skip or you may need to run with elevated privileges.
    """
    if sys.platform != "win32":
        return False
    try:
        # Windows: try sas.dll SendSAS (Windows 8+); may require elevation
        sas = getattr(__import__("ctypes").windll, "sas", None)
        if sas is not None:
            # SendSAS(TRUE) = send SAS
            result = sas.SendSAS(1)
            if result:
                return True
    except Exception:
        pass
    try:
        # Fallback: some setups use user32 (undocumented / version-dependent)
        user32 = __import__("ctypes").windll.user32
        if hasattr(user32, "SendSAS"):
            result = user32.SendSAS(1)
            if result:
                return True
    except Exception:
        pass
    return False
