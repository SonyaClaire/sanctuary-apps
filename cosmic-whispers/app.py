"""
Cosmic Whispers HUD — Python Backend v3.0
==========================================
Flask API serving all astronomical data for the WCC Astrology App.
Includes the OrbitalLens ISS planetary chart engine.

Stack: Flask · ephem · python-dotenv · flask-cors · requests
Install: pip install flask ephem python-dotenv flask-cors requests gunicorn

Run locally:  python app.py
Deploy:       Render.com free tier (see README.md)

Endpoints:
  GET /health                     → status check
  GET /api/all?lat=&lon=         → everything in one call (frontend uses this)
  GET /api/planets               → planetary positions (sign, degree, retro, oph)
  GET /api/moon                  → moon phase, illumination, sign
  GET /api/day                   → day ruler, date
  GET /api/sun-times?lat=&lon=   → sunrise, sunset, daylight, moonrise, moonset
  GET /api/retrogrades           → active + upcoming retrograde list
  GET /api/iss                   → OrbitalLens ISS full chart
  GET /api/iss/week              → OrbitalLens 7-day sign readout (dawn+dusk)
  GET /api/journal               → get journal entries from Supabase
  POST /api/journal              → save journal entry to Supabase
  POST /api/profile              → save new member signup to Supabase
"""

import math
import os
import json
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS

try:
    import ephem
    EPHEM_OK = True
except ImportError:
    EPHEM_OK = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────────────
# SUPABASE CONFIG
# ─────────────────────────────────────────────
# Credentials loaded from environment variables (set in Render.com dashboard)
# Never hardcode credentials in source code

SUPA_URL = os.environ.get('SUPABASE_URL', '')
SUPA_KEY = os.environ.get('SUPABASE_ANON_KEY', '')

def supa_headers():
    return {
        'apikey': SUPA_KEY,
        'Authorization': f'Bearer {SUPA_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal',
    }

def supa_insert(table, row):
    """Insert a row into a Supabase table."""
    if not SUPA_URL or not SUPA_KEY:
        return False
    try:
        r = requests.post(
            f'{SUPA_URL}/rest/v1/{table}',
            headers=supa_headers(),
            json=row,
            timeout=5
        )
        return r.ok
    except Exception:
        return False

def supa_select(table, limit=50, order='created_at.desc'):
    """Select rows from a Supabase table."""
    if not SUPA_URL or not SUPA_KEY:
        return []
    try:
        r = requests.get(
            f'{SUPA_URL}/rest/v1/{table}?order={order}&limit={limit}',
            headers={'apikey': SUPA_KEY, 'Authorization': f'Bearer {SUPA_KEY}'},
            timeout=5
        )
        return r.json() if r.ok else []
    except Exception:
        return []



# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

SIGNS = [
    'Aries','Taurus','Gemini','Cancer','Leo','Virgo',
    'Libra','Scorpio','Sagittarius','Capricorn','Aquarius','Pisces'
]
SIGN_GLYPHS  = ['♈','♉','♊','♋','♌','♍','♎','♏','♐','♑','♒','♓']
SIGN_EL      = ['Fire','Earth','Air','Water','Fire','Earth',
                'Air','Water','Fire','Earth','Air','Water']
SIGN_MOD     = ['Cardinal','Fixed','Mutable'] * 4
SIGN_RULERS  = ['Mars','Venus','Mercury','Moon','Sun','Mercury',
                'Venus','Pluto','Jupiter','Saturn','Uranus','Neptune']

DAY_RULERS = ['Sun','Moon','Mars','Mercury','Jupiter','Venus','Saturn']
DAY_GLYPHS = {
    'Sun':'☉','Moon':'☽','Mars':'♂','Mercury':'☿',
    'Jupiter':'♃','Venus':'♀','Saturn':'♄'
}

# Ophiuchus zone: 27° Sco → 27° Sag = 237°–267° ecliptic
OPH_MIN, OPH_MAX = 237.0, 267.0

# OrbitalLens constants
ISS_PERIOD_MIN  = 92.68          # minutes per orbit
ISS_NATAL_JD    = 2451850.93264  # Nov 2 2000 10:21 UTC — Expedition 1

