import binascii
import inspect
import discord.ui
import json
import win32event
import win32api
# from fileinput import close
import aiohttp
import gspread
import discord
from typing import Optional
import imagehash
from discord import Message
import asyncio
from datetime import datetime, timedelta
import win32process
from fuzzywuzzy import fuzz, process
import pyautogui
import win32gui
import win32ui
import win32con
import pygetwindow as gw
import ctypes
from ctypes import wintypes
import cv2
import numpy as np
import time
import sys
import atexit
import requests
import os
from pathlib import Path
import shutil
import pytesseract
import random
from PIL import Image, ImageFilter, ImageOps
from typing import Tuple
import PIL
import functools
from threading import Lock
import re
import io
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import logging
from difflib import SequenceMatcher
import subprocess
# from doctr.models import recognition_predictor
import warnings
import uuid
import websockets
# from numpy.random import random_integers

# identify tesseract folder in lieu of PATH
TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA_DIR = r"C:\Program Files\Tesseract-OCR\tessdata"
DISABLE_TESS_DAWGS_FOR_GAME_OCR = True
TESS_DAWG_OFF_FLAGS = "-c load_system_dawg=0 -c load_freq_dawg=0"
DEFAULT_OCR_WHITELIST = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789[] '
ANOM_SCAN_REV = "2026-02-09-row-walk-r10"
pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE
os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR
try:
    TESSDATA_DIR_SHORT = win32api.GetShortPathName(TESSDATA_DIR)
except Exception:
    TESSDATA_DIR_SHORT = TESSDATA_DIR
tessdata_dir_config = f'--tessdata-dir {TESSDATA_DIR_SHORT}'


@functools.lru_cache(maxsize=256)
def build_tesseract_config(psm=8, whitelist=None, preserve_spaces=True):
    parts = [tessdata_dir_config, f'--psm {int(psm)}']
    if DISABLE_TESS_DAWGS_FOR_GAME_OCR:
        parts.append(TESS_DAWG_OFF_FLAGS)
    if whitelist:
        parts.append(f'-c tessedit_char_whitelist={whitelist}')
    if preserve_spaces:
        parts.append('-c preserve_interword_spaces=1')
    return ' '.join(parts)


@functools.lru_cache(maxsize=64)
def _whitelist_char_set(whitelist):
    allowed = set(whitelist or '')
    allowed.update({'\n', '\r', '\t'})
    return frozenset(allowed)


def _apply_char_whitelist(text, whitelist):
    if not whitelist:
        return text
    allowed = _whitelist_char_set(whitelist)
    return ''.join(ch for ch in text if ch in allowed)


def _detect_cjk_or_cyrillic(text):
    has_cjk = any(('\u3400' <= ch <= '\u4dbf') or ('\u4e00' <= ch <= '\u9fff') for ch in text)
    has_cyrillic = any('\u0400' <= ch <= '\u052f' for ch in text)
    return has_cjk, has_cyrillic


def _extract_corp_tag(text):
    if not text:
        return ''
    patterns = [
        r'\[([^\[\]\r\n]{2,20})\]',
        r'\u3010([^\u3010\u3011\r\n]{2,20})\u3011',
        r'\(([^\(\)\r\n]{2,20})\)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            corp_inner = match.group(1).strip()
            if corp_inner:
                return f'[{corp_inner}]'
    return ''


def _strip_leading_corp_tag(text):
    if not text:
        return ''
    return re.sub(
        r'^\s*(?:\[[^\[\]\r\n]{1,24}\]|\u3010[^\u3010\u3011\r\n]{1,24}\u3011|\([^\(\)\r\n]{1,24}\))\s*',
        '',
        text
    )


def _compose_corp_and_name(corp_tag, name_text):
    corp_tag = (corp_tag or '').strip()
    name_text = (name_text or '').strip()
    if not corp_tag:
        return name_text
    if not name_text:
        return corp_tag
    if name_text.startswith(corp_tag):
        return name_text
    return f'{corp_tag}{_strip_leading_corp_tag(name_text).strip()}'.strip()


def _looks_like_latin_ocr_noise_for_cjk(text):
    """
    Heuristic gate for a cheap CJK rescue pass.
    We only trigger when the OCR output looks like transliterated/noisy Latin text.
    """
    if not text:
        return False

    body = _strip_leading_corp_tag(text)
    compact = ''.join(ch for ch in body if not ch.isspace())
    if len(compact) < 5:
        return False
    if any(ord(ch) > 127 for ch in compact):
        return False

    latin_chars = [ch for ch in compact if ('A' <= ch <= 'Z') or ('a' <= ch <= 'z')]
    if len(latin_chars) < max(4, int(len(compact) * 0.6)):
        return False

    lower = ''.join(ch.lower() for ch in latin_chars)
    vowel_count = sum(ch in 'aeiou' for ch in lower)
    vowel_ratio = (vowel_count / len(lower)) if lower else 0.0

    confusable_count = sum(ch in 'Il1Oo0' for ch in compact)
    confusable_ratio = confusable_count / len(compact)

    upper_positions = [i for i, ch in enumerate(compact) if 'A' <= ch <= 'Z']
    upper_scatter = (
        len(upper_positions) >= 3
        and upper_positions[0] == 0
        and (upper_positions[-1] - upper_positions[0] >= 4)
    )

    no_vowel_long = len(lower) >= 7 and vowel_count <= 1

    return (
        no_vowel_long
        or (upper_scatter and confusable_ratio >= 0.10)
        or (vowel_ratio < 0.22 and confusable_ratio >= 0.20)
    )


# import langdetect
PIL.Image.ANTIALIAS = PIL.Image.LANCZOS  # Pil deprecation workaround

print('[startup] Preparing scout...')

scout = None
model_name = 'crnn_mobilenet_v3_small'
screen_capture_lock = Lock()

# Constants
guild_id = 920343361544679514
# EC2_WEBSOCKET_URL = "ws://ec2-54-198-110-160.compute-1.amazonaws.com:6789"
# WEBSOCKET_SERVER_URI = "ws://<server-ip>:6789"  # Replace <server-ip> with the IP or hostname of your server
HEARTBEAT_INTERVAL = 1  # Interval in seconds between heartbeats
heartbeat_task = None  # To store the heartbeat task reference
MUTEX_NAME = "Global\\EVE_REFUEL_MUTEX"
# Uptime/status display knobs.
# In VS Code's integrated terminal, updating the *window title* usually isn't visible, so an in-place status line
# tends to be the most useful.
UPTIME_STATUS_TO_CONSOLE_INPLACE = True  # Updates a single console line in-place (no scrolling).
UPTIME_STATUS_INPLACE_PERIOD_SECONDS = 5
UPTIME_STATUS_TO_CONSOLE = False  # If True, logs periodic uptime lines to console (adds lines / can get noisy).
UPTIME_STATUS_PERIOD_SECONDS = 60
UPTIME_STATUS_TO_TITLE = False  # If True, updates the console window title with uptime.
UPTIME_TITLE_PERIOD_SECONDS = 5
UI_DEBUG_DEFAULT = False
BASE_FRAME_WIDTH = 960
BASE_FRAME_HEIGHT = 540
INPUT_BACKEND_PYAUTOGUI = "pyautogui"
INPUT_BACKEND_UINPUT = "uinput"
DEFAULT_EMUINPUT_SERIAL = "127.0.0.1:5555"
DEFAULT_EMUINPUT_HOST_PORT = 27183
DEFAULT_EMUINPUT_ADB_EXE = "adb"
DEFAULT_EMUINPUT_ADB_SERVER_PORT = 5037
DEFAULT_EMUINPUT_ROTATION = "auto"
DEFAULT_EMUINPUT_AUTOFIX = True

_emuinput_adb_cls = None
_emuinput_controller_cls = None
_emuinput_import_error = None
_emuinput_controller = None
_emuinput_hello = None
_emuinput_resolved_adb_exe = None
_emuinput_lock = threading.RLock()

# Logging setup for console output only
logging.basicConfig(
    level=logging.INFO,  # Set the minimum logging level
    format='%(asctime)s [%(levelname)s] %(message)s',  # Log format
    handlers=[logging.StreamHandler()]  # Output to console (stdout)
)


def startup_info(msg, *args):
    logging.info("[startup] " + msg, *args)


def startup_warn(msg, *args):
    logging.warning("[startup] " + msg, *args)


def startup_error(msg, *args):
    logging.error("[startup] " + msg, *args)


# Uses the ctypes library to load the user32.dll dynamic-link library
user32 = ctypes.WinDLL('user32')
shcore = ctypes.WinDLL('shcore')
# Define PrintWindow signature
PrintWindow = user32.PrintWindow
PrintWindow.restype = wintypes.BOOL
PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
_dpi_aware_initialized = False


def _ensure_process_dpi_aware() -> None:
    global _dpi_aware_initialized
    if _dpi_aware_initialized:
        return
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        return
    _dpi_aware_initialized = True


class _PullWinCaptureContext:
    """
    Reuse GDI capture objects for pull_win to avoid per-frame allocation churn.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._hwnd = None
        self._width = 0
        self._height = 0
        self._hwnd_dc = None
        self._mfc_dc = None
        self._save_dc = None
        self._save_bitmap = None

    def _release_unlocked(self):
        if self._save_bitmap is not None:
            try:
                win32gui.DeleteObject(self._save_bitmap.GetHandle())
            except Exception:
                pass
            self._save_bitmap = None

        if self._save_dc is not None:
            try:
                self._save_dc.DeleteDC()
            except Exception:
                pass
            self._save_dc = None

        if self._mfc_dc is not None:
            try:
                self._mfc_dc.DeleteDC()
            except Exception:
                pass
            self._mfc_dc = None

        if self._hwnd_dc is not None and self._hwnd is not None:
            try:
                win32gui.ReleaseDC(self._hwnd, self._hwnd_dc)
            except Exception:
                pass
            self._hwnd_dc = None

        self._hwnd = None
        self._width = 0
        self._height = 0

    def _recreate_unlocked(self, hwnd, width, height):
        self._release_unlocked()
        self._hwnd = hwnd
        self._width = int(width)
        self._height = int(height)
        self._hwnd_dc = win32gui.GetWindowDC(hwnd)
        self._mfc_dc = win32ui.CreateDCFromHandle(self._hwnd_dc)
        self._save_dc = self._mfc_dc.CreateCompatibleDC()
        self._save_bitmap = win32ui.CreateBitmap()
        self._save_bitmap.CreateCompatibleBitmap(self._mfc_dc, self._width, self._height)
        self._save_dc.SelectObject(self._save_bitmap)

    def _ensure_unlocked(self, hwnd, width, height):
        if (
            self._save_bitmap is None or
            self._save_dc is None or
            self._mfc_dc is None or
            self._hwnd_dc is None or
            self._hwnd != hwnd or
            self._width != int(width) or
            self._height != int(height)
        ):
            self._recreate_unlocked(hwnd, width, height)

    def capture(self, hwnd, width, height, flags):
        with self._lock:
            self._ensure_unlocked(hwnd, width, height)
            result = PrintWindow(hwnd, self._save_dc.GetSafeHdc(), flags)
            bmpinfo = self._save_bitmap.GetInfo()
            bmpstr = self._save_bitmap.GetBitmapBits(True)
            return bool(result), bmpinfo, bmpstr

    def reset(self):
        with self._lock:
            self._release_unlocked()


class _DesktopBitBltCaptureContext:
    """
    Reuse desktop DC/memory DC/bitmap for BitBlt captures (overlay path).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._desktop_dc_handle = None
        self._src_dc = None
        self._mem_dc = None
        self._bitmap = None
        self._width = 0
        self._height = 0

    def _release_unlocked(self):
        if self._bitmap is not None:
            try:
                win32gui.DeleteObject(self._bitmap.GetHandle())
            except Exception:
                pass
            self._bitmap = None

        if self._mem_dc is not None:
            try:
                self._mem_dc.DeleteDC()
            except Exception:
                pass
            self._mem_dc = None

        if self._src_dc is not None:
            try:
                self._src_dc.DeleteDC()
            except Exception:
                pass
            self._src_dc = None

        if self._desktop_dc_handle is not None:
            try:
                win32gui.ReleaseDC(0, self._desktop_dc_handle)
            except Exception:
                pass
            self._desktop_dc_handle = None

        self._width = 0
        self._height = 0

    def _recreate_unlocked(self, width, height):
        self._release_unlocked()
        self._width = int(width)
        self._height = int(height)
        self._desktop_dc_handle = win32gui.GetDC(0)
        self._src_dc = win32ui.CreateDCFromHandle(self._desktop_dc_handle)
        self._mem_dc = self._src_dc.CreateCompatibleDC()
        self._bitmap = win32ui.CreateBitmap()
        self._bitmap.CreateCompatibleBitmap(self._src_dc, self._width, self._height)
        self._mem_dc.SelectObject(self._bitmap)

    def _ensure_unlocked(self, width, height):
        if (
            self._bitmap is None or
            self._mem_dc is None or
            self._src_dc is None or
            self._desktop_dc_handle is None or
            self._width != int(width) or
            self._height != int(height)
        ):
            self._recreate_unlocked(width, height)

    def capture(self, left, top, width, height):
        with self._lock:
            self._ensure_unlocked(width, height)
            self._mem_dc.BitBlt((0, 0), (int(width), int(height)), self._src_dc, (int(left), int(top)), win32con.SRCCOPY)
            bmpinfo = self._bitmap.GetInfo()
            bmpstr = self._bitmap.GetBitmapBits(True)
            return bmpinfo, bmpstr

    def reset(self):
        with self._lock:
            self._release_unlocked()


_pull_win_capture_ctx = _PullWinCaptureContext()
_grab_screen_capture_ctx = _PullWinCaptureContext()
_overlay_blt_capture_ctx = _DesktopBitBltCaptureContext()


def _cleanup_capture_contexts() -> None:
    _pull_win_capture_ctx.reset()
    _grab_screen_capture_ctx.reset()
    _overlay_blt_capture_ctx.reset()


atexit.register(_cleanup_capture_contexts)


def _format_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02}h {minutes:02}m {secs:02}s"
    if hours:
        return f"{hours:02}h {minutes:02}m {secs:02}s"
    return f"{minutes:02}m {secs:02}s"


def _set_console_title(title: str) -> None:
    # Avoid breaking execution if running without a console or on non-Windows environments.
    try:
        ctypes.windll.kernel32.SetConsoleTitleW(str(title))
    except Exception:
        return


_status_line_lock = threading.Lock()
_status_line_len = 0
_status_line_last = ""


def _clear_status_line() -> None:
    """Best-effort clear of the current status line (does not print a newline)."""
    global _status_line_len
    if _status_line_len <= 0:
        return
    try:
        with _status_line_lock:
            sys.stdout.write("\r" + (" " * _status_line_len) + "\r")
            sys.stdout.flush()
            _status_line_len = 0
    except Exception:
        return


def _write_status_line(msg: str) -> None:
    """
    Best-effort in-place status line update for terminals like VS Code's integrated terminal.
    Uses carriage return + padding (no ANSI required).
    """
    global _status_line_len, _status_line_last
    try:
        msg = str(msg)
        with _status_line_lock:
            pad = max(0, _status_line_len - len(msg))
            sys.stdout.write("\r" + msg + (" " * pad))
            sys.stdout.flush()
            _status_line_len = len(msg)
            _status_line_last = msg
    except Exception:
        return


def _status_line_cleanup_on_exit() -> None:
    # Leave the terminal in a sane state (cursor not stuck on the status line).
    try:
        if _status_line_len > 0:
            _clear_status_line()
            sys.stdout.write("\n")
            sys.stdout.flush()
    except Exception:
        return


atexit.register(_status_line_cleanup_on_exit)


class _StatusAwareStreamHandler(logging.StreamHandler):
    """Ensures log lines don't get appended onto the in-place status line."""

    def emit(self, record):
        try:
            _clear_status_line()
            super().emit(record)
            if UPTIME_STATUS_TO_CONSOLE_INPLACE and _status_line_last:
                _write_status_line(_status_line_last)
        except Exception:
            self.handleError(record)


def _install_status_aware_logging_handler() -> None:
    if not UPTIME_STATUS_TO_CONSOLE_INPLACE:
        return
    try:
        root = logging.getLogger()
        fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        for h in list(root.handlers):
            root.removeHandler(h)
        handler = _StatusAwareStreamHandler(stream=sys.stdout)
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except Exception:
        return


_install_status_aware_logging_handler()

# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# pytesseract.pytesseract.tesseract_cmd = 'C:/Program Files/Tesseract-OCR/tesseract.exe'


def _tesseract_startup_check():
    try:
        version = pytesseract.get_tesseract_version()
        logging.info("Tesseract version: %s", version)
    except Exception as exc:
        logging.warning("Tesseract version check failed: %s", exc)

    try:
        result = subprocess.run(
            [pytesseract.pytesseract.tesseract_cmd, "--list-langs"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            logging.info("Tesseract languages:\n%s", result.stdout.strip())
        else:
            logging.warning(
                "Tesseract --list-langs failed (code %s): %s",
                result.returncode,
                result.stderr.strip(),
            )
    except Exception as exc:
        logging.warning("Tesseract --list-langs failed: %s", exc)


_tesseract_startup_check()

# Determine if the application is a frozen executable or a script file
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
    script_filename = os.path.splitext(os.path.basename(sys.executable))[0]
else:
    application_path = os.path.dirname(__file__)
    script_filename = os.path.splitext(os.path.basename(__file__))[0]

# Continue with setting up the configuration filename and path
config_filename = f'config_{script_filename}.txt'
config_search_paths = [
    os.path.join(application_path, config_filename),
    os.path.join(os.getcwd(), config_filename),
    os.path.join(os.path.dirname(application_path), config_filename),
]
config_filepath = next((p for p in config_search_paths if os.path.exists(p)), config_search_paths[0])

# Define global variables
last_message_content = ''
last_message_channel = ''
channel_id = ''
eyes_running = False
last_center_crop_pixel_count = 69
flask_server_url = 'http://ec2-54-198-110-160.compute-1.amazonaws.com:5000/update_heartbeat'
target_hwnd = None
pause_requested = False
resume_time = None
# refuel_delay = time.time()
refuel_delay = time.time() + random.randint(1800, 3600)
contact_peep_delay = time.time() + random.randint(1080, 2700)
scanning_active = True  # Flag to control scanning state
current_enemy_list = {}
sheets_buffer = []
detected_enemies = []
captured_screenshots = {}
num_worker_threads = 5
channel = None
worksheet = None
client_busy = False
window_height = None
instance_mutex_handle = None
top_inset_override_px = None
auto_top_inset_cache_px = None

with open('systems.txt', 'r') as file:
    system_list = [line.strip() for line in file]

# Dictionary mapping category names to Discord role IDs
role_ids = {
    'Super': '1267872006767120384',
    'VAC': '1267911151425949749',
    'Capital': '1267911341075857523',
    'Blop': '1267911725651464353',
    'Bomber': '1267911440975527957',
    'Cyno': '1267911569623486465',
    'Interdictor': '1267911624195571855',
    'Miner': '1270084975990935685',
    'Transport': '1270084599007023174',
    'PVP': '1267918668734664857',
    'All': '1267879547765002373',
    'AOA': '1350294951451426917'
}

# Define the ping categories based on the given structure
ping_categories = {
    'Super': ['Supercarriers'],
    'VAC': ['Versatile Assault Ships'],
    'Capital': ['Dreadnoughts', 'Force Auxiliaries', 'Carriers'],
    'Blop': ['Special Ops Battleships'],
    'Bomber': ['Stealth Bombers', 'Bomber Battleships'],
    'Cyno': ['Covert Ops', 'Force Recon Ships'],
    'Interdictor': ['Interdictors', 'Heavy Interdiction Cruisers'],
    'Miner': ['Industrial Command Ships', 'Mining Barges', 'Expedition Frigate'],
    'Transport': ['Transport Ships', 'Freighters', 'Jump Freighters']
}

# List of ships that should be in the PVP ping category
pvp_ships = [
    'Worm', 'Dramiel', 'Cruor', 'Astero', 'Garmur', 'Succubus', 'Daredevil',
    'Condor Interceptor', 'Condor II Interceptor', 'Slasher Interceptor', 'Slasher II Interceptor',
    'Executioner Interceptor', 'Executioner II Interceptor', 'Atron Interceptor', 'Atron II Interceptor',
    'Gila', 'Cynabal', 'Ashimmu', 'Stratios', 'Orthrus', 'Phantasm', 'Vigilant', 'Chameleon',
    'Saleos', 'Fiend', 'Adrestia', 'Naga', 'Naga II', 'Naga III', 'Tornado', 'Tornado II',
    'Tornado III', 'Oracle', 'Oracle II', 'Oracle III', 'Talos', 'Talos II', 'Talos III',
    'Scorpion', 'Scorpion II', 'Raven', 'Raven Striker', 'Rokh', 'Maelstrom', 'Typhoon',
    'Typhoon II', 'Tempest', 'Tempest Striker', 'Armageddon', 'Armageddon II', 'Apocalypse Striker',
    'Apocalypse', 'Abaddon', 'Megathron Striker', 'Dominix', 'Dominix II', 'Megathron', 'Hyperion',
    'Rattlesnake', 'Machariel', 'Bhaalgorn', 'Nestor', 'Barghest', 'Nightmare', 'Vindicator',
    'Raven Navy Issue', 'Tempest Fleet Issue', 'Apocalypse Navy Issue', 'Megathron Navy Issue',
    'Dominix Navy Issue', 'Rokh Bomber', 'Maelstrom Bomber', 'Abaddon Bomber', 'Hyperion Bomber',
    "Cobra", "Marzio", "Azazel", "Anubis", "Annihilator"
]


def categorize_ship(ship_type, ship_category): # <--- CORRECTED: Removed ship_categoris_tmp parameter
    role_pings = []

    # Check if the ship is in the PVP list
    if ship_type in pvp_ships:
        role_pings.append(role_ids['PVP'])

    # Check the ping category based on the ship category
    for category, ship_list in ping_categories.items(): # CORRECTED: Loop variable renamed to ship_list
        if ship_category in ship_list:
            role_pings.append(role_ids[category])

    return role_pings


# Create a lock for synchronization
lock = threading.Lock()


# Function to clean and categorize ship types using fuzzy matching
def clean_and_categorize_ship_type(ocr_ship_type, ship_categories_t, threshold=65):
    logging.info(f'clean_and_categorize_ship_type called with ocr_ship_type: {ocr_ship_type}')
    if not ocr_ship_type:
        logging.info('No OCR ship type provided, returning None.')
        return None, None

    logging.debug(f"Input OCR Ship Type: {ocr_ship_type}")
    logging.debug(f"Ship Categories: {ship_categories_t}")
    logging.debug(f"Threshold: {threshold}")

    best_match = None
    best_category = None
    highest_ratio = 0

    for category, ships in ship_categories_t.items():
        match, ratio = process.extractOne(ocr_ship_type, ships)
        logging.debug(f'Category: {category}, Match: {match}, Ratio: {ratio}')
        if ratio > highest_ratio:
            highest_ratio = ratio
            if ratio >= threshold:
                best_match = match
                best_category = category

    logging.info(f'Best Match: {best_match}')
    logging.info(f'Best Category: {best_category}')
    logging.info(f'Highest Ratio: {highest_ratio}')

    # Now insert the fallback mechanism
    if highest_ratio < threshold:
        logging.warning(f"New or unrecognized ship detected: {ocr_ship_type}")
        best_category = 'Unknown'
        best_match = ocr_ship_type  # Keep the raw OCR ship type in the report

    return best_match, best_category


def verify(im_v):
    try:
        im_v.verify()
        return False, None
    except (IOError, SyntaxError, ValueError):
        return True, inspect.currentframe().f_back.f_lineno


def print_line_number():
    try:
        current_frame = inspect.currentframe()
        calling_frame = inspect.getouterframes(current_frame, 2)
        line_number = calling_frame[1].lineno
        return line_number
    except Exception as e:
        # Handle any potential errors gracefully
        print(f"Error fetching line number: {e}")
        return None



async def delay(min_time=100, max_time=400):
    random_delay = random.randint(min_time, max_time) / 1000
    await asyncio.sleep(random_delay)
    return


def symbol_present(compare_img, symbol_img, left_bound, top_bound, right_bound, bottom_bound,
                   tolerance=0.4):
    # Crop the comparison image for the area of interest
    cropped_image = compare_img.crop((left_bound, top_bound, right_bound, bottom_bound))

    # Convert PIL images to numpy arrays
    symbol_img_np = np.array(symbol_img)
    cropped_image_np = np.array(cropped_image)

    # Convert the images to grayscale
    symbol_gray = cv2.cvtColor(symbol_img_np, cv2.COLOR_RGB2GRAY)
    cropped_gray = cv2.cvtColor(cropped_image_np, cv2.COLOR_RGB2GRAY)

    # Apply thresholding to the images
    _, symbol_thresh = cv2.threshold(symbol_gray, 127, 255, cv2.THRESH_BINARY)
    _, cropped_thresh = cv2.threshold(cropped_gray, 127, 255, cv2.THRESH_BINARY)

    # Compare the threshold images for matches
    match = cv2.matchTemplate(cropped_thresh, symbol_thresh, cv2.TM_CCOEFF_NORMED)[0][0]

    # Check if the match value is above the calculated threshold
    # print(f'Match: {match}')
    return match > tolerance


# Init Discord
# Set the logging level for discord.py's internal logger
logging.getLogger('discord').setLevel(logging.INFO)  # or ERROR to suppress more messages
logging.getLogger('discord.client').setLevel(logging.INFO)
logging.getLogger('discord.gateway').setLevel(logging.INFO)
intents = discord.Intents.default()
# intents.typing = True
# intents.messages = True
# intents.message_content = True
user = ""
# client = MyClient(intents=intents)

# --- Retrieve Remote Configuration ---
config_url = "https://pfpd28eujl.execute-api.us-east-1.amazonaws.com/prod/eyes_config"
response = None # Initialize response to None
gc = None # Initialize Google Sheets client to None
ws = None # Initialize worksheet to None
discord_bot_token = None
EC2_WEBSOCKET_URL = None

# Create thread pool executor for asynchronous threading (Currently unused in this snippet)
executor = ThreadPoolExecutor(max_workers=5)

# --- Load Local Configuration ---
# Check if the configuration file exists before opening it
config = {}
input_backend = INPUT_BACKEND_PYAUTOGUI
emuinput_serial = DEFAULT_EMUINPUT_SERIAL
emuinput_host_port = DEFAULT_EMUINPUT_HOST_PORT
emuinput_adb_exe = DEFAULT_EMUINPUT_ADB_EXE
emuinput_adb_server_port = DEFAULT_EMUINPUT_ADB_SERVER_PORT
emuinput_bin_dir = ""
emuinput_rotation = DEFAULT_EMUINPUT_ROTATION
emuinput_autofix = DEFAULT_EMUINPUT_AUTOFIX
scout = 'Eyes'
system = 'EFLU'
target_channel_name = 'eflu'
report_min = 1
text_local_cnt_report = '1'
img_local_cnt_report = '1'
img_grid_report = '1'
text_grid_report = '1'
refuel_switch = '0'
contact_peep_switch = '0'
refuel_logoff = '1'
range_finding = '1'
google_sheets_logging = '1'
station_bound = '0'
seeker_timer = 2
last_screenshot_button_crop_pixel_count = 21
reverse_gate_polarity = '0'
save_img_log = '0'
contact_upper_bound = 35
contact_lower_bound = 28

if os.path.exists(config_filepath):
    with open(config_filepath, 'r') as config_file:
        config = {}
        for line in config_file:
            line = line.strip()
            # Check if the line contains '=' and is not empty/comment
            if '=' in line and not line.startswith('#'):
                key, value = map(str.strip, line.split('=', 1))
                config[key] = value

        startup_info("Local config loaded: %s", config_filepath)
        logging.debug("[startup] Local config payload: %s", config)

    # Scout Settings (Set defaults first, then override from local config)
    scout = config.get('scout', 'Eyes')
    system = config.get('system', 'EFLU')
    target_channel_name = config.get('target_channel_name', 'eflu')
    try:
        report_min = int(config.get('report_min', '1'))
    except ValueError:
        logging.warning(f'Invalid value for local config report_min. Using default value 1.')
        report_min = 1
    text_local_cnt_report = config.get('text_local_cnt_report', '1')
    img_local_cnt_report = config.get('img_local_cnt_report', '1')
    img_grid_report = config.get('img_grid_report', '1')
    text_grid_report = config.get('text_grid_report', '1')
    refuel_switch = config.get('refuel', '0')
    # Note: The comma at the end of the original line created a tuple, removed it.
    contact_peep_switch = config.get('contact_peep_switch', '0')
    refuel_logoff = config.get('refuel_logoff', '1')
    range_finding = config.get('range_finding', '1')
    google_sheets_logging = config.get('google_sheets_logging', '1') # This might control *if* sheets are used
    station_bound = config.get('station_bound', '0')
    try:
        seeker_timer = int(config.get('seeker_timer', '2'))  # in hours
    except ValueError:
        logging.warning(f'Invalid value for local config seeker_timer. Using default value 2.')
        seeker_timer = 2
    try:
        last_screenshot_button_crop_pixel_count = int(config.get('last_screenshot_button_crop_pixel_count', 21))
    except ValueError:
        logging.warning(f'Invalid value for local config last_screenshot_button_crop_pixel_count. Using default value 21.')
        last_screenshot_button_crop_pixel_count = 21
    reverse_gate_polarity = config.get('reverse_gate_polarity', '0')
    save_img_log = config.get('save_img_log', '0')
    try:
        contact_upper_bound = int(config.get('contact_upper_bound', '35'))
    except ValueError:
        logging.warning(f'Invalid value for local config contact_upper_bound. Using default value 35.')
        contact_upper_bound = 35
    try:
        contact_lower_bound = int(config.get('contact_lower_bound', '28'))
    except ValueError:
        logging.warning(f'Invalid value for local config contact_lower_bound. Using default value 28.')
        contact_lower_bound = 28
    input_backend = str(config.get('input_backend', input_backend)).strip().lower()
    emuinput_serial = str(config.get('emuinput_serial', emuinput_serial)).strip() or DEFAULT_EMUINPUT_SERIAL
    try:
        emuinput_host_port = int(config.get('emuinput_host_port', str(emuinput_host_port)))
    except ValueError:
        logging.warning(
            "Invalid emuinput_host_port '%s'. Using default value %s.",
            config.get('emuinput_host_port'),
            DEFAULT_EMUINPUT_HOST_PORT,
        )
        emuinput_host_port = DEFAULT_EMUINPUT_HOST_PORT
    emuinput_adb_exe = str(config.get('emuinput_adb_exe', emuinput_adb_exe)).strip() or DEFAULT_EMUINPUT_ADB_EXE
    try:
        emuinput_adb_server_port = int(config.get('emuinput_adb_server_port', str(emuinput_adb_server_port)))
    except ValueError:
        logging.warning(
            "Invalid emuinput_adb_server_port '%s'. Using default value %s.",
            config.get('emuinput_adb_server_port'),
            DEFAULT_EMUINPUT_ADB_SERVER_PORT,
        )
        emuinput_adb_server_port = DEFAULT_EMUINPUT_ADB_SERVER_PORT
    emuinput_bin_dir = str(config.get('emuinput_bin_dir', emuinput_bin_dir)).strip()
    emuinput_rotation = str(config.get('emuinput_rotation', emuinput_rotation)).strip().lower() or DEFAULT_EMUINPUT_ROTATION
    emuinput_autofix = str(config.get('emuinput_autofix', str(int(emuinput_autofix)))).strip().lower() in {
        "1", "true", "yes", "y", "on"
    }

    # Optional manual top-inset override for emulator variants that render chrome inside the 960x540 frame.
    # Accepted keys (first present wins): top_inset_override, top_trim_override, top_bar_height.
    # Legacy compatibility: negative top_bar_height means "trim abs(value) pixels from top".
    top_inset_key = None
    top_inset_raw = ""
    for candidate_key in ("top_inset_override", "top_trim_override", "top_bar_height"):
        candidate_value = str(config.get(candidate_key, "")).strip()
        if candidate_value:
            top_inset_key = candidate_key
            top_inset_raw = candidate_value
            break
    if top_inset_key:
        try:
            parsed_top_inset = int(top_inset_raw)
            if top_inset_key == "top_bar_height" and parsed_top_inset < 0:
                top_inset_override_px = abs(parsed_top_inset)
                logging.info(
                    "Using legacy local config %s=%s as top inset override of %s px.",
                    top_inset_key,
                    parsed_top_inset,
                    top_inset_override_px,
                )
            elif parsed_top_inset > 0:
                top_inset_override_px = parsed_top_inset
                logging.info(
                    "Using local config %s=%s as top inset override.",
                    top_inset_key,
                    top_inset_override_px,
                )
            elif parsed_top_inset < 0:
                top_inset_override_px = abs(parsed_top_inset)
                logging.info(
                    "Using absolute value of local config %s=%s as top inset override of %s px.",
                    top_inset_key,
                    parsed_top_inset,
                    top_inset_override_px,
                )
            else:
                top_inset_override_px = None
                logging.info(
                    "Local config %s=0 disables top inset override (auto-detect mode).",
                    top_inset_key,
                )
        except ValueError:
            logging.warning(
                "Invalid value for local config %s='%s'. Ignoring top inset override.",
                top_inset_key,
                top_inset_raw,
            )

else:
    startup_warn(
        "Local config '%s' not found. Using defaults. Searched: %s",
        config_filename,
        config_search_paths,
    )

startup_info(
    "Profile: scout=%s system=%s channel=%s backend=%s uinput_autofix=%s",
    scout,
    system,
    target_channel_name,
    input_backend,
    "ON" if emuinput_autofix else "OFF",
)
if str(input_backend).strip().lower() == INPUT_BACKEND_UINPUT:
    startup_info(
        "Input settings: serial=%s host_port=%s adb_server_port=%s rotation=%s",
        emuinput_serial,
        emuinput_host_port,
        emuinput_adb_server_port,
        emuinput_rotation,
    )

# --- Process Remote Configuration (Lambda Response) ---
try:
    startup_info("Fetching remote config from %s", config_url)
    response = requests.get(config_url, timeout=10) # Added timeout
    response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)

    # Check content type
    content_type = response.headers.get('Content-Type', '').lower()
    if 'application/json' in content_type:
        startup_info("Remote config received (JSON).")
        config_data = response.json()
        # print(config_data) # Uncomment for debugging if needed

        discord_bot_token = config_data.get("discord_bot_token")
        if discord_bot_token:
            startup_info("Discord token loaded from remote config.")
        else:
            # Log as warning or error depending on whether it's critical
            startup_warn("Remote config missing 'discord_bot_token'.")

        EC2_WEBSOCKET_URL = config_data.get("ec2_websocket_url")
        if EC2_WEBSOCKET_URL:
            startup_info("WebSocket URL loaded from remote config.")
        else:
            # Log as warning or error depending on whether it's critical
            startup_warn("Remote config missing 'ec2_websocket_url'.")

        # --- Google Sheets Credentials Handling ---
        # Check if Google Sheets logging is enabled in local config *before* processing credentials
        # (Assuming '1' means enabled)
        if config.get('google_sheets_logging', '1') == '1': # Check the potentially loaded local config setting
            startup_info("Google Sheets logging enabled. Authenticating...")
            # Extracting Google Sheets credentials carefully using .get()
            credentials = {
                "type": config_data.get("type"),
                "project_id": config_data.get("project_id"),
                "private_key_id": config_data.get("private_key_id"),
                "private_key": config_data.get("private_key"), # Get the key as is
                "client_email": config_data.get("client_email"),
                "client_id": config_data.get("client_id"),
                "auth_uri": config_data.get("auth_uri"),
                "token_uri": config_data.get("token_uri"),
                "auth_provider_x509_cert_url": config_data.get("auth_provider_x509_cert_url"),
                "client_x509_cert_url": config_data.get("client_x509_cert_url")
            }

            # Check if all necessary credential parts were found
            required_keys = ["type", "project_id", "private_key_id", "private_key", "client_email", "client_id"]
            if all(credentials.get(key) for key in required_keys):
                try:
                    # Apply the replace operation
                    credentials["private_key"] = credentials["private_key"].replace("\\n", "\n")

                    # Using the corrected credentials to authenticate with the Google Sheets API
                    gc = gspread.service_account_from_dict(credentials)  # <--- Line 426 approx. in your full script
                    # Consider making sheet/worksheet names configurable too
                    sh = gc.open("Public Eyes")
                    ws = sh.worksheet('Log')

                    startup_info("Google Sheets authentication complete.")
                    # Now gc and ws are ready to be used later in the script

                # ... rest of your except blocks ...
                except binascii.Error as base64_error:  # Catch the specific error
                    logging.error(f"Failed to authenticate Google Sheets - Base64 Error: {base64_error}", exc_info=True)
                    startup_error("Google Sheets auth failed (Base64): %s", base64_error)
                    # Print partial credentials for debugging (NEVER print the full private key in production logs)
                    debug_creds = credentials.copy()
                    key_preview = credentials.get("private_key", "")  # Get the potentially modified key
                    print(
                        f"Key causing error (first/last 50 chars):\n{key_preview[:50]}\n...\n{key_preview[-50:]}")  # Log snippet carefully
                    debug_creds.pop("private_key", None)
                    logging.error(f"Credentials used (key omitted): {debug_creds}")

                except gspread.exceptions.APIError as api_error:
                    logging.error(f"Google Sheets API Error: {api_error}")
                    startup_error("Google Sheets API error during startup: %s", api_error)
                    # Print partial credentials for debugging (NEVER print the private key)
                    debug_creds = credentials.copy()
                    debug_creds.pop("private_key", None)
                    logging.error(f"Credentials used (key omitted): {debug_creds}")
                except Exception as auth_error: # Catch other potential errors (like auth lib issues)
                    logging.error(f"Failed to authenticate Google Sheets: {auth_error}", exc_info=True) # Log traceback
                    startup_error("Google Sheets authentication failed: %s", auth_error)
                    debug_creds = credentials.copy()
                    debug_creds.pop("private_key", None)
                    logging.error(f"Credentials used (key omitted): {debug_creds}")

            else:
                missing_keys = [key for key in required_keys if not credentials.get(key)]
                logging.error(f"Incomplete Google Sheets credentials received from Lambda. Missing: {missing_keys}")
                startup_error("Incomplete Google Sheets credentials. Missing keys: %s", missing_keys)
        else:
            startup_info("Google Sheets logging disabled by local config.")

    elif 'text/plain' in content_type:
        logging.error(f'Error: Received plain text response from Lambda. Content: {response.text[:500]}...') # Log part of content
        startup_error("Remote config returned text/plain instead of JSON.")
    else:
        logging.error(f'Error: Unexpected content type from Lambda: {content_type}. Content: {response.text[:500]}...') # Log part of content
        startup_error("Remote config returned unexpected content type: %s", content_type)

except requests.exceptions.Timeout:
    logging.error(f"Failed to retrieve config from {config_url}: Request timed out.")
    startup_error("Timed out while fetching remote config.")
except requests.exceptions.RequestException as e:
    logging.error(f"Failed to retrieve config from {config_url}. Error: {e}")
    startup_error("Failed to retrieve remote config: %s", e)
    if response is not None:
        # Log response details if available, even on error status codes caught by raise_for_status
        logging.error(f"Response status code: {response.status_code}")
        logging.error(f"Response content: {response.text[:500]}...") # Log first 500 chars
        startup_error("Response status code: %s", response.status_code)
        startup_error("Response body (first 500 chars): %s...", response.text[:500])


def get_window_info(window_title):
    if not window_title:
        startup_warn("Window title is empty; skipping window metrics probe.")
        return None

    _ensure_process_dpi_aware()
    exact_title = str(window_title).strip()
    if not exact_title:
        startup_warn("Window title is empty after trimming; skipping window metrics probe.")
        return None

    hwnd = win32gui.FindWindow(None, exact_title)
    if not hwnd or not win32gui.IsWindow(hwnd):
        # Fallback: enumerate visible windows and match exact title.
        matches = []

        def _enum_windows_callback(enum_hwnd, _):
            if not win32gui.IsWindowVisible(enum_hwnd):
                return
            if win32gui.GetWindowText(enum_hwnd).strip().lower() == exact_title.lower():
                matches.append(enum_hwnd)

        win32gui.EnumWindows(_enum_windows_callback, None)
        hwnd = matches[0] if matches else None

    if not hwnd or not win32gui.IsWindow(hwnd):
        startup_warn("Window '%s' not found for metrics probe.", exact_title)
        return None

    try:
        get_dpi_for_window = getattr(user32, "GetDpiForWindow", None)
        if callable(get_dpi_for_window):
            get_dpi_for_window.restype = wintypes.UINT
            get_dpi_for_window.argtypes = [wintypes.HWND]
            dpi = int(get_dpi_for_window(hwnd))
        else:
            dpi = 96
    except Exception:
        dpi = 96

    try:
        client_rect = win32gui.GetClientRect(hwnd)
        window_rect = win32gui.GetWindowRect(hwnd)
    except Exception as exc:
        logging.warning("Failed to read window metrics for '%s': %s", exact_title, exc)
        return None

    client_width = max(1, client_rect[2] - client_rect[0])
    client_height = max(1, client_rect[3] - client_rect[1])
    title_bar_height = max(0, client_height - BASE_FRAME_HEIGHT)
    side_bar_width = max(0, (window_rect[2] - window_rect[0]) - client_width)

    startup_info(
        "Window metrics: x=%s y=%s width=%s height=%s top_bar=%s side_bar=%s dpi=%s",
        window_rect[0],
        window_rect[1],
        client_width,
        client_height,
        title_bar_height,
        side_bar_width,
        dpi,
    )
    return dpi, title_bar_height, side_bar_width, window_rect[0], window_rect[1], client_height

# Determine client DPI and Title Bard Height
window_info = get_window_info(scout)
if window_info:
    window_dpi, top_bar_height, sid_bar_width, window_x, window_y, window_height = window_info
else:
    window_dpi, top_bar_height, sid_bar_width, window_x, window_y, window_height = 96, 0, 0, 0, 0, BASE_FRAME_HEIGHT
    logging.warning(
        "Using fallback window metrics for scout '%s': dpi=%s top_bar_height=%s",
        scout,
        window_dpi,
        top_bar_height,
    )
if top_inset_override_px is not None:
    logging.info(
        "Top inset override active for scout '%s': %s px.",
        scout,
        top_inset_override_px,
    )

# Initialize the OCR model
dummy_image = Image.new('RGB', (1, 1), color=(255, 255, 255))
# Perform OCR on the dummy image to "warm-up" Tesseract
_ = pytesseract.image_to_string(dummy_image)
# model = recognition_predictor(model_name, pretrained=True)
startup_info("OCR warm-up complete.")
os.environ['USE_TORCH'] = '1'

# Silence stupid warnings
warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    module=r"doctr\.models\.utils\.pytorch",
    lineno=59
)


