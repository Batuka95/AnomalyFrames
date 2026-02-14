import inspect
import pyautogui
from ctypes import windll
from PIL import Image, ImageFilter, ImageOps
from PIL import ImageOps
import win32gui, win32ui, win32con, win32api
import ctypes
from ctypes import wintypes
import pytesseract
import random
import time
import cv2
import sys
import os
from playsound import playsound
from pynput import mouse
import tkinter as tk
import pyperclip
import pygetwindow
from pygetwindow import PyGetWindowException
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import math
import threading
import hashlib
import io
from threading import Lock

# settings
pilot_name = 'PILOT'
top_bar_height = 35

# init variables
first_pass = 0
global first_approach
global first_anom
first_approach = 0
first_anom = 0
save_img_lock = Lock()
screen_capture_lock = Lock()

# Uses the ctypes library to load the user32.dll dynamic-link library
user32 = ctypes.WinDLL('user32')
# Define PrintWindow signature
PrintWindow = user32.PrintWindow
PrintWindow.restype = wintypes.BOOL
PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]

# Tesseract OCR
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

coords_nav_ui = {'nav_1': (830, 65),
                 'nav_2': (830, 117),
                 'nav_3': (830, 169),
                 'nav_4': (830, 221),
                 'nav_5': (830, 273),
                 'nav_6': (830, 325),
                 'nav_7': (830, 377),
                 'nav_8': (830, 429),
                 'nav_9': (830, 481),
                 'nav_page_select': (800, 15),
                 'nav_page_enemy': (807, 199),
                 'nav_page_anomalies': (818, 254)}

coords_module_ui = {'module_1': (650, 435),
                    'module_2': (705, 435),
                    'module_3': (760, 435),
                    'module_4': (815, 435),
                    'module_5': (870, 435),
                    'module_6': (925, 435),
                    'module_7': (650, 495),
                    'module_8': (705, 495),
                    'module_9': (760, 495),
                    'module_10': (815, 495),
                    'module_11': (870, 495),
                    'module_12': (925, 495)}

coords_anom_vacant = {'nav_1': (613, 203, 675, 218),
                      'nav_2': (613, 255, 675, 270),
                      'nav_3': (613, 306, 675, 321),
                      'nav_4': (613, 358, 675, 373),
                      'nav_5': (613, 410, 675, 425),
                      'nav_6': (613, 462, 675, 477),
                      'nav_7': (613, 516, 675, 531),
                      'nav_8': (613, 516, 675, 531),
                      'nav_9': (612, 516, 675, 531)}

coords_enemy_ui = {'nav_1': (600, 203, 675, 218),
                   'nav_2': (613, 255, 675, 270),
                   'nav_3': (613, 306, 675, 321),
                   'nav_4': (613, 358, 675, 373),
                   'nav_5': (613, 410, 675, 425),
                   'nav_6': (613, 462, 675, 477),
                   'nav_7': (613, 516, 675, 531),
                   'nav_8': (613, 516, 675, 531),
                   'nav_9': (612, 516, 675, 531)}


def print_line_number():
    current_frame = inspect.currentframe()
    calling_frame = inspect.getouterframes(current_frame, 2)
    line_number = calling_frame[1].lineno
    print(f"Line number: {line_number}")


def get_scaling_factor(hwnd):
    # Define the function from user32.dll for DPI
    user32 = ctypes.WinDLL('user32')
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT
    # Get the DPI for the window
    dpi = user32.GetDpiForWindow(hwnd)
    return dpi / 96.0


def resize_window():
    win2find = f'({pilot_name})'
    hwnd = win32gui.FindWindow(None, win2find)
    if not (hwnd == 0):
        scaling_factor = get_scaling_factor(hwnd)  # Get scaling factor for DPI
        new_width = int(820 * scaling_factor)
        new_height = int(510 * scaling_factor)
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, new_width, new_height, 0)


# Crops a screen section and return OCR result
def ocr_section(ocr_section_img, filename, ocr_left, ocr_top, ocr_right, ocr_bottom, preproc=0, psm=8, threshold=75,
                whitelist='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', gaussian_b=0.5):
    # Crop the image
    crop_img = ocr_section_img.crop((ocr_left, ocr_top + top_bar_height, ocr_right, ocr_bottom + top_bar_height))
    # print(preproc)
    # crop_img.save(f'Tools/{pilot_name}_{filename}.png', format="png")
    # crop_img.show
    if preproc == 2:
        # crop_img.save(f'Tools/{pilot_name}_{filename}.png', format="png")
        return count_pixels(crop_img, 100, 120, 100, 130, 95, 130) > 0

    if preproc == 3:
        # crop_img.save(f'Tools/{pilot_name}_{filename}.png', format="png")
        if count_pixels(crop_img, 95, 140, 100, 180, 95, 180) > 0:
            return 2
        else:
            return 'web'

    if preproc == 1:
        '''
        # Convert the image to grayscale
        crop_img = crop_img.convert('L')

        # Apply threshold (you might need to adjust the threshold value)
        threshold_value = 120  # This is an example value; adjust as needed
        crop_img = crop_img.point(lambda x: 250 if x > threshold_value else 0, '1')

        # Invert colors to black text on white background
        crop_img = crop_img.point(lambda x: 0 if x else 1, '1')
        '''

        # Check if enemy is selected and adjust thresholding if needed
        if count_pixels(crop_img, 55, 65, 32, 45, 28, 40) > 0:
            threshold += 40  #it likes 45 and 41

        # skip if not enemy
        if count_pixels(crop_img, 15, 70, 17, 45, 12, 45) == 0 and filename != 'enemy_count':
            # print(f'kicked back {filename}')
            return None

        # Add whitespace to left side of image
        # Covert PIL to numpy
        crop_img_np = np.array(crop_img)
        # Create a white columns array
        white_columns_np = 0 * np.ones((crop_img_np.shape[0], 1, 3), dtype=np.uint8)
        # Concatenate the white columns to the original image
        modified_image_np = np.concatenate((white_columns_np, crop_img_np, white_columns_np), axis=1)
        # Convert back to a PIL image (if needed for saving or further processing)
        crop_img = Image.fromarray(modified_image_np)

        crop_img = ImageOps.grayscale(crop_img)  # Convert to grayscale
        crop_img = crop_img.resize((crop_img.width * 4, crop_img.height * 4), Image.ANTIALIAS)  # Resize image
        crop_img = crop_img.filter(ImageFilter.MedianFilter())  # Apply a median filter for noise reduction
        crop_img = crop_img.filter(ImageFilter.GaussianBlur(float(gaussian_b)))  # Apply a Gaussian Blur to identify 5's in particular
        crop_img = crop_img.point(lambda p: 0 if p > threshold else 255, 'L')  # Apply threshold
        # crop_img = crop_img.point(lambda x: 0 if x else 1, '1')  # Invert colors to black text on white background

    # Save the cropped image
    # crop_img.save(f'Tools/{pilot_name}_{filename}.png', format="png")

    # Open Image
    # crop_img.show()
    # sys.exit()

    # OCR the image
    ocr_result = pytesseract.image_to_string(crop_img, lang='eng', config=f'--psm {psm} -c tessedit_char_whitelist'
                                                                          f'={whitelist}')
    return ocr_result


# Crops a screen section and returns img without saving to file
def grab_img(g_img, filename, crop_left, crop_top, crop_right, crop_bottom):
    # print('Grab Image')
    '''
    # Get the width and height of the image
    width, height = g_img.size

    # Calculate the pixel values of the crop region
    left = int(width - crop_left)
    upper = int(height - crop_top)
    right = int(width * crop_right)
    lower = int(height * crop_bottom)
    '''

    # Crop the image
    crop_img = g_img.crop((crop_left, crop_top + top_bar_height, crop_right, crop_bottom + top_bar_height))

    # Save the cropped image
    # crop_img.save(f'Tools/{pilot_name}_{filename}.png', format="png")

    # Open Image
    # crop_img.show()
    return crop_img


# Crops a screen section and saves the result as image file
def save_img(s_img, filename, left_bound, upper_bound, right_bound, lower_bound):
    global save_img_lock  # Make sure to declare the lock as global if it's defined outside the function

    # Crop the image first, outside of the locked section to minimize locked time
    crop_img = s_img.crop((left_bound, upper_bound + top_bar_height, right_bound, lower_bound + top_bar_height))

    with save_img_lock:
        # The file saving operation is now protected by the lock
        crop_img.save(f'Tools/{pilot_name}_{filename}.png', format="png")

    return crop_img


def symbol_present(compare_img, filename, search_image_path, symbol_image_path, left_bound, top_bound, right_bound,
                   bottom_bound, tolerance=0.3):
    save_img(compare_img, filename, left_bound, top_bound, right_bound, bottom_bound)

    # Load the images
    symbol_img = cv2.imread(search_image_path)
    search_img = cv2.imread(symbol_image_path)

    # Convert the images to grayscale
    symbol_gray = cv2.cvtColor(symbol_img, cv2.COLOR_BGR2GRAY)
    search_gray = cv2.cvtColor(search_img, cv2.COLOR_BGR2GRAY)

    # Apply thresholding to the images
    symbol_thresh = cv2.threshold(symbol_gray, 127, 255, cv2.THRESH_BINARY)[1]
    search_thresh = cv2.threshold(search_gray, 127, 255, cv2.THRESH_BINARY)[1]

    # Compare the thresholded images for matches
    match = cv2.matchTemplate(search_thresh, symbol_thresh, cv2.TM_CCOEFF_NORMED)[0][0]

    # print(f'match: {match}')

    # Map tolerance to match threshold range (0.9 to 0.5)
    # Assuming tolerance ranges from 0 (strict) to 1000 (lenient)
    # match_threshold = 0.9 - (tolerance / 1000) * 0.4  # This maps tolerance 300 to a threshold of 0.78
    # print(f'match_thresh: {tolerance}')

    # Check if the match value is above the calculated threshold
    if match > tolerance:
        return True
    else:
        return False