SIGN_THEMES = {
    'Aries':       'Ignition · Bold action · New fire',
    'Taurus':      'Groundedness · Sensory presence · Patience',
    'Gemini':      'Communication · Quick thinking · Duality',
    'Cancer':      'Emotional depth · Nourishment · Inner life',
    'Leo':         'Visibility · Creative fire · Heart open',
    'Virgo':       'Precision · Service · Sacred detail',
    'Libra':       'Balance · Beauty · Right relationship',
    'Scorpio':     'Transformation · Depth · Power',
    'Sagittarius': 'Expansion · Vision · Truth-seeking',
    'Capricorn':   'Structure · Mastery · Long-term build',
    'Aquarius':    'Innovation · Collective · The future',
    'Pisces':      'Intuition · Compassion · The invisible',
}

MOON_PHASES = [
    ('New Moon',        '🌑',   0.0,  22.5),
    ('Waxing Crescent', '🌒',  22.5,  67.5),
    ('First Quarter',   '🌓',  67.5, 112.5),
    ('Waxing Gibbous',  '🌔', 112.5, 157.5),
    ('Full Moon',       '🌕', 157.5, 202.5),
    ('Waning Gibbous',  '🌖', 202.5, 247.5),
    ('Last Quarter',    '🌗', 247.5, 292.5),
    ('Waning Crescent', '🌘', 292.5, 360.0),
]

# 2026 verified retrograde data
RETROGRADES_2026 = [
    {'planet':'Mercury','g':'☿','sign':'Pisces 22°',
     'period':'Feb 26 – Mar 20, 2026',
     'shadow':'Pre-shadow: Feb 11 · Post-shadow: Apr 9, 2026',
     'tip':'Review before acting. Back up files. Avoid signing contracts.'},
    {'planet':'Jupiter','g':'♃','sign':'Cancer 15°',
     'period':'Nov 11, 2025 – Mar 10, 2026',
     'shadow':'Pre-shadow: Aug 17, 2025 · Post-shadow: Jun 6, 2026',
     'tip':'Expansion returns forward. Home and abundance themes unlock.'},
    {'planet':'Mercury','g':'☿','sign':'Cancer 26°',
     'period':'Jun 29 – Jul 23, 2026',
     'shadow':'Pre-shadow: Jun 12 · Post-shadow: Aug 6, 2026',
     'tip':'Emotional communication goes foggy. Back up data.'},
    {'planet':'Saturn','g':'♄','sign':'Aries 14°',
     'period':'Jul 26 – Dec 10, 2026',
     'shadow':'Pre-shadow: Apr 20, 2026',
     'tip':'Karmic review in fiery Aries. Revisit structures and long-term responsibilities.'},
    {'planet':'Neptune','g':'♆','sign':'Aries 4°',
     'period':'Jul 7 – Dec 12, 2026',
     'shadow':'Pre-shadow: Mar 16, 2026',
     'tip':'Illusions dissolve. Spiritual clarity and raw truth emerge.'},
    {'planet':'Pluto','g':'♇','sign':'Aquarius 5°',
     'period':'May 6 – Oct 15, 2026',
     'shadow':'Pre-shadow: Jan 12, 2026',
     'tip':'Deep transformation surfaces for healing. Shadow integration time.'},
    {'planet':'Uranus','g':'⛢','sign':'Gemini 5°',
     'period':'Sep 10, 2026 – Feb 8, 2027',
     'shadow':'Pre-shadow: May 21, 2026',
     'tip':'Inner revolution in Gemini. Rewire thinking patterns.'},
    {'planet':'Venus','g':'♀','sign':'Scorpio 26° → Libra',
     'period':'Oct 3 – Nov 13, 2026',
     'shadow':'Pre-shadow: Sep 1, 2026',
     'tip':'Relationships and values under review. Old connections resurface.'},
    {'planet':'Mercury','g':'☿','sign':'Scorpio 20°',
     'period':'Oct 24 – Nov 13, 2026',
     'shadow':'Pre-shadow: Oct 4 · Post-shadow: Nov 29, 2026',
     'tip':'Deep secrets surface. Research and hidden truth favored.'},
    {'planet':'Mars','g':'♂','sign':'Virgo 10°',
     'period':'Jan 10 – Apr 1, 2027',
     'shadow':'Shadow begins Nov 5, 2026',
     'tip':'No Mars retrograde in 2026. Shadow begins Nov 5 — slow strategy review.'},
]

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def jdn(y, m, d, h=12.0):
    if m <= 2:
        y -= 1; m += 12
    A = int(y / 100)
    B = 2 - A + int(A / 4)
    return int(365.25*(y+4716)) + int(30.6001*(m+1)) + d + h/24.0 + B - 1524.5