def find_target_window(retries=5, delay=2):
    global target_hwnd

    def enum_windows_callback(hwnd, windows_list):
        if win32gui.IsWindowVisible(hwnd):
            window_title = win32gui.GetWindowText(hwnd)
            if window_title:  # Only add windows with a title
                windows_list.append((hwnd, window_title))

    def list_open_windows():
        windows = []
        win32gui.EnumWindows(enum_windows_callback, windows)
        return windows

    def find_window_by_title(exact_title):
        windows = list_open_windows()
        for hwnd, window_title in windows:
            if window_title.lower() == exact_title.lower():  # Enforce exact match
                return hwnd
        return None

    hwnd = find_window_by_title(scout)
    if hwnd:
        target_hwnd = hwnd
        return

    '''
    for attempt in range(retries):
        pilot_windows = [w for w in gw.getWindowsWithTitle(f'{scout}') if w.title == f'{scout}']

        if pilot_windows:
            target_hwnd = pilot_windows[0]._hWnd
            logging.info(f"Window with title '{scout}' found.")
            return

        logging.warning(
            f"Window with title '{scout}' not found. Attempt {attempt + 1} of {retries}. Retrying in {delay} seconds...")
        time.sleep(delay)
    '''

    logging.error(f"Window with title '{scout}' not found after {retries} attempts.")
    target_hwnd = None  # Ensure target_hwnd is set to None if not found
    return


def activate_window(max_wait_time=3, check_interval=0.1):
    global target_hwnd
    try:
        # Ensure target_hwnd is valid and re-find if necessary
        if not target_hwnd or not win32gui.IsWindow(target_hwnd):
            find_target_window()
        if not target_hwnd or not win32gui.IsWindow(target_hwnd):
            raise Exception('Invalid window handle after re-finding the window')

        # Retrieve thread IDs
        foreground_thread_id = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[0]
        target_thread_id = win32process.GetWindowThreadProcessId(target_hwnd)[0]

        # Attach thread input if needed
        if foreground_thread_id != target_thread_id:
            user32.AttachThreadInput(foreground_thread_id, target_thread_id, True)

        # Bring the window to the foreground
        win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(target_hwnd)

        # Wait for window activation
        start_time = time.time()
        while time.time() - start_time < max_wait_time:
            active_hwnd = win32gui.GetForegroundWindow()
            if active_hwnd == target_hwnd:
                # Successfully activated
                break
            time.sleep(check_interval)

        # Detach thread input if it was attached
        if foreground_thread_id != target_thread_id:
            user32.AttachThreadInput(foreground_thread_id, target_thread_id, False)

        # Final check
        active_hwnd = win32gui.GetForegroundWindow()
        if active_hwnd != target_hwnd:
            raise RuntimeError("Failed to activate window within the given time.")

    except Exception as e:
        print(f"Failed to activate window: {e}")


def activate_window_by_title(window_title):
    try:
        # Find the window handle by title
        matching_windows = [w for w in gw.getAllWindows() if w.title == window_title]
        if not matching_windows:
            raise ValueError(f"Window with title '{window_title}' not found.")

        # Get the first matching window and activate it
        target_window = matching_windows[0]
        target_window.activate()
        print(f"Activated window: {target_window.title}")

    except Exception as e:
        print(f"Failed to activate window by title '{window_title}': {e}")


def _get_client_metrics(hwnd):
    client_rect = win32gui.GetClientRect(hwnd)
    client_w = max(1, client_rect[2] - client_rect[0])
    client_h = max(1, client_rect[3] - client_rect[1])
    client_left, client_top = win32gui.ClientToScreen(hwnd, (0, 0))
    return client_left, client_top, client_w, client_h


def _compute_top_inset(client_h: int) -> int:
    """
    Derive the dynamic non-playfield top inset from current client height.
    Baseline playfield is 960x540; extra vertical pixels are treated as top inset.
    """
    try:
        client_h_i = max(1, int(client_h))
    except Exception:
        client_h_i = int(BASE_FRAME_HEIGHT)

    dynamic_inset = max(0, client_h_i - int(BASE_FRAME_HEIGHT))
    effective_inset = dynamic_inset

    try:
        override_inset = None if top_inset_override_px is None else int(top_inset_override_px)
    except Exception:
        override_inset = None

    if override_inset is not None and override_inset >= 0:
        effective_inset = override_inset
    elif dynamic_inset <= 0:
        try:
            effective_inset = max(0, int(top_bar_height or 0))
        except Exception:
            effective_inset = 0
        if effective_inset <= 0:
            try:
                cached_inset = None if auto_top_inset_cache_px is None else int(auto_top_inset_cache_px)
            except Exception:
                cached_inset = None
            if cached_inset is not None and cached_inset > 0:
                effective_inset = cached_inset

    return max(0, min(client_h_i - 1, int(effective_inset)))


def _estimate_embedded_top_chrome_inset(image: Image.Image, max_scan_px: int = 90) -> int:
    """
    Heuristic for emulators (e.g., BlueStacks) that draw their top chrome *inside* a 960x540 client frame.
    Returns inset in pixels to trim from top, or 0 when no strong signal is found.
    """
    try:
        width, height = image.size
    except Exception:
        return 0

    if width < 200 or height < 80:
        return 0

    scan_h = max(1, min(int(max_scan_px), height - 1))
    # Avoid the far-right panel where in-game UI can be persistently dark.
    x_limit = max(120, min(width, int(width * 0.72)))
    x_step = max(2, int(x_limit / 120))

    candidate = 0
    misses_after_candidate = 0
    min_candidate = 16
    ratio_threshold = 0.42

    for y in range(scan_h):
        blue_dark_hits = 0
        total = 0
        for x in range(0, x_limit, x_step):
            r, g, b = image.getpixel((x, y))
            # BlueStacks top bar tends to be dark and blue-biased; gameplay rows are usually not.
            if b >= (r + 8) and b >= (g + 6) and (r + g + b) <= 180:
                blue_dark_hits += 1
            total += 1

        ratio = blue_dark_hits / float(max(1, total))
        if ratio >= ratio_threshold:
            candidate = y + 1
            misses_after_candidate = 0
            continue

        if candidate >= min_candidate:
            misses_after_candidate += 1
            if misses_after_candidate >= 3:
                break
        else:
            candidate = 0
            misses_after_candidate = 0

    if 18 <= candidate <= 72:
        return int(candidate)
    return 0


def _get_runtime_top_inset(hwnd=None, window_title=None) -> int:
    try:
        resolved_hwnd = hwnd
        if (not resolved_hwnd or not win32gui.IsWindow(resolved_hwnd)) and window_title:
            resolved_hwnd = win32gui.FindWindow(None, str(window_title))
        if resolved_hwnd and win32gui.IsWindow(resolved_hwnd):
            client_rect = win32gui.GetClientRect(resolved_hwnd)
            client_h = max(1, client_rect[3] - client_rect[1])
            return _compute_top_inset(client_h)
    except Exception:
        pass
    try:
        return max(0, int(top_bar_height or 0))
    except Exception:
        return 0


def _map_base_to_client(hwnd, x_position, y_position, action_type=0):
    _, _, client_w, client_h = _get_client_metrics(hwnd)
    top_pad = _compute_top_inset(client_h)

    x_rel = int(round((float(x_position) / float(BASE_FRAME_WIDTH)) * client_w))
    x_scale = client_w / float(BASE_FRAME_WIDTH)

    if action_type == 0:
        usable_h = max(1, client_h - top_pad)
        y_rel = int(round(top_pad + (float(y_position) / float(BASE_FRAME_HEIGHT)) * usable_h))
        y_scale = usable_h / float(BASE_FRAME_HEIGHT)
    else:
        y_rel = int(round((float(y_position) / float(BASE_FRAME_HEIGHT)) * client_h))
        y_scale = client_h / float(BASE_FRAME_HEIGHT)

    x_rel = max(0, min(client_w - 1, x_rel))
    y_rel = max(0, min(client_h - 1, y_rel))
    return x_rel, y_rel, x_scale, y_scale, client_w, client_h


def get_mouse_base_position(hwnd=None, action_type=0):
    global target_hwnd
    hwnd = hwnd or target_hwnd
    if not hwnd or not win32gui.IsWindow(hwnd):
        return None

    client_left, client_top, client_w, client_h = _get_client_metrics(hwnd)
    mouse_x, mouse_y = pyautogui.position()
    rel_x = int(mouse_x - client_left)
    rel_y = int(mouse_y - client_top)
    inside_client = 0 <= rel_x < client_w and 0 <= rel_y < client_h

    rel_x = max(0, min(client_w - 1, rel_x))
    rel_y = max(0, min(client_h - 1, rel_y))

    top_pad = _compute_top_inset(client_h)
    if action_type == 0:
        usable_h = max(1, client_h - top_pad)
        rel_y_visible = max(0, rel_y - top_pad)
        base_y = int(round((rel_y_visible / float(usable_h)) * BASE_FRAME_HEIGHT))
    else:
        base_y = int(round((rel_y / float(client_h)) * BASE_FRAME_HEIGHT))

    base_x = int(round((rel_x / float(client_w)) * BASE_FRAME_WIDTH))
    base_x = max(0, min(BASE_FRAME_WIDTH - 1, base_x))
    base_y = max(0, min(BASE_FRAME_HEIGHT - 1, base_y))

    return {
        "base_x": base_x,
        "base_y": base_y,
        "client_x": rel_x,
        "client_y": rel_y,
        "inside_client": inside_client,
        "client_w": client_w,
        "client_h": client_h,
    }


def _uinput_backend_enabled() -> bool:
    return str(input_backend).strip().lower() == INPUT_BACKEND_UINPUT


def _try_load_emuinput_classes():
    global _emuinput_adb_cls, _emuinput_controller_cls, _emuinput_import_error
    if _emuinput_adb_cls is not None and _emuinput_controller_cls is not None:
        return _emuinput_adb_cls, _emuinput_controller_cls
    if _emuinput_import_error is not None:
        raise RuntimeError(f"emuinput import failed earlier: {_emuinput_import_error}") from _emuinput_import_error

    candidates = []
    if emuinput_bin_dir:
        try:
            candidates.append(Path(emuinput_bin_dir).resolve().parent.parent)
        except Exception:
            pass
    if "__file__" in globals():
        candidates.append(Path(__file__).resolve().parent / "emuinput")
    if "application_path" in globals():
        candidates.append(Path(application_path) / "emuinput")
    candidates.append(Path.cwd() / "emuinput")

    seen = set()
    for candidate in candidates:
        try:
            root = candidate.resolve()
        except Exception:
            root = candidate
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        pkg_init = root / "emuinput" / "__init__.py"
        if pkg_init.exists():
            root_str = str(root)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)

    try:
        from emuinput import Adb as EmuAdb  # type: ignore
        from emuinput import EmuController as EmuControllerType  # type: ignore
    except Exception as exc:
        _emuinput_import_error = exc
        raise RuntimeError(
            "Unable to import emuinput package. Ensure C:\\Projects\\Eyes\\emuinput\\emuinput exists."
        ) from exc

    _emuinput_adb_cls = EmuAdb
    _emuinput_controller_cls = EmuControllerType
    return _emuinput_adb_cls, _emuinput_controller_cls


def _resolve_emuinput_bin_dir() -> Optional[Path]:
    candidates = []
    if emuinput_bin_dir:
        candidates.append(Path(emuinput_bin_dir))
    if "__file__" in globals():
        candidates.append(Path(__file__).resolve().parent / "emuinput" / "bin" / "android")
    if "application_path" in globals():
        candidates.append(Path(application_path) / "emuinput" / "bin" / "android")
    candidates.append(Path.cwd() / "emuinput" / "bin" / "android")

    seen = set()
    for candidate in candidates:
        try:
            root = candidate.resolve()
        except Exception:
            root = candidate
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        if (root / "x86_64" / "uinputd").exists() or (root / "arm64-v8a" / "uinputd").exists():
            return root
    return None


def _resolve_emuinput_adb_exe_candidates(adb_exe_value: str) -> list[str]:
    raw = str(adb_exe_value or "").strip()
    if not raw:
        raw = DEFAULT_EMUINPUT_ADB_EXE

    candidate_paths = []
    candidate_paths.append(raw)

    env_expanded = os.path.expandvars(raw)
    if env_expanded != raw:
        candidate_paths.append(env_expanded)

    try:
        which_hit = shutil.which(raw)
    except Exception:
        which_hit = None
    if which_hit:
        candidate_paths.append(which_hit)

    sdk_roots = [
        os.environ.get("ANDROID_SDK_ROOT", "").strip(),
        os.environ.get("ANDROID_HOME", "").strip(),
        r"C:\Android\Sdk",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk"),
    ]
    for sdk_root in sdk_roots:
        if sdk_root:
            candidate_paths.append(os.path.join(sdk_root, "platform-tools", "adb.exe"))

    # MuMu default install locations.
    candidate_paths.extend(
        [
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
            r"C:\Program Files\Netease\MuMuPlayer\nx_device\12.0\shell\adb.exe",
            r"C:\Program Files\Netease\MuMuPlayer\shell\adb.exe",
            "adb",
        ]
    )

    seen = set()
    resolved = []
    for candidate in candidate_paths:
        if not candidate:
            continue
        expanded = os.path.expandvars(candidate).strip('"').strip()
        if not expanded:
            continue
        key = expanded.lower()
        if key in seen:
            continue
        seen.add(key)

        if os.path.isabs(expanded) or ("\\" in expanded) or ("/" in expanded):
            if os.path.exists(expanded):
                resolved.append(expanded)
            continue

        hit = shutil.which(expanded)
        if hit:
            resolved.append(hit)

    return resolved


def _resolve_emuinput_adb_exe(adb_exe_value: str) -> str:
    resolved = _resolve_emuinput_adb_exe_candidates(adb_exe_value)
    if resolved:
        return resolved[0]
    raise FileNotFoundError(
        "Unable to locate adb executable. Set emuinput_adb_exe in config_prototype.txt "
        "to a full path, for example C:\\Program Files\\Netease\\MuMuPlayer\\nx_main\\adb.exe."
    )


def _run_adb_quick(adb_exe_path: str, args: list[str], timeout_s: float = 10.0) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["ADB_SERVER_PORT"] = str(int(emuinput_adb_server_port))
    return subprocess.run(
        [adb_exe_path, *args],
        capture_output=True,
        text=True,
        timeout=float(timeout_s),
        check=False,
        env=env,
    )


def _attempt_emuinput_adb_repair(adb_exe_path: str) -> bool:
    """
    Best-effort adb server refresh used when uinput init fails.
    This mirrors the manual preflight users run in PowerShell.
    """
    try:
        _run_adb_quick(adb_exe_path, ["kill-server"], timeout_s=8.0)
    except Exception:
        pass

    try:
        start = _run_adb_quick(adb_exe_path, ["start-server"], timeout_s=10.0)
    except Exception as exc:
        logging.warning("[input] adb repair start-server failed via %s: %s", adb_exe_path, exc)
        return False

    if start.returncode != 0:
        logging.warning(
            "[input] adb repair start-server returned %s via %s. stderr=%s",
            start.returncode,
            adb_exe_path,
            (start.stderr or "").strip(),
        )
        return False

    try:
        connect = _run_adb_quick(adb_exe_path, ["connect", str(emuinput_serial)], timeout_s=12.0)
    except Exception as exc:
        logging.warning("[input] adb repair connect failed via %s: %s", adb_exe_path, exc)
        return False

    if connect.returncode != 0:
        logging.warning(
            "[input] adb repair connect returned %s via %s. stderr=%s",
            connect.returncode,
            adb_exe_path,
            (connect.stderr or "").strip(),
        )
        return False

    try:
        state = _run_adb_quick(adb_exe_path, ["-s", str(emuinput_serial), "get-state"], timeout_s=8.0)
    except Exception as exc:
        logging.warning("[input] adb repair get-state failed via %s: %s", adb_exe_path, exc)
        return False

    state_text = (state.stdout or "").strip().lower()
    if state.returncode == 0 and state_text == "device":
        logging.info("[input] adb repair succeeded via %s (serial=%s).", adb_exe_path, emuinput_serial)
        return True

    logging.warning(
        "[input] adb repair could not bring serial online via %s. get-state='%s' stderr=%s",
        adb_exe_path,
        state_text,
        (state.stderr or "").strip(),
    )
    return False


def _ensure_emuinput_controller():
    global _emuinput_controller, _emuinput_hello, _emuinput_resolved_adb_exe
    adb_cls, controller_cls = _try_load_emuinput_classes()
    with _emuinput_lock:
        if _emuinput_controller is not None:
            try:
                _emuinput_hello = _emuinput_controller.ensure_daemon()
                return _emuinput_controller, _emuinput_hello
            except Exception as exc:
                logging.warning(
                    "[input] existing uinput controller failed health-check: %s",
                    exc,
                )
                try:
                    _emuinput_controller.close()
                except Exception:
                    pass
                _emuinput_controller = None
                _emuinput_hello = None

        resolved_bin_dir = _resolve_emuinput_bin_dir()
        if resolved_bin_dir is None:
            raise RuntimeError(
                "Unable to find uinputd binaries. Set emuinput_bin_dir in config_prototype.txt."
            )

        adb_candidates = _resolve_emuinput_adb_exe_candidates(emuinput_adb_exe)
        if not adb_candidates:
            raise FileNotFoundError(
                "Unable to locate adb executable. Set emuinput_adb_exe in config_prototype.txt."
            )

        last_exc = None
        for idx, adb_path in enumerate(adb_candidates[:6], start=1):
            max_attempts_for_candidate = 2 if emuinput_autofix else 1
            for local_try in range(1, max_attempts_for_candidate + 1):
                _emuinput_resolved_adb_exe = adb_path
                adb = adb_cls(
                    adb_exe=adb_path,
                    adb_server_port=int(emuinput_adb_server_port),
                    timeout=18.0,
                )
                controller = controller_cls(
                    serial=emuinput_serial,
                    adb=adb,
                    host_port=int(emuinput_host_port),
                    bin_dir=str(resolved_bin_dir),
                )
                try:
                    hello = controller.ensure_daemon()
                    _emuinput_controller = controller
                    _emuinput_hello = hello
                    logging.info(
                        "[input] uinput connected via adb candidate %s/%s: %s",
                        idx,
                        min(len(adb_candidates), 6),
                        adb_path,
                    )
                    return _emuinput_controller, _emuinput_hello
                except Exception as exc:
                    last_exc = exc
                    logging.warning(
                        "[input] uinput init failed with adb candidate %s/%s (%s) try %s/%s: %s",
                        idx,
                        min(len(adb_candidates), 6),
                        adb_path,
                        local_try,
                        max_attempts_for_candidate,
                        exc,
                    )
                    try:
                        controller.close()
                    except Exception:
                        pass
                    _emuinput_controller = None
                    _emuinput_hello = None

                    if local_try < max_attempts_for_candidate:
                        repaired = _attempt_emuinput_adb_repair(adb_path)
                        if repaired:
                            logging.info(
                                "[input] retrying uinput init after adb repair (%s).",
                                adb_path,
                            )
                        else:
                            logging.warning(
                                "[input] adb repair failed for %s; still retrying once.",
                                adb_path,
                            )
                        time.sleep(0.3)
                        continue
                    time.sleep(0.25)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("uinput controller initialization failed")


def _close_emuinput_controller() -> None:
    global _emuinput_controller, _emuinput_hello, _emuinput_resolved_adb_exe
    with _emuinput_lock:
        controller = _emuinput_controller
        _emuinput_controller = None
        _emuinput_hello = None
        _emuinput_resolved_adb_exe = None
    if controller is not None:
        try:
            controller.close()
        except Exception as exc:
            logging.warning("Failed to close emuinput controller cleanly: %s", exc)


def _invalidate_emuinput_controller() -> None:
    _close_emuinput_controller()


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _normalize_rotation_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized in {"auto", "none", "cw", "ccw"}:
        return normalized
    return DEFAULT_EMUINPUT_ROTATION


def _resolve_rotation_mode(hello: dict[str, int]) -> str:
    mode = _normalize_rotation_mode(emuinput_rotation)
    if mode != "auto":
        return mode

    x_span = abs(int(hello["x_max"]) - int(hello["x_min"]))
    y_span = abs(int(hello["y_max"]) - int(hello["y_min"]))
    src_landscape = BASE_FRAME_WIDTH >= BASE_FRAME_HEIGHT
    dst_landscape = x_span >= y_span
    if src_landscape != dst_landscape:
        # Default to Android's common landscape-left transform.
        return "ccw"
    return "none"


def _map_norm_to_axis(value_norm: float, axis_min: int, axis_max: int) -> int:
    value_norm = _clip(value_norm, 0.0, 1.0)
    value = float(axis_min) + value_norm * float(axis_max - axis_min)
    return int(round(value))


def _map_base_to_uinput_coords(base_x: float, base_y: float, hello: dict[str, int]) -> tuple[int, int, str]:
    src_x = _clip(float(base_x), 0.0, float(BASE_FRAME_WIDTH - 1))
    src_y = _clip(float(base_y), 0.0, float(BASE_FRAME_HEIGHT - 1))
    x_norm = src_x / float(max(1, BASE_FRAME_WIDTH - 1))
    y_norm = src_y / float(max(1, BASE_FRAME_HEIGHT - 1))

    mode = _resolve_rotation_mode(hello)
    if mode == "cw":
        u_x_norm = y_norm
        u_y_norm = 1.0 - x_norm
    elif mode == "ccw":
        u_x_norm = 1.0 - y_norm
        u_y_norm = x_norm
    else:
        u_x_norm = x_norm
        u_y_norm = y_norm

    u_x = _map_norm_to_axis(u_x_norm, int(hello["x_min"]), int(hello["x_max"]))
    u_y = _map_norm_to_axis(u_y_norm, int(hello["y_min"]), int(hello["y_max"]))

    x_low = min(int(hello["x_min"]), int(hello["x_max"]))
    x_high = max(int(hello["x_min"]), int(hello["x_max"]))
    y_low = min(int(hello["y_min"]), int(hello["y_max"]))
    y_high = max(int(hello["y_min"]), int(hello["y_max"]))
    u_x = int(_clip(u_x, x_low, x_high))
    u_y = int(_clip(u_y, y_low, y_high))
    return u_x, u_y, mode


atexit.register(_close_emuinput_controller)


async def click(x_position, y_position, action_type=0, x_variance=5, y_variance=5, index=1, retries=3):
    global target_hwnd
    try:
        use_uinput = _uinput_backend_enabled()
        if not use_uinput:
            if not target_hwnd or not win32gui.IsWindow(target_hwnd):
                print('Having trouble finding window...')
                find_target_window()
                if not target_hwnd or not win32gui.IsWindow(target_hwnd):
                    raise RuntimeError("Failed to locate target window.")

        for attempt in range(retries):
            try:
                if not use_uinput:
                    await asyncio.to_thread(activate_window)

                if use_uinput:
                    controller, hello = await asyncio.to_thread(_ensure_emuinput_controller)
                    jitter_x = random.randint(-abs(int(x_variance)), abs(int(x_variance)))
                    jitter_y = random.randint(-abs(int(y_variance)), abs(int(y_variance)))
                    base_x = int(round(float(x_position))) + jitter_x
                    base_y = int(round(float(y_position))) + jitter_y
                    u_x, u_y, rotation_mode = _map_base_to_uinput_coords(base_x, base_y, hello)
                    print(
                        f"Clicking base({x_position},{y_position}) -> jittered({base_x},{base_y}) -> "
                        f"uinput({u_x},{u_y}) mode={rotation_mode}"
                    )
                    await asyncio.to_thread(controller.tap, u_x, u_y, random.randint(55, 95))
                    print("Click successful.")
                    return

                client_left, client_top, client_w, client_h = _get_client_metrics(target_hwnd)
                x_rel, y_rel, x_scale, y_scale, _, _ = _map_base_to_client(
                    target_hwnd, x_position, y_position, action_type
                )
                x_jitter = int(round(random.randint(-x_variance, x_variance) * max(x_scale, 0.1)))
                y_jitter = int(round(random.randint(-y_variance, y_variance) * max(y_scale, 0.1)))
                x_screen = client_left + x_rel + x_jitter
                y_screen = client_top + y_rel + y_jitter
                x_screen = max(client_left, min(client_left + client_w - 1, x_screen))
                y_screen = max(client_top, min(client_top + client_h - 1, y_screen))

                print(
                    f"Clicking base({x_position},{y_position}) -> client({x_rel},{y_rel}) -> "
                    f"screen({x_screen},{y_screen})"
                )
                (initial_x, initial_y) = pyautogui.position()
                # noinspection PyTypeChecker
                await asyncio.to_thread(
                    pyautogui.click,
                    x=x_screen,
                    y=y_screen,
                    clicks=1,
                    interval=0,
                    button='left'
                )
                # noinspection PyTypeChecker
                await asyncio.to_thread(pyautogui.moveTo, initial_x, initial_y, duration=0.1, tween=pyautogui.linear)
                print("Click successful.")
                return
            except pyautogui.FailSafeException:
                print("Fail-safe triggered! Aborting click.")
                raise
            except Exception as e:
                print(f'Click attempt {attempt + 1} failed: {e}')
                if _uinput_backend_enabled():
                    _invalidate_emuinput_controller()
                await asyncio.sleep(0.2)

        raise RuntimeError(f"All {retries} click attempts failed.")
    except Exception as e:
        print(f'Exception in click function: {e}')
        return