def ocr_cleanup(ocr_dirty, *strip_strings):
    # print_line_number()
    ocr_clean = ocr_dirty.replace('\n', "")
    for strip_string in strip_strings:
        ocr_clean = ocr_clean.replace(strip_string, "")
    if ocr_clean == 'artel' or ocr_clean == 'artal' or ocr_clean == 'arte' or ocr_clean == 'Cartel':
        ocr_clean = 'Base'
    if ocr_clean == 'lerge' or ocr_clean == 'large' or ocr_clean == 'Lrge':
        ocr_clean = 'Large'
    if ocr_clean == 'Meiu' or ocr_clean == 'meiu' or ocr_clean == 'Meu' or ocr_clean == 'meu' or ocr_clean == \
            'ingelMedium' or ocr_clean == 'Mediumn' or ocr_clean == 'AnnelMadinm' or ocr_clean == 'Mediurmn' \
            or ocr_clean == 'Mediur' or ocr_clean == 'Mediurn' or ocr_clean == 'ngelMedium':
        ocr_clean = 'Medium'
    if ocr_clean == 'nguiitar':
        ocr_clean = 'Inquisitor'
    if ocr_clean == 'ingelmall' or ocr_clean == 'mall' or ocr_clean == 'ngelmeall' or ocr_clean == 'AnnelSmall':
        ocr_clean = 'Small'
    if ocr_clean == 'eaut' or ocr_clean == 'eut':
        ocr_clean = 'Scout'
    if ocr_clean == 'ngelFleetRally':
        ocr_clean = 'Rally'
    if ocr_clean == 'GistMaglstrom':
        ocr_clean = 'Maelstrom'
    if ocr_clean == 'Tempesti':
        ocr_clean = 'Tempest Striker'
    if ocr_clean == 'GistTyphoonI1':
        ocr_clean = 'Typhoon'
    # print(f'ocr_clean: {ocr_clean}')
    if ocr_clean.startswith('Hou'):
        ocr_clean = 'Hound'
    if ocr_clean.startswith('Thra'):
        ocr_clean = 'Thrasher'
    if ocr_clean.startswith('Sla') or ocr_clean.startswith('Sas'):
        ocr_clean = 'Slasher'
    # print(f'ocr_clean: {ocr_clean}')
    if ocr_clean.startswith('Pr'):
        ocr_clean = 'Probe'
    if ocr_clean.startswith('Sa'):
        ocr_clean = 'Inquisitor'
    if ocr_clean.startswith('imS') or ocr_clean.startswith('mSt'):
        ocr_clean = 'Stabber'
    if ocr_clean.startswith('imBe') or ocr_clean.startswith('mBe'):
        ocr_clean = 'Bellicose'
    if ocr_clean.startswith('ngelaital') or ocr_clean.startswith('aital'):
        ocr_clean = 'Capital Quarry'
    if ocr_clean.startswith('Ta'):
        ocr_clean = 'Talwar'
    if ocr_clean.startswith('mScy') or ocr_clean.startswith('Scy'):
        ocr_clean = 'Scythe'
    if ocr_clean.startswith('mTh') or ocr_clean.startswith('Thr'):
        ocr_clean = 'Thrasher'
    if ocr_clean.startswith('imRu') or ocr_clean.startswith('Rupt'):
        ocr_clean = 'Rupture'
    return ocr_clean


def ocr_nav_ui(nav_img, ui_position):
    # print_line_number()
    ocr_position = f'system_anomaly_{ui_position}'
    y_top_step = 50 + ((ui_position - 1) * 52)
    y_bottom_step = 70 + ((ui_position - 1) * 52)
    # ocr_position = str(ocr_section(img, ocr_position, 0.782, y_top_step, 0.88, y_bottom_step))
    ocr_position = str(
        ocr_section(nav_img, ocr_position, 804, y_top_step, 910, y_bottom_step, 0, 8, 100,
                    '123456789W0XAngelLargeFtRyMdiumScou'))
    ocr_clean = ocr_cleanup(ocr_position, 'angel', 'Angel', '1gel', 'Ange', 'ange')
    return ocr_clean


def ocr_enemy_ui(nav_img, ui_position):
    # print_line_number()
    ocr_position = f'system_anomaly_{ui_position}'
    y_top_step = 50 + ((ui_position - 1) * 52)
    y_bottom_step = 75 + ((ui_position - 1) * 52)
    # ocr_position = str(ocr_section(img, ocr_position, 0.782, y_top_step, 0.88, y_bottom_step))
    ocr_position = str(
        ocr_section(nav_img, ocr_position, 824, y_top_step, 910, y_bottom_step))
    ocr_position = ocr_position.replace('\n', '')
    frig_list = ocr_cleanup(ocr_position, 'angel', 'Angel', '1gel', 'Ange', 'ange')
    # print(f'here: {frig_list}')
    frig_list = frig_list in ['Prove', 'Probe', 'Talwarll', 'HoundIIF', 'Prope', 'Hound', 'Slasher', 'Tawar',
                              'iSlasherll', 'Thrasher', 'Stabber', 'Bellicose', 'Talwar', 'Scythe', 'Thrasher',
                              'Rupture', 'Prae']
    return ocr_position, frig_list


def ocr_enemy_distance(nav_img, ui_position):
    # print_line_number()
    ocr_position = f'system_anomaly_{ui_position}'
    y_top_step = 50 + ((ui_position - 1) * 52)
    y_bottom_step = 70 + ((ui_position - 1) * 52)
    # ocr_position = str(ocr_section(img, ocr_position, 0.782, y_top_step, 0.88, y_bottom_step))
    # You may need to change the thresh from 30 back to 40
    ocr_position_dst = str(
        ocr_section(nav_img, ocr_position, 765, y_top_step, 792, y_bottom_step, 1, 8, 30, '0123456789', 0.0))
    ocr_position_dst = ocr_position_dst.replace('\n', '')

    valid_digits = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']

    if ocr_position_dst in valid_digits:
        ocr_position_dst = None

    if not ocr_position_dst:
        ocr_position_dst = str(
            ocr_section(nav_img, ocr_position, 765, y_top_step, 792, y_bottom_step, 1, 6, 10, '0123456789', 0.0))

    if ocr_position_dst in valid_digits:
        print('ding2')
        ocr_position_dst = None

    if not ocr_position_dst:
        ocr_position_dst = str(
            ocr_section(nav_img, ocr_position, 765, y_top_step, 792, y_bottom_step, 1, 8, 50, '0123456789', 0.0))

    if ocr_position_dst == '1':
        ocr_position_dst = str(
            ocr_section(nav_img, ocr_position, 765, y_top_step, 792, y_bottom_step, 1, 8, 80, '0123456789', 0.0))
    ocr_clean = ocr_cleanup(ocr_position_dst, 'angel', 'Angel', '1gel', 'Ange', 'ange')
    return ocr_clean


def ocr_enemy_distance_alternative(nav_img, ui_position):
    # print_line_number()
    ocr_position = f'system_anomaly_{ui_position}'
    y_top_step = 50 + ((ui_position - 1) * 52)
    y_bottom_step = 70 + ((ui_position - 1) * 52)
    # ocr_position = str(ocr_section(img, ocr_position, 0.782, y_top_step, 0.88, y_bottom_step))
    # You may need to change the thresh from 30 back to 40
    ocr_position_dst = (ocr_section(nav_img, ocr_position, 782, y_top_step, 790, y_bottom_step, 2, 8, 25, '0123456789', 0.0))
    if ocr_position_dst:
        ocr_position_dst = str(
                    ocr_section(nav_img, ocr_position, 775, y_top_step, 783, y_bottom_step, 3, 8, 35, '0123456789', 0.0))
    if ocr_position_dst == '2':
        ocr_position_dst = str(
                    ocr_section(nav_img, ocr_position, 775, y_top_step, 783, y_bottom_step, 1, 8, 25, '0123456789', 0.0))

    if not ocr_position_dst:
        ocr_position_dst = str(
                    ocr_section(nav_img, ocr_position, 775, y_top_step, 783, y_bottom_step, 1, 6, 35, '0123456789', 0.0))

    if not ocr_position_dst:
        ocr_position_dst = str(
                    ocr_section(nav_img, ocr_position, 775, y_top_step, 783, y_bottom_step, 1, 6, 15, '0123456789', 0.0))

    ocr_position_dst = ocr_position_dst.replace('\n', '')
    ocr_position_dst = str(ui_position) + ': ' + ocr_position_dst

    valid_digits = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']

    '''
    if ocr_position_dst in valid_digits:
        ocr_position_dst = None

    if not ocr_position_dst:
        ocr_position_dst = str(
            ocr_section(nav_img, ocr_position, 765, y_top_step, 792, y_bottom_step, 1, 6, 10, '0123456789', 0.0))

    if ocr_position_dst in valid_digits:
        print('ding2')
        ocr_position_dst = None

    if not ocr_position_dst:
        ocr_position_dst = str(
            ocr_section(nav_img, ocr_position, 765, y_top_step, 792, y_bottom_step, 1, 8, 50, '0123456789', 0.0))

    if ocr_position_dst == '1':
        ocr_position_dst = str(
            ocr_section(nav_img, ocr_position, 765, y_top_step, 792, y_bottom_step, 1, 8, 80, '0123456789', 0.0))
    '''
    ocr_clean = ocr_cleanup(ocr_position_dst, 'angel', 'Angel', '1gel', 'Ange', 'ange')
    return ocr_clean


