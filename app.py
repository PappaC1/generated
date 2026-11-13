import io
import re
import pdfplumber
import pandas as pd
import numpy as np
import streamlit as st

st.set_page_config(page_title="SA Racing Wizard", layout="wide")
st.title("South African Horseracing Prediction Engine")
st.caption("Supports 4Racing ComputaForm (Vaal, Turffontein, KZN) and Race Coast / TAB (Cape Town, Fairview).")

uploaded_pdf = st.file_uploader("Upload South African ComputaForm / Race Coast PDF", type=["pdf"])

c1, c2, c3, c4, c5 = st.columns(5)
w_speed = c1.slider("Speed & Weight", 0.0, 1.0, 0.35, 0.05)
w_class = c2.slider("Class & MR Drop", 0.0, 1.0, 0.25, 0.05)
w_form = c3.slider("Form & Fitness", 0.0, 1.0, 0.20, 0.05)
w_draw = c4.slider("Draw Bias", 0.0, 1.0, 0.10, 0.05)
w_gear = c5.slider("Gear Upgrades", 0.0, 1.0, 0.10, 0.05)

generate_clicked = st.button("Generate Top 3 Picks, Dark Horses & Value Bets", type="primary", use_container_width=True)


def parse_4racing_page(page, page_idx, seen_races):
    text = page.extract_text() or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = ""
    if page_idx == 0:
        for ln in lines:
            if any(k in ln.upper() for k in ["TAB ", "TURFFONTEIN", "VAAL", "GREYVILLE", "SCOTTSVILLE", "FAIRVIEW"]):
                title = ln
                break

    if "No L3 Name R-1-2-3" not in text or "COMPUTAFORM AT A GLANCE" in text or "HOW TO READ" in text:
        return [], title

    dist_m = re.search(r"\b(\d{4})m\b", text)
    race_dist = int(dist_m.group(1)) if dist_m else 1200

    ref_m = re.search(r"Race Ref:\s*(\d+)", text)
    race_ref = ref_m.group(1) if ref_m else str(page_idx)
    if race_ref in seen_races:
        return [], title
    seen_races.add(race_ref)
    current_race = len(seen_races)

    cf_map, sp_map = {}, {}
    for ln in lines:
        m_rate = re.match(r"^(\d{1,2})\s+([A-Za-z\s\'\-\’]+?)\s+(\d{2,3})\b", ln)
        if not m_rate:
            continue
        h_key = m_rate.group(2).strip().upper()
        val = float(m_rate.group(3))
        if h_key not in cf_map:
            cf_map[h_key] = val
        elif h_key not in sp_map:
            sp_map[h_key] = val

    row_re = re.compile(
        r"^(?P<No>\d{1,2})\s+"
        r"(?:(?P<L3>[0-9pq]+)\s+)?"
        r"(?P<Horse>[A-Z0-9\'\-\’]+(?:\s+[A-Z0-9\'\-\’]+)*?)\s+"
        r"(?P<Runs>\d+)-(?P<Wins>\d+)-(?P<Places2>\d+)-(?P<Places3>\d+)\s+"
        r"(?P<F3>\d+)%\s+"
        r"R(?P<Earn>[\d,]+)\s+"
        r"R(?P<AveEarn>[\d,]+)\s+"
        r"\d[A-Za-z]{1,3}\s+"
        r"(?P<Wt>\d{2}(?:\.\d)?)(?:-\d\.\d|\+\d\.\d)?\s+"
        r"(?P<Draw>\d{1,2})\s+"
        r".*?"
        r"(?P<HMR>\d{2,3}|--)\s+"
        r"(?P<CMR>\d{2,3}|--)\s+"
        r"(?P<Comment>.*?)\s+"
        r"(?P<OddsNum>\d+)-(?P<OddsDen>\d+)$"
    )

    page_runners = []
    for ln in lines:
        rm = row_re.match(ln)
        if not rm:
            continue
        horse_name = rm.group("Horse").strip().upper()
        runs = int(rm.group("Runs"))
        wins = int(rm.group("Wins"))
        places = int(rm.group("Places2")) + int(rm.group("Places3"))
        earn = int(rm.group("Earn").replace(",", ""))
        ave_earn = int(rm.group("AveEarn").replace(",", ""))
        hmr = int(rm.group("HMR")) if rm.group("HMR").isdigit() else 0
        cmr = int(rm.group("CMR")) if rm.group("CMR").isdigit() else 0
        l3_str = rm.group("L3") or ""
        l3_digits = [int(ch) if ch != "0" else 10 for ch in l3_str if ch.isdigit()]
        avg_pos = float(np.mean(l3_digits)) if l3_digits else 6.5
        odds_num, odds_den = float(rm.group("OddsNum")), float(rm.group("OddsDen"))
        fcst_odds = round(odds_num / odds_den, 2) if odds_den > 0 else 15.0
        comment = rm.group("Comment").strip()
        gear_boost = 1.0 if any(g in comment.lower() for g in ["blinkers", "headgear", "tongue", "cheek"]) else 0.0
        mr_drop = max(0, hmr - cmr) if (hmr > 0 and cmr > 0) else 0

        page_runners.append({
            "Race": current_race, "Dist": race_dist, "No": int(rm.group("No")),
            "Horse": horse_name, "Draw": int(rm.group("Draw")), "Wt": float(rm.group("Wt")),
            "MR": cmr, "MR_Drop": mr_drop, "Gear_Boost": gear_boost,
            "Runs": runs, "Wins": wins, "Places": places, "Stakes": earn,
            "Earnings_Per_Run": float(ave_earn),
            "Place_Strike": (wins * 2 + places) / runs if runs > 0 else 0.25,
            "Speed_Index": sp_map.get(horse_name, cf_map.get(horse_name, 35.0)),
            "Avg_Lengths_Btn": avg_pos,
            "Days_Rested": 45 if "rest" in comment.lower() else 21,
            "Last_Odds": fcst_odds, "Comment": comment,
        })
    return page_runners, title