def norm(x):
    return ((x % 360) + 360) % 360

def lon_to_sign(lon):
    n = norm(lon)
    idx = int(n / 30)
    deg = round(n - idx*30, 2)
    oph = OPH_MIN <= n <= OPH_MAX
    return {
        'sign':    SIGNS[idx],
        'glyph':   SIGN_GLYPHS[idx],
        'degree':  deg,
        'element': SIGN_EL[idx],
        'modality':SIGN_MOD[idx],
        'ruler':   SIGN_RULERS[idx],
        'longitude': round(n, 4),
        'ophiuchus': oph,
        'ophiuchus_note': (
            'Ophiuchus zone (27°Sco–27°Sag) — '
            'read Scorpio AND Sagittarius + Asclepius archetype'
        ) if oph else '',
    }

def phase_from_elong(elong):
    for name, icon, lo, hi in MOON_PHASES:
        if lo <= elong < hi:
            return name, icon
    return 'Waning Crescent', '🌘'

def parse_retro_date(s, fallback_year):
    """Parse retrograde date string robustly — handles cross-year retrogrades."""
    months = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,
              'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
    parts = s.strip().replace(',','').split()
    m = months.get(parts[0], 1)
    d = int(parts[1]) if len(parts) > 1 else 1
    y = fallback_year
    for p in parts:
        try:
            n = int(p)
            if 2000 < n < 2100:
                y = n
                break
        except ValueError:
            pass
    return datetime(y, m, d, tzinfo=timezone.utc)

def is_active_retro(period):
    try:
        parts = [p.strip() for p in period.replace('–','—').split('—')]
        if len(parts) < 2:
            return False
        end_parts = parts[1].split()
        yr = datetime.now().year
        for p in end_parts:
            try:
                n = int(p.replace(',',''))
                if 2000 < n < 2100:
                    yr = n
                    break
            except ValueError:
                pass
        start = parse_retro_date(parts[0], yr)
        end   = parse_retro_date(parts[1], yr)
        now   = datetime.now(timezone.utc)
        return start <= now <= end
    except Exception:
        return False

# ─────────────────────────────────────────────
# VSOP87 FALLBACK (if ephem not installed)
# ─────────────────────────────────────────────

def vsop87_planets(dt):
    jd = jdn(dt.year, dt.month, dt.day,
             dt.hour + dt.minute/60.0 + dt.second/3600.0)
    T = (jd - 2451545.0) / 36525.0

    def sinD(x): return math.sin(math.radians(x))

    L = {
        'Sun':     norm(280.46646 + 36000.76983*T),
        'Moon':    norm(218.3165  + 481267.8813*T),
        'Mercury': norm(252.2509  + 149472.6747*T),
        'Venus':   norm(181.9798  + 58517.8157 *T),
        'Mars':    norm(355.4330  + 19140.2993 *T),
        'Jupiter': norm(34.3515   + 3034.9057  *T),
        'Saturn':  norm(50.0774   + 1222.1138  *T),
        'Uranus':  norm(314.0550  + 428.4612   *T),
        'Neptune': norm(304.3487  + 218.4862   *T),
        'Pluto':   norm(238.9290  + 145.1843   *T),
    }
    Ms = norm(357.5291 + 35999.0503*T)
    L['Sun'] = norm(L['Sun'] + 1.9146*sinD(Ms) + 0.0200*sinD(2*Ms))

    D  = norm(297.8502 + 445267.1115*T)
    Mm = norm(134.9634 + 477198.8676*T)
    F  = norm(93.2721  + 483202.0175*T)
    L['Moon'] = norm(L['Moon']
        + 6.2888*sinD(Mm) + 1.2740*sinD(2*D-Mm)
        + 0.6583*sinD(2*D) + 0.2136*sinD(2*Mm)
        - 0.1851*sinD(Ms)  - 0.1143*sinD(2*F))

    nn = norm(125.0445 - 1934.1362*T)
    L['NorthNode'] = nn
    L['SouthNode'] = norm(nn + 180)
    return L, T