def count_pixels(count_img, r1, r2, g1, g2, b1, b2):
    # print('Count Pixels')
    # Convert image to RGB mode
    count_img = count_img.convert('RGB')

    # Define the RGB ranges to match
    red_range = range(r1, r2)
    green_range = range(g1, g2)
    blue_range = range(b1, b2)

    # Initialize count variable
    count = 0

    # Loop through pixels in the image
    for pixel in count_img.getdata():
        # Get the RGB values of the current pixel
        r, g, b = pixel

        # Check if the pixel matches the color range
        if r in red_range and g in green_range and b in blue_range:
            count += 1

    # Return count of matching pixels
    # print(count)
    return count


def grab_screen():
    global screen_capture_lock  # Not necessary unless you're assigning a new value to the lock

    with screen_capture_lock:
        win2find = f'{pilot_name}'  # Assuming 'pilot_name' is defined elsewhere in your script
        for attempt in range(3):
            hwndDC, mfcDC, saveDC, saveBitMap = None, None, None, None
            try:
                hwnd = win32gui.FindWindow(None, win2find)
                if hwnd == 0:
                    print(f"Window with title '{win2find}' not found!")
                    continue

                x0, y0, x1, y1 = win32gui.GetWindowRect(hwnd)
                w, h = x1 - x0, y1 - y0
                if w <= 0 or h <= 0:
                    print(f"Invalid window dimensions: {w}x{h}")
                    continue

                hwndDC = win32gui.GetWindowDC(hwnd)
                mfcDC = win32ui.CreateDCFromHandle(hwndDC)
                saveDC = mfcDC.CreateCompatibleDC()
                saveBitMap = win32ui.CreateBitmap()
                saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
                saveDC.SelectObject(saveBitMap)

                # Use ctypes to call PrintWindow
                result = PrintWindow(hwnd, saveDC.GetSafeHdc(), 0)

                if not result:  # PrintWindow Failed
                    print("PrintWindow failed")
                    continue

                bmpinfo = saveBitMap.GetInfo()
                bmpstr = saveBitMap.GetBitmapBits(True)
                img = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRX', 0, 1)
                return img
            except Exception as e:
                print(f"Screen capture failed on attempt {attempt + 1}: {e}")
                time.sleep(0.2)
            finally:
                # Cleanup
                if saveBitMap:
                    try:
                        win32gui.DeleteObject(saveBitMap.GetHandle())
                    except Exception as e:
                        print(f"Failed to delete saveBitMap: {e}")
                if saveDC:
                    try:
                        saveDC.DeleteDC()
                    except Exception as e:
                        print(f"Failed to delete saveDC: {e}")
                if mfcDC:
                    try:
                        mfcDC.DeleteDC()
                    except Exception as e:
                        print(f"Failed to delete mfcDC: {e}")
                if hwndDC:
                    try:
                        win32gui.ReleaseDC(hwnd, hwndDC)
                    except Exception as e:
                        print(f"Failed to release hwndDC: {e}")

        print("Failed to capture screen after multiple attempts.")
        return None


# Click
# action_type 0:None, 1:Approach, 2:Warp 3:? 4:Focus Fire 5:Lock
def click(x_position, y_position, action_type=0, x_variance=5, y_variance=5, index=1):
    try:
        # Find the pilot window and activate it
        # print(f'Click: {x_position}, {y_position}')
        pilot_window = pyautogui.getWindowsWithTitle(f'{pilot_name}')[0]
        pilot_window.activate()

        # Get the coordinates of the window
        window_x, window_y = pilot_window.topleft

        # Calculate the coordinates relative to the window
        x = window_x + x_position
        y = window_y + y_position

        # Add offset for Top Bar
        y = y + top_bar_height

        # Add offset for action types
        if action_type == 1:
            if index == 8:
                x -= 160
                y -= 45
            elif index == 9:
                x -= 160
                y -= 100
            else:
                x -= 160

        if action_type == 2:
            if index == 8:
                x -= 160
                y += 15
            elif index == 9:
                x -= 160
                y -= 40
            else:
                x -= 160
                y += 60

        if action_type == 3:
            x -= 160
            y += 160

        if action_type == 4:
            if index == 5:
                x -= 160
                y += 175
            elif index == 6:
                x -= 160
                y += 125
            elif index == 7:
                x -= 160
                y += 75
            elif index == 8:
                x -= 160
                y += 25
            elif index == 9:
                x -= 160
                y -= 25
            else:
                x -= 160
                y += 175

        if action_type == 5:
            if index == 6:
                x -= 160
                y -= 50
            elif index == 7:
                x -= 160
                y -= 100
            elif index == 8:
                x -= 160
                y -= 150
            elif index == 9:
                x -= 160
                y -= 200
            else:
                x -= 160

        # Adjust coordinates for randomized clicking
        x += random.randint(-x_variance, x_variance)
        y += random.randint(-y_variance, y_variance)

        # Move the cursor to the same coordinates
        # pyautogui.moveTo(x, y)

        # Disable the pyautogui failsafe feature
        pyautogui.FAILSAFE = False

        pilot_window = pyautogui.getWindowsWithTitle(f'{pilot_name}')[0]
        pilot_window.activate()

        # Simulate a left mouse click at the specified location (x, y)
        (initial_x, initial_y) = pyautogui.position()
        pyautogui.click(x=x, y=y, clicks=1, interval=0, button='left')
        # return cursor to original position
        pyautogui.moveTo(initial_x, initial_y)
    except PyGetWindowException:
        print(f'pyget exception at {print_line_number()}')
    return


def calculate_control_point(start_point, end_point, offset_distance, bend_direction=1):
    # Calculate the midpoint
    midpoint = ((start_point[0] + end_point[0]) / 2, (start_point[1] + end_point[1]) / 2)

    # Calculate the slope of the line between start and end points
    dx = end_point[0] - start_point[0]
    dy = end_point[1] - start_point[1]

    # Calculate the direction of the perpendicular
    if dx == 0:
        perp_direction = (1, 0)
    else:
        slope = dy / dx
        perp_slope = -1 / slope
        perp_direction = (1, perp_slope)

    # Normalize the perpendicular direction
    norm = np.sqrt(perp_direction[0] ** 2 + perp_direction[1] ** 2)
    perp_direction_normalized = (perp_direction[0] / norm, perp_direction[1] / norm)

    # Adjust the direction of the offset based on the specified bend direction
    offset_multiplier = -1 if bend_direction == 1 else 1

    # Calculate the control point by applying the offset
    control_point = (midpoint[0] + perp_direction_normalized[0] * offset_distance * offset_multiplier,
                     midpoint[1] + perp_direction_normalized[1] * offset_distance * offset_multiplier)

    return control_point


def calculate_bezier_point(t, start_point, control_point, end_point):
    """Calculate a point on a quadratic Bezier curve."""
    x = (1 - t) ** 2 * start_point[0] + 2 * (1 - t) * t * control_point[0] + t ** 2 * end_point[0]
    y = (1 - t) ** 2 * start_point[1] + 2 * (1 - t) * t * control_point[1] + t ** 2 * end_point[1]
    return x, y


def drag_with_curve(start_point, end_point, steps=30, curve_factor=5):
    # init
    adjusted_start_point = [0, 0]
    adjusted_end_point = [0, 0]

    # Find the pilot window and activate it
    # print(f'Click: {x_position}, {y_position}')
    pilot_window = pyautogui.getWindowsWithTitle(f'{pilot_name}')[0]
    pilot_window.activate()

    # Get the coordinates of the window
    window_x, window_y = pilot_window.topleft

    # Calculate the coordinates relative to the window
    adjusted_start_point[0] = window_x + start_point[0]
    adjusted_start_point[1] = window_y + start_point[1]
    adjusted_end_point[0] = window_x + end_point[0]
    adjusted_end_point[1] = window_y + end_point[1]

    # Add offset for Top Bar
    adjusted_start_point[1] += top_bar_height
    adjusted_end_point[1] += top_bar_height

    control_point = calculate_control_point(adjusted_start_point, adjusted_end_point, curve_factor,
                                            random.randint(1, 2))

    """Perform a drag operation along a quadratic Bezier curve."""
    pyautogui.mouseDown(adjusted_start_point[0], adjusted_start_point[1], button='left')

    for t in np.linspace(0, 1, steps):
        point = calculate_bezier_point(t, adjusted_start_point, control_point, adjusted_end_point)
        pyautogui.moveTo(point[0], point[1], duration=0.01)  # Small duration for smoother movement

    pyautogui.mouseUp(button='left')
    delay(230, 375)
    return


def delay(min_time=100, max_time=400):
    """
    Pauses the execution of the program for a random amount of time between min_time and max_time (in milliseconds).
    If no input is provided, the default range is between 100ms and 300ms.
    """
    random_delay = random.randint(min_time, max_time) / 1000
    time.sleep(random_delay)