def parse_4racing_computaform(pdf, status_box):
    all_runners = []
    meeting_title = "4Racing ComputaForm Meeting"
    seen_races = set()
    total = len(pdf.pages)
    for idx, page in enumerate(pdf.pages):
        status_box.info(f"Scanning page {idx + 1} of {total}...")
        p_runners, p_title = parse_4racing_page(page, idx, seen_races)
        if p_title:
            meeting_title = p_title
        all_runners.extend(p_runners)
    return pd.DataFrame(all_runners), meeting_title


def finalize_rc_runner(r):
    runs = r["Runs"]
    r["Earnings_Per_Run"] = float(r["Stakes"]) / runs if runs > 0 else 0.0
    r["Place_Strike"] = (r["Wins"] * 2 + r["Places"]) / runs if runs > 0 else 0.25
    r["Speed_Index"] = 50.0 + r["Speed_Rating"] if not np.isnan(r["Speed_Rating"]) else 40.0
    btns = r.pop("Lengths_Behind", [])
    r["Avg_Lengths_Btn"] = float(np.mean(btns[:4])) if btns else 5.0
    return r


def parse_racecoast_page(page, page_idx):
    text = page.extract_text() or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = ""
    if page_idx in (0, 1):
        for ln in lines[:4]:
            if any(k in ln.upper() for k in ["FAIRVIEW", "KENILWORTH", "DURBANVILLE", "RACE COAST", "TAB"]):
                title = ln
                break

    race_header_re = re.compile(r"RACE\s+(\d+)\s*[-–]\s*(?:Abt/)?(\d+)\s*m", re.IGNORECASE)
    race_m = next((race_header_re.search(ln) for ln in lines[:10] if race_header_re.search(ln)), None)
    if not race_m:
        return [], title

    current_race = int(race_m.group(1))
    race_distance = int(race_m.group(2))
    full_text = " ".join(lines)

    speed_map, rest_map = {}, {}
    sp_blk = re.search(r"SPEED RATINGS:\s*(.*?)(?:BEST AVERAGE:|DAYS RESTED:)", full_text)
    if sp_blk:
        for item in sp_blk.group(1).split(";"):
            sm = re.search(r"([A-Za-z\s\'\-\’]+?)\s+(-?\d+\.\d+)", item.strip())
            if sm:
                speed_map[sm.group(1).strip().upper()] = float(sm.group(2))

    rs_blk = re.search(r"DAYS RESTED:\s*(.*?)(?:\b1\s+[A-Z]{2,})", full_text)
    if rs_blk:
        for item in rs_blk.group(1).split(";"):
            rm = re.search(r"([A-Za-z\s\'\-\’]+?)\s*\((\d+)\s*days\)", item.strip(), re.IGNORECASE)
            if rm:
                rest_map[rm.group(1).strip().upper()] = int(rm.group(2))

    runner_re = re.compile(
        r"^(?P<No>\d{1,2})\s+"
        r"(?P<Horse>[A-Z0-9\'\-\’]+(?:\s+[A-Z0-9\'\-\’]+)*?)\s+"
        r"(?:(?P<Gear>[ASLF](?:\s+[BCPXHJKNZte])*)\s+)?"
        r"(?P<Draw>\d{1,2}|RESERVE\s*\d)\s+"
        r"(?P<Weight>\d{2}(?:\.\d)?)"
        r"(?:\s+\((?P<MR>\d+)\))?"
        r"(?:\s+\[(?P<LastMR>\d+)\])?"
    )
    run_re = re.compile(r"^(?P<Date>\d{2}\.\d{2}\.\d{2})\s+.*?\b(?P<Dist>\d{3,4})\b.*?\b(?P<Pos>\d{1,2})-(?P<Field>\d{1,2})\s+(?P<Btn>\d+\.\d{2}|\d+)")

    page_runners = []
    curr = None
    for line in lines:
        rm = runner_re.match(line)
        if rm:
            if curr:
                page_runners.append(finalize_rc_runner(curr))
            draw_raw = rm.group("Draw")
            if "RESERVE" in draw_raw.upper():
                curr = None
                continue
            h_name = rm.group("Horse").strip().upper()
            mr_val = int(rm.group("MR")) if rm.group("MR") else 0
            last_mr = int(rm.group("LastMR")) if rm.group("LastMR") else mr_val
            gear_str = rm.group("Gear") or ""
            curr = {
                "Race": current_race, "Dist": race_distance, "No": int(rm.group("No")),
                "Horse": h_name, "Draw": int(draw_raw) if draw_raw.isdigit() else 8,
                "Wt": float(rm.group("Weight")), "MR": mr_val, "MR_Drop": max(0, last_mr - mr_val),
                "Gear_Boost": 1.0 if any(g in gear_str.split() for g in ["B", "P", "X", "C", "t"]) else 0.0,
                "Runs": 0, "Wins": 0, "Places": 0, "Stakes": 0,
                "Speed_Rating": speed_map.get(h_name, np.nan), "Days_Rested": rest_map.get(h_name, 21),
                "Comment": "", "Last_Odds": 12.0, "Lengths_Behind": [],
            }
            continue

        if curr is None:
            continue

        st_m = re.search(r"Runs:\s*(\d+)\s+Wins:\s*(\d+)\s+Places:\s*(\d+)\s+Stakes Won:\s*R([\d,]+)", line)
        if st_m:
            curr["Runs"] = int(st_m.group(1))
            curr["Wins"] = int(st_m.group(2))
            curr["Places"] = int(st_m.group(3))
            curr["Stakes"] = int(st_m.group(4).replace(",", ""))
            continue

        od_m = re.search(r"(?:Forecast|Betting|Odds).*?(\d+)\s*[-/]\s*(\d+)", line, re.IGNORECASE)
        if od_m and float(od_m.group(2)) > 0:
            curr["Last_Odds"] = round(float(od_m.group(1)) / float(od_m.group(2)), 2)

        if line.startswith("COMMENT:") or line.startswith("TRAINER COMMENT:"):
            curr["Comment"] = line.split(":", 1).pop().strip()
            continue

        rn_m = run_re.match(line)
        if rn_m and rn_m.group("Btn").replace(".", "", 1).isdigit():
            curr["Lengths_Behind"].append(float(rn_m.group("Btn")))

    if curr:
        page_runners.append(finalize_rc_runner(curr))
    return page_runners, title


def parse_racecoast_pdf(pdf, status_box):
    all_runners = []
    meeting_title = "Race Coast / TAB Meeting"
    total = len(pdf.pages)