def save_image_in_memory(image, format="PNG"):
    img_byte_arr = BytesIO()
    image.save(img_byte_arr, format=format)
    img_byte_arr.seek(0)  # Ensure the BytesIO object is at the start
    return img_byte_arr


# Crops a screen section and saves the result as an image file
def save_img(s_img, filename, left_bound=None, upper_bound=None, right_bound=None, lower_bound=None):
    # Set the default bounds to the edges of the image if not provided
    if left_bound is None:
        left_bound = 0
    if upper_bound is None:
        upper_bound = 0
    if right_bound is None:
        right_bound = s_img.width
    if lower_bound is None:
        lower_bound = s_img.height

    # Crop the image first, outside of the locked section to minimize locked time
    crop_img = s_img.crop((left_bound, upper_bound, right_bound, lower_bound))

    # Construct the full path for the file
    directory = scout
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    full_path = os.path.join(directory, f"{filename}.png")

    with lock:
        # The file saving operation is now protected by the lock
        crop_img.save(full_path, format="png")

    return crop_img



# Save intermediate images for debugging
def save_intermediate_image(image, filename):
    if not os.path.exists('debug_images'):
        os.makedirs('debug_images')
    image.save(f'debug_images/{filename}')


def open_image(filename):
    # Open the file and load it into an image object
    with Image.open(filename) as img:
        # Copy the image into a new variable
        processed_image = img.copy()
    # Return the processed image
    return processed_image


def _as_rgb_array(image_or_arr):
    if isinstance(image_or_arr, np.ndarray):
        arr = image_or_arr
        if arr.ndim != 3 or arr.shape[2] < 3:
            raise ValueError("Expected an RGB-like array with shape (H, W, >=3).")
        if arr.dtype != np.uint8:
            arr = arr.astype(np.uint8, copy=False)
        return arr[..., :3]
    return np.asarray(image_or_arr.convert("RGB"), dtype=np.uint8)


def _count_pixels_arr_rgb(arr_rgb, r1, r2, g1, g2, b1, b2):
    # Preserve legacy half-open range semantics from range(low, high).
    if r2 <= r1 or g2 <= g1 or b2 <= b1:
        return 0
    mask = (
        (arr_rgb[..., 0] >= r1) & (arr_rgb[..., 0] < r2) &
        (arr_rgb[..., 1] >= g1) & (arr_rgb[..., 1] < g2) &
        (arr_rgb[..., 2] >= b1) & (arr_rgb[..., 2] < b2)
    )
    return int(np.count_nonzero(mask))


def count_pixels_arr(arr_rgb, r1, r2, g1, g2, b1, b2):
    arr_rgb = _as_rgb_array(arr_rgb)
    return _count_pixels_arr_rgb(arr_rgb, r1, r2, g1, g2, b1, b2)


def count_pixels_roi_arr(arr_rgb, left, top, right, bottom, bounds):
    arr_rgb = _as_rgb_array(arr_rgb)
    h, w = arr_rgb.shape[:2]
    l = max(0, int(left))
    t = max(0, int(top))
    r = min(w, int(right))
    b = min(h, int(bottom))
    if r <= l or b <= t:
        return 0
    r1, r2, g1, g2, b1, b2 = bounds
    return _count_pixels_arr_rgb(arr_rgb[t:b, l:r, :], r1, r2, g1, g2, b1, b2)


_ANOM_LEGACY_BOUNDS = (140, 240, 140, 240, 145, 240)
_ANOM_RED_BOUNDS = (
    (150, 255, 25, 140, 25, 140),
    (180, 255, 45, 180, 45, 170),
)


def _scaled_ratio_x_range(width, left_ratio, right_ratio, min_width=8):
    l = max(0, int(round(width * left_ratio)))
    r = min(int(width), int(round(width * right_ratio)))
    if r - l < min_width:
        r = min(int(width), l + int(min_width))
    return l, r


def _build_anom_row_areas(width, height, row_count=5):
    # Anchor rows from the bottom so the lowest visible result row is included.
    x1, x2 = _scaled_ratio_x_range(width, 807 / 970.0, 840 / 970.0, min_width=20)
    centers = [int(round(height - 10 - (i * 52))) for i in range(row_count)]
    areas = []
    for y in centers:
        y = max(1, min(int(height) - 2, y))
        areas.append((x1, y - 1, x2, y + 2))
    return areas


def _build_anom_icon_area_for_row(width, height, row_top, row_bottom):
    x1, x2 = _scaled_ratio_x_range(width, 722 / 970.0, 765 / 970.0, min_width=24)
    y_mid = int((int(row_top) + int(row_bottom)) / 2)
    return (x1, max(0, y_mid - 12), x2, min(int(height), y_mid + 12))


def _build_anom_text_area_for_row(width, height, row_top, row_bottom):
    # Text label area on the right anomaly list where "... Wasteseeker ... Checkpoint" appears.
    x1, x2 = _scaled_ratio_x_range(width, 780 / 970.0, 962 / 970.0, min_width=96)
    y_mid = int((int(row_top) + int(row_bottom)) / 2)
    y_anchor = y_mid - 22
    return (x1, max(0, y_anchor - 20), x2, min(int(height), y_anchor + 18))