def retro_vsop(planet, T):
    if planet in ('Sun','Moon','NorthNode','SouthNode'):
        return False
    rates = {
        'Mercury':149472.6747,'Venus':58517.8157,'Mars':19140.2993,
        'Jupiter':3034.9057,'Saturn':1222.1138,'Uranus':428.4612,
        'Neptune':218.4862,'Pluto':145.1843,
    }
    bases = {
        'Mercury':252.2509,'Venus':181.9798,'Mars':355.4330,
        'Jupiter':34.3515,'Saturn':50.0774,'Uranus':314.0550,
        'Neptune':304.3487,'Pluto':238.9290,
    }
    dt = 1.0/36525.0
    l1 = norm(bases[planet] + rates[planet]*(T-dt))
    l2 = norm(bases[planet] + rates[planet]*(T+dt))
    diff = l2 - l1
    if diff >  180: diff -= 360
    if diff < -180: diff += 360
    return diff < 0

# ─────────────────────────────────────────────
# EPHEM ENGINE (high precision)
# ─────────────────────────────────────────────

EPHEM_BODIES = {
    'Sun': 'Sun', 'Moon': 'Moon', 'Mercury': 'Mercury',
    'Venus': 'Venus', 'Mars': 'Mars', 'Jupiter': 'Jupiter',
    'Saturn': 'Saturn', 'Uranus': 'Uranus',
    'Neptune': 'Neptune',
}

def get_planets_ephem(dt):
    now = ephem.Date(dt.strftime('%Y/%m/%d %H:%M:%S'))
    results = {}

    for name, _ in EPHEM_BODIES.items():
        try:
            body = getattr(ephem, name)()
            body.compute(now)
            ecl = ephem.Ecliptic(body, epoch=now)
            lon_deg = math.degrees(ecl.lon)
            sign_data = lon_to_sign(lon_deg)

            retro = False
            if name not in ('Sun', 'Moon'):
                b2 = getattr(ephem, name)()
                b2.compute(ephem.Date(now - 1))
                e2 = ephem.Ecliptic(b2, epoch=now)
                diff = lon_deg - math.degrees(e2.lon)
                if diff >  180: diff -= 360
                if diff < -180: diff += 360
                retro = diff < 0

            results[name] = {**sign_data, 'retrograde': retro}
        except Exception:
            pass

    # North/South Node via VSOP87
    dt_utc = dt.replace(tzinfo=None) if dt.tzinfo else dt
    lons, _ = vsop87_planets(dt_utc)
    results['NorthNode'] = {**lon_to_sign(lons['NorthNode']), 'retrograde': False}
    results['SouthNode'] = {**lon_to_sign(lons['SouthNode']), 'retrograde': False}
    return results

def get_planets_vsop(dt):
    lons, T = vsop87_planets(dt)
    return {
        p: {**lon_to_sign(lon), 'retrograde': retro_vsop(p, T)}
        for p, lon in lons.items()
    }

def get_planets(dt):
    if EPHEM_OK:
        try:
            return get_planets_ephem(dt)
        except Exception:
            pass
    return get_planets_vsop(dt)

# ─────────────────────────────────────────────
# MOON PHASE
# ─────────────────────────────────────────────

def get_moon_phase(dt, planets=None):
    if EPHEM_OK:
        try:
            now = ephem.Date(dt.strftime('%Y/%m/%d %H:%M:%S'))
            moon = ephem.Moon(); moon.compute(now)
            sun  = ephem.Sun();  sun.compute(now)
            ecl_m = ephem.Ecliptic(moon, epoch=now)
            ecl_s = ephem.Ecliptic(sun,  epoch=now)
            elong = norm(math.degrees(ecl_m.lon) - math.degrees(ecl_s.lon))
            illum = round(moon.phase, 1)
            name, icon = phase_from_elong(elong)
            moon_sign = lon_to_sign(math.degrees(ecl_m.lon))
            return {
                'phase': name, 'icon': icon,
                'illumination': illum, 'elongation': round(elong,1),
                'sign': moon_sign['sign'], 'glyph': moon_sign['glyph'],
                'degree': moon_sign['degree'],
            }
        except Exception:
            pass

    # VSOP fallback
    if planets:
        sun_lon  = planets.get('Sun',  {}).get('longitude', 0)
        moon_lon = planets.get('Moon', {}).get('longitude', 0)
    else:
        lons, _ = vsop87_planets(dt)
        sun_lon  = lons['Sun']
        moon_lon = lons['Moon']
    elong = norm(moon_lon - sun_lon)
    illum = round((1 - math.cos(math.radians(elong))) / 2 * 100, 1)
    name, icon = phase_from_elong(elong)
    ms = lon_to_sign(moon_lon)
    return {
        'phase': name, 'icon': icon,
        'illumination': illum, 'elongation': round(elong,1),
        'sign': ms['sign'], 'glyph': ms['glyph'], 'degree': ms['degree'],
    }

