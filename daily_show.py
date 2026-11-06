#!/usr/bin/env python3
"""Give the Govee Front led lights a different show every day.

Paints one color and pattern a day through Govee's cloud API, section by
section, leaving the neighbors' section dark. With --animate it plays the
evening effect for that show. With --power it switches the lights on or off
to match the schedule: on from sunset to midnight and from MORNING_ON to
sunrise. No computer has to stay on.

Needs the GOVEE_API_KEY environment variable. Run with --dry-run to see what
would be sent without changing the lights.
"""
import datetime
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
import uuid
import zoneinfo

API = "https://openapi.api.govee.com/router/api/v1"
SKU = os.environ.get("GOVEE_SKU", "H805C")
TIME_ZONE = zoneinfo.ZoneInfo(os.environ.get("SHOW_TIME_ZONE", "America/Los_Angeles"))

# Simi Valley, CA, for sunset and sunrise. The lights are on from sunset to midnight and from
# MORNING_ON to sunrise.
LATITUDE = 34.2694
LONGITUDE = -118.7815
MORNING_ON = datetime.time(4, 30)

# The first sections stay dark because they bother the neighbors. Each section is about 4
# boxes. Scenes and DIY scenes light these sections, so every show is painted section by section.
DARK_SEGMENTS = 4

# How bright each section is, repeating along the roofline. 1 is full color. Every level stays
# lit, so only the dark sections are ever off.
PATTERNS = {
    "Solid": (1,),
    "Stripes": (1, 0.4),
    "Wide Stripes": (1, 1, 0.4, 0.4),
    "Sparks": (1, 0.4, 0.4),
    "Waves": (1, 0.7, 0.4, 0.7),
    "Two Tone": (1, 0.55),
}

SHOWS = [
    ("Royal Purple", 0x7800FF, "Waves"),
    ("Lava Orange", 0xFF4600, "Stripes"),
    ("Ice Blue", 0x80E0FF, "Sparks"),
    ("Emerald", 0x00C040, "Two Tone"),
    ("Hot Pink", 0xFF0090, "Wide Stripes"),
    ("Crimson", 0xFF0000, "Solid"),
    ("Electric Blue", 0x0040FF, "Stripes"),
    ("Gold", 0xFFB000, "Sparks"),
    ("Teal", 0x00FFD0, "Waves"),
    ("Magenta", 0xFF00FF, "Two Tone"),
    ("Slime Green", 0x60FF00, "Solid"),
    ("Violet", 0xA040FF, "Wide Stripes"),
    ("Tangerine", 0xFF7A00, "Sparks"),
    ("Deep Ocean", 0x0010FF, "Waves"),
    ("Cherry", 0xFF0030, "Stripes"),
    ("Cyan", 0x00FFFF, "Solid"),
    ("Lime", 0xB0FF00, "Two Tone"),
    ("Amber", 0xFF9000, "Wide Stripes"),
    ("Orchid", 0xE040FF, "Waves"),
    ("Sapphire", 0x0060FF, "Sparks"),
    ("Coral", 0xFF4060, "Two Tone"),
    ("Jade", 0x00FF80, "Stripes"),
    ("Ultraviolet", 0x4000FF, "Solid"),
    ("Sunset Pink", 0xFF2060, "Sparks"),
    ("Aqua", 0x00C0FF, "Wide Stripes"),
    ("Ruby", 0xD00020, "Waves"),
    ("Mint", 0x40FFB0, "Two Tone"),
    ("Plum", 0x9000C0, "Stripes"),
    ("Honey", 0xFFC830, "Solid"),
    ("Bubblegum", 0xFF60C0, "Wide Stripes"),
]

# The evening effect: solid shows pulse brighter and dimmer, the others drift along the
# roofline. Each hourly run plays for up to EFFECT_MINUTES, so the effect lasts all evening.
EFFECT_MINUTES = 60
PULSE = (100, 75, 50, 30, 20, 30, 50, 75)
# Govee allows 10,000 requests a day. One command every 4 seconds from sunset to midnight
# stays under that.
COMMAND_SECONDS = 4
# How many commands go by between checks that the lights are still on
POWER_CHECK_COMMANDS = 15


class RateLimited(Exception):
    """Govee asked for fewer requests."""


