"""Whiteboard sketch render engine (OpenCV + NumPy + PyAV)."""

import datetime
import math
import os
import time
from pathlib import Path

import cv2
import numpy as np

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
HAND_PATH = os.path.join(ASSETS_DIR, "drawing-hand-drawclip.png")
HAND_MASK_PATH = os.path.join(ASSETS_DIR, "hand-mask-drawclip.png")

RATIO_RESOLUTIONS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:3": (1440, 1080),
}
ALLOWED_RATIOS = ("auto",) + tuple(RATIO_RESOLUTIONS.keys())
DEFAULT_SPLIT_LEN = 20
DEFAULT_FRAME_RATE = 25
MAX_VIDEO_DURATION = 20  # seconds — caps total_image_duration to avoid CPU/disk overload


def _euc_dist(arr1, point):
    return np.sqrt(np.sum((arr1 - point) ** 2, axis=1))


def _get_extreme_coordinates(mask):
    indices = np.where(mask == 255)
    return (np.min(indices[1]), np.min(indices[0])), (np.max(indices[1]), np.max(indices[0]))


def _resize_with_padding(img, target_width, target_height, color=(255, 255, 255)):
    h, w = img.shape[:2]
    scale = min(target_width / w, target_height / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    pad_w = target_width - new_w
    pad_h = target_height - new_h
    top, bottom = pad_h // 2, pad_h - pad_h // 2
    left, right = pad_w // 2, pad_w - pad_w // 2
    return cv2.copyMakeBorder(resized, top, bottom, left, right,
                              cv2.BORDER_CONSTANT, value=color)


def _find_nearest_res(given):
    arr = np.array([640, 360, 480, 1280, 720, 1920, 1080, 2560, 1440, 3840, 2160, 7680, 4320])
    return arr[(np.abs(arr - given)).argmin()]


def _resolve_target_resolution(image_bgr, ratio: str):
    img_ht, img_wd = image_bgr.shape[0], image_bgr.shape[1]
    if ratio in RATIO_RESOLUTIONS:
        target_w, target_h = RATIO_RESOLUTIONS[ratio]
        return target_w, target_h, _resize_with_padding(image_bgr, target_w, target_h)
    if img_ht > 1920 or img_wd > 1920:
        if img_wd > img_ht:
            return 1920, 1080, _resize_with_padding(image_bgr, 1920, 1080)
        return 1080, 1920, _resize_with_padding(image_bgr, 1080, 1920)
    aspect_ratio = img_wd / img_ht
    target_h = int(_find_nearest_res(img_ht))
    target_w = int(_find_nearest_res(int(target_h * aspect_ratio)))
    return target_w, target_h, image_bgr


def _count_drawing_cells(image_bgr, target_w, target_h, split_len, black_pixel_threshold=10):
    img_resized = cv2.resize(image_bgr, (target_w, target_h))
    img_gray = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
    img_thresh = cv2.adaptiveThreshold(
        img_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10
    )
    n_cuts_v = int(math.ceil(target_h / split_len))
    n_cuts_h = int(math.ceil(target_w / split_len))
    grid = np.array(np.split(img_thresh, n_cuts_h, axis=-1))
    grid = np.array(np.split(grid, n_cuts_v, axis=-2))
    cut_having_black = (grid < black_pixel_threshold).sum(axis=(-1, -2))
    return int(np.sum(cut_having_black > 0))


class _RenderState:
    """Mutable container for shared state during rendering."""


def _preprocess_image(img, state):
    img = cv2.resize(img, (state.resize_wd, state.resize_ht))
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cv2.createCLAHE(clipLimit=2.0, tileGridSize=(3, 3)).apply(img_gray)
    img_thresh = cv2.adaptiveThreshold(
        img_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10
    )
    state.img_gray = img_gray
    state.img_thresh = img_thresh
    state.img = img
    return state


def _preprocess_hand(state):
    hand = cv2.imread(HAND_PATH)
    hand_mask = cv2.imread(HAND_MASK_PATH, cv2.IMREAD_GRAYSCALE)
    top_left, bottom_right = _get_extreme_coordinates(hand_mask)
    hand = hand[top_left[1]:bottom_right[1], top_left[0]:bottom_right[0]]
    hand_mask = hand_mask[top_left[1]:bottom_right[1], top_left[0]:bottom_right[0]]
    hand_mask_inv = (255 - hand_mask) / 255
    hand_mask = hand_mask / 255
    hand[np.where(hand_mask == 0)] = [0, 0, 0]
    state.hand_ht, state.hand_wd = hand.shape[0], hand.shape[1]
    state.hand = hand
    state.hand_mask_inv = hand_mask_inv
    return state


def _draw_hand_on_img(drawing, hand, x, y, hand_mask_inv, hand_ht, hand_wd, img_ht, img_wd):
    crop_h = hand_ht if (img_ht - y) > hand_ht else (img_ht - y)
    crop_w = hand_wd if (img_wd - x) > hand_wd else (img_wd - x)
    hand_cropped = hand[:crop_h, :crop_w]
    mask_inv_cropped = hand_mask_inv[:crop_h, :crop_w]
    ys, xs = slice(y, y + crop_h), slice(x, x + crop_w)
    for ch in range(3):
        drawing[ys, xs][:, :, ch] = drawing[ys, xs][:, :, ch] * mask_inv_cropped
    drawing[ys, xs] = drawing[ys, xs] + hand_cropped
    return drawing


def _draw_grid(state, skip_rate=5, black_pixel_threshold=10,
               progress_callback=None, color_while_drawing=False):
    img_thresh_copy = state.img_thresh.copy()
    n_cuts_v = int(math.ceil(state.resize_ht / state.split_len))
    n_cuts_h = int(math.ceil(state.resize_wd / state.split_len))

    grid_of_cuts = np.array(np.split(img_thresh_copy, n_cuts_h, axis=-1))
    grid_of_cuts = np.array(np.split(grid_of_cuts, n_cuts_v, axis=-2))

    cut_having_black = (grid_of_cuts < black_pixel_threshold).sum(axis=(-1, -2))
    cut_black_indices = np.array(np.where(cut_having_black > 0)).T

    step_div = max(len(cut_black_indices) / 40, 1)
    progress_step = 100 / step_div
    progress = 0.0
    selected_ind = 0
    counter = 0

    while len(cut_black_indices) > 1:
        ind_val = cut_black_indices[selected_ind].copy()
        v_start = ind_val[0] * state.split_len
        v_end = v_start + state.split_len
        h_start = ind_val[1] * state.split_len
        h_end = h_start + state.split_len

        if color_while_drawing:
            state.drawn_frame[v_start:v_end, h_start:h_end] = state.img[v_start:v_end, h_start:h_end]
        else:
            cell = grid_of_cuts[ind_val[0]][ind_val[1]]
            patch = np.zeros((state.split_len, state.split_len, 3))
            patch[:, :, 0] = cell
            patch[:, :, 1] = cell
            patch[:, :, 2] = cell
            state.drawn_frame[v_start:v_end, h_start:h_end] = patch

        if state.draw_hand:
            hand_x = h_start + int(state.split_len / 2)
            hand_y = v_start + int(state.split_len / 2)
            frame = _draw_hand_on_img(
                state.drawn_frame.copy(), state.hand.copy(), hand_x, hand_y,
                state.hand_mask_inv.copy(),
                state.hand_ht, state.hand_wd, state.resize_ht, state.resize_wd,
            )
        else:
            frame = state.drawn_frame.copy()

        cut_black_indices[selected_ind] = cut_black_indices[-1]
        cut_black_indices = cut_black_indices[:-1]
        del selected_ind
        selected_ind = np.argmin(_euc_dist(cut_black_indices, ind_val))

        counter += 1
        if counter % skip_rate == 0:
            state.video_object.write(frame)
        if counter % 40 == 0:
            progress += progress_step
            if progress_callback:
                progress_callback(min(progress, 100))

    state.drawn_frame[:, :, :] = state.img


def _ffmpeg_h264_convert(source_vid, dest_vid):
    try:
        import av
        with av.open(Path(source_vid), mode="r") as in_c, av.open(dest_vid, mode="w") as out_c:
            in_stream = in_c.streams.video[0]
            out_stream = out_c.add_stream("h264", rate=in_stream.average_rate)
            out_stream.width = in_stream.codec_context.width
            out_stream.height = in_stream.codec_context.height
            out_stream.pix_fmt = "yuv420p"
            out_stream.options = {"crf": "20"}
            for frame in in_c.decode(video=0):
                packet = out_stream.encode(frame)
                if packet:
                    out_c.mux(packet)
            packet = out_stream.encode(None)
            if packet:
                out_c.mux(packet)
        return True
    except Exception as e:
        print(f"ffmpeg convert error: {e}")
        return False


def generate(
    image_path: str,
    save_path: str,
    total_image_duration: int = 10,
    writing_duration: int = 6,
    ratio: str = "auto",
    draw_hand: bool = True,
    color_while_drawing: bool = False,
    progress_callback=None,
) -> str:
    """Generate a whiteboard sketch animation video.

    Returns the absolute path to the generated mp4 file. Raises ValueError on
    invalid arguments or unreadable input.
    """
    if ratio not in ALLOWED_RATIOS:
        raise ValueError(f"ratio must be one of {ALLOWED_RATIOS}, got {ratio!r}")
    if writing_duration <= 0:
        raise ValueError("writing_duration must be > 0")
    if total_image_duration > MAX_VIDEO_DURATION:
        raise ValueError(
            f"total_image_duration ({total_image_duration}) exceeds maximum "
            f"allowed of {MAX_VIDEO_DURATION} seconds"
        )
    if total_image_duration < writing_duration:
        raise ValueError(
            f"total_image_duration ({total_image_duration}) must be >= "
            f"writing_duration ({writing_duration})"
        )

    image_bgr = cv2.imread(image_path)
    if image_bgr is None:
        raise ValueError(f"Could not read image: {image_path}")

    target_w, target_h, image_bgr = _resolve_target_resolution(image_bgr, ratio)

    n_cells = _count_drawing_cells(image_bgr, target_w, target_h, DEFAULT_SPLIT_LEN)
    if n_cells <= 0:
        raise ValueError("Image has no detectable drawing content (uniform / blank).")

    target_writing_frames = max(1, writing_duration * DEFAULT_FRAME_RATE)
    object_skip_rate = max(1, round(n_cells / target_writing_frames))
    end_hold_seconds = max(0, total_image_duration - writing_duration)

    os.makedirs(save_path, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    raw_video_path = os.path.join(save_path, f"vid_{stamp}.mp4")
    final_video_path = os.path.join(save_path, f"vid_{stamp}_h264.mp4")

    state = _RenderState()
    state.frame_rate = DEFAULT_FRAME_RATE
    state.resize_wd = target_w
    state.resize_ht = target_h
    state.split_len = DEFAULT_SPLIT_LEN
    state.draw_hand = draw_hand

    state = _preprocess_image(image_bgr, state)
    state = _preprocess_hand(state)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    state.video_object = cv2.VideoWriter(
        raw_video_path, fourcc, state.frame_rate, (state.resize_wd, state.resize_ht),
    )
    state.drawn_frame = np.zeros(state.img.shape, np.uint8) + np.array([255, 255, 255], np.uint8)

    start_time = time.time()
    _draw_grid(
        state, skip_rate=object_skip_rate,
        progress_callback=progress_callback,
        color_while_drawing=color_while_drawing,
    )
    end_img = state.img
    for _ in range(state.frame_rate * end_hold_seconds):
        state.video_object.write(end_img)
    print(f"whiteboard render time: {time.time() - start_time:.2f}s")
    state.video_object.release()

    if _ffmpeg_h264_convert(raw_video_path, final_video_path):
        os.unlink(raw_video_path)
        return final_video_path
    return raw_video_path