# ─────────────────────────────────────────────
# SUN TIMES
# ─────────────────────────────────────────────

def get_sun_times(dt, lat, lon):
    if not EPHEM_OK:
        return {'sunrise':'N/A','sunset':'N/A','daylight':'N/A',
                'moonrise':'N/A','moonset':'N/A',
                'note':'Install ephem for accurate sun/moon times'}
    try:
        obs = ephem.Observer()
        obs.lat = str(lat); obs.lon = str(lon)
        obs.date = ephem.Date(dt.strftime('%Y/%m/%d 12:00:00'))
        obs.horizon = '-0:34'
        sun  = ephem.Sun()
        moon = ephem.Moon()

        def fmt(t):
            if t is None: return '—'
            try:
                return ephem.localtime(t).strftime('%H:%M')
            except Exception:
                return '—'

        sr = obs.next_rising(sun)
        ss = obs.next_setting(sun)
        mr = obs.next_rising(moon)
        ms = obs.next_setting(moon)
        daylight = ''
        if sr and ss:
            hrs = (ephem.localtime(ss) - ephem.localtime(sr)).seconds/3600
            daylight = f'{hrs:.1f}h'
        return {
            'sunrise': fmt(sr), 'sunset': fmt(ss),
            'daylight': daylight,
            'moonrise': fmt(mr), 'moonset': fmt(ms),
        }
    except Exception as e:
        return {'sunrise':'N/A','sunset':'N/A','daylight':'N/A',
                'moonrise':'N/A','moonset':'N/A','error':str(e)}

# ─────────────────────────────────────────────
# DAY RULER
# ─────────────────────────────────────────────

def get_day_info(dt):
    # weekday(): Mon=0 Sun=6 → convert to Sun=0 Mon=1 … Sat=6
    day_idx = (dt.weekday() + 1) % 7
    ruler = DAY_RULERS[day_idx]
    return {
        'weekday':    dt.strftime('%A'),
        'date':       dt.strftime('%B %d, %Y'),
        'iso':        dt.strftime('%Y-%m-%d'),
        'ruler':      ruler,
        'ruler_glyph':DAY_GLYPHS[ruler],
    }

# ─────────────────────────────────────────────
# RETROGRADE STATUS
# ─────────────────────────────────────────────

def get_active_retrogrades():
    active   = [r for r in RETROGRADES_2026 if is_active_retro(r['period'])]
    upcoming = [r for r in RETROGRADES_2026 if not is_active_retro(r['period'])]
    return {'active': active, 'upcoming': upcoming, 'all': RETROGRADES_2026}

# ─────────────────────────────────────────────
# ORBITALLENS — ISS PLANETARY CHART ENGINE
# Algorithm: Sub-solar point method — SonyaClaire, 2026
# ─────────────────────────────────────────────

def fetch_iss_position():
    """Fetch live ISS position from wheretheiss.at API."""
    try:
        r = requests.get(
            'https://api.wheretheiss.at/v1/satellites/25544',
            timeout=4
        )
        if r.ok:
            return r.json(), False
    except Exception:
        pass

    # Fallback: approximate from mean orbital motion
    jd_now = jdn(*datetime.now(timezone.utc).timetuple()[:3],
                 datetime.now(timezone.utc).hour +
                 datetime.now(timezone.utc).minute/60.0)
    minutes_since_natal = (jd_now - ISS_NATAL_JD) * 1440
    lon = norm((minutes_since_natal * (360 / ISS_PERIOD_MIN)))
    return {
        'latitude': 51.6,
        'longitude': lon,
        'altitude': 408,
        'velocity': 27600,
        'timestamp': datetime.now(timezone.utc).timestamp(),
    }, True  # True = approximated