def call(path, api_key, payload=None):
    """Call the Govee API and return the decoded response."""
    data = None
    method = "GET"
    if payload is not None:
        method = "POST"
        data = json.dumps({"requestId": str(uuid.uuid4()), "payload": payload}).encode()
    request = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Govee-API-Key": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise RateLimited(path)
        sys.exit(f"Govee API error {error.code} on {path}: {error.read().decode()[:300]}")


def find_device(api_key):
    """Return the device record for the lights."""
    devices = call("/user/devices", api_key).get("data", [])
    for device in devices:
        if device.get("sku") == SKU:
            return device
    found = ", ".join(str(d.get("sku")) for d in devices) or "none"
    sys.exit(f"No {SKU} on this Govee account. Devices found: {found}")


def lights_are_off(device, api_key):
    """Report whether the lights are off, since painting them could switch them on."""
    target = {"sku": device["sku"], "device": device["device"]}
    state = call("/device/state", api_key, target).get("payload", {})
    for capability in state.get("capabilities", []):
        if capability.get("instance") == "powerSwitch":
            return capability.get("state", {}).get("value") == 0
    return False


def sun_times(day):
    """Return the local sunrise and sunset for a day, using NOAA's approximation."""
    g = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    lat = math.radians(LATITUDE)
    hour_angle = math.degrees(math.acos(
        math.cos(math.radians(90.833)) / (math.cos(lat) * math.cos(decl))
        - math.tan(lat) * math.tan(decl)))
    midnight = datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc)
    rise, set_ = (midnight + datetime.timedelta(minutes=720 - 4 * (LONGITUDE + sign * hour_angle)
                                                - eqtime) for sign in (1, -1))
    return rise.astimezone(TIME_ZONE), set_.astimezone(TIME_ZONE)


def should_be_on(now):
    """Report whether the schedule has the lights on at this local time."""
    sunrise, sunset = sun_times(now.date())
    return now >= sunset or (now.time() >= MORNING_ON and now < sunrise)


def keep_schedule(device, api_key, dry_run):
    """Switch the lights on or off to match the schedule."""
    now = datetime.datetime.now(TIME_ZONE)
    sunrise, sunset = sun_times(now.date())
    wanted = should_be_on(now)
    print(f"Sunrise {sunrise:%H:%M}, sunset {sunset:%H:%M}, lights should be "
          f"{'on' if wanted else 'off'}")
    if dry_run:
        return
    is_on = not lights_are_off(device, api_key)
    if is_on != wanted:
        set_power(device, api_key, wanted)
        print(f"Switched the lights {'on' if wanted else 'off'}.")


def pick_for_day(names, day):
    """Pick one name per day, using every name once before any repeats."""
    cycle, position = divmod(day.toordinal(), len(names))
    order = list(names)
    random.Random(cycle).shuffle(order)
    return order[position]


def usable_segments(device):
    """Return how many sections the lights have, stopping if they can't be set separately."""
    for capability in device.get("capabilities", []):
        if capability.get("instance") == "segmentedColorRgb":
            for field in capability.get("parameters", {}).get("fields", []):
                if field.get("fieldName") == "segment":
                    segments = field.get("elementRange", {}).get("max", -1) + 1
                    if segments > DARK_SEGMENTS:
                        return segments
    sys.exit("Can't set sections separately, so nothing was sent. A whole-roofline color "
             "would light the section that stays dark.")


def dim(rgb, level):
    """Return the color at a fraction of its full brightness."""
    return sum(int((rgb >> shift & 255) * level) << shift for shift in (16, 8, 0))


def layout(pattern, segments, offset=0):
    """Group the lit sections by brightness level, with the pattern moved along by offset."""
    groups = {}
    for index, segment in enumerate(range(DARK_SEGMENTS, segments)):
        groups.setdefault(pattern[(index + offset) % len(pattern)], []).append(segment)
    return groups


def control(device, api_key, capability):
    """Send one command, stopping if Govee refuses."""
    target = {"sku": device["sku"], "device": device["device"], "capability": capability}
    reply = call("/device/control", api_key, target)
    if reply.get("code") != 200:
        sys.exit(f"Govee refused the command: {str(reply)[:300]}")


def paint(device, api_key, segments, rgb):
    control(device, api_key, {
        "type": "devices.capabilities.segment_color_setting",
        "instance": "segmentedColorRgb",
        "value": {"segment": segments, "rgb": rgb},
    })