def open_nav():
    # Open Nav UI
    click(924, 299)
    # print('Opening nav')


def close_nav():
    # Close Nav UI
    click(690, 301)


def click_nav(nav_num, action_type=0, min_delay=876, max_delay=2212):
    # f'Tools/{pilot_name}_{filename}.png'
    click(coords_nav_ui[f'nav_{nav_num}'][0], coords_nav_ui[f'nav_{nav_num}'][1], action_type, 5, 5, nav_num)
    delay(min_delay, max_delay)


def grab_click_nav_coords(nav_num, action_type=0):
    # Initially create click_nav_coords as a list for mutability
    click_nav_coords = [coords_nav_ui[f'nav_{nav_num}'][0], coords_nav_ui[f'nav_{nav_num}'][1], action_type, 5, 5,
                        nav_num]
    # Adjust coordinates for randomized clicking
    click_nav_coords[0] += random.randint(-5, 5)
    click_nav_coords[1] += random.randint(-5, 5)
    if nav_num == 8:
        click_nav_coords[0] -= 160
        click_nav_coords[1] += 15
    elif nav_num == 9:
        click_nav_coords[0] -= 160
        click_nav_coords[1] -= 40
    else:
        click_nav_coords[0] -= 160
        click_nav_coords[1] += 60

    # print(f'click_nav_coords: {click_nav_coords}')

    return click_nav_coords


def click_module(module, action_type=0):
    # f'Tools/{pilot_name}_{filename}.png'
    click(coords_module_ui[f'{module}'][0], coords_module_ui[f'{module}'][1], action_type)
    delay(276, 999)


def click_autolock():
    click(600, 339)
    delay(220, 700)
    return


# Check if AutoLock available
def grab_auto_lock(auto_lock_img):
    auto_locker_check = symbol_present(auto_lock_img, 'carrot', 'Tools/carrot.png', f'Tools/{pilot_name}_carrot.png',
                                       589, 330, 611, 355)
    # print(f'Carrot match: {auto_locker_check}')
    # auto_locker_check = not auto_locker_check
    # print(f'Not auto_locker_check: {auto_locker_check}')
    if not auto_locker_check:
        return auto_locker_check
    auto_locker_check = grab_img(img, 'autolock image', 590, 330, 612, 355)
    # quick_check.save(f'Tools/{pilot_name}_quick_check.png', format="png")
    auto_locker_check = count_pixels(auto_locker_check, 120, 132, 135, 150, 130, 140)
    auto_locker_check = auto_locker_check > 0
    # print(f'auto_locker_check2: {auto_locker_check}')
    return auto_locker_check


def scan_enemy_ui(scan_img):
    scan_img = grab_img(scan_img, 'none', 607, 25, 685, 45)
    # scan_img.save(f'Tools/{pilot_name}_enemy_ui.png', format="png")
    enemy_status = count_pixels(scan_img, 39, 40, 15, 23, 11, 19)
    if enemy_status > 0:
        enemy_status = True
    else:
        enemy_status = False
    return enemy_status


# check velocity for warp
def scan_approach_velocity(velocity_img):
    global first_approach
    if first_approach == 0:
        time.sleep(6)
        first_approach = 1
    velocity_img = grab_img(grab_screen(), 'none', 504, 486, 507, 490)
    approach_speed = count_pixels(velocity_img, 50, 60, 100, 210, 195, 220)
    approach_speed = approach_speed > 0
    return approach_speed


def grab_siege(scan_img):
    scan_img = grab_img(scan_img, 'none', 898, 470, 950, 518)
    siege_status = count_pixels(scan_img, 90, 120, 140, 185, 120, 175)
    # print(f'Siege Status: {siege_status}')
    siege_status = siege_status > 0
    return siege_status


def grab_web(web_img, mod_num):
    if mod_num == 3:
        web_left = 750
        web_right = 785
    if mod_num == 4:
        web_left = 793
        web_right = 838
    if mod_num == 5:
        web_left = 850
        web_right = 895

    web_img = grab_img(web_img, 'none', web_left, 415, web_right, 460)
    web_status = count_pixels(web_img, 130, 140, 195, 205, 175, 185)
    # print(f'Siege Status: {siege_status}')
    web_status = web_status > 0
    return web_status


def grab_fca_1(fca_1_img):
    fca_1_img = grab_img(fca_1_img, 'none', 785, 410, 807, 425)
    fca_1_status = count_pixels(fca_1_img, 90, 120, 140, 185, 120, 175)
    fca_1_status = fca_1_status > 0
    return fca_1_status


def grab_fca_2(fca_2_img):
    fca_2_img = grab_img(fca_2_img, 'none', 842, 410, 860, 425)
    fca_2_status = count_pixels(fca_2_img, 90, 120, 140, 185, 120, 175)
    fca_2_status = fca_2_status > 0
    return fca_2_status


def grab_fca_3(fca_3_img):
    fca_3_img = grab_img(fca_3_img, 'none', 895, 410, 915, 425)
    fca_3_status = count_pixels(fca_3_img, 90, 120, 140, 185, 120, 175)
    fca_3_status = fca_3_status > 0
    return fca_3_status


def grab_battery(battery_img):
    battery_img = grab_img(battery_img, 'none', 625, 468, 675, 518)
    # battery_img.show()
    battery_status = count_pixels(battery_img, 130, 175, 130, 175, 130, 175)
    if battery_status > 0:
        battery_status = False
    else:
        battery_status = True
    return battery_status


def backup_grab_enemy(bak_enemy_img):
    bak_enemy_img = grab_img(bak_enemy_img, bak_enemy_img, 728, 54, 750, 75)
    # bak_enemy_img.show()
    # bak_enemy_img.save(f'Tools/{pilot_name}_bak_check.png', format="png")
    bak_status = count_pixels(bak_enemy_img, 100, 150, 20, 30, 30, 50)
    # print(bak_status)
    bak_status = bak_status > 0
    return bak_status


# open/close nav ui to refresh list
def refresh_nav_ui(ui_open_check_img):
    ui_open_check = symbol_present(ui_open_check_img, 'ui_toggle', 'Tools/ui_toggle.png',
                                   f'Tools/{pilot_name}_ui_toggle.png', 680, 295, 700, 306)
    # save_img(ui_open_check_img, 'test', 680, 295, 700, 306)
    # print(f'UI Symbol Present: {ui_open_check}')

    break_check = False
    while not break_check:
        if ui_open_check:
            close_nav()
            delay(1000, 2193)
            open_nav()
            delay(1500, 2193)
        else:
            open_nav()
            delay(1500, 2193)

        # Confirm Nav open
        ui_open_check = symbol_present(grab_screen(), 'ui_toggle', 'Tools/ui_toggle.png',
                                       f'Tools/{pilot_name}_ui_toggle.png', 680, 295, 700, 306)
        # print(f'Nav Open: {ui_open_check}')
        if ui_open_check:
            break_check = True
    return ui_open_check


# open nav ui if closed
def open_nav_ui(ui_open_check_img):
    ui_open_check = symbol_present(ui_open_check_img, 'ui_toggle', 'Tools/ui_toggle.png',
                                   f'Tools/{pilot_name}_ui_toggle.png', 680, 295, 700, 306, 0.4)
    # print(f'UI Symbol Present: {ui_open_check}')

    break_check = False
    while not break_check and not ui_open_check:
        open_nav()
        delay(1500, 2193)

        # Confirm Nav open
        ui_open_check = symbol_present(grab_screen(), 'ui_toggle', 'Tools/ui_toggle.png',
                                       f'Tools/{pilot_name}_ui_toggle.png', 680, 295, 700, 306)
        # print(f'Nav Open: {ui_open_check}')
        if ui_open_check:
            break_check = True
    return ui_open_check


# Drags the Nav/Enemy UI down a little to expand it
def expand_ui():
    drag_with_curve((820, 115), (840, 216), random.randint(2, 5), random.randint(4, 15))
    delay(250, 300)
    return


# Get shield status
def grab_health():
    # 5 = 5% damage
    # 20 = 10%
    # 45 = 20%
    # 60 = 25%
    # 72 = 30%
    # 125 = 50%
    health_img = grab_img(img, 'shield', 428, 415, 510, 505)
    health = count_pixels(health_img, 100, 127, 19, 23, 19, 23)
    # print(pilot_damage)
    return health


def process_image(proc_img, i, ui_custom):
    frig_list = None  # Default value for frig_list in case it's not set by ui_custom == 1
    try:
        if ui_custom == 0:
            ocr_result = ocr_nav_ui(proc_img, i + 1)
            # Filter anomalies and return, with None for frig_list since it's not applicable here
            return i, filter_anomalies([ocr_result])[0] if ocr_result else None, None
        elif ui_custom == 1:
            ocr_result, frig_list = ocr_enemy_ui(proc_img, i + 1)
            # Filter anomalies if ocr_result is not None, else return None; frig_list is returned as-is
            return i, filter_anomalies([ocr_result])[0] if ocr_result else None, frig_list
        elif ui_custom == 2:
            ocr_result = ocr_enemy_distance(proc_img, i + 1)
            # Filter anomalies and return, with None for frig_list since it's not applicable here
            return i, filter_anomalies([ocr_result])[0] if ocr_result else None, None
        elif ui_custom == 3:
            ocr_result = ocr_enemy_distance_alternative(proc_img, i + 1)
            # Filter anomalies and return, with None for frig_list since it's not applicable here
            return i, filter_anomalies([ocr_result])[0] if ocr_result else None, None
    except Exception as e:
        print(f'Error processing image at index {i}: {e}')
        # Return index with None for both ocr_result and frig_list if an exception occurs
        return i, None, None

    # If for some reason the try block completes without returning (should not happen in this structure),
    # return None for both ocr_result and frig_list. This line is more for completeness and clarity.
    return i, None, frig_list