def iss_sign_at(sun_lon_now, iss_lon_now, now_dt, target_dt):
    """Compute ISS ecliptic sign at a future/past UTC moment."""
    day_offset = (target_dt - now_dt).total_seconds() / 86400.0
    min_offset  = (target_dt - now_dt).total_seconds() / 60.0
    sun_lon  = norm(sun_lon_now + day_offset * 0.9856)
    iss_lon  = norm(iss_lon_now + min_offset * (360 / ISS_PERIOD_MIN))
    iss_ecl  = norm(sun_lon + iss_lon)
    idx      = int(iss_ecl / 30)
    deg      = round(iss_ecl % 30, 1)
    oph      = OPH_MIN <= iss_ecl <= OPH_MAX
    return {
        'sign':       SIGNS[idx],
        'glyph':      SIGN_GLYPHS[idx],
        'degree':     deg,
        'ecliptic_lon': round(iss_ecl, 2),
        'ophiuchus':  oph,
        'theme':      SIGN_THEMES.get(SIGNS[idx], ''),
    }

def build_iss_chart(pos, approximated, planets):
    """Build complete OrbitalLens ISS natal-style chart."""
    # Sun longitude from precision planet data
    sun_data = planets.get('Sun', {})
    sun_lon  = (SIGNS.index(sun_data.get('sign','Aries')) * 30
                + sun_data.get('degree', 0))

    # STEP 1 — ISS Sun Sign (Sub-solar method)
    iss_ecl  = norm(sun_lon + pos['longitude'])
    idx      = int(iss_ecl / 30)
    deg      = round(iss_ecl % 30, 1)
    oph      = OPH_MIN <= iss_ecl <= OPH_MAX

    # STEP 2 — ISS Moon (orbital phase within 92.68min cycle)
    jd_now = jdn(
        *datetime.now(timezone.utc).timetuple()[:3],
        datetime.now(timezone.utc).hour +
        datetime.now(timezone.utc).minute/60.0
    )
    orbits_since_natal = (jd_now - ISS_NATAL_JD) * 1440 / ISS_PERIOD_MIN
    frac = orbits_since_natal % 1
    moon_elong = frac * 360
    moon_phase_name, moon_phase_icon = phase_from_elong(moon_elong)
    moon_lon  = norm(iss_ecl + moon_elong)
    moon_sign = SIGNS[int(moon_lon / 30)]

    # STEP 3 — Ascendant (local sidereal time at ISS ground track)
    gst = norm(280.46061837 + 360.98564736629 * (jd_now - 2451545.0))
    lst = norm(gst + pos['longitude'])
    asc = SIGNS[int(norm(lst + 90) / 30)]

    # STEP 4 — Midheaven
    mc = SIGNS[int(norm(lst + 180) / 30)]

    # STEP 5 — ISS Nodes
    nn_lon = norm(pos['longitude'] + 90)
    nn = SIGNS[int(nn_lon / 30)]
    sn = SIGNS[int(norm(nn_lon + 180) / 30)]

    # STEP 6 — All planets from ISS ground track (Moon gets parallax correction)
    iss_planets = {}
    for name, pdata in planets.items():
        lon = pdata.get('longitude', 0)
        if name == 'Moon':
            # ~0.9° horizontal parallax at 408km altitude
            parallax = 0.9517 * math.cos(math.radians(pos.get('latitude', 51.6)))
            lon = norm(lon + parallax)
        p_idx = int(lon / 30)
        iss_planets[name] = {
            'sign':      SIGNS[p_idx],
            'glyph':     SIGN_GLYPHS[p_idx],
            'degree':    round(lon % 30, 2),
            'retrograde':pdata.get('retrograde', False),
            'iss_parallax_corrected': name == 'Moon',
        }

    orbit_min  = round(frac * ISS_PERIOD_MIN, 1)
    orbit_pct  = round(frac * 100)
    velocity   = pos.get('velocity', 27600)
    km_s       = round(velocity / 3600, 2) if velocity else 7.66

    return {
        'current_sign':  SIGNS[idx],
        'glyph':         SIGN_GLYPHS[idx],
        'degree':        deg,
        'ecliptic_lon':  round(iss_ecl, 2),
        'ophiuchus':     oph,
        'ophiuchus_note':('Ophiuchus zone (27°Sco–27°Sag) — '
                          'read Scorpio AND Sagittarius + Asclepius') if oph else '',
        'theme':         SIGN_THEMES.get(SIGNS[idx], ''),
        'moon': {
            'phase': moon_phase_name, 'icon': moon_phase_icon,
            'sign': moon_sign, 'elongation': round(moon_elong, 1),
        },
        'ascendant':  asc,
        'midheaven':  mc,
        'north_node': nn,
        'south_node': sn,
        'orbit_progress_pct': orbit_pct,
        'orbit_progress_min': orbit_min,
        'altitude_km':  round(pos.get('altitude', 408), 0),
        'velocity_kms': km_s,
        'latitude':     round(pos.get('latitude',  51.6), 2),
        'longitude':    round(pos.get('longitude',   0.0), 2),
        'planets':      iss_planets,
        'approximated': approximated,
        'natal_note':   'ISS natal: Nov 2 2000, 10:21 UTC — Expedition 1',
        'algorithm':    'Sub-solar point method — SonyaClaire, 2026',
        'tool':         'OrbitalLens',
    }