def set_brightness(device, api_key, percent):
    control(device, api_key, {
        "type": "devices.capabilities.range",
        "instance": "brightness",
        "value": percent,
    })


def set_power(device, api_key, on):
    control(device, api_key, {
        "type": "devices.capabilities.on_off",
        "instance": "powerSwitch",
        "value": 1 if on else 0,
    })


def show_pattern(device, api_key, rgb, pattern):
    """Paint the pattern along the roofline, leaving the dark sections off."""
    segments = usable_segments(device)
    set_brightness(device, api_key, 100)
    time.sleep(1)
    paint(device, api_key, list(range(DARK_SEGMENTS)), 0)
    time.sleep(1)
    for level, group in layout(pattern, segments).items():
        paint(device, api_key, group, dim(rgb, level))
        time.sleep(1)


def animate(device, api_key, rgb, pattern, dry_run):
    """Play the effect for a while, stopping early if the lights go off."""
    segments = usable_segments(device)
    pulse = len(set(pattern)) == 1
    end = time.monotonic() + EFFECT_MINUTES * 60
    step = 0
    commands = 0
    try:
        while time.monotonic() < end:
            if pulse:
                actions = [("brightness", PULSE[step % len(PULSE)])]
            else:
                actions = list(layout(pattern, segments, step).items())
            if dry_run:
                print(f"Step {step}: " + ", ".join(
                    f"{value}%" if kind == "brightness" else f"{kind:.0%} on {value}"
                    for kind, value in actions))
                step += 1
                if step == 3:
                    return
                continue
            for kind, value in actions:
                # Painting switches the lights on, so stop at midnight before sending anything
                if not should_be_on(datetime.datetime.now(TIME_ZONE)):
                    print(f"Schedule says off after {step} steps, switching the lights off.")
                    set_power(device, api_key, False)
                    return
                if commands % POWER_CHECK_COMMANDS == 0:
                    if lights_are_off(device, api_key):
                        print(f"Lights went off after {step} steps, stopping the effect.")
                        return
                    time.sleep(1)
                try:
                    if kind == "brightness":
                        set_brightness(device, api_key, value)
                    else:
                        paint(device, api_key, value, dim(rgb, kind))
                except RateLimited:
                    print("Govee asked for fewer requests, pausing for a minute.")
                    time.sleep(60)
                commands += 1
                time.sleep(COMMAND_SECONDS)
            step += 1
        print(f"Played {step} steps.")
    finally:
        if (pulse and not dry_run and should_be_on(datetime.datetime.now(TIME_ZONE))
                and not lights_are_off(device, api_key)):
            set_brightness(device, api_key, 100)


def play_effect(device, api_key, rgb, pattern, dry_run):
    """Play the effect in the evening while the lights are on."""
    now = datetime.datetime.now(TIME_ZONE)
    if not dry_run:
        if now.hour < 12 or not should_be_on(now):
            print("It isn't evening yet, so no effect now.")
            return
        if lights_are_off(device, api_key):
            print("Lights are off, so no effect now.")
            return
    effect = "Pulse" if len(set(pattern)) == 1 else "Drift"
    print(f"Effect: {effect} for {EFFECT_MINUTES} minutes")
    animate(device, api_key, rgb, pattern, dry_run)


def main():
    dry_run = "--dry-run" in sys.argv
    api_key = os.environ.get("GOVEE_API_KEY")
    if not api_key:
        sys.exit("GOVEE_API_KEY is not set")

    today = datetime.datetime.now(TIME_ZONE).date()
    device = find_device(api_key)
    if "--power" in sys.argv:
        keep_schedule(device, api_key, dry_run)
        return
    shows = {f"{name} {pattern}": (rgb, pattern) for name, rgb, pattern in SHOWS}

    name = pick_for_day(list(shows), today)
    print(f"Today's show: {name}")
    rgb, pattern = shows[name]

    if "--animate" in sys.argv:
        play_effect(device, api_key, rgb, PATTERNS[pattern], dry_run)
        return
    if dry_run:
        return
    was_off = lights_are_off(device, api_key)
    print(f"Lights were {'off' if was_off else 'on'}")
    try:
        show_pattern(device, api_key, rgb, PATTERNS[pattern])
    finally:
        if was_off:
            set_power(device, api_key, False)

    with open("last-show.txt", "w", encoding="utf-8") as log:
        log.write(f"{today}: {name}\n")


if __name__ == "__main__":
    main()