def process_images_concurrently(anom_type_img, anom_max, ui_custom):
    anom_type = [None] * anom_max
    positive_hit = [None] * anom_max
    with ThreadPoolExecutor() as executor:
        # Schedule the processing of each image
        future_to_index = {executor.submit(process_image, anom_type_img, i, ui_custom): i for i in range(anom_max)}

        # Collect results as they complete
        for future in as_completed(future_to_index):
            index, result, frig_hit = future.result()
            anom_type[index] = result
            positive_hit[index] = frig_hit
    # print(anom_type)
    # Check if the lists contain results before unpacking
    if any(anom_type) or any(positive_hit):  # Check if there's at least one non-None value
        filtered_anom_type, filtered_positive_hit = zip(*[(result, frig) for result, frig in zip(anom_type, positive_hit) if result is not None])
    else:
        # Handle the case where both lists are empty or contain only None values
        filtered_anom_type, filtered_positive_hit = [], []  # Set to empty lists or other default values as appropriate
    return list(filtered_anom_type), list(filtered_positive_hit)


# Check the type of Anoms in UI
def grab_anom_types(anom_type_img, anom_max=5, ui_custom=0):
    anom_type, frig_list = process_images_concurrently(anom_type_img, anom_max, ui_custom)
    return anom_type, frig_list


def grab_enemy_present(enemy_present_img):
    enemy_img = grab_img(enemy_present_img, 'enemy image', 665, 25, 685, 50)
    # enemy_img.save(f'Tools/{pilot_name}_enemy_check.png', format="png")
    enemy_pres = count_pixels(enemy_img, 140, 180, 25, 50, 45, 75)
    # print(enemy_pres)
    # print(f'Enemy Present: {enemy_pres}')
    enemy_pres = enemy_pres > 0
    return enemy_pres


def filter_anomalies(anomaly_list):
    filtered_list = []  # List to store the filtered anomalies
    found_medium_or_small = False  # Flag to track if "Medium" or "Small" has been found

    for anomaly in anomaly_list:
        if found_medium_or_small and anomaly == "Large":
            break  # Stop adding to the list once a "Large" is found after "Medium" or "Small"
        filtered_list.append(anomaly)
        if anomaly in ["Medium", "Small"]:
            found_medium_or_small = True  # Set flag once "Medium" or "Small" is encountered

    return filtered_list


# function to read the previously selected index from the file
def read_previous_anom_type():
    try:
        with open('Tools/anomaly_switch.txt', 'r') as f:
            index = f.read().strip()
            return index
    except FileNotFoundError:
        return None


def anom_alarm():
    # warning_alarm = 'warning2.mp3'
    # warning_path = os.path.join(os.getcwd(), 'Tools', warning_alarm)
    # playsound(warning_path)
    return


def grab_enemy_list_ocr():
    # Check what enemies are available
    enemy_ocr_result = filter_anomalies(grab_anom_types(grab_screen(), 9, 1))
    # print(enemy_ocr_result)
    return enemy_ocr_result


def grab_next_anom():
    global first_anom
    specials_list = ('Rally', 'Quarry', 'Scout', 'Capital Quarry', 'Inquisitor')

    # read the previously selected index from the file
    previous_anom_type = read_previous_anom_type()
    print(f'Previous Anom Type: {previous_anom_type}')
# IT FAILED TO CHANGE THE PAGE SELECT
    # focus window
    pilot_window2 = pyautogui.getWindowsWithTitle(f'{pilot_name}')[0]
    pilot_window2.activate()
    # Set page to Anomalies
    click_nav('page_select', 0, 851, 987)
    # delay(454, 978)
    click_nav('page_anomalies', 0, 350, 650)
    # delay(700, 900)
    expand_ui()

    # Check what anomalies are available
    anomaly_data = filter_anomalies(grab_anom_types(grab_screen(), 9, 0))
    anomaly_result = anomaly_data[0]  # Use the first list which contains anomaly types
    print(anomaly_result)

    if any(special in anomaly_result for special in specials_list):
        anom_alarm()

    preferred_order = ["Small", "Medium", "Large"]
    selection_order = []

    for pref_anom in preferred_order:
        skipped_first_occurrence = False
        for i, anom in enumerate(anomaly_result):  # Here, anomaly_result is already the correct list
            # print(f'anom_{i + 1}:{anom}')
            if anom == previous_anom_type and not skipped_first_occurrence and first_anom != 0:
                # print(f'Skipping first {previous_anom_type}...')
                skipped_first_occurrence = True  # Skip the first occurrence
                continue
            if anom == pref_anom:
                selection_order.append(i + 1)  # Use 1-based indexing

    first_anom = 1

    if not anomaly_result or not selection_order:
        print("No anomalies found.")
        anom_alarm()
        return []

    return anomaly_result, selection_order


def travel(nav_action=0):
    travel_img = grab_screen()
    # siege = grab_siege(travel_img)
    enemy_found = grab_enemy_present(travel_img)

    # exit if enemy present
    if enemy_found and nav_action == 1:
        return

    stop_distance_cycle[0] = True

    # Check siege mode and disable if needed
    siege = grab_siege(grab_screen())
    if siege and nav_action == 1:
        click_module('module_12')
        delay(350, 930)
        '''
        # wait for siege cooldown
        while siege:
            print(f'Siege = {siege}')
            click_module('module_12')
            delay(2500, 3000)
            siege = grab_siege(grab_screen())
            if siege:
                print('Waiting for siege cooldown.')
                delay(4870, 7800)
                siege = grab_siege(grab_screen())
        '''

    next_anom_types, next_anom_list = grab_next_anom()
    print(f'Anom Priority: {next_anom_list}')

    for anomaly_index in next_anom_list:
        # refresh_nav_ui(grab_screen())
        expand_ui()
        click_nav(anomaly_index, 0, 516, 876)

        nav_key = f'nav_{anomaly_index}'  # Construct the key for the dictionary
        coords = coords_anom_vacant[nav_key]  # Access the tuple from the dictionary
        vacant = (ocr_cleanup(ocr_section(grab_screen(), f'test', coords[0], coords[1], coords[2], coords[3], 0, 8, 100,
                                          '123456789W0XAngelLargeFtRyMdiumScou')))
        if vacant:
            break

    if nav_action == 0:
        click_nav(anomaly_index, 1, 516, 876)
        # Set page to Enemies
        click_nav('page_select', 0, 454, 987)
        click_nav('page_enemy', 0, 1100, 1350)
        click(300, 76)
        return

    # Click to warp
    warp_at_range_coords = (grab_click_nav_coords(anomaly_index))
    warp_at_range_coords = warp_at_range_coords[:2]

    # Generate a random angle in radians
    angle = random.uniform(0, 2 * math.pi)

    radius = 225  # Distance from the center point

    # Calculate the x and y coordinates of the point on the circumference
    curve_endpoint_x = warp_at_range_coords[0] + radius * math.cos(angle)
    curve_endpoint_y = warp_at_range_coords[1] + radius * math.sin(angle)

    # print(f"The end point is: ({curve_endpoint_x}, {curve_endpoint_y})")
    drag_with_curve((warp_at_range_coords[0], warp_at_range_coords[1]), (curve_endpoint_x, curve_endpoint_y),
                    5, random.randint(40, 125))

    # Set page to Enemies
    click_nav('page_select', 0, 454, 987)
    click_nav('page_enemy', 0, 1100, 1350)

    # save the anomaly type to file
    with open('Tools/anomaly_switch.txt', 'w') as f:
        write_index = next_anom_types[anomaly_index - 1]
        # if write_index > previous_anom_type:
        # write_index -= 1anomaly_result
        f.write(str(write_index))

    # Check enemy list to signal landing
    print('Waiting to Land...')
    img_landing = grab_screen()
    backup_enemy_check_status = backup_grab_enemy(img_landing)
    grab_enemy_status = grab_enemy_present(img_landing)
    while not backup_enemy_check_status and not grab_enemy_status:
        time.sleep(3)
        img_landing = grab_screen()
        backup_enemy_check_status = backup_grab_enemy(img_landing)
        grab_enemy_status = grab_enemy_present(img_landing)
        # print(f'bak_status: {backup_enemy_check_status}')
        # print(f'grab_enemy_status: {grab_enemy_status}')

    # wait for autolock
    # time.sleep(22)

    # start anomaly timer for pre-approach
    if next_anom_types[anomaly_index - 1] == 'Small':
        travel_anomaly_timer = time.time() + 60 * 3
    elif next_anom_types[anomaly_index - 1] == 'Medium':
        travel_anomaly_timer = time.time() + 60 * 8
    else:
        travel_anomaly_timer = time.time() + 60 * 13

    # Check siege mode and disable if needed
    '''
    siege = grab_siege(grab_screen())
    while not siege:
        click_module('module_12')
        siege = grab_siege(grab_screen())
        # print(f'Siege = {siege}')
        time.sleep(1)
    click_module('module_9')
    click_module('module_10')
    click_module('module_11')
    '''
    print('Entering Combat')
    return travel_anomaly_timer