def _build_anom_text_area_variants_for_row(width, height, row_top, row_bottom):
    x_narrow = _scaled_ratio_x_range(width, 788 / 970.0, 962 / 970.0, min_width=96)
    x_wide = _scaled_ratio_x_range(width, 772 / 970.0, 962 / 970.0, min_width=104)
    y_mid = int((int(row_top) + int(row_bottom)) / 2)

    variants = []
    for y_off, hh in ((-28, 42), (-22, 42), (-16, 46)):
        y_anchor = y_mid + y_off
        t = max(0, y_anchor - (hh // 2))
        b = min(int(height), y_anchor + (hh // 2))
        variants.append((x_narrow[0], t, x_narrow[1], b))
        variants.append((x_wide[0], t, x_wide[1], b))

    # De-duplicate while preserving order.
    dedup = []
    seen = set()
    for v in variants:
        if v in seen:
            continue
        seen.add(v)
        dedup.append(v)
    return dedup


def _normalize_anom_row_text(raw_text):
    txt = str(raw_text or "")
    txt = txt.replace("\n", " ").replace("\r", " ")
    txt = txt.replace("0", "O")
    txt = re.sub(r"[^A-Za-z ]+", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip().upper()
    return txt


def _max_window_similarity(compact_text, target_text):
    if not compact_text or not target_text:
        return 0.0
    score = SequenceMatcher(None, compact_text, target_text).ratio()
    if len(compact_text) >= len(target_text):
        window = len(target_text)
        for i in range(0, len(compact_text) - window + 1):
            score = max(score, SequenceMatcher(None, compact_text[i:i + window], target_text).ratio())
    return float(score)


def _classify_wasteseeker_row_text(raw_text):
    norm = _normalize_anom_row_text(raw_text)
    compact = norm.replace(" ", "")
    if not compact:
        return "unknown", 0, norm, 0.0

    chk_score = _max_window_similarity(compact, "CHECKPOINT")
    enc_score = _max_window_similarity(compact, "ENCAMPMENT")
    cap_score = _max_window_similarity(compact, "CAPITAL")
    wst_score = _max_window_similarity(compact, "WASTESEEKER")

    has_checkpoint = (
        ("CHECKPOINT" in compact)
        or ("CHECK" in compact and "POINT" in compact)
        or chk_score >= 0.67
    )
    has_encampment = ("ENCAMPMENT" in compact) or enc_score >= 0.70
    has_wasteseeker = ("WASTESEEKER" in compact) or wst_score >= 0.78
    has_capital = (
        ("CAPITAL" in compact) or ("CAPITAI" in compact) or ("CAPITAU" in compact) or (cap_score >= 0.74)
    )

    if has_checkpoint:
        special_type = 2 if has_capital else 1
        kind = "capital_checkpoint" if special_type == 2 else "checkpoint"
        return kind, special_type, norm, chk_score + (0.10 if has_capital else 0.0)

    if has_encampment:
        return "encampment", 0, norm, enc_score

    # OCR often truncates the second line ("... Encampment"). If we still see
    # WASTESEEKER but not CHECKPOINT, treat it as encampment-like for row-walk stop.
    if has_wasteseeker and not has_checkpoint:
        return "encampment", 0, norm, wst_score * 0.9

    return "unknown", 0, norm, max(chk_score, enc_score) * 0.5


def _classify_wasteseeker_checkpoint_text(raw_text):
    _, special_type, norm, _ = _classify_wasteseeker_row_text(raw_text)
    return special_type, norm


def _count_redish_pixels_roi_arr(arr_rgb, left, top, right, bottom):
    arr_rgb = _as_rgb_array(arr_rgb)
    h, w = arr_rgb.shape[:2]
    l = max(0, int(left))
    t = max(0, int(top))
    r = min(w, int(right))
    b = min(h, int(bottom))
    if r <= l or b <= t:
        return 0

    roi = arr_rgb[t:b, l:r, :]
    rr = roi[..., 0].astype(np.int16)
    gg = roi[..., 1].astype(np.int16)
    bb = roi[..., 2].astype(np.int16)
    # Blend strict RGB bounds with ratio-based "red dominance" to tolerate glow/shimmer.
    strict = (
        ((rr >= 150) & (rr < 255) & (gg >= 25) & (gg < 140) & (bb >= 25) & (bb < 140))
        | ((rr >= 180) & (rr < 255) & (gg >= 45) & (gg < 180) & (bb >= 45) & (bb < 170))
    )
    dominant = (rr >= 80) & (rr - gg >= 28) & (rr - bb >= 28) & (gg <= 210) & (bb <= 210)
    return int(np.count_nonzero(strict | dominant))


def _detect_anom_rows_from_icon_profile(arr_rgb, row_count=5):
    arr_rgb = _as_rgb_array(arr_rgb)
    h, w = arr_rgb.shape[:2]
    icon_x1, icon_x2 = _scaled_ratio_x_range(w, 722 / 970.0, 765 / 970.0, min_width=24)
    legacy_x1, legacy_x2 = _scaled_ratio_x_range(w, 807 / 970.0, 840 / 970.0, min_width=20)

    rr = arr_rgb[:, icon_x1:icon_x2, 0].astype(np.int16)
    gg = arr_rgb[:, icon_x1:icon_x2, 1].astype(np.int16)
    bb = arr_rgb[:, icon_x1:icon_x2, 2].astype(np.int16)
    red_mask = (rr >= 80) & (rr - gg >= 28) & (rr - bb >= 28) & (gg <= 210) & (bb <= 210)
    profile = red_mask.sum(axis=1).astype(np.int32)

    kernel = np.array([1, 2, 3, 2, 1], dtype=np.int32)
    smooth = np.convolve(profile, kernel, mode='same')
    min_peak = max(8, int((icon_x2 - icon_x1) * 0.30))
    min_sep = 28

    peaks = []
    for y in range(1, len(smooth) - 1):
        v = int(smooth[y])
        if v < min_peak:
            continue
        if v < int(smooth[y - 1]) or v < int(smooth[y + 1]):
            continue
        if not peaks:
            peaks.append(y)
            continue
        if y - peaks[-1] < min_sep:
            if smooth[y] > smooth[peaks[-1]]:
                peaks[-1] = y
        else:
            peaks.append(y)

    if not peaks:
        return [], [], [], profile.tolist(), smooth.tolist(), min_peak

    peaks = sorted(peaks)[-int(max(1, row_count)):]
    peaks.sort(reverse=True)

    legacy_areas = []
    icon_areas = []
    for y in peaks:
        yy = max(1, min(h - 2, int(y)))
        legacy_areas.append((legacy_x1, yy - 1, legacy_x2, yy + 2))
        icon_areas.append((icon_x1, max(0, yy - 12), icon_x2, min(h, yy + 12)))

    return legacy_areas, icon_areas, peaks, profile.tolist(), smooth.tolist(), min_peak


def count_pixels(count_img, r1, r2, g1, g2, b1, b2):
    return count_pixels_arr(count_img, r1, r2, g1, g2, b1, b2)


# Load the images once
comma = open_image("comma.png")
space = open_image("space.png")
ap_running = open_image("ap_running.png")
ap_paused = open_image("ap_paused.png")
ap_unset = open_image("ap_unset.png")
warp_status = open_image("warp.png")
ui_toggle = open_image("ui_toggle.png")
x_symbol = open_image("x_symbol.png")


class FuelDepletedError(RuntimeError):
    """Raised when refuel flow cannot locate/select fuel after bounded retries."""


class UiDetector:
    """
    Resolution-tolerant UI detector that prefers template matching and keeps
    bounded color checks only as fallback compatibility during migration.
    """

    def __init__(self, templates=None, base_size=(960, 540), debug_enabled=False):
        self.base_width, self.base_height = base_size
        self.template_gray = {}
        self.debug_enabled = bool(debug_enabled)
        templates = templates or {}

        for name, img in templates.items():
            try:
                arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
                self.template_gray[name] = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            except Exception as exc:
                logging.warning("Failed to prepare template '%s': %s", name, exc)

    def set_debug(self, enabled):
        self.debug_enabled = bool(enabled)
        logging.info("UI debug mode %s.", "enabled" if self.debug_enabled else "disabled")

    def _debug(self, message, *args):
        if self.debug_enabled:
            logging.info("[ui-debug] " + message, *args)

    def _scaled_roi(self, frame_shape, roi):
        fh, fw = frame_shape[:2]
        sx = fw / float(self.base_width)
        sy = fh / float(self.base_height)
        l, t, r, b = roi
        l2 = max(0, int(round(l * sx)))
        t2 = max(0, int(round(t * sy)))
        r2 = min(fw, int(round(r * sx)))
        b2 = min(fh, int(round(b * sy)))
        return l2, t2, r2, b2

    def _frame_rgb(self, frame_img):
        return np.asarray(frame_img.convert("RGB"), dtype=np.uint8)

    def scaled_roi(self, frame_img, roi):
        # PIL size order is (width, height)
        fw, fh = frame_img.size
        sx = fw / float(self.base_width)
        sy = fh / float(self.base_height)
        l, t, r, b = roi
        l2 = max(0, int(round(l * sx)))
        t2 = max(0, int(round(t * sy)))
        r2 = min(fw, int(round(r * sx)))
        b2 = min(fh, int(round(b * sy)))
        return l2, t2, r2, b2

    def color_count(self, frame_img, roi, rgb_bounds):
        """
        Count pixels within half-open [low, high) bounds to match legacy range()
        semantics from count_pixels.
        """
        arr = self._frame_rgb(frame_img)
        l, t, r, b = self._scaled_roi(arr.shape, roi)
        if r <= l or b <= t:
            return 0

        roi_arr = arr[t:b, l:r, :3]
        r1, r2, g1, g2, b1, b2 = rgb_bounds
        mask = (
            (roi_arr[..., 0] >= r1) & (roi_arr[..., 0] < r2) &
            (roi_arr[..., 1] >= g1) & (roi_arr[..., 1] < g2) &
            (roi_arr[..., 2] >= b1) & (roi_arr[..., 2] < b2)
        )
        count = int(np.count_nonzero(mask))
        self._debug("color_count roi=%s bounds=%s count=%s", roi, rgb_bounds, count)
        return count

    def template_score(self, frame_img, template_name, roi=None):
        template = self.template_gray.get(template_name)
        if template is None:
            return 0.0

        frame_arr = self._frame_rgb(frame_img)
        gray = cv2.cvtColor(frame_arr, cv2.COLOR_RGB2GRAY)

        if roi is not None:
            l, t, r, b = self._scaled_roi(gray.shape, roi)
            if r <= l or b <= t:
                return 0.0
            gray = gray[t:b, l:r]

        th, tw = template.shape[:2]
        gh, gw = gray.shape[:2]
        if gh < th or gw < tw:
            return 0.0

        result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        score = float(result.max()) if result.size else 0.0
        self._debug("template_score template=%s roi=%s score=%.3f", template_name, roi, score)
        return score

    def template_present(self, frame_img, template_name, roi=None, threshold=0.78):
        return self.template_score(frame_img, template_name, roi=roi) >= threshold

    def generic_menu_highlight_present(self, frame_img, roi):
        # Legacy "light gray-ish pixel" heuristic used by click_menu.
        count = self.color_count(frame_img, roi, (100, 110, 100, 110, 100, 110))
        return count >= 1

    def symbol_present_in_roi(self, frame_img, symbol_img, roi, tolerance=0.4):
        l, t, r, b = self.scaled_roi(frame_img, roi)
        return symbol_present(frame_img, symbol_img, l, t, r, b, tolerance)

    # --- Semantic states used by refuel flow ---
    def is_main_menu_open(self, frame_img):
        # Keep prior heuristic as fallback until menu template anchors are available.
        count = self.color_count(frame_img, (507, 354, 537, 380), (50, 255, 50, 255, 50, 255))
        state = count >= 200
        self._debug("state=is_main_menu_open count=%s threshold=200 result=%s", count, state)
        return state

    def is_inventory_open(self, frame_img):
        # Prefer close-button template in expected inventory header region.
        score = self.template_score(frame_img, "x_close", roi=(917, 22, 933, 38))
        if score >= 0.72:
            self._debug("state=is_inventory_open template_score=%.3f threshold=0.72 result=True", score)
            return True
        count = self.color_count(frame_img, (917, 22, 933, 38), (50, 255, 50, 255, 50, 255))
        state = count >= 50
        self._debug("state=is_inventory_open fallback_count=%s threshold=50 result=%s", count, state)
        return state

    def is_inventory_overlay_open(self, frame_img):
        # Full overlay close hotspot used by legacy close loop.
        score = self.template_score(frame_img, "x_close", roi=(742, 14, 769, 38))
        if score >= 0.70:
            self._debug("state=is_inventory_overlay_open template_score=%.3f threshold=0.70 result=True", score)
            return True
        count = self.color_count(frame_img, (742, 14, 769, 38), (50, 255, 50, 255, 50, 255))
        state = count > 350
        self._debug("state=is_inventory_overlay_open fallback_count=%s threshold=350 result=%s", count, state)
        return state

    def is_fuel_selected(self, frame_img):
        count = self.color_count(frame_img, (437, 306, 570, 360), (190, 220, 150, 175, 90, 120))
        state = count >= 1
        self._debug("state=is_fuel_selected count=%s threshold=1 result=%s", count, state)
        return state

    def is_use_button_available(self, frame_img):
        count = self.color_count(frame_img, (930, 205, 946, 221), (50, 255, 50, 255, 50, 255))
        state = count >= 50
        self._debug("state=is_use_button_available count=%s threshold=50 result=%s", count, state)
        return state

    def is_contacts_menu_open(self, frame_img):
        count = self.color_count(frame_img, (19, 376, 30, 390), (165, 175, 0, 20, 0, 20))
        state = count >= 50
        self._debug("state=is_contacts_menu_open count=%s threshold=50 result=%s", count, state)
        return state

    def is_top_right_close_visible(self, frame_img):
        # Main top-right close icon state used by menu/logoff flow.
        score = self.template_score(frame_img, "x_close", roi=(915, 21, 931, 37))
        if score >= 0.72:
            self._debug("state=is_top_right_close_visible template_score=%.3f threshold=0.72 result=True", score)
            return True
        count = self.color_count(frame_img, (915, 21, 931, 37), (50, 255, 50, 255, 50, 255))
        state = count >= 50
        self._debug("state=is_top_right_close_visible fallback_count=%s threshold=50 result=%s", count, state)
        return state

    def is_map_search_panel_open(self, frame_img):
        """
        Detect whether map search/filter panel is currently open on the right side.
        Heuristic derived from pixel-stable UI regions:
        - gray input bar + magnifier area near top-right,
        - subtle vertical panel edge near x~700.
        """
        input_gray = self.color_count(frame_img, (705, 108, 949, 140), (55, 170, 55, 170, 55, 170))
        magnifier_bright = self.color_count(frame_img, (930, 112, 952, 134), (120, 255, 120, 255, 120, 255))
        panel_edge = self.color_count(frame_img, (697, 96, 704, 532), (20, 120, 20, 120, 20, 120))
        # Calibrated from live captures:
        # closed ~= input_gray 177 / magnifier 0 / edge 33
        # open   ~= input_gray 424 / magnifier 40 / edge 78
        state = (input_gray >= 320 and magnifier_bright >= 20) or (input_gray >= 360 and panel_edge >= 60)
        self._debug(
            "state=is_map_search_panel_open input_gray=%s magnifier=%s panel_edge=%s result=%s",
            input_gray,
            magnifier_bright,
            panel_edge,
            state,
        )
        return state

    def is_map_search_eye_closed_visible(self, frame_img):
        """
        Detect closed-state right-edge eye button (used to slide open search panel).
        """
        eye_roi = (904, 247, 945, 289)
        eye_bright = self.color_count(frame_img, eye_roi, (85, 255, 85, 255, 85, 255))
        eye_dark = self.color_count(frame_img, eye_roi, (0, 70, 0, 70, 0, 70))
        state = eye_bright >= 90 and eye_dark >= 200
        self._debug(
            "state=is_map_search_eye_closed_visible bright=%s dark=%s result=%s",
            eye_bright,
            eye_dark,
            state,
        )
        return state

    def map_search_debug_metrics(self, frame_img):
        input_gray = self.color_count(frame_img, (705, 108, 949, 140), (55, 170, 55, 170, 55, 170))
        magnifier_bright = self.color_count(frame_img, (930, 112, 952, 134), (120, 255, 120, 255, 120, 255))
        panel_edge = self.color_count(frame_img, (697, 96, 704, 532), (20, 120, 20, 120, 20, 120))
        eye_roi = (904, 247, 945, 289)
        eye_bright = self.color_count(frame_img, eye_roi, (85, 255, 85, 255, 85, 255))
        eye_dark = self.color_count(frame_img, eye_roi, (0, 70, 0, 70, 0, 70))
        panel_open = (input_gray >= 320 and magnifier_bright >= 20) or (input_gray >= 360 and panel_edge >= 60)
        eye_closed_visible = eye_bright >= 90 and eye_dark >= 200
        return {
            "input_gray": int(input_gray),
            "magnifier_bright": int(magnifier_bright),
            "panel_edge": int(panel_edge),
            "eye_bright": int(eye_bright),
            "eye_dark": int(eye_dark),
            "panel_open": bool(panel_open),
            "eye_closed_visible": bool(eye_closed_visible),
        }

    def find_teal_destination_y(self, frame_img, start_x=855, start_y=130, target_rgb=(59, 109, 101), tolerance=10):
        l, t, r, b = self.scaled_roi(frame_img, (start_x, start_y, start_x + 1, 540))
        if r <= l or b <= t:
            return None

        arr = self._frame_rgb(frame_img)
        column = arr[t:b, l, :3]
        target = np.array(target_rgb, dtype=np.int16)
        diffs = np.abs(column.astype(np.int16) - target)
        matches = np.all(diffs <= int(tolerance), axis=1)

        idx = np.flatnonzero(matches)
        if idx.size == 0:
            self._debug("state=find_teal_destination_y result=None tolerance=%s", tolerance)
            return None

        found_y = int(t + idx[0])
        y_out = found_y + 55
        self._debug("state=find_teal_destination_y result=%s tolerance=%s", y_out, tolerance)
        return y_out

    def autopilot_status(self, frame_img):
        # Use both a tight ROI and a slightly expanded ROI to tolerate shimmer/offset.
        rois = ((13, 137, 31, 159), (10, 132, 36, 164))
        score_running = max(self.template_score(frame_img, "ap_running", roi=roi) for roi in rois)
        score_unset = max(self.template_score(frame_img, "ap_unset", roi=roi) for roi in rois)
        score_paused = max(self.template_score(frame_img, "ap_paused", roi=roi) for roi in rois)

        scores = {
            "running": float(score_running),
            "unset": float(score_unset),
            "paused": float(score_paused),
        }
        ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_status, best_score = ordered[0]
        second_score = ordered[1][1]

        # Hard threshold handles clean matches; soft+margin handles tinted/shimmer states.
        hard_threshold = 0.68
        soft_threshold = 0.50
        min_margin = 0.06

        if best_score >= hard_threshold:
            status = best_status
        elif best_score >= soft_threshold and (best_score - second_score) >= min_margin:
            status = best_status
        else:
            status = "unknown"

        self._debug(
            "state=autopilot_status running=%.3f unset=%.3f paused=%.3f best=%s best_score=%.3f second=%.3f hard=%.2f soft=%.2f margin=%.2f result=%s",
            score_running,
            score_unset,
            score_paused,
            best_status,
            best_score,
            second_score,
            hard_threshold,
            soft_threshold,
            min_margin,
            status,
        )
        return status


class UiNavigator:
    """
    Small action/state helper for menu navigation.
    Designed to keep control flow deterministic and testable.
    """

    REFUEL_CLOSE_INVENTORY_XY = (925, 32)
    REFUEL_CLICK_JITTER = 15

    def __init__(self, client, detector):
        self.client = client
        self.detector = detector

    async def capture_frame(self):
        async with self.client.pull_win_lock:
            frame, _ = await self.client.async_pull_win()
        return frame

    async def ensure_state(self, state_name, predicate, click_action, max_attempts, delay_min, delay_max):
        frame = await self.capture_frame()
        if predicate(frame):
            logging.info("[ui] State '%s' already true.", state_name)
            return True, frame

        for attempt in range(1, max_attempts + 1):
            await click_action()
            await delay(delay_min, delay_max)
            frame = await self.capture_frame()
            if predicate(frame):
                logging.info("[ui] State '%s' reached on attempt %s.", state_name, attempt)
                return True, frame

        logging.warning("[ui] Failed to reach state '%s' after %s attempts.", state_name, max_attempts)
        return False, frame

    async def transition_state(self, state_name, predicate, click_action, target_value, max_attempts, delay_min, delay_max):
        frame = await self.capture_frame()
        if bool(predicate(frame)) is bool(target_value):
            logging.info("[ui] State '%s' already at target=%s.", state_name, target_value)
            return True, frame

        for attempt in range(1, max_attempts + 1):
            await click_action()
            await delay(delay_min, delay_max)
            frame = await self.capture_frame()
            if bool(predicate(frame)) is bool(target_value):
                logging.info("[ui] State '%s' reached target=%s on attempt %s.", state_name, target_value, attempt)
                return True, frame

        logging.warning("[ui] Failed state transition '%s' to target=%s after %s attempts.", state_name, target_value, max_attempts)
        return False, frame

    async def click_until_menu_state(
            self,
            menu_name,
            click_action,
            symbol_img,
            roi,
            invert=False,
            max_retries=2,
            timeout=8.0,
            pre_delay_min=200,
            pre_delay_max=300,
            poll_interval=0.1
    ):
        async def state_reached(frame_img):
            highlight = self.detector.generic_menu_highlight_present(frame_img, roi)
            symbol_hit = self.detector.symbol_present_in_roi(frame_img, symbol_img, roi)
            if not invert:
                return highlight or symbol_hit
            return highlight or (not symbol_hit)

        await delay(pre_delay_min, pre_delay_max)
        await click_action()

        retries = 0
        while retries < max_retries:
            start_time = time.time()
            while time.time() - start_time < timeout:
                frame = await self.capture_frame()
                if await state_reached(frame):
                    logging.info("[ui] %s opened successfully.", menu_name)
                    return True
                await asyncio.sleep(poll_interval)

            retries += 1
            if retries < max_retries:
                logging.info("[ui] Retrying '%s' (%s/%s).", menu_name, retries, max_retries)
                await click_action()

        logging.warning("[ui] Failed to open '%s' after %s retries.", menu_name, max_retries)
        return False

    async def close_inventory_overlay(self, frame_img, close_inventory_xy=(927, 32), jitter=8, max_attempts=8):
        attempts = 0
        frame = frame_img
        while self.detector.is_inventory_overlay_open(frame) and attempts < max_attempts:
            await click(close_inventory_xy[0], close_inventory_xy[1], 0, jitter, jitter)
            await delay(1300, 1700)
            frame = await self.capture_frame()
            attempts += 1

        return not self.detector.is_inventory_overlay_open(frame)

    async def close_refuel_inventory(self, frame_img=None, max_attempts=8):
        if frame_img is None:
            frame_img = await self.capture_frame()
        return await self.close_inventory_overlay(
            frame_img,
            close_inventory_xy=self.REFUEL_CLOSE_INVENTORY_XY,
            jitter=self.REFUEL_CLICK_JITTER,
            max_attempts=max_attempts
        )

    async def run_refuel_flow(self):
        await asyncio.to_thread(activate_window, 2)
        await delay()

        # Refuel click calibration points (viewport/base coordinates).
        open_inventory_xy = (23, 88)
        select_fuel_xy = (264, 113)
        click_refuel_xy = (829, 130)
        confirm_refuel_xy = (867, 407)
        close_inventory_xy = self.REFUEL_CLOSE_INVENTORY_XY
        refuel_click_jitter = self.REFUEL_CLICK_JITTER

        ok, frame = await self.ensure_state(
            "inventory_open",
            self.detector.is_inventory_open,
            lambda: click(open_inventory_xy[0], open_inventory_xy[1], 0, refuel_click_jitter, refuel_click_jitter),
            max_attempts=5,
            delay_min=1800,
            delay_max=2400
        )
        if not ok:
            raise RuntimeError("Failed to open inventory during refuel.")

        failure_count = 0
        while True:
            frame = await self.capture_frame()
            if self.detector.is_fuel_selected(frame):
                break

            if failure_count >= 3:
                raise FuelDepletedError("Fuel row not detected after retries.")

            await click(select_fuel_xy[0], select_fuel_xy[1], 0, refuel_click_jitter, refuel_click_jitter)
            await delay(1500, 3000)
            failure_count += 1

        ok, frame = await self.ensure_state(
            "use_button_available",
            self.detector.is_use_button_available,
            lambda: click(click_refuel_xy[0], click_refuel_xy[1], 0, refuel_click_jitter, refuel_click_jitter),
            max_attempts=5,
            delay_min=1300,
            delay_max=1900
        )
        if not ok:
            raise RuntimeError("Failed to expose fuel 'Use' action.")

        ok, frame = await self.transition_state(
            "confirm_refuel_usage",
            self.detector.is_use_button_available,
            lambda: click(confirm_refuel_xy[0], confirm_refuel_xy[1], 0, refuel_click_jitter, refuel_click_jitter),
            target_value=False,
            max_attempts=5,
            delay_min=1300,
            delay_max=1900
        )
        if not ok:
            raise RuntimeError("Failed to confirm fuel usage.")

        if not await self.close_inventory_overlay(
            frame,
            close_inventory_xy=close_inventory_xy,
            jitter=refuel_click_jitter
        ):
            logging.warning("[ui] Overlay close did not fully converge; continuing.")

        return time.time() + random.randint(1800, 3600)

    async def run_logoff_flow(self):
        await asyncio.to_thread(activate_window, 2)
        await delay()

        # If a close button is visible, close overlays first.
        _, frame = await self.transition_state(
            "overlay_closed_before_logoff",
            self.detector.is_top_right_close_visible,
            lambda: click(922, 27, 0, 8, 8),
            target_value=False,
            max_attempts=8,
            delay_min=1300,
            delay_max=2000
        )

        # Open menu (close icon should become visible).
        ok, frame = await self.transition_state(
            "menu_open_for_logoff",
            self.detector.is_top_right_close_visible,
            lambda: click(80, 88, 0, 8, 8),
            target_value=True,
            max_attempts=6,
            delay_min=1800,
            delay_max=2800
        )
        if not ok:
            raise RuntimeError("Failed to open menu for logoff.")

        # Open settings submenu before triggering logoff.
        await click(525, 477, 0, 20, 20)
        await delay(900, 1400)

        # Trigger logoff until menu closes.
        ok, frame = await self.transition_state(
            "menu_closed_after_logoff_click",
            self.detector.is_top_right_close_visible,
            lambda: click(879, 505, 0, 80, 30),
            target_value=False,
            max_attempts=8,
            delay_min=1800,
            delay_max=2800
        )
        if not ok:
            logging.warning("[ui] Menu remained open after logoff attempts; continuing.")

        return frame

    async def find_destination_y(self, retries=3, retry_delay=0.5, tolerance=10):
        for attempt in range(1, retries + 1):
            frame = await self.capture_frame()
            y = self.detector.find_teal_destination_y(frame, tolerance=tolerance)
            if y is not None:
                logging.info("[ui] Destination marker found at y=%s on attempt %s.", y, attempt)
                return y
            logging.info("[ui] Destination marker not found on attempt %s/%s.", attempt, retries)
            await asyncio.sleep(retry_delay)
        return None

    async def ensure_autopilot_running(self, max_attempts=3):
        # Initial probe: avoid toggling AP if it is already running but one frame is noisy.
        frame = await self.capture_frame()
        status = self.detector.autopilot_status(frame)
        if status == "running":
            return True, status, frame
        await delay(180, 320)
        frame = await self.capture_frame()
        status = self.detector.autopilot_status(frame)
        if status == "running":
            return True, status, frame

        for attempt in range(1, max_attempts + 1):
            # Re-check just before toggling to prevent accidental pause.
            frame = await self.capture_frame()
            status = self.detector.autopilot_status(frame)
            if status == "running":
                return True, status, frame

            # Unknown is ambiguous (often shimmer/noise while AP is actually running).
            # Avoid blind toggles in that state; just wait and re-sample.
            if status == "unknown":
                await delay(420, 760)
                continue

            # Confidently non-running states can be toggled.
            await click(20, 148, 0, 0, 0)
            await delay(350, 650)
            frame = await self.capture_frame()
            status = self.detector.autopilot_status(frame)
            if status == "running":
                logging.info("[ui] Autopilot running after attempt %s.", attempt)
                return True, status, frame

        logging.warning("[ui] Autopilot did not enter running state (last status=%s).", status)
        return False, status, frame


def _channel_name_matches(channel_name: Optional[str], target_name: Optional[str]) -> bool:
    channel_norm = str(channel_name or "").strip().lower()
    target_norm = str(target_name or "").strip().lower()
    if not channel_norm or not target_norm:
        return False
    return target_norm == channel_norm or target_norm in channel_norm


async def check_channel_name(message: Message, target_channel_name: str, warning_msg: Optional[str],
                             image_byte_arr: Optional[BytesIO] = None) -> None:
    assert resume_time is None or isinstance(resume_time, datetime)

    if pause_requested or (isinstance(resume_time, datetime) and datetime.now() < resume_time):
        await asyncio.sleep(1)  # Brief sleep to prevent busy-waiting
        return

    # Find the channels that match the target channel name
    channels = [
        channel
        for channel in message.guild.text_channels
        if _channel_name_matches(channel.name, target_channel_name)
    ]

    if channels:
        for channel in channels:
            try:
                if image_byte_arr:
                    # Ensure image_byte_arr is a BytesIO object
                    if not isinstance(image_byte_arr, io.BytesIO):
                        raise ValueError("image_byte_arr should be a BytesIO object")

                    image_byte_arr.seek(0)  # Ensure the BytesIO object is at the start

                    # Use BytesIO object for the image
                    await channel.send(file=discord.File(fp=image_byte_arr, filename=f"image_{scout}.png"))
                    print("IMAGE SENT")
                    return
                elif warning_msg:  # Ensure warning_msg is not empty
                    if warning_msg.strip():  # Check if the warning message contains non-whitespace characters
                        # Escape special characters for Discord
                        # warning_msg = re.sub(r'([*_~`|])', r'\\\1', warning_msg)
                        await channel.send(f'{warning_msg}')
                    else:
                        print(f"Warning: Attempted to send an empty message to channel {channel.name}")
                else:
                    print(f"Warning: Attempted to send an empty message to channel {channel.name}")
            except Exception as e:
                logging.error(f'An error occurred while sending message to channel {channel.name}: {e}')
                print(f'An error occurred while sending message to channel {channel.name}: {e}')
    else:
        print(f'Error: Cannot find any channel to post text warning')
        try:
            print(f'Error: Cannot find any channel to post text warning')
        except Exception as e:
            logging.error(f'An error occurred while sending error message to the current channel: {e}')
            print(f'An error occurred while sending error message to the current channel: {e}')

def try_acquire_refuel_mutex_nonblocking():
    """
    Returns True if we successfully acquire the mutex.
    Returns False if another process holds it, so we skip.
    """
    mutex_handle = win32event.CreateMutex(None, False, MUTEX_NAME)
    # Zero-timeout => non-blocking
    result = win32event.WaitForSingleObject(mutex_handle, 0)
    if result in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
        # We now own the lock
        return mutex_handle
    else:
        # WAIT_TIMEOUT => lock is busy
        win32api.CloseHandle(mutex_handle)
        return None


def try_acquire_instance_mutex_nonblocking():
    """
    Acquire a process-wide single-instance lock for this app variant.
    Uses script/exe name in the mutex to allow distinct scouts (e.g., cam1/prototype)
    to run concurrently while preventing accidental duplicate instances of the same bot.
    """
    global script_filename
    mutex_name = f"Local\\Eyes_Instance_{str(script_filename).lower()}"
    mutex_handle = win32event.CreateMutex(None, False, mutex_name)
    result = win32event.WaitForSingleObject(mutex_handle, 0)
    if result in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
        return mutex_handle
    win32api.CloseHandle(mutex_handle)
    return None

def release_refuel_mutex(mutex_handle):
    """Release and close our handle."""
    if mutex_handle:
        win32event.ReleaseMutex(mutex_handle)
        win32api.CloseHandle(mutex_handle)


def release_instance_mutex(mutex_handle):
    if mutex_handle:
        win32event.ReleaseMutex(mutex_handle)
        win32api.CloseHandle(mutex_handle)


def pull_win(scout):
    # Begin gathering screenshot
    # define window
    hwnd = win32gui.FindWindow(None, f'{scout}')
    if hwnd == 0:
        print(f"Window with title '{scout}' not found.")
        return None, None  # Return None values indicating failure

    if not win32gui.IsWindow(hwnd):
        print("Invalid window handle.")
        return None, None

    # pull window
    _ensure_process_dpi_aware()
    '''
    left_pw, top_pw, right_pw, bot = win32gui.GetClientRect(hwnd)
    screen_width = right_pw - left_pw
    screen_height = bot - top_pw
    '''

    window_rect = win32gui.GetClientRect(hwnd)
    screen_width = window_rect[2] - window_rect[0]
    screen_height = window_rect[3] - window_rect[1]
    # print(f"It thinks it is: {screen_width}x{screen_height}")

    '''
    # if screen_width != 960 or screen_height != 575:
    if screen_width != 960 or screen_height != 589:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except AttributeError:
            logging.error(f'Failed to set DPI awareness.')

        if hwnd:
            # Get the current window position and size
            original_rect = win32gui.GetClientRect(hwnd)
            original_width_sc = original_rect[2] - original_rect[0]
            original_height_sc = original_rect[3] - original_rect[1]
            print(f"Original Window Size: {original_width_sc}x{original_height_sc}")

            # Set the new window size and stretch its contents
            new_width_sc = 960
            new_height_sc = 575

            # Use the SWP_NOREPOSITION flag to stretch the contents
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOP, 0, 0, new_width_sc, new_height_sc,
                win32con.SWP_SHOWWINDOW | win32con.SWP_NOREPOSITION
            )
        else:
            print(f"Window with title '{scout}' not found.")
    '''
    # screen_width = 960
    # screen_height = 575
    try:
        result, pnginfo, pngstr = _pull_win_capture_ctx.capture(hwnd, screen_width, screen_height, 1 | 0x00000002)
    except Exception:
        # One best-effort reset/retry if cached GDI objects became stale.
        _pull_win_capture_ctx.reset()
        try:
            result, pnginfo, pngstr = _pull_win_capture_ctx.capture(hwnd, screen_width, screen_height, 1 | 0x00000002)
        except Exception as capture_error:
            logging.error("pull_win capture failed after context reset: %s", capture_error)
            return None, None

    # Convert the captured data into an image
    im = Image.frombuffer(
        'RGB',
        (pnginfo['bmWidth'], pnginfo['bmHeight']),
        pngstr, 'raw', 'BGRX', 0, 1
    )

    top_inset = _compute_top_inset(screen_height)
    if top_inset <= 0 and top_inset_override_px is None and screen_height == BASE_FRAME_HEIGHT:
        global auto_top_inset_cache_px
        cached_inset = None if auto_top_inset_cache_px is None else int(auto_top_inset_cache_px)
        if cached_inset is not None and 0 < cached_inset < im.height:
            top_inset = cached_inset
        else:
            detected_inset = _estimate_embedded_top_chrome_inset(im)
            if detected_inset > 0 and detected_inset < im.height:
                auto_top_inset_cache_px = detected_inset
                top_inset = detected_inset
                logging.info(
                    "Auto-detected embedded top inset for scout '%s': %spx.",
                    scout,
                    detected_inset,
                )

    # Verify and reload the image
    # (is_corrupted := verify(im))[0] and print(f"Image is corrupted at line {(is_corrupted := verify(im))[1]}")

    '''
    Reload the image after verification
    im = Image.frombuffer(
        'RGB',
        (pnginfo['bmWidth'], pnginfo['bmHeight']),
        pngstr, 'raw', 'BGRX', 0, 1
    )
    (is_corrupted := verify(im))[0] and print(f"Image is corrupted at line {(is_corrupted := verify(im))[1]}")


    # Further process the image (e.g., cropping, resizing)
    def find_non_menu_pixel(image):
        width, height = image.size
        menu_color = (20, 24, 31)  # Adjusted RGB values based on the top-left pixel
        menu_color2 = (6, 6, 31)
        menu_color3 = (19, 19, 19)

        for y in range(height):
            pixel = image.getpixel((10, y))
            if pixel != menu_color and pixel != menu_color2 and pixel != menu_color3:
                return y
        return height  # Return the full height if no non-blue pixel is found

    def remove_menu_band(image):
        top_non_menu = find_non_menu_pixel(image)
        if top_non_menu > 0:
            cropped_image = image.crop((0, top_non_menu, image.width, image.height))
            return cropped_image
        return image  # No blue band found, return the original image

    def find_non_menu_pixel_bottom(image, column=10):
        width, height = image.size
        menu_colors = [(0, 0, 0), (20, 24, 31), (32, 32, 58)]

        for y in range(height - 1, -1, -1):  # Start from the bottom and move up
            pixel = image.getpixel((column, y))
            if pixel not in menu_colors:
                return y

        return 0  # Return 0 if no non-menu pixel is found, i.e., keep the entire height

    def remove_bottom_menu_band(image):
        bottom_non_menu = find_non_menu_pixel_bottom(image)
        if bottom_non_menu < image.height - 1:
            cropped_image = image.crop((0, 0, image.width, bottom_non_menu + 1))
            return cropped_image

        return image  # No non-menu pixel found at the bottom, return the original image

    def find_non_menu_pixel_left(image, row_fraction=0.5, menu_colors=None):
        if menu_colors is None:
            menu_colors = [(6, 6, 31), (20, 24, 31), (32, 32, 58)]

        width, height = image.size
        row_height = int(height * row_fraction)

        for x in range(width):
            # Check the pixel color at the current x-coordinate and a specific y-coordinate
            pixel = image.getpixel((x, row_height))
            if pixel not in menu_colors:
                return x

        return 0  # Return 0 if no non-menu pixel is found, i.e., keep the entire width

    def remove_side_menu_band(image, cut_pixels=100, side_menu_colors=None):
        if menu_colors is None:
            side_menu_colors = [(6, 6, 31), (20, 24, 31), (32, 32, 58)]

        width, height = image.size

        # Find the leftmost non-menu pixel
        left_non_menu = find_non_menu_pixel_left(image, menu_colors=side_menu_colors)

        # Adjust to cut an equal number of pixels from both sides
        pixels_to_cut_each_side = cut_pixels

        if left_non_menu < width - cut_pixels:
            # Adjust the left and right boundaries
            new_left = max(pixels_to_cut_each_side, 0)  # Ensures we don't go negative
            new_right = min(width - pixels_to_cut_each_side, width)  # Ensures we don't exceed image width

            cropped_image = image.crop((new_left, 0, new_right, height))
            return cropped_image

        return image  # No non-menu pixel found from the side, return the original image

    bottom_check = 575 - find_non_menu_pixel_bottom(im)
    side_check = find_non_menu_pixel_left(im)
    im = remove_menu_band(im)
    if side_check > 1:
        menu_colors = [(6, 6, 31), (20, 24, 31), (32, 32, 58)]
        im = remove_side_menu_band(im, side_check, menu_colors)
    if bottom_check > 1:
        im = remove_bottom_menu_band(im)
    '''

    if top_inset > 0 and top_inset < im.height:
        logging.debug(
            "pull_win: applying top inset crop=%s (client_h=%s scout=%s)",
            top_inset,
            screen_height,
            scout,
        )
        im = im.crop((0, top_inset, im.width, im.height))
    # print(f'After removing topbar: {im.width} x {im.height}')
    if im.size != (BASE_FRAME_WIDTH, BASE_FRAME_HEIGHT):
        im = im.resize((BASE_FRAME_WIDTH, BASE_FRAME_HEIGHT), Image.Resampling.LANCZOS)

    # Keep the processed frame in-memory directly (avoid PNG encode/decode roundtrip).

    return im, result


def load_data():
    with open('ships.json', 'r') as f:
        ship_categories = json.load(f)

    with open('exclusions.json', 'r') as f:
        exclusions = json.load(f)

    return ship_categories, exclusions


# Class definition for the Discord client
class MyClient(discord.Client):
    def __init__(self, num_worker_threads=5, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.message = None
        self.eyes_running = False
        self.eyes_task = None
        self.heartbeat_task = None
        self.batch_queue = asyncio.Queue()
        self.num_worker_threads = num_worker_threads  # Set the number of worker threads
        self.result_queue = asyncio.Queue()
        self.executor = ThreadPoolExecutor()
        # Keep OCR out of the event loop; also avoid starving screen-capture work.
        self.ocr_executor = ThreadPoolExecutor(max_workers=2)
        # Bound enemy processing fan-out to avoid unbounded task accumulation.
        self.enemy_worker_concurrency = 2
        self.enemy_task_backlog_limit = self.enemy_worker_concurrency * 2
        self.enemy_process_semaphore = asyncio.Semaphore(self.enemy_worker_concurrency)

        # Queue and list to handle enemy detection and images
        self.enemy_queue = asyncio.Queue(maxsize=50)  # Set a max size for the queue
        self.detected_enemies = []  # Initialize list to store detected enemies
        self.screenshots = {}  # Dictionary to store screenshots by enemy ID or position
        self.image_batch = {}  # List or dict to hold image pairs (Enemy Name, Shiptype)

        # Target channel attributes
        self.channel = None  # Store channel object
        self.channel_id = None  # Store the current channel ID where the bot sends images
        self.target_channel_id = None  # Store the target channel ID
        self.target_channel_name = None  # Store the target channel name

        self.scout = scout
        self.target_channel_name = target_channel_name
        self.system = system

        # Locking mechanisms for batch and window processing
        self.batch_lock = asyncio.Lock()
        self.pull_win_lock = asyncio.Lock()
        self.ui_debug_enabled = UI_DEBUG_DEFAULT
        self.ui_detector = UiDetector(
            templates={
                "x_close": x_symbol,
                "ap_running": ap_running,
                "ap_paused": ap_paused,
                "ap_unset": ap_unset,
            },
            debug_enabled=self.ui_debug_enabled
        )
        self.ui_navigator = UiNavigator(self, self.ui_detector)

        # Batch processing variables
        self.batch_send_task = None  # Task for sending batches of images
        self.batch_send_in_progress = False  # Flag to check if batch sending is ongoing
        self.batches = {}  # Dictionary to store image batches by unique ID

        # Stitching queue and worker task
        self.stitch_queue = asyncio.Queue()
        self.stitch_worker_task = None

        # Recently processed enemies and detection interval
        self.recent_enemies = {}
        self.detection_interval = 0.5  # Set detection interval time
        # Final image-send dedupe guard (protects against duplicate stitched reports).
        self.recent_stitched_reports = {}
        self.stitched_report_cooldown_seconds = 20
        self.stitched_report_hash_tolerance = 2

        # In-flight guard: prevents the detector from enqueueing the same contact repeatedly while an OCR/report task
        # is still running (or stuck). Keys are perceptual hashes (hex strings). Values are "last touched" timestamps.
        self.inflight_enemies = {}
        self.inflight_ttl_seconds = 60
        self.inflight_hash_tolerance = 2

        # Load ship categories and exclusions from files
        self.ship_categories, self.exclusions = load_data()  # Load data from files
        self.exclusions = self.exclusions['exclusions']  # Extract the list of exclusions

        # Handle Seeker initiation and self-termination timer
        self.seek_task = None
        self.seek_end_time = None  # Track when the seek task should end
        self.seeking_active = False

        # Misc
        self.resume_time: Optional[datetime] = None
        self.save_img_log = save_img_log
        self.websocket = None
        self.websocket_url = EC2_WEBSOCKET_URL # Replace with your server's address
        self.websocket_task = None
        self._uinput_warmup_task = None
        self.sightings_lock = asyncio.Lock()
        self.heartbeat_task = None
        self.peep_task = None
        self.button_message_id = 1350284130834972836
        self.aoa_cnt = 0
        self.aoa_threat_active = False

        # Load constellations.json once during initialization
        with open('constellations.json', 'r') as file:
            self.constellations_data = json.load(file)

    def set_ui_debug(self, enabled: bool):
        self.ui_debug_enabled = bool(enabled)
        self.ui_detector.set_debug(self.ui_debug_enabled)

    def ui_debug_status_text(self):
        return "ON" if self.ui_debug_enabled else "OFF"

    async def close(self):
        if self._uinput_warmup_task is not None and not self._uinput_warmup_task.done():
            self._uinput_warmup_task.cancel()
        _close_emuinput_controller()
        await super().close()

    async def _ocr_image_to_string(self, img, *, lang=None, config=""):
        """
        pytesseract is a blocking subprocess call; run it off the event loop.
        """
        loop = asyncio.get_running_loop()
        fn = functools.partial(pytesseract.image_to_string, img, lang=lang, config=config)
        return await loop.run_in_executor(self.ocr_executor, fn)

    def _prune_inflight_enemies(self, now=None):
        now = time.time() if now is None else now
        expired = [k for k, ts in self.inflight_enemies.items() if (now - ts) > self.inflight_ttl_seconds]
        for k in expired:
            del self.inflight_enemies[k]

    def _find_inflight_match(self, enemy_signature: str):
        """
        Returns an existing in-flight key that matches within tolerance, else None.
        This helps if the perceptual hash jitters slightly frame-to-frame.
        """
        try:
            sig_hash = imagehash.hex_to_hash(enemy_signature)
        except Exception:
            return None

        for k in self.inflight_enemies.keys():
            try:
                if (sig_hash - imagehash.hex_to_hash(k)) <= self.inflight_hash_tolerance:
                    return k
            except Exception:
                continue
        return None

    def _prune_recent_stitched_reports(self, now=None):
        now = time.time() if now is None else now
        expired = [
            k for k, ts in self.recent_stitched_reports.items()
            if (now - ts) > self.stitched_report_cooldown_seconds
        ]
        for k in expired:
            del self.recent_stitched_reports[k]

    def _is_recent_stitched_report_duplicate(self, report_hash, now=None):
        now = time.time() if now is None else now
        self._prune_recent_stitched_reports(now)

        try:
            current_hash = imagehash.hex_to_hash(report_hash)
        except Exception:
            return False

        for prior_hash_hex, prior_ts in self.recent_stitched_reports.items():
            if (now - prior_ts) > self.stitched_report_cooldown_seconds:
                continue
            try:
                prior_hash = imagehash.hex_to_hash(prior_hash_hex)
            except Exception:
                continue
            if (current_hash - prior_hash) <= self.stitched_report_hash_tolerance:
                return True

        self.recent_stitched_reports[report_hash] = now
        return False

    async def async_pull_win(self):
        loop = asyncio.get_running_loop()
        # Assuming 'scout' is an attribute of 'self'
        im, result = await loop.run_in_executor(self.executor, pull_win, self.scout)
        return im, result

    # Stitch worker to process the queue sequentially
    async def stitch_worker(self):
        while True:
            # Get the next task (batch) from the queue
            batch = await self.stitch_queue.get()

            try:
                # Process the batch (stitch and send images)
                if batch:  # Ensure the batch is not empty
                    await self.stitch_and_send_images(batch)
            except Exception as e:
                logging.error(f"Error while processing stitch task: {e}")
            finally:
                # Mark the task as done to unblock the queue
                self.stitch_queue.task_done()

    # Queue size monitoring
    async def monitor_queue_size(self):
        QUEUE_WARNING_THRESHOLD = 0.8  # 80% full
        QUEUE_OVERFLOW_THRESHOLD = 0.95  # 95% full

        while True:
            queue_size = self.enemy_queue.qsize()
            max_queue_size = self.enemy_queue.maxsize

            # Log a warning if the queue is nearing its capacity
            if queue_size / max_queue_size >= QUEUE_WARNING_THRESHOLD:
                logging.warning(f"Enemy detection queue is almost full: {queue_size}/{max_queue_size}")

            # Trigger load reduction if the queue is about to overflow
            if queue_size / max_queue_size >= QUEUE_OVERFLOW_THRESHOLD:
                logging.error(f"Queue overflow imminent! Adjusting processing logic to prevent overload.")
                await self.increase_queue_size(new_maxsize=max_queue_size * 2)  # Increase queue size dynamically
                await self.reduce_detection_load()

            await asyncio.sleep(1)  # Check every second (adjust as needed)

    # Dynamically increase the queue size
    async def increase_queue_size(self, new_maxsize):
        logging.info(f"Increasing queue size from {self.enemy_queue.maxsize} to {new_maxsize}")
        self.enemy_queue._maxsize = new_maxsize  # Dynamically change the max size of the queue

    # Function to reduce the detection load
    async def reduce_detection_load(self):
        logging.info("Reducing detection load due to queue overload.")
        # Slow down detection frequency to reduce overload
        self.detection_interval = min(self.detection_interval * 2, 10)  # Increase detection interval
        logging.info(f"Detection interval increased to {self.detection_interval} seconds.")

    sheets_buffer = []

    async def add_to_buffer(self, worksheet, row_data):
        global sheets_buffer
        MAX_BUFFER_SIZE = 5  # Max number of rows before sending
        sheets_buffer.append(row_data)

        # Flush if buffer is full
        if len(sheets_buffer) >= MAX_BUFFER_SIZE:
            await self.flush_to_sheets(worksheet)

    async def flush_to_sheets(self, worksheet):
        global sheets_buffer
        if sheets_buffer:
            try:
                start_time = time.time()

                # Get the current event loop
                loop = asyncio.get_running_loop()

                # Offload the append_row operation to an executor
                await loop.run_in_executor(None, worksheet.append_rows, sheets_buffer)

                end_time = time.time()
                logging.info(f'Google Sheets append_rows took {end_time - start_time} seconds')

                # Clear the buffer after sending
                sheets_buffer = []
            except Exception as e:
                logging.error(f'An error occurred while updating Google Sheet: {e}')

    async def send_image(self, crop_img, scout=''):
        global channel

        img_byte_arr = BytesIO()
        crop_img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)

        if self.channel is None:
            logging.error(f"Failed to retrieve channel. Cannot send image.")
            return False

        # Send the image with rate limit handling
        await self.send_image_with_retry(img_byte_arr)

    def is_excluded(self, ocr_result, exclude_keywords):
        for keyword in exclude_keywords:
            if keyword in ocr_result:
                return True
        return False

    async def batch_processor(self):
        while True:
            try:
                # Wait for new batch processing tasks
                name_img, shiptype_img, range_img, ocr_result, ocr_ship_type = await self.batch_queue.get()

                # Handle the batch addition and delayed send here
                await self.add_to_batch(name_img, shiptype_img, range_img, ocr_result, ocr_ship_type)

                # Notify the queue that this task is complete
                self.batch_queue.task_done()

            except Exception as e:
                logging.error(f"Error in batch_processor: {e}")

    async def ocr_enemy_ui(self, name_img, shiptype_img, engine='echoes'):
        # Get the width and height of the original image
        name_width, name_height = name_img.size
        shiptype_width, shiptype_height = shiptype_img.size

        # Perform OCR on name and ship type in parallel to reduce end-to-end latency.
        name_task = asyncio.create_task(
            self.ocr_section(
                name_img,
                0,
                0,
                name_width,
                name_height,
                psm=7,
                debug_num='1',
                engine=engine
            )
        )
        shiptype_task = asyncio.create_task(
            self.ocr_section(
                shiptype_img,
                0,
                0,
                shiptype_width,
                shiptype_height,
                whitelist='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ',
                debug_num='2',
                engine='shiptype'
            )
        )
        ocr_position, ocr_position_ship_type = await asyncio.gather(name_task, shiptype_task)

        # Debugging output to confirm the type and content
        if not isinstance(ocr_position, str):
            raise TypeError(f"Expected string, got {type(ocr_position)} instead.")

        # Clean up newlines and carriage returns from the OCR result
        ocr_position = ocr_position.replace('\n', '').replace('\r', "")

        # Perform OCR on the ship type image
        ocr_position_ship_type = str(ocr_position_ship_type)

        # Clean up newlines and carriage returns from the OCR result for the ship type
        ocr_position_ship_type = ocr_position_ship_type.replace('\n', '').replace('\r', "")

        # Debugging logs before cleanup
        # print(f'[INFO] Raw OCR result before cleanup: {ocr_position}')
        # print(f'[INFO] Raw OCR result before cleanup: {ocr_position_ship_type}')

        # Clean up the OCR results to ensure they're in a valid state
        ocr_position = self.ocr_cleanup(ocr_position, name=1)
        ocr_position_ship_type = self.ocr_cleanup(ocr_position_ship_type, add_space=1)

        # Debugging logs after cleanup
        logging.info(f'[INFO] Cleaned OCR result: {ocr_position}')
        logging.info(f'[INFO] Cleaned OCR result: {ocr_position_ship_type}')

        # Check if the cleaned enemy name or ship type is valid
        if len(ocr_position.strip()) == 0:
            logging.error(f"Invalid enemy name after cleanup: {ocr_position}")
            return "", "", False  # Return empty strings if the OCR failed for the enemy name

        if len(ocr_position_ship_type.strip()) == 0:
            logging.error(f"Invalid ship type after cleanup: {ocr_position_ship_type}")
            return ocr_position, "", False  # Return only enemy name if the ship type failed

        # Check if the result should be excluded[p
        if self.is_excluded(ocr_position, self.exclusions):
            print(f"Excluding OCR result: {ocr_position}")

            return ocr_position, ocr_position_ship_type, False

        ping_list = False  # You can adjust this based on other criteria if needed

        # Debug logging of the final OCR results
        logging.info(f"Final OCR enemy name: {ocr_position}")
        logging.info(f"Final OCR ship type: {ocr_position_ship_type}")

        return ocr_position, ocr_position_ship_type, ping_list

    # Function to clean up OCR results
    def ocr_cleanup(self, ocr_dirty, *strip_strings, add_space=0, name=0):
        # logging.info(f'[DEBUG] Raw OCR result before cleanup: {ocr_dirty}')
        ocr_clean = ocr_dirty.replace('\n', "").replace('\r', "")
        if name == 1:
            ocr_clean = ocr_clean.lstrip()
            # Check if the first character is '(' and replace it with '['
            if ocr_clean.startswith('('):
                ocr_clean = '[' + ocr_clean[1:]
            # Normalize full-width/round leading corp tags to square brackets.
            ocr_clean = re.sub(r'^\u3010([^\u3010\u3011\r\n]{1,24})\u3011', r'[\1]', ocr_clean)
            ocr_clean = re.sub(r'^\(([^()\r\n]{1,24})\)', r'[\1]', ocr_clean)
            # Common OCR miss: opening '[' is dropped while closing ']' is retained.
            # Example: "LASD]LIRIK90" -> "[LASD]LIRIK90"
            ocr_clean = re.sub(r'^(?!\[)([A-Za-z0-9]{2,8}\])', r'[\1', ocr_clean)
        # ocr_clean = '' if len(ocr_clean) < 3 else ocr_clean

        if add_space != 0:
            ocr_clean = re.sub(r'Nav.*', 'NavyIssue', ocr_clean)

        for strip_string in strip_strings:
            ocr_clean = ocr_clean.replace(strip_string, "")

        replacements = {
            'rielI': 'riel', 'IIInter': ' II Inter', 'IDps': 't Ops', 'ii': 'II', 'ITln': 'II In', 'iI': 'II',
            'lll': 'III',
            'Il': 'II', 'il': 'II', 'veN': 'ven N', 'Aorn': 'Bomb', 'Ae I': 'Bel', 'TI': 'II',
            'Badger III': 'Badger II',
            'ill': 'III', 'elI': 'e II', 'Wenturg': 'Venture', 'DorninixlI': 'Dominix II', 'Dorninixll': 'Dominix II',
            'alq': 'alg', 'rrn': 'rm', 'Loq': 'Log', 'Oar': 'Dar', 'Dorn': 'Dom',
            'Hry': 'Kry', 'oalI': 'oa II', 'IITCovertC': 'III Covert Ops',
            'lbi': 'Ibi', 'isllI': 'is II', ' Aad': 'Bad', 'hbII': 'bil', 'GIIa': 'Gila', 'Dps': 'Ops'

        }

        regex_replacements = {
            r'\bInterd.*': 'Interdictor',
            r'\bCya.*': 'CyanSea',
            r'\bCyn.*': 'Cynabal',
            r'\bFleet.*': 'FleetIssue',
            r'\bInterc.*': 'Interceptor',
            r'\bCharm.*': 'Chameleon',
            r'\bSun.*': 'Sunesis',
            r'\bPrax.*': 'Praxis',
            r'\bCorm.*': 'Cormorant',
            r'\bTra.*': 'Trainer',
            r'\bCover.*': 'CovertOps',
            r'\bAst.*': 'Astero',
            r'\bMamm.*': 'Mammoth',
            r'\bCarn.*': 'Command',
            r'\bAnn.*': 'Annihilator',
            r'J$': ''  # Add this to remove capital 'J' at the end of a string
        }

        last_sweep = {
            'Atrontl': 'Atron II', 'IIC': 'II C', 'lI': ' II'
        }

        if name != 1:
            for pattern, value in regex_replacements.items():
                ocr_clean = re.sub(pattern, value, ocr_clean)
            for key, value in replacements.items():
                ocr_clean = ocr_clean.replace(key, value)
            ocr_clean = re.sub(r'(?<!e)(?<!h)(?<!G)(?<!a)l$', 'I', ocr_clean)
            for key2, value in last_sweep.items():
                ocr_clean = ocr_clean.replace(key2, value)

        # if add_space != 0:
        #     ocr_clean = re.sub(r'(?<=[^A-Z\s])(?=[A-Z])', ' ', ocr_clean)

        # print(f'[DEBUG] Cleaned OCR result: {ocr_clean}')
        return ocr_clean

    # Crops a screen section and return OCR result
    async def ocr_section(self, ocr_section_img, ocr_left=None, ocr_top=None, ocr_right=None, ocr_bottom=None,
                          preproc=0, psm=8, threshold=75,
                          whitelist=DEFAULT_OCR_WHITELIST,
                          gaussian_b=0.5, debug_num='', engine='echoes', crop_left=True):
        # Crop the image
        if ocr_left is not None and ocr_top is not None and ocr_right is not None and ocr_bottom is not None:
            crop_img = ocr_section_img.crop(
                (ocr_left, ocr_top, ocr_right, ocr_bottom))
        else:
            crop_img = ocr_section_img
        # crop_img.show()
        if preproc == 2:
            return str(count_pixels(crop_img, 100, 120, 100, 130, 95, 130) > 0)

        if preproc == 3:
            if count_pixels(crop_img, 95, 140, 100, 180, 95, 180) > 0:
                return '2'
            else:
                return 'web'

        if preproc == 1:
            if count_pixels(crop_img, 55, 65, 32, 45, 28, 40) > 0:
                threshold += 40

            if count_pixels(crop_img, 15, 70, 17, 45, 12, 45) == 0:
                return ''

            crop_img_np = np.array(crop_img)
            white_columns_np = 0 * np.ones((crop_img_np.shape[0], 1, 3), dtype=np.uint8)
            modified_image_np = np.concatenate((white_columns_np, crop_img_np, white_columns_np), axis=1)
            crop_img = Image.fromarray(modified_image_np)

            crop_img = ImageOps.grayscale(crop_img)
            crop_img = crop_img.resize((crop_img.width * 4, crop_img.height * 4), resample=Image.Resampling.LANCZOS)
            crop_img = crop_img.filter(ImageFilter.MedianFilter())
            crop_img = crop_img.filter(ImageFilter.GaussianBlur(float(gaussian_b)))
            crop_img = crop_img.point(lambda p: 0 if p > threshold else 255, 'L')

        base_cfg = build_tesseract_config(psm=psm, whitelist=None, preserve_spaces=True)
        whitelist_cfg = build_tesseract_config(psm=psm, whitelist=whitelist, preserve_spaces=True)

        if engine == 'echoes':
            # Probe once with multilingual model; use this as the final result when quality is already good.
            probe_result = await self._ocr_image_to_string(
                crop_img,
                lang=f'{engine}+chi_sim',
                config=base_cfg
            )
            if not isinstance(probe_result, str):
                probe_result = str(probe_result or '')
            has_cjk, has_cyrillic = _detect_cjk_or_cyrillic(probe_result)
            corp_from_probe = _extract_corp_tag(probe_result)

            if has_cjk or has_cyrillic:
                # Keep corp tags and prefer the multilingual probe text for mixed scripts.
                result_enemy_name = _strip_leading_corp_tag(probe_result).strip()

                # If probe has script markers but no usable body, take one targeted fallback pass.
                if not result_enemy_name:
                    lang_hint = 'chi_sim' if has_cjk else 'rus'
                    lang_result = await self._ocr_image_to_string(
                        crop_img,
                        lang=lang_hint,
                        config=base_cfg
                    )
                    if not isinstance(lang_result, str):
                        lang_result = str(lang_result or '')
                    result_enemy_name = _strip_leading_corp_tag(lang_result).strip()

                if not corp_from_probe and any(ch in probe_result for ch in ('[', ']', '\u3010', '\u3011', '(', ')')):
                    corp_fallback_result = await self._ocr_image_to_string(
                        crop_img,
                        lang=engine,
                        config=base_cfg
                    )
                    if not isinstance(corp_fallback_result, str):
                        corp_fallback_result = str(corp_fallback_result or '')
                    corp_from_probe = _extract_corp_tag(corp_fallback_result)

                ocr_result = _compose_corp_and_name(corp_from_probe, result_enemy_name or probe_result)

            else:
                should_try_script_rescue = (
                    whitelist == DEFAULT_OCR_WHITELIST
                    and bool(corp_from_probe)
                    and _looks_like_latin_ocr_noise_for_cjk(probe_result)
                )
                if should_try_script_rescue:
                    rescue_cfg = build_tesseract_config(psm=7, whitelist=None, preserve_spaces=True)
                    # Try Cyrillic first (fast win for names like "Некромант"), then CJK.
                    for rescue_lang, expected_script in (('rus', 'cyrillic'), ('chi_sim', 'cjk')):
                        rescue_result = await self._ocr_image_to_string(
                            crop_img,
                            lang=rescue_lang,
                            config=rescue_cfg
                        )
                        if not isinstance(rescue_result, str):
                            rescue_result = str(rescue_result or '')
                        rescue_has_cjk, rescue_has_cyrillic = _detect_cjk_or_cyrillic(rescue_result)
                        rescue_hit = rescue_has_cyrillic if expected_script == 'cyrillic' else rescue_has_cjk
                        if rescue_hit:
                            rescue_corp = _extract_corp_tag(rescue_result) or corp_from_probe
                            rescue_name = _strip_leading_corp_tag(rescue_result).strip()
                            if rescue_name:
                                ocr_result = _compose_corp_and_name(rescue_corp, rescue_name)
                                return ocr_result

                filtered_probe = _apply_char_whitelist(probe_result, whitelist)
                probe_compact = ''.join(ch for ch in probe_result if not ch.isspace())
                filtered_compact = ''.join(ch for ch in filtered_probe if not ch.isspace())
                retained_ratio = (len(filtered_compact) / len(probe_compact)) if probe_compact else 1.0
                has_non_ascii = any(ord(ch) > 127 for ch in probe_result if not ch.isspace())

                # Fast path: if probe output is mostly whitelist-compatible, skip a second OCR pass.
                if filtered_probe.strip() and retained_ratio >= 0.75:
                    ocr_result = filtered_probe
                # Preserve mixed-script names instead of stripping non-Latin chars via whitelist fallback.
                elif (
                    whitelist == DEFAULT_OCR_WHITELIST
                    and probe_result.strip()
                    and retained_ratio < 0.75
                    and has_non_ascii
                ):
                    ocr_result = probe_result
                else:
                    ocr_result = await self._ocr_image_to_string(
                        crop_img,
                        lang=engine,
                        config=whitelist_cfg,
                    )

        elif engine == 'shiptype':
            ocr_result = await self._ocr_image_to_string(
                crop_img,
                lang='echoes',
                config=whitelist_cfg
            )

        else:
            # Perform OCR if the engine is not 'echoes'
            ocr_result = await self._ocr_image_to_string(
                crop_img,
                lang=engine,
                config=whitelist_cfg
            )

        # Ensure the OCR result is a string
        if not isinstance(ocr_result, str):
            logging.error(f"OCR result is not a string: {ocr_result}")
            return ''
        return ocr_result

    def ocr_nav_ui(self, nav_img, ui_position):
        ocr_position = f'system_anomaly_{ui_position}'
        y_top_step = 50 + ((ui_position - 1) * 52)
        y_bottom_step = 70 + ((ui_position - 1) * 52)
        ocr_position = str(
            self.ocr_section(nav_img, 804, y_top_step, 910, y_bottom_step,
                             0,
                             8, 100,
                             '123456789W0XAngelLargeFtRyMdiumScou'))
        ocr_clean = self.ocr_cleanup(ocr_position, 'angel', 'Angel', '1gel', 'Ange',
                                     'ange')
        return ocr_clean

    class LoadContactsButton(discord.ui.Button):
        def __init__(self):
            super().__init__(
                style=discord.ButtonStyle.success,
                label="Refresh Contacts",
                custom_id="load_contacts_button"
            )

        async def callback(self, interaction: discord.Interaction):
            global contact_peep_switch  # Make sure contact_peep_switch is accessible here

            logging.info(
                f"LoadContactsButton.callback: Button clicked by user: {interaction.user.name}, contact_peep_switch: {contact_peep_switch}")  # Logging button click

            # If this instance is not designated to process contact peeping:
            if contact_peep_switch != '1':
                logging.info(
                    "LoadContactsButton.callback: contact_peep_switch is not '1', sending ephemeral message and returning.")  # Logging switch check failure
                # Send a zero-width ephemeral message so Discord sees a valid response
                await interaction.response.send_message("\u200B", ephemeral=True)
                return

            logging.info(
                "LoadContactsButton.callback: contact_peep_switch is '1', proceeding with contact_peep.")  # Logging switch check success
            # This instance is the designated one.
            await interaction.response.defer()  # Acknowledge the interaction

            client = interaction.client
            if not isinstance(client, MyClient):
                logging.error(
                    "LoadContactsButton.callback: Error: Could not access bot functions.")  # Logging client type error
                await interaction.followup.send("Error: Could not access bot functions.", ephemeral=True)
                return

            await interaction.followup.send("Loading contacts...", ephemeral=True)
            contact_peep_delay_new = await client.contact_peep()  # <--- Call contact_peep
            if contact_peep_delay_new:
                client.contact_peep_delay = contact_peep_delay_new
                await interaction.followup.send("...contacts refreshed successfully", ephemeral=True)
                logging.info("LoadContactsButton.callback: Contacts refreshed successfully.")  # Logging success
            else:
                await interaction.followup.send("Failed to initiate contact load.", ephemeral=True)
                logging.warning("LoadContactsButton.callback: Failed to initiate contact load.")  # Logging failure

    async def _read_contacts_once(self) -> Tuple[int, int, int, int, int, Image.Image, Image.Image]:
        """
        1) Opens the Contacts UI (click/wait, up to N retries).
        2) Takes a final overlay screenshot.
        3) OCRs the five counters (Armor, BLOPs, etc.).
        4) Returns (c1, c2, c3, c4, c5, contact_img, full_screenshot).
        """
        logging.info("_read_contacts_once: Starting to read contacts.")  # Logging start of function

        # ================= OPEN THE MAIN MENU =================
        menu_ok, _ = await self.ui_navigator.ensure_state(
            "contacts_main_menu_open",
            self.ui_detector.is_main_menu_open,
            lambda: click(40, 20, 0, 10, 10),
            max_attempts=5,
            delay_min=1500,
            delay_max=2000
        )
        if not menu_ok:
            error_msg = "Failed to open the main menu after multiple retries."
            logging.error(f"_read_contacts_once: {error_msg}")
            raise RuntimeError(error_msg)

        # ================= SELECT "CONTACTS" =================
        contacts_ok, _ = await self.ui_navigator.ensure_state(
            "contacts_panel_open",
            self.ui_detector.is_contacts_menu_open,
            lambda: click(318, 471, 0, 10, 10),
            max_attempts=5,
            delay_min=2300,
            delay_max=2600
        )
        if not contacts_ok:
            error_msg = "Failed to open 'Contacts' after multiple retries."
            logging.error(f"_read_contacts_once: {error_msg}")
            raise RuntimeError(error_msg)

        # ================= FINAL OVERLAY SCREENSHOT =================
        logging.info(
            "_read_contacts_once: Taking final overlay screenshot for contact data.")  # Logging final screenshot
        async with self.pull_win_lock:
            overlay_img, _ = await self.pull_win_overlays(self.scout)
            full_screenshot = overlay_img
        logging.info("_read_contacts_once: Final overlay screenshot taken.")  # Logging final screenshot complete

        runtime_top_inset = _get_runtime_top_inset(window_title=self.scout)
        contact_img = overlay_img.crop((10, 55 + runtime_top_inset, 200, 445 + runtime_top_inset))

        # ================= OCR THE FIVE COUNTERS =================
        logging.info("_read_contacts_once: Starting OCR of contact counters.")  # Logging OCR start
        c1_task = asyncio.create_task(
            self.ocr_section(contact_img, 120, 10, 142, 28, whitelist='0123456789', crop_left=False, engine='shiptype')
        )
        c2_task = asyncio.create_task(
            self.ocr_section(contact_img, 120, 89, 141, 105, whitelist='0123456789', crop_left=False, engine='shiptype')
        )
        c3_task = asyncio.create_task(
            self.ocr_section(contact_img, 120, 167, 142, 183, whitelist='0123456789', crop_left=False, engine='shiptype')
        )
        c4_task = asyncio.create_task(
            self.ocr_section(contact_img, 120, 245, 142, 261, whitelist='0123456789', crop_left=False, engine='shiptype')
        )
        c5_task = asyncio.create_task(
            self.ocr_section(contact_img, 128, 323, 150, 338, whitelist='0123456789', crop_left=False, engine='shiptype')
        )
        c1_str, c2_str, c3_str, c4_str, c5_str = await asyncio.gather(
            c1_task, c2_task, c3_task, c4_task, c5_task
        )
        logging.info("_read_contacts_once: OCR of contact counters complete.")  # Logging OCR complete

        def safe_int(val: str) -> int:
            val = val.strip() if val else ''
            return int(val) if val.isdigit() else 0

        c1 = safe_int(c1_str)
        c2 = safe_int(c2_str)
        c3 = safe_int(c3_str)
        c4 = safe_int(c4_str)
        c5 = safe_int(c5_str)

        logging.info(
            f"_read_contacts_once: Returning contact counts and images. Counts: c1={c1}, c2={c2}, c3={c3}, c4={c4}, c5={c5}")  # Logging return values
        return c1, c2, c3, c4, c5, contact_img, full_screenshot

    async def contact_peep(self) -> Optional[float]:
        global client_busy
        client_busy = True
        logging.info("contact_peep: Opening contacts for AOA check...")  # Log entry into contact_peep

        try:
            # 1) Attempt reading contacts once
            logging.info("contact_peep: Calling _read_contacts_once().")  # Log call to _read_contacts_once
            c1, c2, c3, c4, c5, contact_img, full_screenshot = await self._read_contacts_once()
            logging.info(
                "contact_peep: _read_contacts_once() returned successfully.")  # Log success of _read_contacts_once

            # 2) Threat checks
            self.aoa_cnt = c1 + c2 + c3 + c4 + c5
            logging.info(f"contact_peep: AOA Count: {self.aoa_cnt}")  # Log AOA count

            # Example: If these variables are defined in your config
            # or as class attributes:
            # contact_upper_bound = 35
            # contact_lower_bound = 28

            if self.aoa_cnt >= contact_upper_bound and not self.aoa_threat_active:
                self.aoa_threat_active = True
                await self.send_text_message_to_channel_id(
                    1194713481363075213,
                    "Warning! Significant <@&1350294951451426917> activity detected in <#1325664432759640159>."
                )
                logging.info("contact_peep: AOA Threat level increased, warning message sent.")  # Log threat warning

            if self.aoa_cnt < contact_lower_bound and self.aoa_threat_active:
                self.aoa_threat_active = False
                await self.send_text_message_to_channel_id(
                    1194713481363075213,
                    "Notice: <@&1350294951451426917> <#1325664432759640159> level has lowered."
                )
                logging.info(
                    "contact_peep: AOA Threat level lowered, notice message sent.")  # Log threat lowered notice

            # 3) Prepare embed
            channel_id = 1325664432759640159
            target_message_id = 1325697265867948125
            channel = self.get_channel(channel_id)
            if not channel:
                error_msg = f"Channel with ID {channel_id} not found. Skipping embed update."
                logging.warning(f"contact_peep: {error_msg}")  # Log channel not found warning
                print(error_msg)
                return None

            current_time = int(time.time())
            embed = discord.Embed(title="AOA Fleet Intel", color=discord.Color.blue())
            embed.add_field(name="", value=f"Last Updated: <t:{current_time}:R>", inline=True)

            # Use the same logic you had for the fields
            embed.add_field(name="", value=f"Armor: {c1}", inline=False)
            embed.add_field(name="", value=f"BLOPs: {c2}", inline=False)
            embed.add_field(name="", value=f"Marizio/Marshal: {c3}", inline=False)
            embed.add_field(name="", value=f"Nestors: {c4}", inline=False)
            embed.add_field(name="", value=f"Supers: {c5}", inline=False)
            embed.add_field(name="", value=f"Total: {self.aoa_cnt}", inline=False)

            # Attach the 'contact_img'
            image_bytes = io.BytesIO()
            contact_img.save(image_bytes, format="PNG")
            image_bytes.seek(0)
            file = discord.File(image_bytes, filename="contact_image.png")
            embed.set_image(url="attachment://contact_image.png")
            embed.set_footer(text="")

            # Fetch pinned message and edit
            try:
                message_obj = await channel.fetch_message(target_message_id)
            except discord.NotFound:
                error_msg = f"Message with ID {target_message_id} not found in channel {channel_id}."
                logging.warning(f"contact_peep: {error_msg}")  # Log message not found warning
                print(error_msg)
                return None

            await message_obj.edit(embed=embed, attachments=[], files=[file])
            logging.info(
                f"contact_peep: Embed updated successfully in message {message_obj.id}.")  # Log embed update success
            print(f"Embed updated successfully in message {message_obj.id}.")

            # 4) Close the menu if still open
            logging.info("contact_peep: Closing contacts menu if open...")  # Log menu closing start
            closed = await self.ui_navigator.close_inventory_overlay(full_screenshot)
            if not closed:
                logging.warning("contact_peep: Contacts/menu overlay may still be open after retries.")
            logging.info("contact_peep: Contacts menu closed (if it was open).")  # Log menu closing complete

            # 5) Return next peep delay
            new_contact_peep_delay = time.time() + random.randint(1080, 2700)
            logging.info(
                f"contact_peep: Completed successfully. Next contact_peep delay: {new_contact_peep_delay}")  # Log function completion and next delay
            return new_contact_peep_delay

        except RuntimeError as e:
            # Means _read_contacts_once() couldn't open the menu or contacts
            logging.error(
                f"contact_peep: Failed to open or read Contacts: {e}. Skipping.")  # Log RuntimeError in contact_peep
            print(f"Failed to open or read Contacts: {e}. Skipping.")
            return None

        except Exception as e:
            logging.exception(
                f"contact_peep: Failed with unexpected error: {e}")  # Log unexpected exception with traceback
            print(f"Failed here: {e}")
            return None

        finally:
            client_busy = False
            logging.info("contact_peep: Completed (finally block). Busy status cleared.")  # Log finally block execution
            print("contact_peep completed. Busy cleared.")

    async def process_image(self, proc_img, i, ui_custom):
        try:
            logging.info(
                f"Processing image index {i} with UI custom value {ui_custom}")

            if ui_custom == 0:
                ocr_result = self.ocr_nav_ui(proc_img, i + 1)
                logging.info(f"OCR result for nav UI: {ocr_result}")
                await self.result_queue.put((i, ocr_result, None, None))

            elif ui_custom == 1:
                ocr_result, ocr_result2, ping_list = await self.ocr_enemy_ui(proc_img, i + 1)
                logging.info(f'ocr_result: {ocr_result}')
                logging.info(f'ocr_result2: {ocr_result2}')
                logging.info(f'ping_list: {ping_list}')

                if ocr_result == '' or ocr_result2 == '':
                    logging.info(f'Failed OCR, attempting eng engine..')
                    if ocr_result == '' or ocr_result2 == '':
                        ocr_result, ocr_result2, ping_list = await self.ocr_enemy_ui(proc_img, i + 1, 'eng')
                        logging.info(f'Failed again.')
                    logging.info(f'ocr_result: {ocr_result}')
                    logging.info(f'ocr_result2: {ocr_result2}')

                cleaned_ship_type, ship_category = clean_and_categorize_ship_type(
                    ocr_result2, self.ship_categories)
                logging.info(
                    f'Cleaned Ship Type: {cleaned_ship_type}, Ship Category: {ship_category}')

                await self.result_queue.put(
                    (i, ocr_result, cleaned_ship_type, ping_list, ship_category))

                # Fire and forget - Send image asynchronously
                # asyncio.create_task(self.send_image(self.channel, proc_img, scout, channel_id))

            '''
            elif ui_custom == 2:
                ocr_result = await self.ocr_enemy_distance(proc_img, i + 1)
                logging.info(f"OCR result for enemy distance: {ocr_result}")
                await self.result_queue.put((i, ocr_result, None, None))

            elif ui_custom == 3:
                ocr_result = await self.ocr_enemy_distance_alternative(proc_img, i + 1)
                logging.info(
                    f"OCR result for enemy distance alternative: {ocr_result}")
                await self.result_queue.put((i, ocr_result, None, None))
            '''

            logging.info(f"Finished processing image index {i}")

        except Exception as e:
            logging.error(f'Error processing image at index {i}: {e}')

    async def process_task(self, task):
        func, args = task
        try:
            logging.info(f"Processing task: {task}")
            if asyncio.iscoroutinefunction(func):
                await func(*args)
            else:
                func(*args)
        except Exception as e:
            logging.error(f"Error processing task: {e}")

    async def worker(self, queue):
        while True:
            task = await queue.get()
            if task is None:  # None is a signal to exit the worker
                break
            await self.process_task(task)
            queue.task_done()
            await asyncio.sleep(0.01)

    async def logoff(self):
        try:
            im = await self.ui_navigator.run_logoff_flow()

            if self.channel is not None:
                await self.channel.send("<@751440571201093761> Pilot on standby, awaiting fuel drop. o7")
                # Briefly wait for any lingering overlay state to settle.
                for _ in range(6):
                    if not self.ui_detector.is_top_right_close_visible(im):
                        break
                    await delay(500, 700)
                    im = await self.ui_navigator.capture_frame()

                # Initialize img_byte_arr_im as None
                img_byte_arr_im = None

                try:
                    img_byte_arr_im = save_image_in_memory(im)
                    img_byte_arr_im.seek(0)  # Ensure the BytesIO object is at the start
                except Exception as e:
                    logging.error(f'An error occurred while saving image to memory: {e}')

                if img_byte_arr_im:  # Ensure img_byte_arr_im is not None before sending
                    try:
                        await check_channel_name(self.message, target_channel_name, None, img_byte_arr_im)
                    except Exception as e:
                        logging.error(f'An error occurred while sending image to Discord: {e}')
            await self.close()
        except Exception as e:
            logging.error(f'An error occurred during the logoff process: {e}')

    async def refuel(self):
        global client_busy

        # Attempt to acquire the system-wide mutex immediately (non-blocking).
        mutex_handle = try_acquire_refuel_mutex_nonblocking()
        if not mutex_handle:
            logging.info("Refuel skipped; another process is busy refueling.")
            return

        try:
            client_busy = True
            logging.info("Refuel lock acquired. Executing UI state-machine flow.")
            refuel_delay_new = await self.ui_navigator.run_refuel_flow()
            return refuel_delay_new

        except FuelDepletedError as depleted_error:
            logging.warning("Refuel failed due to missing fuel: %s", depleted_error)
            try:
                closed = await self.ui_navigator.close_refuel_inventory()
                if not closed:
                    logging.warning("[ui] Inventory close did not fully converge after fuel depletion.")
            except Exception as close_error:
                logging.warning("Failed to close inventory after missing fuel: %s", close_error)
            if refuel_logoff == '1':
                if self.channel is not None:
                    await self.channel.send("Fuel depleted, Shutdown Initiated...")
                await self.logoff()
            return time.time() + 60

        except Exception as e:
            print(f'Failed to refuel: {e}')
            refuel_delay_new = time.time() + 60
            return refuel_delay_new

        finally:
            # Release the mutex so other processes can refuel
            release_refuel_mutex(mutex_handle)
            client_busy = False
            logging.info("Refuel done; lock released. Continuing normal duties.")

    # Background enemy detection method
    async def background_enemy_detection(self):
        while True:
            try:
                # Wait if scanning is not active
                while not scanning_active:
                    await asyncio.sleep(1)  # Sleep while paused to avoid busy-waiting

                # Check if pause is requested
                if pause_requested or (self.resume_time and datetime.now() < self.resume_time):
                    await asyncio.sleep(1)  # Sleep while paused to avoid busy-waiting
                    continue  # Skip the rest of the loop until pause is over

                logging.debug("Starting enemy detection loop.")

                # Capture the screen and check for new enemies
                async with self.pull_win_lock:
                    logging.debug("Acquired pull_win_lock.")
                    im, result = await self.async_pull_win()
                    logging.debug("Captured screen and received result.")

                # Check for new enemies
                new_enemy_detected, screenshots = await self.check_enemy_presence(im)
                logging.debug(
                    f"New enemy detected: {repr(new_enemy_detected)}, screenshots available: {len(screenshots)}"
                )

                # Log queue size for debugging purposes
                logging.debug(f"Enemy queue size before sending: {self.enemy_queue.qsize()}")

                # If new enemies are detected, add them to the enemy queue for processing.
                # Use an in-flight guard so detection jitter can't enqueue duplicates while an OCR/report task is active.
                if new_enemy_detected:
                    now = time.time()
                    self._prune_inflight_enemies(now)

                    # check_enemy_presence() only returns screenshots for *new* contacts, so we can enqueue directly.
                    for ui_pos, (enemy_signature, name_img, shiptype_img, range_img, range_pxl_cnt) in screenshots.items():
                        inflight_match = self._find_inflight_match(enemy_signature)
                        if inflight_match is not None:
                            # Touch the existing entry so it doesn't expire mid-processing.
                            self.inflight_enemies[inflight_match] = now
                            logging.debug(f"Enemy {enemy_signature} matched in-flight {inflight_match}; skipping enqueue.")
                            continue

                        self.inflight_enemies[enemy_signature] = now
                        await self.enemy_queue.put(
                            (ui_pos, enemy_signature, name_img, shiptype_img, range_img, range_pxl_cnt)
                        )

                await asyncio.sleep(self.detection_interval)
                logging.debug("Sleeping for %s seconds.", self.detection_interval)

            except Exception as e:
                logging.error(f"Error in background enemy detection: {e}", exc_info=True)

    async def send_image_with_retry(self, img_byte_arr_data, retries=3, delay=2):
        if self.channel is None:
            logging.error("Channel is None. Cannot send the image.")
            return False

        img_data = img_byte_arr_data.getvalue() if isinstance(img_byte_arr_data, BytesIO) else img_byte_arr_data
        logging.debug(f"Image size: {len(img_data)} bytes")

        for attempt in range(1, retries + 1):
            try:
                logging.debug(
                    f"Attempt {attempt} to send image to channel {self.channel.name} (ID: {self.channel.id}).")

                # Set up the data to send
                data = aiohttp.FormData()
                data.add_field('file', img_data, filename="stitched_report.png", content_type='image/png')

                async with aiohttp.ClientSession() as session:
                    headers = {'Authorization': f'Bot {discord_bot_token}'}
                    async with session.post(f'https://discord.com/api/v9/channels/{self.channel.id}/messages',
                                            headers=headers, data=data) as response:
                        if response.status == 200:
                            logging.info(f"Image successfully sent to channel: {self.channel.name}")
                            return True
                        elif response.status == 400:
                            logging.error(f"Bad Request: Invalid form body.")
                            break  # Stop retrying if the request is invalid
                        elif response.status == 429:  # Rate limit hit
                            retry_after = float(response.headers.get("Retry-After", "2"))
                            logging.warning(f"Rate limit hit. Retrying after {retry_after} seconds.")
                            await asyncio.sleep(retry_after)  # Wait and retry
                        else:
                            logging.error(f"Unexpected error during image send. Status code: {response.status}")
                            response_text = await response.text()
                            logging.debug(f"Response text: {response_text}")

            except aiohttp.ClientError as e:
                logging.error(f"Client error on attempt {attempt}: {e}")

            if attempt < retries:
                logging.info(f"Retrying in {delay} seconds (Attempt {attempt}/{retries})...")
                await asyncio.sleep(delay)
            else:
                logging.critical(f"Failed to send image after {retries} attempts.")
                return False  # All attempts failed

    async def stitch_and_send_images(self, batch):
        logging.debug("Entering stitch_and_send_images()")

        # Check if image reporting is enabled
        if img_grid_report != '1':
            logging.debug("Image grid report is not enabled, exiting stitch_and_send_images.")
            return  # Exit if image reporting is not enabled

        if not batch:
            return

        # Calculate total width and height for the final stitched image
        try:
            widths, heights = zip(*(
                (batch[key]['name_img'].size[0],
                 batch[key]['name_img'].size[1] + batch[key]['shiptype_img'].size[1])
                for key in batch
            ))
            total_width = max(widths)
            total_height = sum(heights)
        except Exception as e:
            return

        # Create a new blank image with the calculated dimensions
        try:
            stitched_image = Image.new('RGB', (total_width, total_height))
        except Exception as e:
            logging.error(f"Error creating blank image: {e}", exc_info=True)
            return

        # Stitch images together by pasting them one after another
        y_offset = 0
        try:
            for key in batch:
                name_img = batch[key]['name_img']
                shiptype_img = batch[key]['shiptype_img']
                stitched_image.paste(name_img, (0, y_offset))
                y_offset += name_img.size[1]
                stitched_image.paste(shiptype_img, (0, y_offset))
                y_offset += shiptype_img.size[1]
            logging.debug("Images stitched successfully.")
        except Exception as e:
            logging.error(f"Error stitching images together: {e}", exc_info=True)
            return

        try:
            stitched_hash = str(imagehash.phash(stitched_image))
            if self._is_recent_stitched_report_duplicate(stitched_hash):
                logging.info(
                    "Skipping stitched image send: near-duplicate report within %ss.",
                    self.stitched_report_cooldown_seconds
                )
                return
        except Exception as e:
            logging.debug(f"Stitched image dedupe hash check failed; continuing send. Error: {e}")

        # Save the stitched image to a BytesIO object (in-memory file-like object)
        try:
            img_byte_arr = BytesIO()
            stitched_image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)  # Rewind the buffer to the beginning
            logging.debug(f"Stitched image saved to memory.")
        except Exception as e:
            logging.error(f"Error saving stitched image to memory: {e}", exc_info=True)
            return

        # Send the stitched image to the specified Discord channel
        try:
            if self.channel:
                logging.debug(f"Channel found: {self.channel}")

                # Queue the task asynchronously so it doesn’t block the bot
                asyncio.create_task(self.send_image_with_retry(img_byte_arr))

                # Log after successfully sending the image
                logging.info(f"Stitched images successfully sent to {self.channel.name}")
            else:
                logging.error(f"Channel {self.channel} not found. Cannot send image.")

        except asyncio.TimeoutError:
            logging.error("Timeout error: Discord API is taking too long.", exc_info=True)
        except discord.HTTPException as e:
            logging.error(f"HTTP exception while sending image to Discord: {e}", exc_info=True)
        except Exception as e:
            logging.error(f"Unexpected error while sending image to Discord: {e}", exc_info=True)

        logging.debug("Exiting stitch_and_send_images()")

    async def add_to_batch(self, name_img, shiptype_img, range_image, ocr_result, ocr_ship_type):
        BATCH_LIMIT = 50
        try:
            name_hash = str(imagehash.phash(name_img))
            shiptype_hash = str(imagehash.phash(shiptype_img))

            enemy_key = f"{name_hash}_{shiptype_hash}"

            logging.debug(f"Attempting to acquire batch_lock{print_line_number()}")
            async with self.batch_lock:
                # logging.debug("Acquired batch_lock")
                logging.debug(f"Batch size before adding: {len(self.image_batch)}")
                logging.debug(f"Attempting to add {ocr_result} with hash {enemy_key} to batch.")

                # Ensure that the image is not skipped due to duplicate detection
                if enemy_key in self.recent_enemies:
                    if time.time() - self.recent_enemies[enemy_key] < 20:
                        logging.debug(f'Image {enemy_key} is within cooldown period, skipping.')
                        return

                self.recent_enemies[enemy_key] = time.time()

                if enemy_key not in self.image_batch:
                    self.image_batch[enemy_key] = {
                        'name_img': name_img,
                        'shiptype_img': shiptype_img,
                        'ocr_result': ocr_result,
                        'ocr_ship_type': ocr_ship_type
                    }

                logging.debug(f"Batch size after adding: {len(self.image_batch)}")

                if len(self.image_batch) >= BATCH_LIMIT:
                    logging.debug(f"Batch size reached limit ({BATCH_LIMIT}), sending now.")
                    await self.delayed_batch_send()
            logging.debug(f"Released batch_lock: {print_line_number()}")

            if self.batch_send_task is None or self.batch_send_task.done():
                logging.debug(f"Starting delayed batch send.")
                self.batch_send_task = asyncio.create_task(self.delayed_batch_send())

        except Exception as e:
            logging.error(f"Error in add_to_batch: {e}")

    async def delayed_batch_send(self, retries=3, delay=5, min_batch_size=1):
        attempt = 0
        while attempt < retries:
            try:
                logging.debug(
                    f"Starting delayed batch send (Attempt {attempt + 1}/{retries}). Batch size: {len(self.image_batch)}")

                # Only attempt to send if batch meets the minimum size
                if len(self.image_batch) < min_batch_size:
                    logging.debug(
                        f"Batch size {len(self.image_batch)} is smaller than the minimum required {min_batch_size}. Waiting for more images...")
                    await asyncio.sleep(delay)
                    continue  # Retry only if there are not enough images, without incrementing attempt counter

                await asyncio.sleep(min(1.5, len(self.image_batch) * 0.2))  # Adaptive delay based on batch size

                logging.debug("Attempting to acquire batch_lock")
                async with self.batch_lock:
                    logging.debug(f"Acquired batch_lock, Batch size: {len(self.image_batch)}")

                    # Check if both the channel and batch are valid
                    if not self.channel:
                        logging.warning("No channel defined. Exiting batch send.")
                        return  # Exit if no channel is set

                    if not self.image_batch:
                        logging.warning("No images to send. Exiting batch send.")
                        return  # Exit if the batch is empty after acquiring the lock

                    # Generate a unique batch ID and store the current batch
                    unique_batch_id = str(uuid.uuid4())
                    temp_image_batch = self.image_batch.copy()
                    self.batches[unique_batch_id] = temp_image_batch  # Store the batch by unique ID
                    self.image_batch.clear()

                logging.debug(f"Queued batch {unique_batch_id} for processing.")

                # Create a task to process this batch asynchronously and pass the batch
                asyncio.create_task(self.process_batch(unique_batch_id, temp_image_batch))  # Pass temp_image_batch here

                logging.debug("Released batch_lock after processing.")
                return  # Exit after successfully queuing the batch

            except Exception as e:
                logging.error(f"Error during batch send (Attempt {attempt + 1}/{retries}): {e}")
                # Retry only if an actual exception occurred
                attempt += 1
                if attempt < retries:
                    logging.info(f"Retrying batch send in {delay} seconds... (Attempt {attempt + 1}/{retries})")
                    await asyncio.sleep(delay)

            finally:
                # Ensure batch_send_in_progress is reset to False after the send attempt (whether success or failure)
                self.batch_send_in_progress = False

        if attempt == retries and self.image_batch:
            logging.critical(f"Failed to send batch after {retries} retries. Batch size: {len(self.image_batch)}")

    async def send_text_message_to_channel_id(self, target_channel_id_int, message_content):
        send_channel = self.get_channel(target_channel_id_int)
        if send_channel:
            try:
                await send_channel.send(message_content)
                print(f"Sent message to channel ID {target_channel_id_int}: '{message_content}'")
            except discord.Forbidden:
                logging.error(f"No permission to send message to channel ID {target_channel_id_int}.")
            except discord.HTTPException as e:
                logging.error(f"Error sending message to channel ID {target_channel_id_int}: {e}")
        else:
            logging.error(f"Channel with ID {target_channel_id_int} not found.")

    async def send_message_with_retry(self, message, retries=3, delay=2):
        global discord_bot_token
        if self.channel is None:
            logging.error("Channel is None. Cannot send the message.")
            return False

        for attempt in range(1, retries + 1):
            try:
                logging.debug(f"Attempt {attempt} to send message: {message}")

                async with aiohttp.ClientSession() as session:
                    headers = {
                        'Authorization': f'Bot {discord_bot_token}',
                        'Content-Type': 'application/json'
                    }
                    data = {'content': message}

                    async with session.post(f'https://discord.com/api/v9/channels/{self.channel.id}/messages',
                                            json=data, headers=headers) as response:
                        if response.status == 200:
                            logging.info(f"Message successfully sent to channel: {self.channel} - {message}")
                            return True

                        elif response.status == 429:  # Rate limit encountered
                            retry_after = float(str(response.headers.get("Retry-After", "0")))
                            global_limit = response.headers.get("X-RateLimit-Global", "False")
                            global_limit = global_limit.lower() == "true"  # Convert to boolean

                            if global_limit:
                                logging.error(f"Global rate limit hit, retrying after {retry_after} seconds.")
                            else:
                                logging.error(f"Per-route rate limit hit, retrying after {retry_after} seconds.")

                            await asyncio.sleep(retry_after)  # Wait for the specified time before retrying

                        else:
                            logging.error(f"Unexpected error while sending message: {response.status}")

            except aiohttp.ClientError as e:
                logging.error(f"Client error while sending message on attempt {attempt}: {str(e)}")

            if attempt < retries:
                logging.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
            else:
                logging.critical(f"Failed to send message after {retries} attempts.")
                return False  # All attempts failed

    async def process_batch(self, batch_id, batch):
        logging.debug(f"Processing batch {batch_id} with {len(batch)} entries.")
        temp_image_batch = self.batches.pop(batch_id, None)  # Retrieve and remove the batch

        if temp_image_batch:
            logging.debug(f"Batch {batch_id} retrieved successfully, processing...")
            await self.stitch_and_send_images(temp_image_batch)  # Pass batch here
        else:
            logging.warning(f"Batch {batch_id} not found or empty.")

    async def process_enemy_queue(self):
        watchlist_dict = {}
        roles_to_trigger_screenshot = ['1267872006767120384', '1267911151425949749', '1267911341075857523']
        active_enemy_tasks = set()

        def watchlist(enemy_name, threshold=85, time_limit=20):
            current_time = datetime.now()

            # Remove outdated entries
            outdated_keys = [name_key for name_key, value in watchlist_dict.items() if
                             (current_time - value['timestamp']).seconds > time_limit]
            for name_key in outdated_keys:
                logging.debug(f"Removing outdated watchlist entry: {name_key}")
                del watchlist_dict[name_key]

            # Check for matches in the watchlist using fuzzy matching
            for name_key in watchlist_dict.keys():
                match_score = fuzz.partial_ratio(enemy_name, name_key)
                logging.debug(f"Matching {enemy_name} against {name_key} with score {match_score}")
                if match_score > threshold:
                    logging.debug(f"Enemy {enemy_name} skipped due to watchlist match with {name_key}")
                    return False  # Enemy already exists in the watchlist

            # Add new entry to the watchlist with timestamp
            logging.debug(f"Current watchlist before adding {enemy_name}: {watchlist_dict}")
            watchlist_dict[enemy_name] = {'timestamp': current_time}
            logging.debug(f"Enemy {enemy_name} added to watchlist.")
            return True  # Enemy is new or outside the time limit

        # Modify process_enemy to put items in the batch_queue instead of processing directly
        async def process_enemy(ui_pos, enemy_signature, name_img, shiptype_img, range_img, range_pxl_cnt):
            logging.debug(f"Processing enemy from queue at UI position {ui_pos}.")
            now = time.time()
            self._prune_inflight_enemies(now)
            # Refresh the in-flight timestamp (and ensure it's present) while this task is alive.
            self.inflight_enemies[enemy_signature] = now

            try:
                # Perform OCR before adding to the batch for stitching
                ocr_result, ocr_ship_type, ping_list = await self.ocr_enemy_ui(name_img, shiptype_img)

                if self.is_excluded(ocr_result, self.exclusions):
                    logging.info(f"Enemy {ocr_result} is on the exclusion list, skipping report.")
                    return  # Skip this enemy entirely

                if not ocr_result or not ocr_ship_type:
                    logging.warning(f"OCR failed for UI position {ui_pos}. Skipping batch addition.")
                    return

                logging.info(f"OCR result: {ocr_result}, Ship type: {ocr_ship_type}, Range Value: {range_pxl_cnt}")
                # save_img(range_img, f'Range_{range_pxl_cnt}')

                # Now perform text reporting and message generation
                if watchlist(ocr_result):
                    # Queue image batch only for newly reported contacts.
                    await self.batch_queue.put((name_img, shiptype_img, range_img, ocr_result, ocr_ship_type))
                    logging.debug(f"Queued enemy batch for UI position {ui_pos}.")

                    cleaned_ship_type, ship_category = clean_and_categorize_ship_type(ocr_ship_type, self.ship_categories)
                    role_pings = categorize_ship(cleaned_ship_type, ship_category)
                    current_time = datetime.now()
                    unix_timestamp = int(current_time.timestamp())
                    warning_msg = ""

                    # Ensure cleaned_ship_type is reported even if it is 'Unknown'
                    if cleaned_ship_type and isinstance(cleaned_ship_type,
                                                        str) and cleaned_ship_type.strip() and range_finding != '1':

                        logging.info(f'Ship type detected: {cleaned_ship_type}, role pings: {role_pings}')
                        if role_pings:
                            warning_msg += f'<t:{unix_timestamp}:t>: {ocr_result}: {cleaned_ship_type} {" ".join([f"<@&{role_id}>" for role_id in role_pings])} <@&{role_ids["All"]}>\n'
                            # print(f'warning_msg: {warning_msg}')
                        else:
                            # Report unknown ship type without role pings
                            warning_msg += f'<t:{unix_timestamp}:t>: {ocr_result}: {cleaned_ship_type} <@&{role_ids["All"]}>\n'

                    if cleaned_ship_type and isinstance(cleaned_ship_type,
                                                        str) and cleaned_ship_type.strip() and range_finding == '1':

                        print(f'range: {range_pxl_cnt}')
                        if reverse_gate_polarity == '1':
                            direction = 'Inbound' if range_pxl_cnt > 1 else 'Outbound'
                        else:
                            direction = 'Outbound' if range_pxl_cnt > 1 else 'Inbound'
                        logging.info(
                            f'Ship type detected: {cleaned_ship_type}, role pings: {role_pings}, direction: {direction}')
                        if role_pings:
                            warning_msg += f'<t:{unix_timestamp}:t>: {ocr_result}: {cleaned_ship_type} - {direction} - {" ".join([f"<@&{role_id}>" for role_id in role_pings])} <@&{role_ids["All"]}>\n'
                        else:
                            # Report unknown ship type without role pings and with direction
                            warning_msg += f'<t:{unix_timestamp}:t>: {ocr_result}: {cleaned_ship_type} - {direction} - <@&{role_ids["All"]}>\n'

                    if warning_msg.strip():

                        # Send Textual Report
                        logging.debug(f"Text Report: {warning_msg}")
                        await self.send_message_with_retry(warning_msg)
                        if self.save_img_log == '1':
                            # Ensure the directories exist
                            os.makedirs(os.path.join(target_channel_name, "names"), exist_ok=True)
                            os.makedirs(os.path.join(target_channel_name, "shiptypes"), exist_ok=True)

                            ocr_result = os.path.basename(ocr_result)
                            ocr_ship_type = os.path.basename(ocr_ship_type)

                            # Save the images
                            save_img(name_img, os.path.join(target_channel_name, "names", ocr_result))
                            save_img(shiptype_img, os.path.join(target_channel_name, "shiptypes", ocr_ship_type))

                        if google_sheets_logging == '1':
                            try:
                                # After sending the report to Discord, update Google Sheets
                                row_data = [
                                    datetime.now().strftime("%m/%d/%Y, %H:%M:%S"),
                                    str(system).strip() if system else "N/A",
                                    str(ocr_result).strip() if ocr_result else "N/A",
                                    str(cleaned_ship_type).strip() if cleaned_ship_type else "N/A",
                                    str(ship_category).strip() if ship_category else "Unknown"
                                ]
                                await self.add_to_buffer(worksheet, row_data)
                            except Exception as e:
                                logging.error(f"Error updating Google Sheets log: {e}")

                        # If certain roles are present, send a screenshot
                        if any(role in role_pings for role in
                               ['1267872006767120384', '1267911151425949749', '1267911341075857523']):
                            async with self.pull_win_lock:
                                im, result = await self.async_pull_win()
                            send_task = asyncio.create_task(self.send_image(im))
                else:
                    logging.debug(f"Enemy {ocr_result} skipped by watchlist; not queuing image batch.")
            finally:
                # Task-based release: allow this signature to be enqueued again once processing completes.
                self.inflight_enemies.pop(enemy_signature, None)

        async def run_enemy_item(ui_pos, enemy_signature, name_img, shiptype_img, range_img, range_pxl_cnt):
            started = time.perf_counter()
            try:
                async with self.enemy_process_semaphore:
                    await process_enemy(ui_pos, enemy_signature, name_img, shiptype_img, range_img, range_pxl_cnt)
            except Exception as e:
                logging.error(f"Error in process_enemy task for UI position {ui_pos}: {e}", exc_info=True)
            finally:
                self.enemy_queue.task_done()
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                logging.debug(
                    "Finished enemy task ui_pos=%s elapsed_ms=%.1f queue_size=%s active_tasks=%s",
                    ui_pos, elapsed_ms, self.enemy_queue.qsize(), len(active_enemy_tasks)
                )

        while True:
            try:
                logging.debug(f"Enemy queue size: {self.enemy_queue.qsize()}")
                logging.debug("Waiting for enemy from queue...")

                # Preserve queue backpressure: do not dequeue new items while too many tasks are in-flight.
                while len(active_enemy_tasks) >= self.enemy_task_backlog_limit:
                    done, _ = await asyncio.wait(active_enemy_tasks, return_when=asyncio.FIRST_COMPLETED)
                    for finished in done:
                        try:
                            exc = finished.exception()
                        except asyncio.CancelledError:
                            exc = None
                        if exc:
                            logging.error("Enemy processing task ended with exception: %s", exc, exc_info=True)
                    active_enemy_tasks.difference_update(done)

                # Get the next enemy from the queue
                ui_pos, enemy_signature, name_img, shiptype_img, range_img, range_pxl_cnt = await self.enemy_queue.get()

                logging.debug(f"Dequeued enemy at UI position {ui_pos} for processing.")

                # Create a bounded worker task; queue.task_done() happens only after full processing.
                enemy_task = asyncio.create_task(
                    run_enemy_item(ui_pos, enemy_signature, name_img, shiptype_img, range_img, range_pxl_cnt)
                )
                active_enemy_tasks.add(enemy_task)
                enemy_task.add_done_callback(active_enemy_tasks.discard)

                logging.debug(
                    "Task for enemy at UI position %s queued (active_tasks=%s/%s).",
                    ui_pos, len(active_enemy_tasks), self.enemy_task_backlog_limit
                )

                await asyncio.sleep(0)

            except asyncio.CancelledError:
                for enemy_task in active_enemy_tasks:
                    enemy_task.cancel()
                if active_enemy_tasks:
                    await asyncio.gather(*active_enemy_tasks, return_exceptions=True)
                raise
            except Exception as e:
                logging.error(f"Error processing enemy from queue: {e}")

    async def check_enemy_presence(self, im):
        global current_enemy_list  # Dictionary that stores pixel counts with > 1 pixel

        logging.debug(f"Starting check_enemy_presence with image: {im}")

        frame_rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
        enemy_list_left = 750
        enemy_list_top = 40
        enemy_list_img = im.crop((750, 40, 960, 305))

        # Temporary dictionary to hold new state
        new_enemy_list = {}
        screenshots = {}  # Initialize the dictionary

        for ui_pos in range(5):
            try:
                logging.debug(f"Processing UI position {ui_pos}")
                y_top_step = 12 + (ui_pos * 52)
                y_bottom_step = 28 + (ui_pos * 52)
                logging.debug(
                    f"Cropped enemy_list_img at position {ui_pos}, top: {y_top_step}, bottom: {y_bottom_step}")

                # Count the pixels within a color range
                pixel_count = count_pixels_roi_arr(
                    frame_rgb,
                    enemy_list_left + 44,
                    enemy_list_top + y_top_step,
                    enemy_list_left + 85,
                    enemy_list_top + y_bottom_step,
                    (170, 255, 170, 255, 170, 255)
                )
                logging.debug(f"Pixel count for position {ui_pos}: {pixel_count}")

                if pixel_count > 1:
                    enemy_list_cropped = enemy_list_img.crop((44, y_top_step, 85, y_bottom_step))
                    # Generate a perceptual hash for the cropped image
                    enemy_signature = str(imagehash.phash(enemy_list_cropped))
                    logging.debug(f"Generated perceptual hash for position {ui_pos}: {enemy_signature}")

                    # Define tolerance for Hamming distance
                    hash_tolerance = 2  # Adjust this value to control sensitivity
                    logging.debug(f"Using hash tolerance: {hash_tolerance}")

                    # Check if the enemy is already in the current_enemy_list based on hash, allowing for some tolerance
                    previous_entry = next(
                        (
                            (k, v) for k, v in current_enemy_list.items()
                            if (imagehash.hex_to_hash(enemy_signature) - imagehash.hex_to_hash(k)) <= hash_tolerance
                        ),
                        None  # Return None if no match is found
                    )

                    if previous_entry:
                        try:
                            hash_key, entry_value = previous_entry
                            ui_pos_prev = entry_value['ui_pos']  # Access using key
                            logging.debug(f"Found previous entry for hash {hash_key} with UI position {ui_pos_prev}")
                            new_enemy_list[enemy_signature] = {
                                'ui_pos': ui_pos,
                                'pixel_count': pixel_count,
                                'processed': entry_value.get('processed', False),
                                'timestamp': time.time()
                            }
                        except (ValueError, KeyError) as e:
                            logging.error(f"Unexpected structure in previous_entry: {previous_entry}, Error: {e}")
                    else:
                        # New enemy detected
                        logging.debug(f"New enemy detected at position {ui_pos}, adding to new_enemy_list")
                        new_enemy_list[enemy_signature] = {
                            'ui_pos': ui_pos,
                            'pixel_count': pixel_count,
                            'processed': False,
                            'timestamp': time.time()
                        }

                        # Capture the images for enemy name and ship type
                        range_img = enemy_list_img.crop((18, y_top_step + 1, 24, y_bottom_step + 3))
                        name_img = enemy_list_img.crop((44, y_top_step - 2, 164, y_bottom_step + 1))
                        shiptype_img = enemy_list_img.crop((42, y_top_step + 16, 164, y_bottom_step + 17))
                        range_pxl_cnt = count_pixels_roi_arr(
                            frame_rgb,
                            enemy_list_left + 18,
                            enemy_list_top + y_top_step + 1,
                            enemy_list_left + 24,
                            enemy_list_top + y_bottom_step + 3,
                            (40, 70, 50, 95, 50, 95)
                        )

                        # Store the screenshots in the dictionary for further processing
                        screenshots[ui_pos] = (enemy_signature, name_img, shiptype_img, range_img, range_pxl_cnt)

                        logging.debug(
                            f"Captured images for UI position {ui_pos}: name_img size {name_img.size}, shiptype_img size {shiptype_img.size}")

            except Exception as e:
                logging.error(f"Error cropping enemy at UI position {ui_pos}. Error: {e}", exc_info=True)
                sys.exit()

        current_enemy_list = new_enemy_list
        logging.debug(f"Updated current_enemy_list with {len(new_enemy_list)} entries.")

        # Return True if any new enemy positions were detected, along with the screenshots
        return bool(screenshots), screenshots

    async def process_images_concurrently(self, anom_type_img, anom_max, ui_custom):
        anom_type = [None] * anom_max
        positive_hit = [None] * anom_max
        ping_list = [None] * anom_max
        ship_type_list = [None] * anom_max
        ship_category_list = [None] * anom_max

        # Create and start worker tasks
        queue = asyncio.Queue()
        workers = [asyncio.create_task(self.worker(queue)) for _ in range(self.num_worker_threads)]

        # Enqueue tasks for processing
        for i in range(anom_max):
            await queue.put((self.process_image, (anom_type_img, i, ui_custom)))

        # Signal the workers to exit by putting None in the queue
        for _ in range(self.num_worker_threads):
            await queue.put(None)

        # Wait for all workers to finish
        await asyncio.gather(*workers)

        # Collect results from the result queue
        results = []
        while not self.result_queue.empty():
            results.append(await self.result_queue.get())

        # Sort results by index
        results.sort(key=lambda x: x[0])

        # Populate the lists with the sorted results
        for result in results:
            i = result[0]
            anom_type[i] = result[1]
            ship_type_list[i] = result[2] if len(result) > 2 else None
            ping_list[i] = result[3] if len(result) > 3 else None
            if len(result) > 4:
                ship_category_list[i] = result[4] if result[4] else None

        return anom_type, positive_hit, ping_list, ship_type_list, ship_category_list

    async def match_system(self, system_to_match):
        def normalize_system_query(raw_text):
            txt = str(raw_text or "").upper()
            txt = txt.replace("\n", " ").replace("\r", " ")
            txt = re.sub(r"[^A-Z0-9\- ]+", " ", txt)
            txt = re.sub(r"\s+", " ", txt).strip()
            return txt

        # Flatten all solar systems into a single list.
        all_systems = []
        for constellation in self.constellations_data['constellations'].values():
            all_systems.extend(constellation['solarSystems'])

        query_raw = str(system_to_match or "")
        query_norm = normalize_system_query(query_raw)
        alnum_count = sum(ch.isalnum() for ch in query_norm)
        if alnum_count < 3:
            logging.warning("match_system: OCR query not usable for fuzzy match: raw=%r normalized=%r", query_raw, query_norm)
            return None

        # Build normalized lookup and match without fuzzywuzzy's default processor
        # to avoid "processor reduces input query to empty string" warnings.
        norm_to_original = {}
        norm_choices = []
        for system_name in all_systems:
            norm_name = normalize_system_query(system_name)
            if not norm_name:
                continue
            if norm_name not in norm_to_original:
                norm_to_original[norm_name] = system_name
                norm_choices.append(norm_name)

        if not norm_choices:
            logging.warning("match_system: No system names available to match against.")
            return None

        best_match = process.extractOne(query_norm, norm_choices, processor=None)
        if best_match:
            best_norm, score = best_match[0], int(best_match[1])
            resolved = norm_to_original.get(best_norm, best_norm)
            print(f'Best match for {query_norm}: {resolved} with a score of {score}')
            # Guard against very weak matches; avoid poisoning logs/manifest with random systems.
            if score < 45:
                logging.warning("match_system: low-confidence system match ignored (query=%r match=%r score=%s)", query_norm, resolved, score)
                return None
            return resolved

        print(f'No match found for {query_norm}')
        return None

    async def get_next_desto(self):
        try:
            # Open the file and read the waypoints
            with open('waypoints.txt', 'r') as f:
                waypoints = f.readlines()

            # Check if the file is empty
            if not waypoints:
                print("Error: waypoints.txt is empty.")
                return None

            # Remove any newline characters and strip extra spaces
            waypoints = [wp.strip() for wp in waypoints if wp.strip()]

            # Ensure there's at least one valid waypoint
            if not waypoints:
                print("Error: waypoints.txt contains only empty lines.")
                return None

            # Check if any waypoint has the '*' symbol (denotes the last selected destination)
            if any('*' in wp for wp in waypoints):
                current_index = next(i for i, wp in enumerate(waypoints) if '*' in wp)
                next_index = (current_index + 1) % len(waypoints)
                next_desto = waypoints[next_index].replace('*', '')
            else:
                # If no '*' found, start from the first waypoint
                next_desto = waypoints[0]

            return next_desto
        except FileNotFoundError:
            print(f"Error: waypoints.txt not found.")
            return None
        except IndexError as e:
            print(f"Error: IndexError occurred - {e}")
            return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None

    # Function to update the waypoint file with the next destination
    async def update_desto(self, next_desto=None):
        if next_desto is None:
            return

        try:
            # Open the file and read the waypoints
            with open('waypoints.txt', 'r') as f:
                waypoints = f.readlines()

            # Remove any '*' symbol from all lines
            waypoints = [wp.replace('*', '').strip() for wp in waypoints]

            # Find the index of the next destination and add '*' in front of it
            if next_desto in waypoints:
                next_index = waypoints.index(next_desto)
                waypoints[next_index] = f"*{waypoints[next_index]}"

            # Write the updated waypoints back to the file
            with open('waypoints.txt', 'w') as f:
                f.write('\n'.join(waypoints) + '\n')

        except FileNotFoundError:
            print(f"Error: waypoints.txt not found.")

    async def sticky_fingers(self, code):
        """
        Simulates human-like typing for short, code-like inputs.

        This function types a given string into the active input field, emulating natural typing patterns.
        It handles uppercase letters, numbers, and hyphens, introducing occasional typos and immediate corrections
        to enhance realism.

        Parameters:
            code (str): The code string to type (e.g., "1-7B6D", "C0O6-K").

        Behavior:
            - Initial Pause: Waits briefly before starting to type.
            - Character Typing: Types each character with realistic key press durations.
                - Uppercase Letters: Uses 'Shift' for uppercase characters.
                - Hyphens: Adds slight pauses to mimic natural breaks.
            - Typo Simulation:
                - Probability: 2% chance per character to introduce a typo.
                - Substitutions: Replaces characters with similar ones (e.g., 'O' ↔ '0').
                - Immediate Correction: Deletes and retypes the correct character.
            - Inter-Key Delays: Implements random delays between keystrokes.
        """
        # Typing settings
        typo_probability = 0.02  # 2% chance to make a typo
        key_press_duration = (0.06, 0.10)  # Duration to hold each key press
        inter_key_delay = (0.1, 0.04)  # Delay between key presses
        pause_before_start = (0.5, 1.0)  # Pause before typing starts
        pause_at_hyphen = (0.2, 0.5)  # Pause when typing a hyphen

        # Common character substitutions for typos
        substitution_options = {
            '0': ['O'], 'O': ['0'],
            '1': ['I', 'l'], 'I': ['1', 'l'],
            'l': ['1', 'I'],
            '*': ['8'], '-': ['_']
        }

        # Initial pause before typing
        await asyncio.sleep(random.uniform(*pause_before_start))

        for i, char in enumerate(code):
            # Determine if a typo should be made
            make_typo = None
            # make_typo = random.random() < typo_probability
            typed_char = substitution_options.get(char, [char])
            if make_typo and char in substitution_options:
                typed_char = random.choice(substitution_options[char])
            else:
                typed_char = char

            # Simulate key press
            if char.isupper():
                pyautogui.keyDown('shift')
                pyautogui.keyDown(char.lower())
                await asyncio.sleep(random.uniform(*key_press_duration))
                pyautogui.keyUp(char.lower())
                pyautogui.keyUp('shift')
            else:
                pyautogui.keyDown(char)
                await asyncio.sleep(random.uniform(*key_press_duration))
                pyautogui.keyUp(char)

            # Correct typo immediately if made
            if make_typo and char in substitution_options:
                await asyncio.sleep(random.uniform(0.05, 0.1))
                pyautogui.press('backspace')  # Delete wrong character
                # Re-type correct character
                if char.isupper():
                    pyautogui.keyDown('shift')
                    pyautogui.keyDown(char.lower())
                    await asyncio.sleep(random.uniform(*key_press_duration))
                    pyautogui.keyUp(char.lower())
                    pyautogui.keyUp('shift')
                else:
                    pyautogui.keyDown(char)
                    await asyncio.sleep(random.uniform(*key_press_duration))
                    pyautogui.keyUp(char)

            # Add delay after each character
            if char == '-':
                await asyncio.sleep(random.uniform(*pause_at_hyphen))
            elif i < len(code) - 1:
                await asyncio.sleep(random.uniform(*inter_key_delay))

    async def type_text_backend(self, text: str):
        raw = str(text or "")
        if _uinput_backend_enabled():
            for attempt in range(2):
                try:
                    controller, _ = await asyncio.to_thread(_ensure_emuinput_controller)
                    await asyncio.to_thread(controller.type_text, raw)
                    await delay(50, 120)
                    return
                except Exception:
                    _invalidate_emuinput_controller()
                    if attempt == 0:
                        continue
                    raise
        await self.sticky_fingers(raw)

    async def press_enter_backend(self):
        if _uinput_backend_enabled():
            for attempt in range(2):
                try:
                    controller, _ = await asyncio.to_thread(_ensure_emuinput_controller)
                    await asyncio.to_thread(controller.press_enter)
                    await delay(40, 90)
                    return
                except Exception:
                    _invalidate_emuinput_controller()
                    if attempt == 0:
                        continue
                    raise
        pyautogui.press('enter')

    async def click_menu(self, menu_coord_x, menu_coord_y, menu_item, symbol_img, left_menu, top_menu, right_menu,
                         bottom_menu, invert=False, max_retries=2, timeout=8):
        try:
            roi = (left_menu, top_menu, right_menu, bottom_menu)
            return await self.ui_navigator.click_until_menu_state(
                menu_name=menu_item,
                click_action=lambda: click(menu_coord_x, menu_coord_y, 0),
                symbol_img=symbol_img,
                roi=roi,
                invert=invert,
                max_retries=max_retries,
                timeout=float(timeout),
                pre_delay_min=200,
                pre_delay_max=300,
                poll_interval=0.1
            )

        except Exception as e:
            print(f"Error occurred while opening the {menu_item}: {e}")
            return False

    async def set_desto_map(self, desto):
        try:
            async def wait_for_ap_status(desired_statuses, timeout_s=10.0, poll_s=0.4):
                desired = set(desired_statuses)
                frame_local = None
                last_status = "unknown"
                end_ts = time.monotonic() + float(timeout_s)
                while time.monotonic() < end_ts:
                    frame_local = await self.ui_navigator.capture_frame()
                    last_status = self.ui_detector.autopilot_status(frame_local)
                    if last_status in desired:
                        return True, last_status, frame_local
                    await asyncio.sleep(float(poll_s))
                return False, last_status, frame_local

            if not _uinput_backend_enabled():
                await asyncio.to_thread(activate_window, 2)
            await delay()

            search_eye_toggle_xy = (923, 269)
            search_input_xy = (794, 124)
            map_menu_xy = (614, 467)

            # Perform the map and search sequence (updated workflow coordinates)
            await click(40, 20, 0, 15, 15)
            await delay(250, 500)
            await click(map_menu_xy[0], map_menu_xy[1], 0, 0, 0)

            # Fast map-open verification: map is considered open when either:
            # - search panel is visible, or
            # - closed-eye toggle is visible on the right edge.
            frame = await self.ui_navigator.capture_frame()
            map_ready = (
                self.ui_detector.is_map_search_panel_open(frame)
                or self.ui_detector.is_map_search_eye_closed_visible(frame)
            )
            for attempt in range(1, 4):
                if map_ready:
                    logging.info("[ui] Map view confirmed on attempt %s.", attempt)
                    break
                await click(map_menu_xy[0], map_menu_xy[1], 0, 0, 0)
                await delay(350, 600)
                frame = await self.ui_navigator.capture_frame()
                map_ready = (
                    self.ui_detector.is_map_search_panel_open(frame)
                    or self.ui_detector.is_map_search_eye_closed_visible(frame)
                )
            if not map_ready:
                raise RuntimeError("Failed to open map view (search/eye state not detected).")

            # If search panel is closed, open it via the right-edge eye toggle.
            if not self.ui_detector.is_map_search_panel_open(frame):
                for attempt in range(1, 4):
                    if self.ui_detector.is_map_search_eye_closed_visible(frame) or attempt == 1:
                        await click(search_eye_toggle_xy[0], search_eye_toggle_xy[1], 0, 0, 0)
                    await delay(325, 500)
                    frame = await self.ui_navigator.capture_frame()
                    if self.ui_detector.is_map_search_panel_open(frame):
                        logging.info("[ui] Map search panel opened on attempt %s.", attempt)
                        break
                if not self.ui_detector.is_map_search_panel_open(frame):
                    logging.warning("[ui] Map search panel did not validate as open; continuing with input click fallback.")
            else:
                logging.info("[ui] Map search panel already open.")

            await click(search_input_xy[0], search_input_xy[1], 0, 0, 0)
            await delay(350, 650)
            await self.type_text_backend(desto)
            await self.press_enter_backend()
            # Required by current map UI: trigger Search twice with subtle spacing.
            await delay(660, 1080)
            await click(820, 24, 0, 0, 0)
            await delay(540, 900)
            await click(820, 24, 0, 0, 0)
            await delay(1050, 1800)

            # Single click only: second click can collapse/close the result row.
            await click(744, 177, 0, 0, 0)
            await delay(1400, 2100)

            # Set destination.
            await click(610, 308, 0, 0, 0)
            await delay(800, 1300)

            # AP icon/state-driven flow (single-toggle policy):
            # - wait briefly for AP to reflect paused/running after destination set
            # - if paused, click AP exactly once
            # - do not re-click inside this routine; close map and let outer flow validate
            got_ap_state, ap_state, _ = await wait_for_ap_status({"paused", "running"}, timeout_s=4.5, poll_s=0.35)
            if got_ap_state and ap_state == "paused":
                await click(20, 148, 0, 0, 0)
                await delay(600, 900)
            elif got_ap_state and ap_state == "running":
                logging.info("[ui] AP already running after destination set.")
            else:
                logging.warning("[ui] AP did not reach paused/running before map close (status=%s).", ap_state)

            # Close map and finalize.
            await click(923, 30, 0, 0, 0)
            await delay(3500, 4500)
            await click(650, 495, 0, 0, 0)
            await delay(600, 900)
            return desto

        except Exception as e:
            print(f"Error in set_desto_map: {e}")

    async def ap_status(self, im_ap):
        return self.ui_detector.autopilot_status(im_ap)

    async def drag_with_curve(self, start_point, end_point, steps=30, curve_factor=5):
        def calculate_control_point(start_point, end_point, offset_distance, bend_direction=1):
            midpoint = ((start_point[0] + end_point[0]) / 2, (start_point[1] + end_point[1]) / 2)
            dx = end_point[0] - start_point[0]
            dy = end_point[1] - start_point[1]
            perp_direction = (1, 0) if dx == 0 else (1, -1 / (dy / dx))
            perp_direction_normalized = (perp_direction[0] / np.linalg.norm(perp_direction),
                                         perp_direction[1] / np.linalg.norm(perp_direction))
            control_point = (midpoint[0] + perp_direction_normalized[0] * offset_distance * bend_direction,
                             midpoint[1] + perp_direction_normalized[1] * offset_distance * bend_direction)
            return control_point

        def calculate_bezier_point(t, start_point, control_point, end_point):
            x = (1 - t) ** 2 * start_point[0] + 2 * (1 - t) * t * control_point[0] + t ** 2 * end_point[0]
            y = (1 - t) ** 2 * start_point[1] + 2 * (1 - t) * t * control_point[1] + t ** 2 * end_point[1]
            return x, y

        try:
            if _uinput_backend_enabled():
                controller, hello = await asyncio.to_thread(_ensure_emuinput_controller)
                u_start_x, u_start_y, mode_a = _map_base_to_uinput_coords(start_point[0], start_point[1], hello)
                u_end_x, u_end_y, mode_b = _map_base_to_uinput_coords(end_point[0], end_point[1], hello)
                if mode_a != mode_b:
                    logging.warning(
                        "Rotation mode changed during drag mapping (%s -> %s).",
                        mode_a,
                        mode_b,
                    )
                duration_ms = max(180, int(max(2, int(steps))) * 35)
                drag_steps = max(8, int(max(2, int(steps))) * 3)
                print(
                    f"Drag base({start_point}->{end_point}) -> "
                    f"uinput(({u_start_x},{u_start_y})->({u_end_x},{u_end_y})) mode={mode_b}"
                )
                await asyncio.to_thread(
                    controller.drag,
                    u_start_x,
                    u_start_y,
                    u_end_x,
                    u_end_y,
                    duration_ms,
                    drag_steps,
                )
                await delay(230, 375)
                return

            # Find the target window based on the scout title
            pilot_window = next((w for w in pyautogui.getAllWindows() if scout in w.title and ".py" not in w.title),
                                None)
            if not pilot_window:
                raise ValueError(f"Window with title containing '{scout}' not found.")

            # Activate the target window using scout as the title
            activate_window(2)

            # Verify window activation by checking titles
            active_window = pyautogui.getActiveWindow()
            if active_window and active_window.title != pilot_window.title:
                activate_window_by_title('prototype')

            # Verify window activation by checking titles
            active_window = pyautogui.getActiveWindow()
            if active_window and active_window.title != pilot_window.title:
                raise RuntimeError(f"Failed to activate window: {pilot_window.title}")

            if not target_hwnd or not win32gui.IsWindow(target_hwnd):
                raise RuntimeError("Failed to locate target window for drag.")
            client_left, client_top, _, _ = _get_client_metrics(target_hwnd)
            start_x_rel, start_y_rel, _, _, _, _ = _map_base_to_client(
                target_hwnd, start_point[0], start_point[1], action_type=0
            )
            end_x_rel, end_y_rel, _, _, _, _ = _map_base_to_client(
                target_hwnd, end_point[0], end_point[1], action_type=0
            )
            adjusted_start = (client_left + start_x_rel, client_top + start_y_rel)
            adjusted_end = (client_left + end_x_rel, client_top + end_y_rel)

            # Calculate the control point for drag curve
            control_point = calculate_control_point(adjusted_start, adjusted_end, curve_factor, random.choice([-1, 1]))

            # Perform the drag. Always release the button even if movement fails.
            drag_started = False
            try:
                # Clear any stale pressed state before starting.
                pyautogui.mouseUp(button='left')
            except Exception:
                pass
            try:
                pyautogui.mouseDown(adjusted_start[0], adjusted_start[1], button='left')
                drag_started = True
                for t in np.linspace(0, 1, steps):
                    point = calculate_bezier_point(t, adjusted_start, control_point, adjusted_end)
                    pyautogui.moveTo(point[0], point[1], duration=0.02)
            finally:
                if drag_started:
                    try:
                        pyautogui.mouseUp(button='left')
                    except Exception as release_error:
                        logging.warning("drag_with_curve: failed to release mouse button cleanly: %s", release_error)

            await delay(230, 375)  # Adjust delay as needed

        except (ValueError, RuntimeError) as e:
            print(e)
        except Exception as e:
            if _uinput_backend_enabled():
                _invalidate_emuinput_controller()
            print(e)

    async def click_anom_nav(self, x_position, y_position, action_type=0, x_variance=5, y_variance=5, index=1):
        await click(
            x_position,
            y_position,
            action_type=action_type,
            x_variance=x_variance,
            y_variance=y_variance,
            index=index
        )
        return

    async def open_anom_nav(self):
        # Open Nav UI
        await self.click_anom_nav(793, 20)

    async def close_anom_nav(self):
        # Select anomaly filter (updated workflow)
        await self.click_anom_nav(807, 257)

    async def refresh_anom_nav_ui(self, ui_open_check_img):
        while True:
            async with self.pull_win_lock:
                im, result = await self.async_pull_win()
            ui_open_check = symbol_present(im, ui_toggle, 677, 295, 700, 310)
            # print(f'ui_open_check: {ui_open_check}')
            if ui_open_check:
                await self.close_anom_nav()
            await self.open_anom_nav()
            await delay(1500, 2193)
            im, report = await self.async_pull_win()
            ui_open_check = symbol_present(im, ui_toggle, 677, 295, 700, 310)
            if ui_open_check:
                break
        return ui_open_check

    async def open_anom_nav_ui_if_closed(self, ui_open_check_img):
        ui_open_check = symbol_present(ui_open_check_img, ui_toggle, 677, 295, 700, 310, 0.4)

        while not ui_open_check:
            await self.open_anom_nav()
            async with self.pull_win_lock:
                im, result = await self.async_pull_win()
            await delay(1500, 2193)
            # print('saving')
            # save_img(pull_win()[0], 'test2', 677, 295, 700, 310)
            # print('saved')
            ui_open_check = symbol_present(im, ui_toggle, 677, 295, 700, 310)
            print(f'ui_open_check: {ui_open_check}')
            if ui_open_check:
                break
        return ui_open_check

    async def expand_anom_ui(self):
        await self.drag_with_curve((820, 115), (840, 216), random.randint(2, 5), random.randint(4, 15))
        await delay(200, 250)

    async def grab_screen(self):
        hwnd = win32gui.FindWindow(None, scout)
        if hwnd == 0:
            print(f"Window with title '{scout}' not found!")
            return None

        _ensure_process_dpi_aware()
        x0, y0, x1, y1 = win32gui.GetWindowRect(hwnd)
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            print(f"Invalid window dimensions: {w}x{h}")
            return None

        try:
            result, bmpinfo, bmpstr = _grab_screen_capture_ctx.capture(hwnd, w, h, 0)
        except Exception:
            # One best-effort reset/retry if cached GDI objects became stale.
            _grab_screen_capture_ctx.reset()
            try:
                result, bmpinfo, bmpstr = _grab_screen_capture_ctx.capture(hwnd, w, h, 0)
            except Exception as capture_error:
                logging.error("grab_screen capture failed after context reset: %s", capture_error)
                return None

        if not result:
            print("PrintWindow failed")
            return None

        img = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRX', 0, 1)

        # Locking the shared resource after processing
        with screen_capture_lock:
            return img

    async def update_anomaly_embed(self, anom_manifest, channel_id, message_id):
        try:
            # Fetch the channel
            target_channel = self.get_channel(channel_id)
            if target_channel is None:
                print(f"Channel with ID {channel_id} not found.")
                return

            # Fetch the message
            message = await target_channel.fetch_message(message_id)

            # Create embed
            embed = discord.Embed(title="Anomaly SIGINT", color=0x00ff00)

            # Load seeker log
            if os.stat('seeker_log.json').st_size == 0:  # Check if the file is empty
                seeker_log = []
            else:
                try:
                    with open('seeker_log.json', 'r') as log_file:
                        seeker_log = json.load(log_file)
                except (FileNotFoundError, json.JSONDecodeError) as e:
                    print(f"Failed to load seeker_log.json: {e}")
                    seeker_log = []

            # Set of existing entries in log to avoid duplication
            existing_log_entries = {(entry["system_name"], entry["timestamp"]) for entry in seeker_log}

            # Store new entries for seeker_log
            new_log_entries = []

            # Track sightings per system in the current batch
            system_type_1_sightings = {}

            # Process the manifest for this system
            checkpoints = {}
            cap_checkpoints = {}

            for constellation_name, constellation_data in self.constellations_data['constellations'].items():
                for system_name in constellation_data['solarSystems']:
                    system_sightings = [entry for entry in anom_manifest if entry['system_name'] == system_name]

                    for entry in system_sightings:
                        special_type = entry["special_type"]
                        timestamp = entry["timestamp"]

                        # Only count new sightings
                        if (system_name, timestamp) not in existing_log_entries:
                            new_log_entries.append(entry)

                            # Count Type 1 sightings for the current system
                            if special_type == 1:
                                system_type_1_sightings[system_name] = system_type_1_sightings.get(system_name, 0) + 1

                        # Group by type for checkpoints and cap checkpoints
                        if special_type == 1:
                            checkpoints[constellation_name] = checkpoints.get(constellation_name, {})
                            checkpoints[constellation_name][system_name] = checkpoints[constellation_name].get(
                                system_name, 0) + 1
                        elif special_type == 2:
                            cap_checkpoints[constellation_name] = cap_checkpoints.get(constellation_name, {})
                            cap_checkpoints[constellation_name][system_name] = cap_checkpoints[constellation_name].get(
                                system_name, 0) + 1

            # Add new log entries
            seeker_log.extend(new_log_entries)
            try:
                with open('seeker_log.json', 'w') as log_file:
                    json.dump(seeker_log, log_file, indent=4)
            except Exception as e:
                print(f"Failed to write to seeker_log.json: {e}")

            # Prepare the fields for the embed
            def format_sightings(sightings_dict):
                text = ""
                for constellation, systems in sightings_dict.items():
                    systems_list = "\n".join(
                        [f"{system} ({count})" if count > 1 else system for system, count in systems.items()]
                    )
                    text += f"**{constellation}**\n{systems_list}\n\n"  # Add a blank line after each constellation
                return text

            checkpoints_text = format_sightings(checkpoints)
            cap_checkpoints_text = format_sightings(cap_checkpoints)

            # Ensure there's a placeholder if no sightings are found
            embed.add_field(name="Checkpoints\n--------------", value=checkpoints_text or "No Type 1 Anomalies",
                            inline=True)
            embed.add_field(name="Cap Checkpoints\n--------------", value=cap_checkpoints_text or "No Type 2 Anomalies",
                            inline=True)

            # Edit the message with the new embed
            await message.edit(embed=embed)

        except Exception as e:
            print(f"Error in update_anomaly_embed: {e}")

    async def send_sighting_to_server(self, sighting_data):
        ws = self.websocket
        if not ws:
            logging.warning("WebSocket is not connected. Cannot send sighting.")
            return

        try:
            # Compatibility across websocket client implementations.
            if getattr(ws, "closed", False):
                logging.warning("WebSocket is closed. Cannot send sighting.")
                return
            if hasattr(ws, "open"):
                try:
                    if not bool(getattr(ws, "open")):
                        logging.warning("WebSocket is not open. Cannot send sighting.")
                        return
                except Exception:
                    pass
        except Exception:
            pass

        try:
            message = {
                'type': 'anomaly_update',
                'data': sighting_data
            }
            await ws.send(json.dumps(message))
            logging.info(f"Sent sighting to server: {sighting_data}")
        except Exception as e:
            logging.error(f"Failed to send sighting to server: {e}")

    async def detect_checkpoint_from_image(self, im, debug_dump=False, debug_tag="", max_rows=5):
        w, h = im.size
        tx1, tx2 = _scaled_ratio_x_range(w, 786 / 970.0, 952 / 970.0, min_width=108)

        attempts = []
        row_results = []
        checkpoint_hits = []
        dump_dir = None
        should_dump = bool(debug_dump)
        if should_dump:
            try:
                tag_raw = str(debug_tag or "anomscan")
                tag_safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag_raw).strip("_") or "anomscan"
                run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                dump_dir = os.path.join("debug_images", "anomscan", f"{tag_safe}_{run_id}")
                os.makedirs(dump_dir, exist_ok=True)
                im.save(os.path.join(dump_dir, "frame.png"), format="PNG")
            except Exception:
                should_dump = False
                dump_dir = None

        # Bottom row first, then walk upward one row at a time.
        scale = max(0.7, min(1.6, float(h) / 540.0))
        row_step = max(36, int(round(52 * scale)))
        # Tighten vertical band and shift downward to avoid clipping the row above.
        row_height = max(34, int(round(42 * scale)))
        bottom_margin = max(2, int(round(6 * scale)))

        cfg_echoes_p6 = build_tesseract_config(psm=6, whitelist=None, preserve_spaces=True)
        cfg_echoes_p7 = build_tesseract_config(psm=7, whitelist=None, preserve_spaces=True)

        for row_idx in range(int(max_rows)):
            b = int(h - bottom_margin - (row_idx * row_step))
            t = int(b - row_height)
            area = (tx1, max(0, t), tx2, max(0, b))
            if area[3] - area[1] < 24:
                continue

            crop = im.crop(area)
            up = crop.resize((crop.width * 4, crop.height * 4), resample=Image.Resampling.LANCZOS)
            gray = ImageOps.grayscale(up)
            bw140 = gray.point(lambda p: 255 if p > 140 else 0, 'L')
            inv140 = ImageOps.invert(bw140)
            variants = [("gray", gray), ("inv140", inv140)]

            if should_dump and dump_dir:
                try:
                    crop.save(os.path.join(dump_dir, f"row{row_idx + 1}_raw_{area[0]}_{area[1]}_{area[2]}_{area[3]}.png"), format="PNG")
                    up.save(os.path.join(dump_dir, f"row{row_idx + 1}_up4x.png"), format="PNG")
                except Exception:
                    pass

            best_kind = "unknown"
            best_type = 0
            best_norm = ""
            best_score = 0.0

            for vtag, vimg in variants:
                if should_dump and dump_dir:
                    try:
                        vimg.save(os.path.join(dump_dir, f"row{row_idx + 1}_{vtag}.png"), format="PNG")
                    except Exception:
                        pass
                for lang_tag, lang_name, cfg in (
                    ("echoes6", "echoes", cfg_echoes_p6),
                    ("echoes7", "echoes", cfg_echoes_p7),
                ):
                    raw = await self._ocr_image_to_string(vimg, lang=lang_name, config=cfg)
                    if not isinstance(raw, str):
                        raw = str(raw or "")
                    raw = raw.replace("\n", " ").replace("\r", " ")
                    kind, special_type, norm, score = _classify_wasteseeker_row_text(raw)
                    attempts.append(f"r{row_idx + 1}:{lang_tag}/{vtag}@{area}:{norm[:64]!r}:{special_type}:{kind}")
                    if (
                        (special_type > best_type)
                        or (special_type == best_type and score > best_score)
                        or (special_type == best_type and score == best_score and len(norm) > len(best_norm))
                    ):
                        best_kind = kind
                        best_type = special_type
                        best_norm = norm
                        best_score = score

            row_entry = {
                "row": row_idx + 1,
                "kind": best_kind,
                "type": int(best_type),
                "text": best_norm,
                "area": area,
            }
            row_results.append(row_entry)

            # Row-walk rule:
            # 1) If bottom row is encampment, stop immediately (no checkpoints).
            # 2) If row is checkpoint/capital-checkpoint, record and continue upward.
            # 3) Stop at first encampment after one or more checkpoints.
            # 4) Stop on unknown to avoid drifting into unrelated rows.
            if best_type > 0:
                checkpoint_hits.append(row_entry)
                continue
            if best_kind == "encampment":
                break
            break

        if checkpoint_hits:
            primary = checkpoint_hits[0]
            return primary["type"], primary["text"], primary["area"], attempts, dump_dir, row_results, checkpoint_hits
        if row_results:
            primary = row_results[0]
            return 0, primary["text"], primary["area"], attempts, dump_dir, row_results, checkpoint_hits
        return 0, "", None, attempts, dump_dir, row_results, checkpoint_hits

    async def capture_scan_frame(self):
        """
        Capture a gameplay frame for anomaly/map diagnostics.
        Prefer pull_win pipeline because it reliably captures emulator content.
        """
        try:
            async with self.pull_win_lock:
                im, _ = await self.async_pull_win()
            if im is not None:
                return im, "pull_win"
        except Exception as e:
            logging.warning("capture_scan_frame: pull_win path failed: %s", e)

        im = await self.grab_screen()
        if im is not None:
            return im, "grab_screen_fallback"
        return None, "capture_failed"

    async def find_wasteseeker(self, desto_system=None):
        try:
            im, capture_source = await self.capture_scan_frame()
            if im is None:
                logging.warning("find_wasteseeker: failed initial frame capture (source=%s)", capture_source)
                return

            # Grab current system name
            system_name = await self.get_system(im)
            if not system_name:
                system_name = (str(desto_system).strip() if desto_system else "UNKNOWN")
                logging.warning("find_wasteseeker: system OCR failed; using fallback system_name=%s", system_name)
            # await self.open_anom_nav_ui_if_closed(im)
            await self.drag_with_curve((random.randint(740, 890), random.randint(275, 315)),
                                       (random.randint(780, 890), random.randint(5, 90)),
                                       random.randint(5, 12), random.randint(7, 30))
            im, capture_source = await self.capture_scan_frame()
            if im is None:
                logging.warning("find_wasteseeker: failed post-drag frame capture (source=%s)", capture_source)
                return
            im_arr = np.asarray(im.convert("RGB"), dtype=np.uint8)

            # Define the pixel areas to check, starting from top to bottom
            areas_to_check, icon_areas_to_check, peaks, _, _, peak_min = _detect_anom_rows_from_icon_profile(
                im_arr, row_count=5
            )
            if not areas_to_check:
                areas_to_check = _build_anom_row_areas(im.width, im.height)
                icon_areas_to_check = [
                    _build_anom_icon_area_for_row(im.width, im.height, t, b) for _, t, _, b in areas_to_check
                ]
                logging.info("[ui] anom rows: icon profile empty (min_peak=%s). Using fallback rows.", peak_min)
            else:
                logging.info("[ui] anom rows from icon profile: peaks=%s min_peak=%s", peaks, peak_min)
            '''
            (807, 554, 840, 556),
            (807, 502, 840, 504),
            (807, 450, 840, 452),
            (807, 398, 840, 400),
            (807, 347, 840, 349)
            '''

            # Load the existing manifest file
            try:
                with open('anom_manifest.json', 'r') as file:
                    anom_manifest = json.load(file)
            except FileNotFoundError:
                anom_manifest = []

            # Remove all previous sightings for the current system
            anom_manifest = [entry for entry in anom_manifest if entry["system_name"] != system_name]

            # List to store new sightings for this scan
            new_sightings = []

            # Pixel telemetry for bottom-most rows (kept for debug/context).
            rows_to_check = list(zip(areas_to_check, icon_areas_to_check))[:3]
            legacy_bottom = [count_pixels_roi_arr(im_arr, *a, _ANOM_LEGACY_BOUNDS) for a, _ in rows_to_check]
            icon_bottom = [_count_redish_pixels_roi_arr(im_arr, *ia) for _, ia in rows_to_check]
            anom_pixl_cnt = max([0] + [max(int(l), int(i)) for l, i in zip(legacy_bottom, icon_bottom)])

            panel_type, panel_norm, panel_area, attempts, _, row_results, checkpoint_hits = await self.detect_checkpoint_from_image(im)
            logging.info(
                "[ui] checkpoint panel detect: type=%s area=%s text=%r hits=%s rows=%s attempts=%s",
                panel_type, panel_area, panel_norm, len(checkpoint_hits), row_results[:3], attempts[:4]
            )

            for hit in checkpoint_hits:
                new_sightings.append({
                    "datetime": datetime.now().isoformat(),
                    "timestamp": int(time.time()),
                    "system_name": system_name,
                    "special_type": int(hit.get("type", 0)),
                    "anom_pixl_cnt": anom_pixl_cnt,
                    "row_text": str(hit.get("text", "")),
                })

            # If any system in the current batch has 5 or more new Type 1 sightings, exit early
            if len(new_sightings) >= 5:
                print(f"Five or more new anomalies found for system {system_name}. Exiting.")
                return  # Exit without updating anything

            # If any new sightings were found, append them to the manifest
            if new_sightings:
                anom_manifest.extend(new_sightings)
                print(f"New sightings recorded: {new_sightings}")

            # Prepare the data to send
            for sighting in new_sightings:
                sighting["system_name"] = system_name
                # Send the sighting to the server
                await self.send_sighting_to_server(sighting)

            if new_sightings:
                # Persist sightings locally even if websocket delivery fails.
                with open('anom_manifest.json', 'w') as file:
                    json.dump(anom_manifest, file, indent=4)

                # Refresh Discord embed from persisted manifest.
                await self.update_anomaly_embed(anom_manifest, 1291799816107589664, 1291806724008706068)
            return

        except Exception as e:
            print(f"Error during OCR: {e}")
            return

    async def get_system(self, im_sys):
        runtime_top_inset = _get_runtime_top_inset(window_title=self.scout)
        # Primary + fallback crops around the large white system label to the right of portrait.
        # Coordinates are in base/full-window space used by grab_screen().
        system_rois = [
            (86, 17, 200, 37),   # legacy crop
            (82, 12, 235, 42),   # wider fallback
            (78, 8, 270, 46),    # widest fallback
        ]

        best_raw = None
        y_offsets = [0]
        if runtime_top_inset and runtime_top_inset > 0:
            y_offsets.append(int(runtime_top_inset))

        for y_off in y_offsets:
            for idx, (l, t, r, b) in enumerate(system_rois, start=1):
                crop_img = im_sys.crop((l, t + y_off, r, b + y_off))
                proc_img = ImageOps.grayscale(crop_img)
                proc_img = proc_img.point(lambda p: 255 if p > 175 else 0, '1')
                sys_result = await self.ocr_section(proc_img, 0, 0, proc_img.width, proc_img.height, crop_left=False)
                best_raw = sys_result
                system_name = await self.match_system(sys_result)
                if system_name:
                    print(f'System Name: {system_name} (roi#{idx}, y_off={y_off})')
                    return system_name

        logging.warning("get_system: failed to resolve system from OCR. last_raw=%r", best_raw)
        return None

    async def get_first_desto_from_waypoints(self):
        with open('waypoints.txt', 'r') as file:
            waypoints = file.readlines()

        for line in waypoints:
            if line.startswith('*'):
                return line.strip().replace('*', '').strip()  # Remove the '*' and return the system name

        return None  # Return None if no waypoint with '*' is found

    # Seek logic function
    async def seek_logic(self):
        try:
            self.seeking_active = True
            jump_trigger = False
            ap_stat_last = None
            unset_streak = 0
            first_run = True  # Initialize the first_run flag
            desto_system = None

            # Load the manifest
            try:
                with open('anom_manifest.json', 'r') as file:
                    anom_manifest = json.load(file)
            except FileNotFoundError:
                print("No manifest found.")
                return

            # Update the Discord embed with the new sightings
            await self.update_anomaly_embed(anom_manifest, 1291799816107589664, 1291806724008706068)

            jump_trigger = True  # set True to trigger anom scan on first run

            while True:
                async with self.pull_win_lock:
                    im, result = await self.async_pull_win()
                # im.show()
                # save_img(im, 'temper2')
                ap_stat = await self.ap_status(im)
                save_img(im, 'temper2')
                prev_ap_stat = ap_stat_last
                status_changed = (ap_stat != ap_stat_last)
                if ap_stat == 'unset':
                    unset_streak += 1
                else:
                    unset_streak = 0
                if status_changed:
                    print(f'AP Status: {ap_stat}')
                    ap_stat_last = ap_stat
                    if ap_stat == 'unknown':
                        # Arm post-jump scan trigger as soon as AP enters transit/unknown.
                        jump_trigger = True
                        logging.info("seek_logic: AP entered unknown; jump-trigger armed.")

                if ap_stat == 'unset':
                    # Debounce transient AP misreads; only treat unset as actionable when stable.
                    if unset_streak < 3:
                        logging.info("seek_logic: transient unset (%s/3), waiting before reroute.", unset_streak)
                        await asyncio.sleep(1)
                        continue

                    if not _uinput_backend_enabled():
                        activate_window(2)
                    # On the first run, use the system marked with '*'
                    if first_run:
                        next_desto = await self.get_first_desto_from_waypoints()
                        first_run = False  # Disable first_run flag after the first run
                    else:
                        next_desto = await self.get_next_desto()  # Regular waypoint logic after the first run

                    # jump_trigger = True

                    if next_desto:
                        print(f"Next destination: {next_desto}")
                        unset_streak = 0
                        jump_trigger = False
                        await self.find_wasteseeker()
                        # Set the destination via map search
                        desto_system = await self.set_desto_map(next_desto)
                        await self.update_desto(next_desto=next_desto)
                        await delay(500, 501)
                        '''
                        async with self.pull_win_lock:
                            im, result = await self.async_pull_win()
                        ap_stat = await self.ap_status(im)
                        if ap_stat == 'paused':
                            await self.find_wasteseeker()
                            await click(20, 148, 0)
                            await delay(250, 500)
                        '''
                        # await self.send_window_to_back(scout)

                elif ap_stat == 'running' and jump_trigger:
                    # print(f'jump_trigger: {jump_trigger}')
                    # Prefer scan when we just transitioned unknown -> running.
                    if prev_ap_stat == 'unknown' and status_changed:
                        logging.info("seek_logic: AP transitioned unknown -> running; triggering anomaly scan.")
                        await delay(650, 950)
                    else:
                        logging.info("seek_logic: AP running with armed jump-trigger; triggering anomaly scan.")
                    jump_trigger = False
                    await self.find_wasteseeker(desto_system)
                    # await self.send_window_to_back(scout)

                if ap_stat == 'paused':
                    first_run = False
                    await delay(1000, 1200)
                    async with self.pull_win_lock:
                        im, result = await self.async_pull_win()
                    ap_stat = await self.ap_status(im)
                    if ap_stat == 'paused':
                        await self.find_wasteseeker()
                        # Already scanned in this paused state; don't immediately rescan on running.
                        jump_trigger = False
                        resumed, ap_status_now, _ = await self.ui_navigator.ensure_autopilot_running(max_attempts=3)
                        if not resumed:
                            logging.warning("seek_logic: Failed to resume autopilot (status=%s).", ap_status_now)
                        # await self.send_window_to_back(scout)

                # Check if the time limit is reached
                if datetime.now() >= self.seek_end_time:
                    print("Seek task time limit reached, stopping...")
                    break  # Exit the loop when time is up

                await asyncio.sleep(1)  # Adjust sleep as needed to prevent busy-waiting

        except asyncio.CancelledError as e:
            print(f"Seek task was cancelled. [{e}]")  # Handle task cancellation cleanly

    '''
    async def send_window_to_back(self, window_title):
        try:
            # Find the window handle by title
            target_hwnd = next(
                (w._hWnd for w in pyautogui.getAllWindows() if window_title in w.title),
                None
            )
            if not target_hwnd:
                raise ValueError(f"Window with title '{window_title}' not found.")

            # Set the window to the bottom of the Z-order
            win32gui.SetWindowPos(target_hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

        except Exception as e:
            print(f"Failed to send window '{window_title}' to back: {e}")
    '''

    async def websocket_connect(self):
        while True:
            try:
                async with websockets.connect(self.websocket_url) as websocket:
                    self.websocket = websocket
                    logging.info("Connected to the WebSocket server.")
                    # Optionally send an initial message to the server
                    await self.websocket.send(json.dumps({
                        'type': 'register',
                        'system': self.target_channel_name  # Assuming self.scout is the system name
                    }))
                    # Keep the connection open
                    while True:
                        await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"WebSocket connection error: {e}. Reconnecting in 5 seconds.")
                self.websocket = None  # Reset the websocket reference
                await asyncio.sleep(5)

    async def _warmup_uinput_backend(self):
        if not _uinput_backend_enabled():
            return
        try:
            _, hello = await asyncio.to_thread(_ensure_emuinput_controller)
            startup_info(
                "Input backend active: uinput (serial=%s, host_port=%s, rotation=%s, autofix=%s).",
                emuinput_serial,
                emuinput_host_port,
                _resolve_rotation_mode(hello),
                "ON" if emuinput_autofix else "OFF",
            )
            logging.info(
                "[input] backend=%s serial=%s host_port=%s adb=%s hello=%s rotation=%s",
                input_backend,
                emuinput_serial,
                emuinput_host_port,
                _emuinput_resolved_adb_exe,
                hello,
                _resolve_rotation_mode(hello),
            )
        except Exception as exc:
            logging.warning(
                "[input] backend=uinput startup preflight failed (%s). "
                "Keeping backend=uinput; runtime calls will retry.",
                exc,
            )
            startup_warn("Input backend not ready yet (uinput preflight failed). Runtime will retry.")

    async def on_ready(self):
        startup_info("Discord connected.")
        startup_info("Script loaded: %s | anom_rev=%s", os.path.abspath(__file__), ANOM_SCAN_REV)
        if not _uinput_backend_enabled():
            startup_info("Input backend active: %s", input_backend)

        # ----- Setup Target Channel -----
        target_guild = discord.utils.get(self.guilds, id=guild_id)
        if target_guild is None:
            logging.error("Target guild not found.")
        else:
            # Prefer exact name match; fallback to substring for legacy channel naming.
            channel_tmp = discord.utils.find(
                lambda c: _channel_name_matches(c.name, target_channel_name),
                target_guild.text_channels,
            )
            if channel_tmp:
                self.target_channel_id = channel_tmp.id
                self.channel = self.get_channel(self.target_channel_id)
                logging.info(f"Target channel '{target_channel_name}' resolved to ID {self.target_channel_id}.")
            else:
                logging.error("Target channel not found.")

        # ----- Start Auxiliary Tasks -----
        self.queue_monitoring_task = asyncio.create_task(self.monitor_queue_size())
        if self.websocket_task is None or self.websocket_task.done():
            self.websocket_task = asyncio.create_task(self.websocket_connect())
            logging.info("WebSocket connection task started.")
        if self.heartbeat_task is None or self.heartbeat_task.done():
            self.heartbeat_task = asyncio.create_task(
                send_heartbeats(self.target_channel_name, self.target_channel_id)
            )
            logging.info("Heartbeat task started.")
        if _uinput_backend_enabled() and (self._uinput_warmup_task is None or self._uinput_warmup_task.done()):
            self._uinput_warmup_task = asyncio.create_task(self._warmup_uinput_backend())

        # ----- Setup Button for Contact Peep (only if designated) -----
        if contact_peep_switch == '1':
            button_view = self.create_button_view()
            self.add_view(button_view)  # Register the view with the client
            # then send or update your message with the view
            button_channel = self.get_channel(1325664432759640159)
            if button_channel:
                try:
                    if hasattr(self, 'button_message_id') and self.button_message_id:
                        existing_message = await button_channel.fetch_message(self.button_message_id)
                        await existing_message.edit(
                            content="Click once and wait 10 seconds...", view=button_view
                        )
                    else:
                        sent_message = await button_channel.send(
                            content="Click once and wait 10 seconds...", view=button_view
                        )
                        self.button_message_id = sent_message.id
                except discord.NotFound:
                    sent_message = await button_channel.send(
                        content="Click once and wait 10 seconds...", view=button_view
                    )
                    self.button_message_id = sent_message.id

    def create_button_view(self):
        """Helper method to create the button view."""
        view = discord.ui.View(timeout=None)
        load_button = MyClient.LoadContactsButton()
        view.add_item(load_button)
        return view

    async def button_refresh_loop(self, button_channel):
        """Periodically refresh the button message every 5 minutes."""
        while True:
            try:
                if self.button_message_id:
                    button_view = self.create_button_view()
                    existing_message = await button_channel.fetch_message(self.button_message_id)
                    await existing_message.edit(content="Click once and wait 10 seconds...", view=button_view)
                    logging.info(f"Button message refreshed in channel: {button_channel.name}")
            except Exception as e:
                logging.error(f"Error refreshing button message in loop: {e}")
            await asyncio.sleep(60 * 5)

    async def on_message(self, message):
        global pause_requested, resume_time, refuel_delay, scanning_active, refuel_switch, scanning_active
        global eyes_running, last_message_content, last_message_channel, channel_id, last_center_crop_pixel_count
        global num_worker_threads, target_channel_name, last_screenshot_button_crop_pixel_count, heartbeat_task
        global contact_peep_switch, contact_peep_delay
        start_time = time.time()  # Script start time
        run_duration_rate = 5  # How often (in seconds) to print the run duration
        run_duration_check = time.time()  # The initial check for runtime
        roles_to_trigger_screenshot = ['1267872006767120384', '1267911151425949749', '1267911341075857523']
        img_byte_arr_im = None

        last_message_content = ''
        last_message_channel = ''

        self.message = message  # Store the message for later use
        # print(f'content:{message.content}')

        # Check if bot is replying to self
        if message.author.id == self.user.id:
            return

        # Log all received messages
        print(f"Received message: '{message.content}' from '{message.author}' in channel '{message.channel.name}'")

        # Update global variables
        last_message_content = message.content
        last_message_channel = message.channel.name

        # Check if the channel name matches the target channel
        print(target_channel_name)
        if not _channel_name_matches(last_message_channel, target_channel_name):
            return

        # Command: !startscan
        if message.content.startswith('!startscan'):
            scanning_active = True
            await message.channel.send('Scanning for enemies started.')
            return

        # Command: !stopscan
        if message.content.startswith('!stopscan'):
            scanning_active = False
            await message.channel.send('Scanning for enemies stopped.')
            return

        if message.content.startswith('!rem'):
            # Extract the system name from the command
            system_to_remove = message.content.split('_')[1].strip()

            # Load the manifest
            try:
                with open('anom_manifest.json', 'r') as file:
                    anom_manifest = json.load(file)
            except FileNotFoundError:
                await message.channel.send("No manifest found.")
                return

            # Remove the system from the manifest
            anom_manifest = [entry for entry in anom_manifest if entry["system_name"] != system_to_remove]

            # Save the updated manifest
            with open('anom_manifest.json', 'w') as file:
                json.dump(anom_manifest, file, indent=4)

            # Update the embed
            await self.update_anomaly_embed(anom_manifest, channel_id=1291799816107589664,
                                            message_id=1291806724008706068)

            # Confirmation message
            await message.channel.send(f"System {system_to_remove} has been removed from the manifest and the embed.")

        # Command: !pause
        if message.content.startswith('!pause'):
            print("Detected !pause command")
            try:
                duration = int(message.content.split()[1])
                resume_time = datetime.now() + timedelta(seconds=duration)
                await message.channel.send(f'Pausing for {duration} seconds.')
            except (IndexError, ValueError):
                pause_requested = True
                await message.channel.send('Pausing until \'!resume\' command is received.')
            return

        # Command: !load
        if message.content.startswith('!load'):
            print("Detected !load command")
            contact_peep_delay = await self.contact_peep()
            await message.channel.send('Protocols will be initiated shortly..')
            return

        # Command: !refuel
        if message.content.startswith('!refuel'):
            print("Detected !refuel command")
            await message.channel.send('Refueling protocols will be initiated shortly..')
            refuel_delay = await self.refuel()
            return

        # Command: !resume
        if message.content.startswith('!resume'):
            print("Detected !resume command")
            pause_requested = False
            resume_time = None
            await message.channel.send('Resuming operations.')
            return

        # Command: !kill
        if message.content == '!kill' and _channel_name_matches(last_message_channel, target_channel_name):
            await message.channel.send(f'{target_channel_name} terminated.')
            exit()

        # Command: !killall
        if message.content == '!killall':
            await message.channel.send(f'{target_channel_name} terminated.')
            exit()

        if message.content == '!update':
            self.ship_categories, self.exclusions = load_data()
            self.exclusions = self.exclusions['exclusions']  # Extract the list from the dictionary
            await message.channel.send("Ship Manifest and Custom Exclusions updated successfully.")
            return

        if message.content.startswith('!uidebug'):
            cmd_text = str(message.content or "").strip()
            # Accept: !uidebug, !uidebug on/off/status/toggle
            match = re.match(r'^!uidebug(?:\s+(.+))?$', cmd_text, flags=re.IGNORECASE)
            mode = (match.group(1).strip().lower() if match and match.group(1) else 'status')

            if mode in ('on', '1', 'true', 'enable', 'enabled'):
                self.set_ui_debug(True)
            elif mode in ('off', '0', 'false', 'disable', 'disabled'):
                self.set_ui_debug(False)
            elif mode in ('toggle', 'flip'):
                self.set_ui_debug(not self.ui_debug_enabled)
            elif mode not in ('status',):
                await message.channel.send("Usage: !uidebug [on|off|status|toggle]")
                return

            detector_debug = bool(getattr(self.ui_detector, 'debug_enabled', False))
            status_text = self.ui_debug_status_text()
            detector_text = "ON" if detector_debug else "OFF"
            logging.info(
                "uidebug command processed: mode=%s status=%s detector=%s raw=%r",
                mode,
                status_text,
                detector_text,
                message.content,
            )
            await message.channel.send(f"UI debug is {status_text}. Detector debug is {detector_text}.")
            return

        if message.content.startswith('!coords'):
            parts = message.content.strip().split()
            # default: coordinate system used by most click() calls (cropped gameplay viewport)
            action_type = 0
            if len(parts) > 1 and parts[1].lower() in ('full', 'client', 'raw'):
                action_type = 1

            if not target_hwnd or not win32gui.IsWindow(target_hwnd):
                find_target_window()
            if not target_hwnd or not win32gui.IsWindow(target_hwnd):
                await message.channel.send("Could not find target window for coordinate capture.")
                return

            pos = get_mouse_base_position(target_hwnd, action_type=action_type)
            if not pos:
                await message.channel.send("Failed to read current mouse position.")
                return

            mode_txt = "full-client" if action_type != 0 else "viewport"
            await message.channel.send(
                f"[coords:{mode_txt}] base=({pos['base_x']}, {pos['base_y']}) "
                f"client=({pos['client_x']}, {pos['client_y']}) "
                f"inside={pos['inside_client']} client_size={pos['client_w']}x{pos['client_h']}"
            )
            return

        if message.content.startswith('!mapdebug'):
            parts = message.content.strip().split()
            sample_count = 1
            if len(parts) > 1:
                try:
                    sample_count = max(1, min(5, int(parts[1])))
                except ValueError:
                    await message.channel.send("Usage: !mapdebug [1-5]")
                    return

            lines = []
            for i in range(sample_count):
                frame = await self.ui_navigator.capture_frame()
                metrics = self.ui_detector.map_search_debug_metrics(frame)
                lines.append(
                    f"s{i + 1}: open={metrics['panel_open']} eye_closed={metrics['eye_closed_visible']} "
                    f"input_gray={metrics['input_gray']} magnifier={metrics['magnifier_bright']} "
                    f"edge={metrics['panel_edge']} eye_bright={metrics['eye_bright']} eye_dark={metrics['eye_dark']}"
                )
                if i + 1 < sample_count:
                    await asyncio.sleep(0.2)

            await message.channel.send("`" + "\n".join(lines) + "`")
            return

        if message.content.startswith('!anomdebug'):
            try:
                im, capture_source = await self.capture_scan_frame()
                if im is None:
                    await message.channel.send("`anomdebug: failed to capture screen`")
                    return

                arr = np.asarray(im.convert("RGB"), dtype=np.uint8)
                areas, icon_areas, peaks, profile, smooth, min_peak = _detect_anom_rows_from_icon_profile(
                    arr, row_count=5
                )
                if not areas:
                    areas = _build_anom_row_areas(im.width, im.height)
                    icon_areas = [_build_anom_icon_area_for_row(im.width, im.height, t, b) for _, t, _, b in areas]
                counts_legacy = [count_pixels_roi_arr(arr, *area, _ANOM_LEGACY_BOUNDS) for area in areas]

                counts_icon = []
                for icon_area in icon_areas:
                    counts_icon.append(_count_redish_pixels_roi_arr(arr, *icon_area))

                counts_combined = [max(l, i) for l, i in zip(counts_legacy, counts_icon)]
                hits = [i + 1 for i, c in enumerate(counts_combined) if c > 0]

                system_name = await self.get_system(im)
                lines = [
                    f"size={im.width}x{im.height} system={system_name} source={capture_source}",
                    f"legacy={counts_legacy}",
                    f"icon={counts_icon}",
                    f"combined={counts_combined} hits={hits}",
                    f"legacy_bounds={_ANOM_LEGACY_BOUNDS}",
                    f"red_bounds={_ANOM_RED_BOUNDS}",
                    f"peaks={peaks} min_peak={min_peak}",
                    f"profile_max={max(profile) if profile else 0} smooth_max={max(smooth) if smooth else 0}",
                    f"areas={areas}",
                    f"icon_areas={icon_areas}",
                ]
                await message.channel.send("`" + "\n".join(lines) + "`")
            except Exception as e:
                await message.channel.send(f"`anomdebug error: {e}`")
            return

        if message.content.startswith('!anomscan'):
            try:
                parts = message.content.strip().split()
                do_drag = True
                if len(parts) > 1 and parts[1].lower() in ("nodrag", "no-drag", "static"):
                    do_drag = False

                im, capture_source = await self.capture_scan_frame()
                if im is None:
                    await message.channel.send("`anomscan: failed to capture screen`")
                    return

                system_name = await self.get_system(im)
                if do_drag:
                    await self.drag_with_curve(
                        (random.randint(740, 890), random.randint(275, 315)),
                        (random.randint(780, 890), random.randint(5, 90)),
                        random.randint(5, 12),
                        random.randint(7, 30),
                    )
                    await delay(220, 380)
                    im, capture_source = await self.capture_scan_frame()
                    if im is None:
                        await message.channel.send("`anomscan: failed to capture post-drag screen`")
                        return

                arr = np.asarray(im.convert("RGB"), dtype=np.uint8)
                areas_raw, icon_areas_raw, peaks, profile, smooth, min_peak = _detect_anom_rows_from_icon_profile(
                    arr, row_count=5
                )
                if not areas_raw:
                    areas_raw = _build_anom_row_areas(im.width, im.height)
                    icon_areas_raw = [
                        _build_anom_icon_area_for_row(im.width, im.height, t, b) for _, t, _, b in areas_raw
                    ]

                legacy_raw = [count_pixels_roi_arr(arr, *area, _ANOM_LEGACY_BOUNDS) for area in areas_raw]
                icon_raw = []
                for icon_area in icon_areas_raw:
                    icon_raw.append(_count_redish_pixels_roi_arr(arr, *icon_area))
                counts_raw = [max(l, i) for l, i in zip(legacy_raw, icon_raw)]

                rows_bottom3 = list(zip(legacy_raw, icon_raw))[:3]
                panel_type, panel_norm, panel_area, panel_attempts, panel_dump_dir, panel_rows, panel_hits = await self.detect_checkpoint_from_image(
                    im,
                    debug_dump=True,
                    debug_tag=f"{self.target_channel_name}_{system_name or 'unknown'}"
                )

                hits_raw = [i + 1 for i, c in enumerate(counts_raw) if c > 0]
                lines = [
                    f"scan_rev={ANOM_SCAN_REV}",
                    f"system={system_name} drag={do_drag} size={im.width}x{im.height} source={capture_source}",
                    f"raw_legacy={legacy_raw} raw_icon={icon_raw} raw_counts={counts_raw} raw_hits={hits_raw}",
                    f"legacy_bounds={_ANOM_LEGACY_BOUNDS}",
                    f"red_bounds={_ANOM_RED_BOUNDS}",
                    f"peaks={peaks} min_peak={min_peak}",
                    f"profile_max={max(profile) if profile else 0} smooth_max={max(smooth) if smooth else 0}",
                    f"areas_raw={areas_raw}",
                    f"icon_areas_raw={icon_areas_raw}",
                    f"rows_bottom3_legacy_icon={rows_bottom3}",
                    f"panel_detect=type:{panel_type} text:{panel_norm!r} area:{panel_area}",
                    f"panel_row_results={panel_rows}",
                    f"panel_checkpoint_hits={panel_hits}",
                    f"panel_attempts={panel_attempts[:12]}",
                    f"panel_crop_dir={panel_dump_dir}",
                ]
                await message.channel.send("`" + "\n".join(lines) + "`")
            except Exception as e:
                await message.channel.send(f"`anomscan error: {e}`")
            return

        last_center_crop_pixel_count = 69

        if "_" in message.content:
            user = message.content.split('_')[1]
        else:
            user = message.author.name

        guild = self.get_guild(guild_id)
        print(f'Guild: {guild}')

        if guild:
            found_channel = None  # Add this to track if you found the channel
            for channel in guild.text_channels:  # Ensure you're checking text channels specifically
                if system.lower() in channel.name.lower():  # Ensure case-insensitive check
                    channel_id = channel.id
                    found_channel = channel  # Track found channel
                    break  # Break after finding the first matching channel

            if not found_channel:
                print("No matching channel found.")

        else:
            print("Guild not found.")

        def ocr_doctr(img, left_b, top_b, right_b, bottom_b, proc_num=0):
            global model
            try:
                # Adjust coordinates for the top bar height
                top_b_adjusted = top_b + top_bar_height
                bottom_b_adjusted = bottom_b + top_bar_height

                img = img.crop((left_b, top_b_adjusted, right_b, bottom_b_adjusted))  # Crop image first
                if proc_num == 1:
                    img = ImageOps.grayscale(img)  # Convert image to grayscale
                    img = img.point(lambda p: 255 if p > 175 else 0, '1')  # Apply thresholding
                    img = img.filter(ImageFilter.EDGE_ENHANCE_MORE)
                    img = img.convert('RGB')  # Convert back to 3-channel RGB after processing
                    img = img.filter(ImageFilter.GaussianBlur(.5))  # Apply slight Gaussian Blur

                img_np = np.array(img)  # Convert to numpy array

                # If the image is not already in RGB (3-channel), convert it
                if img_np.ndim == 2:  # If the image is grayscale, convert it to RGB
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_GRAY2RGB)

                # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2LAB)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                img_np[:, :, 0] = clahe.apply(img_np[:, :, 0])
                img_np = cv2.cvtColor(img_np, cv2.COLOR_LAB2RGB)

                # Perform OCR inference
                # start_time = time.time()
                result = model([img_np])
                # print("OCR Inference Time:", time.time() - start_time)

                # Extract and return the recognized text as a list
                words = [word for word, _ in result]
                return words  # Always return a list

            except Exception as e:
                print(f"Error during OCR: {e}")
                return None

        def print_run_duration():
            rd = time.time() - start_time
            days, remainder = divmod(rd, 86400)  # 86400 seconds in a day
            hours, remainder = divmod(remainder, 3600)  # 3600 seconds in an hour
            minutes, seconds = divmod(remainder, 60)  # 60 seconds in a minute

            if days > 0:
                duration_str = f"{int(days)} days, {int(hours)} hours, {int(minutes)} minutes, {int(seconds)} seconds"
            elif hours > 0:
                duration_str = f"{int(hours)} hours, {int(minutes)} minutes, {int(seconds)} seconds"
            elif minutes > 0:
                duration_str = f"{int(minutes)} minutes, {int(seconds)} seconds"
            else:
                duration_str = f"{int(seconds)} seconds"

            print("Run Duration:", duration_str)

        if message.content.startswith('!eyes'):
            # Replace with your actual seeker role ID (as an int or string)
            SEEKER_ROLE_ID = 1030481459108135003

            if not any(role.id == SEEKER_ROLE_ID for role in message.author.roles):
                await message.channel.send("Please contact staff for permission to use that command.")
                return

            if not self.eyes_running:
                self.eyes_running = True
                self.eyes_task = asyncio.create_task(self.eyes_logic(message))
                # await message.channel.send(f"{self.scout} - On it boss! o7")
            else:
                await message.channel.send("Eyes are already running.")
            return

        def send_seeker_status_message(target_channel, operation_hours=2):
            try:
                # Get the current time
                current_time = datetime.now()

                # Calculate the end time for the seeker, e.g., after `operation_hours` (default 2 hours)
                end_time = current_time + timedelta(hours=operation_hours)

                # Convert end_time to a Unix timestamp (seconds since epoch)
                unix_end_time = int(end_time.timestamp())

                # Format the relative time using Discord's dynamic timestamp format
                relative_time_left = f"<t:{unix_end_time}:R>"

                # Construct the dynamic message
                message_content = (
                    "Seeker is currently out of coms range. I will inform him to extend his operations.\n"
                    f"New end time: {relative_time_left}"
                )

                # Send the message to the provided channel
                target_channel.send(content=message_content)

            except Exception as e:
                print(f"Failed to send seeker status message: {e}")

        if message.content.startswith('!seek'):
            # await self.find_wasteseeker()
            # await self.close()
            # time.sleep(10)
            # Set the time limit for 2 hours (7200 seconds) from the current time
            additional_time = timedelta(hours=int(seeker_timer))

            if hasattr(self, 'seek_task') and self.seek_task and not self.seek_task.done():
                # If the task is already running, extend the time
                self.seek_end_time = datetime.now() + additional_time
                # await message.channel.send(f"Seeker is currently operational. Seeking renewed for {seeker_timer} hours. New end time: {self.seek_end_time.strftime('%Y-%m-%d %H:%M:%S')}")

                send_seeker_status_message(message.channel, operation_hours=2)
            else:
                # Start the seek task
                # List of possible replies
                replies = [
                    "On it. I'll dig up the intel and report back.",
                    "Manning the radar. o7",
                    "Blending in with the locals. I'll have something for you soon.",
                    "Intelligence gathering underway. I'll be in touch.",
                    "Going dark. You'll hear from me when I find something.",
                    "I'm headed in. Tell my girlfriend I love her! Tell my wife to eat a bag a' [connection lost..]",
                    "Off to work… and maybe dinner with a 'friend' after?",
                    "Slipping back into the shadows… hope the wife doesn't find my safe house again.",
                    "Another mission, another excuse to be out late. Let's find this intel.",
                    "If my wife asks, I'm 'working late'. Intel's coming soon.",
                    "Going undercover... don't tell the wife!",
                    "Deep undercover with a local source. You’ll get your intel.",
                    "Getting cozy with the locals. They always have the best stories, and... other things.",
                    "I'll, uh, get close to the locals for some... intel. You’ll have your report soon.",
                    "Huh? Oh! Yes, I'm on it! Please don't tell Nox I was sleepin', my ribs are still sore from the last performance review. :/",
                    "You do it!!! This hangover is killing me. Wait, sorry, don't tell Nox! I'm on it."
                ]

                # Select a random reply
                reply = random.choice(replies)

                # Send the selected reply
                await message.channel.send(reply)
                self.seek_end_time = datetime.now() + additional_time
                self.seek_task = asyncio.create_task(self.seek_logic())

        elif message.content.startswith('!stopseek'):
            # Cancel the seek task if it's running
            if hasattr(self, 'seek_task') and self.seek_task and not self.seek_task.done():
                self.seek_task.cancel()  # Cancel the running task
                await message.channel.send("Seek task stopped.")
            else:
                await message.channel.send("No seek task is currently running.")

        def grab_anom_types_and_list(anom_type_img, anom_max=5, ui_custom=0):
            def ocr_section_for_anom(ocr_section_img, anom_type_img, ocr_left, ocr_top, ocr_right, ocr_bottom,
                                     preproc=0,
                                     psm=8, threshold=75,
                                     whitelist='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                                     gaussian_b=0.5):
                try:
                    # Debugging statement before cropping
                    print("Before cropping:")
                    print(f"Image size: {ocr_section_img.size}")
                    print(f"Crop bounds: left={ocr_left}, top={ocr_top}, right={ocr_right}, bottom={ocr_bottom}")
                    print(f"Top bar height: {top_bar_height}")

                    # Cropping the image
                    crop_img = ocr_section_img.crop(
                        (ocr_left, ocr_top + top_bar_height, ocr_right, ocr_bottom + top_bar_height))

                    # Debugging statement after cropping
                    print("After cropping:")
                    print(f"Cropped image size: {crop_img.size}")

                    # Verify image integrity after cropping
                    try:
                        crop_img.verify()
                        print("Image after cropping is verified and intact.")
                    except Exception as e:
                        print(f"Error verifying cropped image: {e}")
                        return None

                    if preproc == 1:
                        crop_img = ImageOps.grayscale(crop_img)  # Convert to grayscale
                        crop_img = crop_img.resize((crop_img.width * 4, crop_img.height * 4),
                                                   resample=Image.Resampling.LANCZOS)  # Resize with LANCZOS filter
                        crop_img = crop_img.filter(ImageFilter.MedianFilter())  # Apply median filter
                        crop_img = crop_img.filter(ImageFilter.GaussianBlur(float(gaussian_b)))  # Apply Gaussian blur
                        crop_img = crop_img.point(lambda p: 0 if p > threshold else 255, 'L')  # Apply thresholding

                    # Converting image to string
                    extra_cfg = f" {TESS_DAWG_OFF_FLAGS}" if DISABLE_TESS_DAWGS_FOR_GAME_OCR else ""
                    ocr_result = pytesseract.image_to_string(
                        crop_img,
                        lang='echoes',
                        config=f"{tessdata_dir_config} --psm {psm}{extra_cfg} -c tessedit_char_whitelist={whitelist}",
                    )

                    crop_img.save(f'deleteme/{scout}_anom.png', format="png")

                    # Debugging statement after OCR
                    print(f"OCR Result: {ocr_result}")

                    return ocr_result

                except Exception as e:
                    print(f"Error during ocr_section_for_anom: {e}")
                    return None

            def ocr_cleanup_for_anom(ocr_dirty, *strip_strings):
                ocr_clean = ocr_dirty.replace('\n', "")
                for strip_string in strip_strings:
                    ocr_clean = ocr_clean.replace(strip_string, "")
                return ocr_clean

            def ocr_anom_nav_ui(nav_img, ui_position):
                y_top_step = 50 + ((ui_position - 1) * 52)
                y_bottom_step = 70 + ((ui_position - 1) * 52)
                ocr_position = str(
                    ocr_section_for_anom(nav_img, f'system_anomaly_{ui_position}', 804, y_top_step, 910, y_bottom_step,
                                         0, 8, 100,
                                         '123456789W0XAngelLargeFtRyMdiumScou'))
                # Ensure ocr_position is a string
                if not isinstance(ocr_position, str):
                    raise TypeError(f"Expected a string from ocr_section, but got {type(ocr_position)} instead.")
                ocr_clean = ocr_cleanup_for_anom(ocr_position, 'angel', 'Angel', '1gel', 'Ange', 'ange')
                return ocr_clean

            def filter_anomalies_for_anom(anomaly_list):
                filtered_list = []
                found_medium_or_small = False
                for anomaly in anomaly_list:
                    if found_medium_or_small and anomaly == "Large":
                        break
                    filtered_list.append(anomaly)
                    if anomaly in ["Medium", "Small"]:
                        found_medium_or_small = True
                return filtered_list

            def process_images_for_anom_concurrently(anom_type_img, anom_max, ui_custom):
                anom_type = [None] * anom_max
                with ThreadPoolExecutor() as executor:
                    future_to_index = {executor.submit(ocr_anom_nav_ui, anom_type_img, i + 1): i for i in
                                       range(anom_max)}
                    for future in as_completed(future_to_index):
                        result = future.result()
                        index = future_to_index[future]  # Ensures `index` is correctly assigned as an integer
                        anom_type[index] = result  # Now `index` should be an integer

                return filter_anomalies_for_anom(anom_type)

            def grab_anom_types(anom_type_img, anom_max=5, ui_custom=0):
                anom_type = process_images_for_anom_concurrently(anom_type_img, anom_max, ui_custom)
                return anom_type

            return grab_anom_types(anom_type_img, anom_max, ui_custom)

        # Additional supporting functions needed for self-containment

        coords_ap_ui = {'ap_1': (188, 225),
                        'ap_2': (188, 265),
                        'ap_3': (188, 300),
                        'ap_4': (188, 340),
                        'ap_5': (188, 375),
                        'ap_6': (188, 415),
                        'ap_7': (188, 450),
                        'ap_menu_init': (22, 148)}

        async def click_ap(ap_num, action_type=0, min_delay=876, max_delay=2212):
            # f'Tools/{pilot_name}_{filename}.png'
            await click(coords_ap_ui[f'ap_menu_init'][0], coords_ap_ui[f'ap_menu_init'][1], action_type, 15, 15,
                  ap_num)
            await delay(1500, 2500)
            await click(coords_ap_ui[f'ap_{ap_num}'][0], coords_ap_ui[f'ap_{ap_num}'][1], action_type, 15, 15,
                  ap_num)
            await delay(min_delay, max_delay)
            return

        print('yup')
        scanning_active = True
        '''
        while True:
            im, result = await self.async_pull_win()
            # print(f'Symbol present: {ap_status(im)}')

            for ui_pos in range(5):
                try:
                    y_top_step = 13 + ((ui_pos) * 52)
                    y_bottom_step = 25 + ((ui_pos) * 52)
                    enemy_list_cropped = enemy_list.crop((44, y_top_step, 55, y_bottom_step))
                    # print(count_pixels(enemy_list_cropped, 170, 255, 170, 255, 170, 255))
                    await asyncio.sleep(0.01)
                except Exception as e:
                    print(f"Error cropping enemy #{ui_pos + 1}. Error: {e}")
            time.sleep(90000)
        system_name = ocr_doctr(im, 86, 14, 200, 34)
        print(system_name[0])
        # print(symbol_present(im, im, ui_toggle, 677, 295, 700, 310, 0.4))
        # print(f'Line: {print_line_number()}')
        time.sleep(90000)


        im, result = await self.async_pull_win()
        if im is None or result != 1:
            print("Failed to capture image or the image is invalid")
            return
        open_anom_nav_ui(im)
        drag_with_curve((random.randint(740, 890), random.randint(275, 315)),
                        (random.randint(780, 890), random.randint(5, 90)),
                        random.randint(5, 12), random.randint(7, 30))
        time.sleep(.25)
        im = grab_screen()
        crop_img = im.crop((820, 555, 850, 556))
        crop_img2 = im.crop((877, 445, 905, 555))
        anom_pixl_cnt = count_pixels(crop_img, 140, 240, 140, 240, 165, 240)
        # crop_img2.save(f'deleteme/{scout}_anompix.png', format="png")
        print(anom_pixl_cnt)
        time.sleep(10000)

        grab_anom_types_and_list(im)
        '''

        if last_message_content == '!check' and _channel_name_matches(last_message_channel, target_channel_name):
            print("!check command received.")
            last_message_content = ''
            async with self.pull_win_lock:
                im, result = await self.async_pull_win()
                print(f"Image captured: {im}, Result: {result}")
            await self.send_image(im)

        if last_message_content == '!test' and _channel_name_matches(last_message_channel, target_channel_name):
            async with self.pull_win_lock:
                im, result = await self.async_pull_win()
            x_img = im.crop((437, 306, 570, 307))
            x_img.show()
            x_count = count_pixels(x_img, 190, 220, 150, 175, 90, 120)
            print(f'White Count: {x_count}')


    async def eyes_logic(self, message):
        try:
            # Declare globals first
            global current_enemy_list, detected_enemies, worksheet, last_message_content, last_center_crop_pixel_count, \
                last_screenshot_button_crop_pixel_count, refuel_delay, contact_peep_delay

            img_byte_arr_im = None
            self.eyes_running = True

            # Ensure the message is coming from the intended target channel
            if message.channel.id == guild_id or _channel_name_matches(message.channel.name, target_channel_name):  # Adjust for your target channel
                # await message.channel.send(f'Starting heartbeat to WebSocket server...')

                # Start sending heartbeats as a background task
                print(f'System is {system} and ChannelID is {message.channel.id}')
                # heartbeat_task_begin = self.loop.create_task(send_heartbeats(system, message.channel.id))
                print("Heartbeats have begun.")
            else:
                await message.channel.send(f"Command must be sent from the correct channel.")

            # Now you can send the message safely
            await message.channel.send(f'{system} - On it boss! o7')

            # self.heartbeat_task = asyncio.create_task(send_heartbeats(system, channel_id))
            print(f'Sent {system} and {channel_id}')
            worksheet = sh.worksheet("Log")

            asyncio.create_task(self.batch_processor())

            self.stitch_worker_task = asyncio.create_task(self.stitch_worker())  # Start the worker

            # Start the background enemy detection loop
            asyncio.create_task(self.background_enemy_detection())
            asyncio.create_task(self.process_enemy_queue())  # This processes the queue for detected enemies
            scanning_active = True

            # Initialize variables and settings
            watchlist_dict = {}
            self.eyes_running = True
            report_tot = 0
            client_check_delay_rate = 1
            client_check_delay = time.time() + client_check_delay_rate  # seconds

            # grab channel
            if target_channel_name and channel_id:
                channel_id_int = int(channel_id) if isinstance(channel_id, str) else channel_id
                channel = self.get_channel(channel_id_int)

            heartbeat_delay_rate = 5
            heartbeat_delay = time.time() + heartbeat_delay_rate  # seconds

            client_check_freeze_rate = 10
            client_check_freeze = time.time() + client_check_freeze_rate  # seconds

            scan_delay_rate = 2
            scan_delay = time.time() + scan_delay_rate  # seconds

            start_time = time.time()  # Script start time
            inplace_duration_rate = max(1, int(UPTIME_STATUS_INPLACE_PERIOD_SECONDS))
            inplace_duration_check = time.time()  # The initial check for in-place console uptime reporting
            run_duration_rate = max(1, int(UPTIME_STATUS_PERIOD_SECONDS))
            run_duration_check = time.time()  # The initial check for console uptime reporting
            title_duration_rate = max(1, int(UPTIME_TITLE_PERIOD_SECONDS))
            title_duration_check = time.time()  # The initial check for title uptime reporting

            while True:
                try:
                    # Check if we need to pause or kill the process
                    # print(f"Debug eyes_logic loop: type(datetime) inside loop = {type(datetime)}")
                    if pause_requested or (isinstance(resume_time, datetime) and datetime.now() < resume_time):
                        await asyncio.sleep(1)
                        continue

                    if last_message_content == '!kill':
                        await message.channel.send(f'{target_channel_name} terminated.')
                        await self.close()

                    def to_unix_timestamp(dt):
                        return int(dt.timestamp())

                    # NOTE: Do not consume self.enemy_queue here.
                    # self.process_enemy_queue() is the single consumer responsible for OCR + reporting + batching.

                    now = time.time()

                    # Timer logic for uptime reporting without flooding the console.
                    if UPTIME_STATUS_TO_CONSOLE_INPLACE and (now > inplace_duration_check + inplace_duration_rate):
                        _write_status_line(f"Uptime: {_format_uptime(now - start_time)}")
                        inplace_duration_check = now

                    if UPTIME_STATUS_TO_TITLE and (now > title_duration_check + title_duration_rate):
                        _set_console_title(f"Eyes - Uptime {_format_uptime(now - start_time)}")
                        title_duration_check = now

                    if UPTIME_STATUS_TO_CONSOLE and (now > run_duration_check + run_duration_rate):
                        logging.info("Uptime: %s", _format_uptime(now - start_time))
                        run_duration_check = now

                        def get_gdi_handle_count():
                            user32 = ctypes.WinDLL('user32', use_last_error=True)
                            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

                            # Define the GetCurrentProcess function
                            GetCurrentProcess = kernel32.GetCurrentProcess
                            GetCurrentProcess.restype = wintypes.HANDLE

                            # Define the GetGuiResources function
                            GetGuiResources = user32.GetGuiResources
                            GetGuiResources.restype = wintypes.DWORD
                            GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]

                            # Obtain a handle to the current process
                            hProcess = GetCurrentProcess()

                            # Retrieve the count of GDI objects
                            count = GetGuiResources(hProcess, 0)  # 0 for GDI objects, 1 for USER objects

                            return count

                        # print(f"Current GDI handle count: {get_gdi_handle_count()}")

                    # Client checking routines
                    if time.time() > client_check_delay and not client_busy:
                        if time.time() > client_check_freeze:
                            async with self.pull_win_lock:
                                im, result = await self.async_pull_win()
                            im_arr = np.asarray(im.convert("RGB"), dtype=np.uint8)
                            teal_count = count_pixels_roi_arr(
                                im_arr, 75, 270, 110, 300, (120, 130, 145, 160, 130, 150)
                            )
                            await asyncio.sleep(0.5)
                            center_crop_pixel_count = count_pixels_roi_arr(
                                im_arr, 455, 245, 505, 295, (50, 255, 50, 255, 50, 255)
                            )
                            screenshot_button_crop_pixel_count = count_pixels_roi_arr(
                                im_arr, 380, 485, 390, 500, (130, 255, 130, 255, 130, 255)
                            )
                            if center_crop_pixel_count == last_center_crop_pixel_count:
                                warning_msg = f'{system} scout appears to have frozen.'
                                print(f'center_crop_pixel_count: {center_crop_pixel_count}')
                                print(f'last_center_crop_pixel_count: {last_center_crop_pixel_count}')
                                print(f'Center Check: {center_crop_pixel_count == last_center_crop_pixel_count}')
                                try:
                                    await check_channel_name(message, target_channel_name, warning_msg)
                                except Exception as e:
                                    logging.error(f'An error occurred while sending warning message: {e}')
                                try:
                                    img_byte_arr_im = save_image_in_memory(im)
                                    img_byte_arr_im.seek(0)  # Ensure the BytesIO object is at the start
                                except Exception as e:
                                    logging.error(f'An error occurred while saving image to memory: {e}')
                                try:
                                    await check_channel_name(message, target_channel_name, None, img_byte_arr_im)
                                except Exception as e:
                                    logging.error(f'An error occurred while sending image to Discord: {e}')
                                while center_crop_pixel_count == last_center_crop_pixel_count:
                                    try:
                                        center_crop_temp, result = await self.async_pull_win()
                                        center_crop_temp_arr = np.asarray(center_crop_temp.convert("RGB"), dtype=np.uint8)
                                        center_crop_pixel_count = count_pixels_roi_arr(
                                            center_crop_temp_arr, 455, 245, 505, 295, (75, 255, 75, 255, 75, 255)
                                        )
                                        await asyncio.sleep(1)
                                    except Exception as e:
                                        logging.error(f'An error occurred: {e}')
                                last_center_crop_pixel_count = center_crop_pixel_count
                                warning_msg = f'Client repair detected, resuming watch.'
                                try:
                                    await check_channel_name(message, target_channel_name, warning_msg)
                                except Exception as e:
                                    logging.error(f'An error occurred: {e}')

                                client_check_freeze = time.time() + client_check_freeze_rate

                            if station_bound == '1' and screenshot_button_crop_pixel_count != last_screenshot_button_crop_pixel_count:
                                # Skip the remaining part of this if chain, but don't skip the whole loop
                                pass
                            else:
                                if screenshot_button_crop_pixel_count != last_screenshot_button_crop_pixel_count:
                                    warning_msg = f'{system} scout appears to have frozen.'
                                    print(f'Screenshot Button: {screenshot_button_crop_pixel_count}')
                                    print(f'Last Scr Button: {last_screenshot_button_crop_pixel_count}')
                                    try:
                                        await check_channel_name(message, target_channel_name, warning_msg)
                                    except Exception as e:
                                        logging.error(f'An error occurred: {e}')
                                    try:
                                        img_byte_arr_im = save_image_in_memory(im)
                                        img_byte_arr_im.seek(0)  # Ensure the BytesIO object is at the start
                                    except Exception as e:
                                        logging.error(f'An error occurred while saving image to memory: {e}')
                                    try:
                                        await check_channel_name(message, target_channel_name, None, img_byte_arr_im)
                                    except Exception as e:
                                        logging.error(f'An error occurred while sending image to Discord: {e}')
                                    while screenshot_button_crop_pixel_count != last_screenshot_button_crop_pixel_count:
                                        try:
                                            screenshot_button_crop_temp, result = await self.async_pull_win()
                                            screenshot_button_crop_temp_arr = np.asarray(
                                                screenshot_button_crop_temp.convert("RGB"), dtype=np.uint8
                                            )
                                            screenshot_button_crop_pixel_count = count_pixels_roi_arr(
                                                screenshot_button_crop_temp_arr, 380, 485, 390, 500,
                                                (130, 255, 130, 255, 130, 255)
                                            )
                                            await asyncio.sleep(1)
                                        except Exception as e:
                                            logging.error(f'An error occurred: {e}')
                                    last_screenshot_button_crop_pixel_count = screenshot_button_crop_pixel_count
                                    warning_msg = f'Client repair detected, resuming watch.'
                                    try:
                                        await check_channel_name(message, target_channel_name, warning_msg)
                                    except Exception as e:
                                        logging.error(f'An error occurred: {e}')

                                    client_check_freeze = time.time() + client_check_freeze_rate

                        client_check_delay = time.time() + client_check_delay_rate

                    if time.time() > refuel_delay and refuel_switch == '1':
                        refuel_delay = await self.refuel()

                    if time.time() > contact_peep_delay and contact_peep_switch == '1':
                        contact_peep_delay = await self.contact_peep()

                    await asyncio.sleep(0.25)
                except Exception as sub_loop_error:
                    logging.error(f'An error occurred: {sub_loop_error}')
                    raise sub_loop_error
        except Exception as main_loop_error:
            logging.exception("Exception in eyes_logic main loop:")
            # Re-raise the exception to stop the script and show the error in the console
            raise main_loop_error  # <--- Re-raise the exception to halt execution
        except asyncio.CancelledError:
            print("Eyes task was cancelled.")
        finally:
            self.eyes_running = False

    async def pull_win_overlays(self, scout):
        hwnd = win32gui.FindWindow(None, scout)
        if hwnd == 0:
            print(f"Window with title '{scout}' not found.")
            return None, None

        _ensure_process_dpi_aware()
        # Ensure the target window is in the foreground
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)  # Restore if minimized
        win32gui.SetForegroundWindow(hwnd)

        # Get window rect
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            print(f"Invalid overlay window dimensions: {width}x{height}")
            return None, None

        try:
            bmpinfo, bmpstr = _overlay_blt_capture_ctx.capture(left, top, width, height)
        except Exception:
            # One best-effort reset/retry if cached GDI objects became stale.
            _overlay_blt_capture_ctx.reset()
            try:
                bmpinfo, bmpstr = _overlay_blt_capture_ctx.capture(left, top, width, height)
            except Exception as capture_error:
                logging.error("pull_win_overlays capture failed after context reset: %s", capture_error)
                return None, None

        img = Image.frombuffer(
            'RGB',
            (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
            bmpstr, 'raw', 'BGRX', 0, 1
        )

        return img, None

# Send heartbeats with connection verification and detailed logging
async def send_heartbeats(sys_id, chan_id):
    print(f"Starting heartbeat task for system: {sys_id}, channel: {chan_id}")

    while True:  # Keep trying to connect indefinitely
        try:
            async with websockets.connect(EC2_WEBSOCKET_URL) as websocket:
                logging.info(f"WebSocket connection established with server for system {sys_id}.")

                # Send heartbeats in a loop
                while True:
                    try:
                        heartbeat_data = {
                            "type": 'heartbeat',
                            "system": sys_id,
                            "timestamp": time.time(),
                            "channel_id": chan_id
                        }
                        await websocket.send(json.dumps(heartbeat_data))
                        # print(f"Heartbeat sent: {heartbeat_data}")
                        await asyncio.sleep(3)  # Adjust the interval as needed

                    except websockets.ConnectionClosed as e:
                        # If the connection is closed, log the error and retry connection
                        logging.error(f"WebSocket connection closed: {e}. Reconnecting...")
                        break  # Break the inner loop to retry connection

                    except Exception as e:
                        # Log other exceptions but don't break the outer loop
                        logging.error(f"Error sending heartbeat: {e}")
                        await asyncio.sleep(5)  # Retry sending after a delay

        except Exception as e:
            # Log connection attempt failure and retry after a delay
            logging.error(f"Failed to connect to WebSocket server: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)  # Wait before trying to reconnect


# Main function to run both the heartbeat task and the Discord bot
async def main():
    global instance_mutex_handle
    instance_mutex_handle = try_acquire_instance_mutex_nonblocking()
    if not instance_mutex_handle:
        logging.error("Another '%s' instance is already running. Exiting to prevent duplicate reporting.", script_filename)
        return

    intents = discord.Intents.default()  # Create default intents
    intents.messages = True  # Ensure message intents are enabled
    intents.message_content = True  # Needed for bots to read message content
    intents.guilds = True  # Enable guild-related events

    client = MyClient(intents=intents)  # Pass intents to the client

    try:
        # Start the Discord bot
        await client.start(discord_bot_token)
    except KeyboardInterrupt:
        print("Shutting down gracefully...")
    finally:
        # If needed, clean up the heartbeat task
        if hasattr(client, 'heartbeat_task') and client.heartbeat_task:
            client.heartbeat_task.cancel()
            await client.heartbeat_task
        release_instance_mutex(instance_mutex_handle)
        instance_mutex_handle = None


# Run the main function
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down gracefully...")