def build_iss_week(sun_lon_now, iss_lon_now, now_dt):
    """
    7-day OrbitalLens readout.
    Shows sign at DAWN (06:00 UTC) and DUSK (18:00 UTC) each day.
    Honest approach: ISS cycles all 12 signs every ~92min — no dominant day sign.
    Dawn and dusk anchors are meaningful, verifiable, non-misleading.
    """
    days = []
    day_names = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']
    for d in range(7):
        base = now_dt + timedelta(days=d)
        dawn = base.replace(hour=6,  minute=0, second=0, microsecond=0)
        dusk = base.replace(hour=18, minute=0, second=0, microsecond=0)
        dawn_sign = iss_sign_at(sun_lon_now, iss_lon_now, now_dt, dawn)
        dusk_sign = iss_sign_at(sun_lon_now, iss_lon_now, now_dt, dusk)
        days.append({
            'day':   'Today' if d == 0 else ('Tomorrow' if d == 1
                     else day_names[base.weekday()]),
            'date':  base.strftime('%b %d'),
            'is_today': d == 0,
            'dawn': dawn_sign,
            'dusk': dusk_sign,
        })
    return {
        'days': days,
        'note': ('ISS cycles all 12 signs every ~92 min (~7.7 min per sign). '
                 'Dawn (06:00 UTC) and Dusk (18:00 UTC) shown as daily anchors. '
                 'Algorithm: Sub-solar point method — SonyaClaire, 2026. '
                 'Tool: OrbitalLens.'),
    }

# ─────────────────────────────────────────────
# API ROUTES
# ─────────────────────────────────────────────

@app.route('/health')
def health():
    return jsonify({
        'status':    'ok',
        'ephem':     EPHEM_OK,
        'engine':    'ephem' if EPHEM_OK else 'VSOP87',
        'version':   '3.0',
        'tool':      'Cosmic Whispers HUD',
        'iss_tool':  'OrbitalLens',
    })

@app.route('/api/planets')
def api_planets():
    dt = datetime.now(timezone.utc)
    return jsonify({
        'planets':      get_planets(dt),
        'engine':       'ephem' if EPHEM_OK else 'vsop87',
        'computed_utc': dt.isoformat(),
    })

@app.route('/api/moon')
def api_moon():
    dt = datetime.now(timezone.utc)
    planets = get_planets(dt)
    return jsonify({**get_moon_phase(dt, planets),
                    'computed_utc': dt.isoformat()})

@app.route('/api/day')
def api_day():
    dt = datetime.now(timezone.utc)
    return jsonify({**get_day_info(dt), 'computed_utc': dt.isoformat()})

@app.route('/api/sun-times')
def api_sun_times():
    try:
        lat = float(request.args.get('lat', 55.7596))
        lon = float(request.args.get('lon', -120.2370))
    except (TypeError, ValueError):
        lat, lon = 55.7596, -120.2370
    dt = datetime.now(timezone.utc)
    return jsonify(get_sun_times(dt, lat, lon))

@app.route('/api/retrogrades')
def api_retrogrades():
    return jsonify(get_active_retrogrades())

@app.route('/api/iss')
def api_iss():
    """OrbitalLens — full ISS planetary chart."""
    dt = datetime.now(timezone.utc)
    planets = get_planets(dt)
    pos, approximated = fetch_iss_position()
    chart = build_iss_chart(pos, approximated, planets)
    return jsonify({**chart, 'computed_utc': dt.isoformat()})

@app.route('/api/iss/week')
def api_iss_week():
    """OrbitalLens — 7-day dawn/dusk sign readout."""
    dt = datetime.now(timezone.utc)
    planets = get_planets(dt)
    sun_data = planets.get('Sun', {})
    sun_lon  = (SIGNS.index(sun_data.get('sign','Aries')) * 30
                + sun_data.get('degree', 0))
    pos, _ = fetch_iss_position()
    week = build_iss_week(sun_lon, pos['longitude'], dt)
    return jsonify({**week, 'computed_utc': dt.isoformat()})