# The enemy count subroutine
def enemy_cnt_cycle():
    def cycle_counter():
        last_enemy_cnt_internal = 0
        while True:
            if kill_switch[0]:
                return
            cnt_img = grab_screen()
            enemy_cnt[0] = grab_enemy_cnt(cnt_img)
            if last_enemy_cnt_internal > 1 and enemy_cnt[0] < last_enemy_cnt_internal - 1:
                enemy_cnt[0] = last_enemy_cnt_internal
            time.sleep(0.2)

    # Start the cycle in a separate thread to allow parallel operations
    threading.Thread(target=cycle_counter).start()


def heatsink_cycle(frig_lock):
    heatsink_ids = [8, 9, 10, 11]  # Module IDs for the heatsinks
    runtime = 22  # Runtime in seconds
    heatsink_cooldown = 176  # Cooldown in seconds
    # Ensure cooldown_ends matches the length of heatsink_ids
    cooldown_ends = [0] * len(heatsink_ids)  # Now correctly supports any number of heatsinks

    def cycle_heatsinks():
        while True:
            if kill_switch[0]:
                return
            current_t = time.time()
            for index, heatsink_id in enumerate(heatsink_ids):
                if frig_lock[0] == 1:  # Check if frig_lock is activated
                    if current_t >= cooldown_ends[index]:  # Check if the heatsink's cooldown has finished
                        click_module(f'module_{heatsink_id}')  # Activate the heatsink
                        time.sleep(runtime)  # Wait for the runtime
                        cooldown_ends[index] = current_t + heatsink_cooldown  # Update cooldown end time
                    else:
                        # Wait for this heatsink's cooldown to finish if necessary
                        time.sleep(max(cooldown_ends[index] - current_t, 0))
                else:
                    # If frig_lock is off, wait until it's back on
                    while frig_lock[0] == 0 and not kill_switch[0]:
                        time.sleep(1)

    # Start the cycle in a separate thread to allow parallel operations
    threading.Thread(target=cycle_heatsinks).start()


def enemy_distance_cycle():
    def cycle_distance():
        print_timer = time.time()
        print('Starting distance checking..')
        while True:
            if kill_switch[0] or stop_distance_cycle[0] is True:
                return
            img3 = grab_screen()
            enemy_distance, frig_list = process_images_concurrently(img3, 5, 3)
            print(f'enemy_distance: {enemy_distance}')

            web_index = None
            for index, distance in enumerate(enemy_distance):
                if 'web' in distance:
                    web_index = index + 1  # Correctly calculate the index considering 'web' as part of a larger string
                    break  # Exit the loop once 'web' is found

            if web_index is not None:
                print('Attempting to target close enemy...')
                if web_index > 5:
                    expand_ui()
                click_nav(web_index, 0, 300, 600)
                click_nav(web_index, 4, 350, 800)
                if grab_siege(img3):
                    click_module('module_12')
                    delay(150, 250)
                # NEED TO CODE WEB SUB
                if not grab_web(img3, 3):
                    click_module('module_3')
                    delay(250, 500)
                if not grab_web(img3, 4):
                    click_module('module_4')
                    delay(250, 500)
                if not grab_web(img3, 5):
                    click_module('module_5')
                    delay(250, 500)
                print(f'Initiated webs..')
                enemy_check = enemy_cnt[0]
                frig_trigger = time.time()
                while enemy_check == enemy_cnt[0]:
                    if frig_trigger + 12 < time.time():
                        frig_lock[0] = 0
                        break
                    time.sleep(1)

            '''
            # Filter and find indices of all items less than 12, ignoring None values
            indices_less_than_12 = []
            for index, value in enumerate(enemy_distance):
                try:
                    int_value = int(value) if value is not None else None
                    if int_value is not None and int_value < 12:
                        indices_less_than_12.append(index + 1)
                except ValueError:
                    print_line_number()
                    pass

            # Filter and find indices of all items less than 60, ignoring None values
            indices_less_than_60 = []
            for index, value in enumerate(enemy_distance):
                try:
                    int_value = int(value) if value is not None else None
                    if int_value is not None and int_value < 60:
                        indices_less_than_60.append(index + 1)
                except ValueError:
                    print_line_number()
                    pass

            
            if time.time() > print_timer + 5:
                print(f'indices_less_than_x: {indices_less_than_x}')
                print_timer = time.time()
            
            img3 = grab_screen()
            # print(indices_less_than_12)
            # Check if the list of indices is not empty and print the indices
            if indices_less_than_12 and 1 == 2:
                print(f'indices_less_than_12: {indices_less_than_12}')
                for index in indices_less_than_12:
                    print('Attempting to target close enemy...')
                    if index > 5:
                        expand_ui()
                    click_nav(index, 0, 300, 600)
                    enemy_distance, frig_list = process_images_concurrently(grab_screen(), 5, 2)
                    if int(enemy_distance[index]) < 12:
                        click_nav(index, 4, 350, 800)
                        if grab_siege(img3):
                            click_module('module_12')
                            delay(150, 250)
                        # NEED TO CODE WEB SUB
                        if not grab_web(img3, 3):
                            click_module('module_3')
                            delay(250, 500)
                        if not grab_web(img3, 4):
                            click_module('module_4')
                            delay(250, 500)
                        if not grab_web(img3, 5):
                            click_module('module_5')
                            delay(250, 500)
                        print(f'Initiated webs..')
                        enemy_check = enemy_cnt[0]
                        frig_trigger = time.time()
                        while enemy_check == enemy_cnt[0]:
                            if frig_trigger + 12 < time.time():
                                frig_lock[0] = 0
                                break
                            time.sleep(1)
                    else:
                        click(280, 70)
                        delay(270, 550)
            '''
            '''
            elif indices_less_than_60:
                print(f'indices_less_than_60: {indices_less_than_60}')
                img_temp = grab_screen()
                for index in indices_less_than_60:
                    print('Attempting to target incoming enemy...')
                    if index > 5:
                        expand_ui()
                    click_nav(index, 0, 300, 600)
                    enemy_distance, frig_list = process_images_concurrently(grab_screen(), 5, 2)
                    if enemy_distance[index] < 60:
                        click_nav(index, 4, 350, 800)
                        if grab_siege(img_temp):
                            click_module('module_12')
                            delay(150, 250)
                        enemy_check = enemy_cnt[0]
                        frig_trigger = time.time()
                        while enemy_check == enemy_cnt[0]:
                            if frig_trigger + 8 < time.time():
                                frig_lock[0] = 0
                                break
                            time.sleep(1)
                    else:
                        click(280, 70)
                        delay(290, 490)
            '''
            time.sleep(1)

    # Start the cycle in a separate thread to allow parallel operations
    threading.Thread(target=cycle_distance).start()


def grab_enemy_cnt(cnt_img):
    try:
        # Get the result of ocr_section
        enemy_cnt_raw = ocr_section(cnt_img, 'enemy_count', 938, 60, 953, 77, 1, 8, 100, '123456789')
        if enemy_cnt_raw == '' or enemy_cnt_raw is None:  # Check if the result is an empty string
            grab_enemy_counter = 0
        else:
            # print(f'enemy-counter: {enemy_cnt_raw}')
            grab_enemy_counter = int(enemy_cnt_raw)  # Attempt to convert a non-empty string to an integer
    except ValueError:
        # Handle the case where the conversion fails due to a ValueError
        print("OCR result is not a valid integer.")
        grab_enemy_counter = 100  # Default to a swarm of enemies
    return grab_enemy_counter


def set_desto():
    # grab screenshot for symbol check
    bm_img = grab_screen()
    # set bookmark
    bm_check = symbol_present(bm_img, 'bm_carrot', 'Tools/bm_carrot.png', f'Tools/{pilot_name}_bm_carrot.png',
                              15, 132, 29, 155)
    save_img(bm_img, 'test', 15, 132, 29, 155)
    if bm_check:
        click(21, 142, 0, 5, 5)
        delay(500, 650)
    else:
        bm_check = symbol_present(bm_img, 'bm_carrot3', 'Tools/bm_carrot3.png', f'Tools/{pilot_name}_bm_carrot3.png',
                                  15, 132, 29, 155)
        if bm_check:
            print('Desto already set.')
            return
        else:
            print('Cannot open bookmarks!')
            sys.exit()
    bm_time = time.time()
    while True:
        # grab screenshot for symbol check
        bm_img = grab_screen()
        bm_check2 = symbol_present(bm_img, 'bm_carrot2', 'Tools/bm_carrot2.png', f'Tools/{pilot_name}_bm_carrot2.png',
                                   192, 136, 206, 155)
        if bm_check2:
            break
        if time.time() > bm_time + 5:
            print('Cannot open bookmarks!')
            sys.exit()
        time.sleep(.5)
    click(185, 500, 0, 5, 5)
    delay(450, 650)
    click(300, 423, 0, 5, 5)
    delay(450, 650)
    click(78, 220, 0, 5, 5)
    delay(450, 650)
    click(307, 186, 0, 5, 5)
    delay(450, 650)
    click(185, 186, 0, 5, 5)
    delay(450, 650)
    return


def pull_local(image):
    def scan_down_pixels(scan_down_image, target_colors, x_offset=0, y_offset=0, color_range=0):
        width, height = scan_down_image.size

        for y in range(y_offset, height):
            pixel = scan_down_image.getpixel((x_offset, y))

            # Check if any of the target colors match the current pixel
            if isinstance(target_colors[0], tuple):  # Check if it's a single color or a list of colors
                colors_to_check = target_colors
            else:
                colors_to_check = [target_colors]

            if any(all(abs(pixel[i] - color[i]) <= color_range for i in range(3)) for color in colors_to_check):
                return y

        return height  # Return the full height if no matching pixel is found within the range

    def isolate_local(local_image_temp):
        scan_colors = [(62, 112, 104), (9, 8, 7)]  # Add the second scan color here
        top_local_bar = scan_down_pixels(local_image_temp, scan_colors[0], 2, 0, 10)

        if top_local_bar > 0:
            cropped_image = local_image_temp.crop((2, top_local_bar + 283, 189, top_local_bar + 323))
            local_image_temp = local_image_temp.crop((2, top_local_bar, 189, top_local_bar + 323))
            return cropped_image, local_image_temp
        else:
            print('Local not found.')
            # Return the original image and a copy of it as local_image_temp to ensure consistency
            return local_image_temp, local_image_temp.copy()

    # Initialize local_image with a default value or None
    local_image = None
    try:
        image, local_image = isolate_local(image)
    except Exception as e:
        print(f'An error occurred: {e}')

    return image, local_image


def grab_local(l_img):
    result = pull_local(l_img)
    # Check if the result is a tuple, extract the image
    if isinstance(result, tuple):
        imt, local_count_image = result
    else:
        imt = result
    '''
    # Assuming imt is supposed to be a PIL Image object
    if isinstance(imt, Image.Image):
        try:
            imt.save(f"imt_{pilot_name}.png", format="png")
        except OSError as e:
            print(f"Failed to save image: {e}")
    else:
        print(f"imt is not an image. It is of type: {type(imt)}")
    '''
    return imt


def open_image(filename2):
    # Open the file and load it into an image object
    with Image.open(filename2) as open_img:
        # Copy the image into a new variable
        processed_image = open_img.copy()
    # Return the processed image
    return processed_image


def grab_hash(hash_img):
    # Assuming hash_img is a PIL Image object
    # Convert the image to bytes directly in memory
    img_byte_arr = io.BytesIO()
    hash_img.save(img_byte_arr, format='PNG')  # Save image to a bytes buffer in PNG format
    img_byte_arr = img_byte_arr.getvalue()  # Get the byte value of the image

    # Calculate the hash directly from the image bytes
    c_hash = hashlib.md5(img_byte_arr).hexdigest()
    return c_hash


def ocr_local(ocr_local_img, comma, space):
    # grab individual numbers
    im1 = ocr_local_img.crop((20, 0, 65, ocr_local_img.height))
    im2 = ocr_local_img.crop((82, 0, 125, ocr_local_img.height))
    im3 = ocr_local_img.crop((143, 0, 180, ocr_local_img.height))

    def get_concat_h(img1, img2, img3, comma, space):
        dst = Image.new('RGB', (
            img1.width + comma.width + img2.width + comma.width + img3.width, img1.height))
        dst.paste(space, (0, 0))
        dst.paste(img1, (10, 0))
        dst.paste(comma, (img1.width, 0))
        dst.paste(img2, (img1.width + comma.width, 0))
        dst.paste(comma, (img1.width + comma.width + img2.width, 0))
        dst.paste(img3, (img1.width + comma.width + img2.width + comma.width, 0))
        return dst

    # paste back together

    if comma is None:
        comma = open_image(f'Tools/comma.png')
    if space is None:
        space = open_image(f'Tools/space.png')

    # assuming im1, im2, im3 are your images
    try:
        # get_concat_h(im1, im2, im3, comma, space).save(f'Tools/{pilot_name}_local_final.png')
        thresh = get_concat_h(im1, im2, im3, comma, space)

    except Exception as e:
        print(f'An error occurred: {e} at {print_line_number()}')

    # thresh = cv2.imread(f'Tools/{pilot_name}_local_final.png')

    thresh = np.array(thresh)
    thresh = cv2.cvtColor(thresh, cv2.COLOR_RGB2BGR)

    lower = np.array([0, 0, 58])
    upper = np.array([179, 255, 255])
    # Create HSV Image and threshold into a range.
    hsv = cv2.cvtColor(thresh, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower, upper)
    thresh = cv2.bitwise_and(thresh, thresh, mask=mask)
    # Bitwise-not
    thresh = cv2.bitwise_not(thresh)

    # Put white border around processed image
    color = [255, 255, 255]  # 'cause purple!
    # border widths; I set them all to 8
    top, bottom, left, right = [8] * 4
    thresh = cv2.copyMakeBorder(thresh, top, bottom, left, right, cv2.BORDER_CONSTANT,
                                value=color)

    thresh = cv2.resize(thresh, None, fx=1.3, fy=1.3, interpolation=cv2.INTER_LANCZOS4)
    cv2.imwrite(f'thresh_{pilot_name}.png', thresh)
    # exit()

    # print('L253')
    data = pytesseract.image_to_string(thresh, lang='eng',
                                       config='--psm 6 --oem 1 -c tessedit_char_whitelist=123456789W0X,')

    # Cleanup OCR Results and make split into list
    data = data.replace("\n", "")
    data = data.replace(" ", "")
    # data = data.replace("", "0")
    data = data.replace("x", "X")
    data = data.replace("o", "0")
    data = data.replace("O", "0")
    data = data.replace("'", "")
    data = data.replace("×", "X")
    data = data.replace("W", "0")
    data = data.replace(",", "")
    # data = data2.replace(",", "")
    # data = data2.replace("O", "0")
    data = data.replace("XX", "X0X")

    # Split the data using 'X' as the delimiter
    split_data = data.split('X')

    # Check and set empty values to 0, and values that cannot be converted to int to 0
    for i in range(len(split_data)):
        if not split_data[i]:  # Check if the element is empty
            split_data[i] = 0  # Set it to 0 if empty
        else:
            try:
                # Try to convert the value to an integer
                split_data[i] = int(split_data[i])
            except ValueError:
                # Handle the case where conversion to int is not possible
                print(f'Warning: Value {split_data[i]} at index {i} '
                      f'cannot be converted to int. Setting to 0.')
                split_data[i] = 0

    # Filter out empty strings
    filtered_data = list(filter(None, split_data))
    # Convert each non-empty element to an integer
    int_values = [int(value) for value in filtered_data]

    # Sum the integer values
    report_tot = sum(int_values)
    return report_tot, comma, space


def kill_switch_cycle():
    def dock_check():
        # set initial local count hash
        local_img = grab_local(grab_screen())
        last_hash = current_hash = grab_hash(local_img)
        comma_hld = None
        space_hld = None

        while True:
            # Compare the current hash with the last hash
            if current_hash != last_hash or kill_switch[0]:
                local_cnt, comma_hld, space_hld = ocr_local(local_img, comma_hld, space_hld)
                if local_cnt > 0 or kill_switch[0]:
                    print(f'Enemy Spotted in local. Docking!!!')
                    kill_switch[0] = True
                    while grab_siege(grab_screen()):
                        click_module('module_12')
                        delay(350, 500)
                    click(20, 145)
                    # bm_check = True
                    while True:
                        bm_check = symbol_present(grab_screen(), 'bm_carrot3', 'Tools/bm_carrot3.png',
                                                  f'Tools/{pilot_name}_bm_carrot3.png',
                                                  15, 132, 29, 155)
                        if bm_check:
                            click(20, 145)
                        time.sleep(1)
                # Update the last hash with the current hash for the next iteration
                last_hash = current_hash
            # check local
            local_img = grab_local(grab_screen())
            current_hash = grab_hash(local_img)
            time.sleep(1)

    # Start the cycle in a separate thread to allow parallel operations
    threading.Thread(target=dock_check).start()


# set window for proper size
resize_window()
# print_line_number()

# Begin bot logic
windll.user32.SetProcessDPIAware()
auto_lock = False
pilot_damage = 0
battery_timer = time.time()
shield_in_use = False
last_enemy_cnt = 0
wave_initial_cnt = 0
first_wave = True
true_indices = [None] * 30
kill_switch = [False]  # start the kill_switch thread
kill_switch_cycle()
frig_lock = [0]  # start the heatsink thread
heatsink_cycle(frig_lock)
enemy_cnt = [0]  # start the counter thread
enemy_cnt_cycle()
auto_lock_timer = time.time()  # init timer
wave_timer = 0
backup_webs_active = False
frig_recheck = time.time() + 10000
force_frig_check = False
stop_distance_cycle = [False]  # Initialize with one element


'''
enemy_distance_cycle()
while True:
    time.sleep(10000)
sys.exit()



while True:
    img = grab_screen()
    enemy_cnt[0] = grab_enemy_cnt(img)
    print(f'Count: {enemy_cnt[0]}')
    time.sleep(1)
'''

# set bookmark desto
set_desto()

# get initial screenshot
img = grab_screen()

# Zoom out
click(480, 466, 10, 10)
delay(500, 750)
# Open nav if closed
open_nav_ui(img)
# Set page to Enemies
pilot_window = pyautogui.getWindowsWithTitle(f'{pilot_name}')[0]
pilot_window.activate()
click_nav('page_select', 0, 454, 987)
click_nav('page_enemy', 0, 750, 1000)
delay(450, 650)

anomaly_timer = time.time() + 3000

commands = {
    "auto_lock = grab_auto_lock(img)": 1,  # cooldown time of 2 seconds
    "pilot_damage = grab_health()": 5,  # cooldown time of 5 seconds

    # "backup_grab_enemy(grab_screen())": 10,
}