@app.route('/api/all')
def api_all():
    """Combined endpoint — frontend calls this once on load."""
    try:
        lat = float(request.args.get('lat', 55.7596))
        lon = float(request.args.get('lon', -120.2370))
    except (TypeError, ValueError):
        lat, lon = 55.7596, -120.2370

    dt      = datetime.now(timezone.utc)
    planets = get_planets(dt)
    moon    = get_moon_phase(dt, planets)
    day     = get_day_info(dt)
    sun_t   = get_sun_times(dt, lat, lon)
    retros  = get_active_retrogrades()

    # OrbitalLens ISS
    pos, approximated = fetch_iss_position()
    iss_chart = build_iss_chart(pos, approximated, planets)
    sun_data  = planets.get('Sun', {})
    sun_lon   = (SIGNS.index(sun_data.get('sign','Aries')) * 30
                 + sun_data.get('degree', 0))
    iss_week  = build_iss_week(sun_lon, pos['longitude'], dt)

    return jsonify({
        'planets':      planets,
        'moon':         moon,
        'day':          day,
        'sun_times':    sun_t,
        'retrogrades':  retros,
        'iss':          iss_chart,
        'iss_week':     iss_week,
        'computed_utc': dt.isoformat(),
        'engine':       'ephem' if EPHEM_OK else 'vsop87',
    })

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# DATA API ROUTES (Supabase)
# ─────────────────────────────────────────────

@app.route('/api/journal', methods=['GET'])
def api_journal_get():
    """Get journal entries from Supabase."""
    limit = int(request.args.get('limit', 50))
    rows = supa_select('journal_entries', limit=limit)
    return jsonify({'entries': rows, 'count': len(rows)})

@app.route('/api/journal', methods=['POST'])
def api_journal_post():
    """Save a journal entry to Supabase."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    entry = {
        'id':          data.get('id', int(datetime.now().timestamp() * 1000)),
        'tester_name': data.get('tester_name', 'Seeker'),
        'title':       data.get('title', '(Untitled)'),
        'entry':       data.get('entry', ''),
        'moon_phase':  data.get('moon_phase', ''),
        'planets':     data.get('planets', ''),
        'created_at':  data.get('created_at', datetime.now(timezone.utc).isoformat()),
    }
    ok = supa_insert('journal_entries', entry)
    return jsonify({'success': ok, 'entry': entry})

@app.route('/api/profile', methods=['POST'])
def api_profile_post():
    """Save a user profile (new member signup) to Supabase."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    profile = {
        'display_name':      data.get('display_name', ''),
        'email':             data.get('email', ''),
        'birth_date':        data.get('birth_date') or None,
        'birth_time':        data.get('birth_time') or None,
        'birth_location':    data.get('birth_location', ''),
        'known_time':        data.get('known_time', True),
        'consent_research':  data.get('consent_research', False),
        'include_ris_pilot': data.get('include_ris_pilot', False),
        'created_at':        datetime.now(timezone.utc).isoformat(),
    }
    # Use URL-encoded table name for "User profiles"
    if not SUPA_URL or not SUPA_KEY:
        return jsonify({'success': False, 'error': 'Supabase not configured'})
    try:
        r = requests.post(
            f'{SUPA_URL}/rest/v1/User%20profiles',
            headers=supa_headers(),
            json=profile,
            timeout=5
        )
        return jsonify({'success': r.ok, 'status': r.status_code})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/profiles', methods=['GET'])
def api_profiles_get():
    """Get user profiles (admin use — protect this in production)."""
    rows = supa_select('User%20profiles', limit=100)
    return jsonify({'profiles': rows, 'count': len(rows)})

if __name__ == '__main__':
    port  = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    print(f'✦ Cosmic Whispers API v3.0 — OrbitalLens enabled')
    print(f'  Engine : {"ephem (high precision)" if EPHEM_OK else "VSOP87 (fallback)"}')
    print(f'  Port   : {port}')
    print(f'  Health : http://localhost:{port}/health')
    print(f'  All    : http://localhost:{port}/api/all')
    print(f'  ISS    : http://localhost:{port}/api/iss')
    app.run(host='0.0.0.0', port=port, debug=debug)