last_executed = {command: 0 for command in commands}

while True:
    if kill_switch[0]:
        sys.exit()
    # print_line_number()
    current_time = time.time()
    img = grab_screen()
    # Open nav_ui if closed
    open_nav_ui(img)

    if enemy_cnt[0] < last_enemy_cnt:
        # print(f'Wave Duration: {int(time.time() - wave_timer)}s')
        # print(f'Enemy Kill-time: {int(time.time() - wave_timer2)}s')
        wave_timer2 = time.time()
        backup_webs_active = False

    if time.time() > frig_recheck:
        print('Checking for more frigs..')
        force_frig_check = True

    # if last_enemy_cnt != enemy_cnt[0]:
        # print(f'wave_initial_cnt: {wave_initial_cnt}')
        # print(f'last_enemy_cnt: {last_enemy_cnt}')
        # print(f'enemy_cnt: {enemy_cnt[0]}')

    '''
    if enemy_cnt[0] > last_enemy_cnt:
        frig_lock[0] = 0
    last_enemy_cnt = enemy_cnt[0]
    '''

    if enemy_cnt[0] == last_enemy_cnt - 1:
        last_enemy_cnt = enemy_cnt[0]

    # print(f'trigger: {(enemy_cnt[0]) * 20}')
    # print(f'timer: {time.time() - wave_timer}')
    if frig_lock[0] == 1 and 80 < time.time() - wave_timer2:
        frig_lock[0] = 0
        print(f'initiating backup web activation')
        if grab_siege(img):
            click_module('module_12')
        click_module('module_3')
        delay(450, 900)
        click_module('module_4')
        delay(450, 900)
        click_module('module_5')
        delay(450, 900)
        backup_webs_active = True

    if enemy_cnt[0] == 0 and frig_lock == 1:
        end_anom_timer = time.time()
        while enemy_cnt[0] == 0:
            if time.time() > end_anom_timer + 6:  # four failed
                travel(1)
                first_wave = True
            time.sleep(1)

    if wave_initial_cnt - enemy_cnt[0] + 1 >= len(true_indices) and frig_lock[0] == 1 and \
            last_enemy_cnt >= enemy_cnt[0] > 1:
        if time.time() > auto_lock_timer + 3:
            img = grab_screen()
            if grab_auto_lock(img):
                print('Clicked Auto-lock')
                click_autolock()
                auto_lock_timer = time.time()

    if wave_initial_cnt - enemy_cnt[0] >= len(true_indices) and frig_lock[0] == 1 and enemy_cnt[0] <= last_enemy_cnt\
            and enemy_cnt[0] != 0 and not backup_webs_active:
        if not grab_siege(grab_screen()):
            print(f'Entering Siege')
            print(f'wave_init: {wave_initial_cnt} | enemy_cnt: {enemy_cnt[0]} | last_enemy_cnt: {last_enemy_cnt}')
            click_module('module_12')

    enemy_present = grab_enemy_present(img)
    # auto_lock = grab_auto_lock(img)
    '''
    bak_grab_enemy = backup_grab_enemy(img)
    if bak_grab_enemy and not enemy_present:
        print(f'attempting to reacquire bak_grab_enemy')
        time.sleep(1)
        img = grab_screen()
        auto_lock = grab_auto_lock(img)
        bak_grab_enemy = backup_grab_enemy(img)
        enemy_present = grab_enemy_present(img)
        # if not enemy_present:
        # refresh_nav_ui(img)
    '''
    '''
    # Begin pre-approach if timer has elapsed
    # print_line_number()
    # Initialize anomaly_timer to a default value if not already set
    anomaly_timer = anomaly_timer if anomaly_timer is not None else 0
    if anomaly_timer - time.time() < 0:
        print('Begin Pre-Approach')
        anomaly_timer = time.time() + 3000
        travel(0)
    '''

    # Begin warp travel if anomaly is completed
    # print(f'- Enemy Present: {enemy_present}')
    # print(f'- AutoLock: {auto_lock}')
    if not enemy_present and not auto_lock and enemy_cnt[0] == 0:  # and not bak_grab_enemy
        pre_board_timer = time.time()
        while enemy_cnt[0] == 0:
            img = grab_screen()
            # print(f'enemy present: {grab_enemy_present(img)}')
            # print(f'auto lock: {grab_auto_lock(img)}')
            # print(f'backup grab: {backup_grab_enemy(img)}')
            if first_pass > 0 and time.time() > pre_board_timer + 4 and not grab_enemy_present(img) and not grab_auto_lock(img) and not backup_grab_enemy(img):
                print('Entering Travel')
                anomaly_timer = travel(1)
                first_wave = True
                break
            if first_pass < 1 and time.time() > pre_board_timer + 1 and not grab_enemy_present(img) and not grab_auto_lock(img) and not backup_grab_enemy(img):
                print('Entering Travel')
                first_pass += 1
                anomaly_timer = travel(1)
                first_wave = True
                break
            if time.time() > pre_board_timer + 5:
                print(f'Preboarding Error, check enemy count ({enemy_cnt[0]}.')
                break

    for command, cooldown in commands.items():
        if current_time - last_executed[command] >= cooldown:
            # execute the command
            exec(command)
            # print(f'Executing command[{command}]')
            last_executed[command] = current_time

    # Frig Function
    if enemy_cnt[0] > 0 and enemy_cnt[0] > last_enemy_cnt or force_frig_check is True:
        # print(f'New Enemy Count: {enemy_cnt[0]}')
        frig_lock[0] == 0
        wave_initial_cnt = enemy_cnt[0]
        last_enemy_cnt = enemy_cnt[0]
        force_frig_check = False

        if not first_wave:
            click_nav(2, 0, 300, 600)
            click_nav(2, 4, 350, 800)
            expand_ui()
            click_nav(2, 0, 300, 600)
            click_nav(2, 4, 350, 800)
            if grab_siege(grab_screen()):
                click_module('module_12')

        # print(f'initial wave cnt: {wave_initial_cnt}')
        for i in range(2):
            expand_ui()
            enemy_list = grab_enemy_list_ocr()
            print(enemy_list)
            if any(enemy_list[1]):
                break
        # Extract indices where the value is True in the second list
        true_indices = [index + 1 for index, value in enumerate(enemy_list[1]) if value]
        print(true_indices)
        img = grab_screen()
        lock_timer = time.time()
        while not grab_auto_lock(img):
            # check the pixels near autolock to see if menu is covering
            px_cnt = count_pixels(grab_img(img, 'grab_px', 605, 316, 610, 320), 30, 45, 35, 45, 40, 50)
            if px_cnt > 0:
                click(280, 70)
                delay(300, 500)
            if time.time() > lock_timer + 11:
                click(280, 70)
                lock_timer = time.time()
                break
            time.sleep(0.1)
            img = grab_screen()
        time.sleep(0.1)
        if first_wave:
            time.sleep(3)

        if true_indices:
            pilot_window = pyautogui.getWindowsWithTitle(f'{pilot_name}')[0]
            pilot_window.activate()
            for index, frig_t in enumerate(true_indices, start=1):
                if kill_switch[0]:
                    sys.exit()
                if frig_t == 2 and first_wave is False:
                    continue
                print(f'{index}: {frig_t}')
                if frig_t > 5:
                    expand_ui()
                click_nav(frig_t, 0, 300, 600)
                if index == 1:
                    click_nav(frig_t, 4, 350, 800)
                    delay(250, 350)
                    click_nav(frig_t, 0, 300, 600)
                    click_nav(frig_t, 4, 350, 800)
                else:
                    click_nav(frig_t, 5, 300, 600)
            if grab_siege(img):
                click_module('module_12')
        else:
            click_nav(1, 0, 300, 600)
            click_nav(1, 4, 350, 800)
        if grab_siege(grab_screen()):
            click_module('module_12')
        print('Turned on Target Painter')
        click_module('module_1')  # turn on target painter

        if 2 not in true_indices:
            click_nav(2, 0, 300, 600)
            click_nav(2, 5, 300, 600)

        auto_lock_timer = time.time() + 5
        if enemy_cnt[0] > 6:
            frig_recheck = time.time() + 30
        else:
            frig_recheck = time.time() + 10000
        delay(2000, 2000)
        frig_lock[0] = 1
        if first_wave:
            stop_distance_cycle[0] = True
            enemy_distance_cycle()
        wave_timer = wave_timer2 = time.time()
        first_wave = False

    '''
    # turn off shield if battery done
    if time.time() - battery_timer > 22 and shield_in_use:
        click_module('module_1')
        click_module('module_1')
        shield_in_use = False
    '''

    # activate battery and shield if injured
    if pilot_damage > 20 and not shield_in_use:
        shield_in_use = True
        print(f'Shield: On')
        # activate shield
        click_module('module_7')
        delay(350, 700)

    # deactivate shield if healed
    if pilot_damage < 10 and shield_in_use:
        shield_in_use = False
        print(f'Shield: Off')
        # deactivate shield
        click_module('module_7')
        delay(350, 600)

    # play warning if below 50% health
    if pilot_damage > 125:
        print('Low Health!!!')
        kill_switch[0] = True
        # filename = 'warning1.mp3'
        # file_path = os.path.join(os.getcwd(), 'Tools', filename)
        # playsound(file_path)
        print('Low Health!')

    time.sleep(0.2)  # sleep for 1 second before checking the commands again
