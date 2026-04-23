# campusalert/ml/train.py

"""
CampusAlert XGBoost Urgency Classifier — Training Script (Phase 2).

Run this once to produce model.pkl and vectorizer.pkl:
    cd campusalert/website
    python ml/train.py

What this script does:
    1. Loads data (CrisisLex/HumAID CSV + synthetic campus alerts)
    2. Relabels to 4 CampusAlert urgency classes
    3. Cleans and normalises text
    4. Splits 80/20 (stratified)
    5. Vectorizes with TF-IDF (unigrams + bigrams, 5,000 features)
    6. Balances with SMOTE (oversamples minority classes)
    7. Trains XGBoost
    8. Evaluates: accuracy, precision, recall, F1, false alarm rate
    9. Saves model.pkl and vectorizer.pkl
    10. Prints a full classification report

PRD targets (§2.2 / §9):
    Overall accuracy   >= 80%
    False alarm rate   <  5%

Data sources:
    CrisisLex: https://crisislex.org/data-collections.html
    HumAID:    https://crisisnlp.qcri.org/humaid_dataset.html
    Place at:  ml/data/crisislex.csv  or  ml/data/humaid.csv

Usage:
    python ml/train.py
    python ml/train.py --data-path ml/data/crisislex.csv
    python ml/train.py --data-path ml/data/humaid.csv --output-dir ml/
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s — %(message)s')
logger = logging.getLogger('campusalert.ml')

URGENCY_TO_LABEL = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
LABEL_TO_URGENCY = {v: k for k, v in URGENCY_TO_LABEL.items()}

# ─── Expanded Synthetic Dataset ───────────────────────────────────────────────
# ~55 examples per class → ~220 total.
# Variety in phrasing, word choice, and sentence structure is essential so
# TF-IDF features generalise rather than memorising exact phrases.
# Campus-specific language (Covenant University halls, chapel, Nigerian English)
# is intentionally mixed with generic emergency phrasing.

SYNTHETIC_SAMPLES = [

    # ── CRITICAL (55 samples) ─────────────────────────────────────────────────
    ('FIRE ALARM: Immediate evacuation of Daniel Hall required. All students leave now.', 'critical'),
    ('Emergency: Armed intruder reported near the library. Lockdown in effect immediately.', 'critical'),
    ('URGENT: Gas explosion in the chemistry lab. Evacuate the science block now.', 'critical'),
    ('Bomb threat received at the chapel. Evacuate the entire area immediately.', 'critical'),
    ('Medical emergency at Oduduwa Hall. Ambulance en route. Clear the entrance.', 'critical'),
    ('Evacuation order: Structural collapse risk in Block C. All occupants must exit now.', 'critical'),
    ('Active shooter alert near the cafeteria. Shelter in place. Do not use main entrance.', 'critical'),
    ('Fatality reported on campus. Emergency services responding. Avoid sports complex.', 'critical'),
    ('EMERGENCY: Hostage situation reported at the administrative building.', 'critical'),
    ('Fire outbreak in the female hostel. Evacuate immediately. Fire service alerted.', 'critical'),
    ('CRITICAL: Explosion heard near the engineering complex. Evacuate the entire block.', 'critical'),
    ('Armed robbery in progress at the main gate. Do not approach. Lockdown now.', 'critical'),
    ('Massive gas leak detected in the cafeteria. All occupants must leave immediately.', 'critical'),
    ('Building collapse at the Faculty of Sciences. Multiple casualties reported.', 'critical'),
    ('EMERGENCY EVACUATION: Toxic chemical spill in the biochemistry lab. Leave now.', 'critical'),
    ('Gunshots fired near the sports complex. Lockdown in effect. Stay indoors.', 'critical'),
    ('Fire spreading rapidly from Block A to Block B hostels. Evacuate all floors.', 'critical'),
    ('Critical emergency: Student found unconscious in the hostel. Ambulance dispatched.', 'critical'),
    ('Bomb squad on campus responding to a threat at Peniel Hall. Clear the area now.', 'critical'),
    ('Structural failure imminent in the old lecture theatre. Evacuate immediately.', 'critical'),
    ('Armed men sighted inside the female hostel. All students remain in rooms and lock doors.', 'critical'),
    ('ALERT: Fatal accident at the campus junction. Emergency response team deployed.', 'critical'),
    ('Evacuation in progress at the auditorium due to fire. Do not use elevators.', 'critical'),
    ('Electrical fire in the ICT building. Evacuate now. Do not use lifts.', 'critical'),
    ('LOCKDOWN: Dangerous suspect on campus. Remain indoors. Secure doors and windows.', 'critical'),
    ('Multiple students trapped after a lab explosion at the chemistry department.', 'critical'),
    ('Emergency: Severe flooding inside Shalom Hall. Evacuate to higher ground now.', 'critical'),
    ('Armed assailant reported inside the library. All persons must exit immediately.', 'critical'),
    ('Gas cylinder explosion behind the student cafeteria. Evacuate the surrounding buildings.', 'critical'),
    ('URGENT: Student suffering from cardiac arrest near the admin block. Paramedics called.', 'critical'),
    ('Riot breaking out near the main gate. Do not go outside. Campus is on lockdown.', 'critical'),
    ('Serious accident on the campus road. Multiple students injured. Avoid the area.', 'critical'),
    ('Critical: Roof of Grace Hall collapsed. Rescue teams responding. Stay away.', 'critical'),
    ('Intruder armed with a weapon spotted near Peniel Hall. Lockdown in effect.', 'critical'),
    ('Emergency services responding to a massive fire at the engineering workshop.', 'critical'),
    ('EVACUATION ALERT: Entire science complex must be cleared immediately due to gas hazard.', 'critical'),
    ('Student attacked and seriously injured near the back gate. Police and ambulance en route.', 'critical'),
    ('Power surge caused equipment fire in the electronics lab. Exit the building now.', 'critical'),
    ('Bomb disposal unit called to the administrative block. All staff and students evacuate.', 'critical'),
    ('CRITICAL: Overcrowding and stampede in the auditorium. Multiple students hurt.', 'critical'),
    ('Outbreak of fire in the university store. Avoid the storage area completely.', 'critical'),
    ('Active emergency: Runaway vehicle has hit students near the hostel entrance.', 'critical'),
    ('All students must leave the female hostel block immediately. Security threat confirmed.', 'critical'),
    ('Collapse of scaffolding near the new building. Workers and students injured. Stay back.', 'critical'),
    ('FIRE: Flames visible from the rooftop of the Faculty of Law. Evacuate now.', 'critical'),
    ('Chemical explosion in the research lab. Hazardous fumes spreading. Leave the area.', 'critical'),
    ('Emergency lockdown: Gunman reported inside the campus boundary. Do not go outside.', 'critical'),
    ('Meningitis outbreak confirmed on campus. Multiple critical cases. Report to clinic now.', 'critical'),
    ('Security breach: Unknown individuals with weapons entered through the back gate.', 'critical'),
    ('Mass food poisoning incident. Over twenty students hospitalised. Avoid the cafeteria.', 'critical'),
    ('IMMEDIATE EVACUATION: Gas main burst beneath the academic complex. Leave now.', 'critical'),
    ('Fatal stabbing incident near the football field. Police on scene. Avoid the area.', 'critical'),
    ('Emergency: Student fell from the third floor of Judah Hall. Ambulance dispatched.', 'critical'),
    ('Toxic smoke filling the corridor of Block D. Evacuate immediately through fire exits.', 'critical'),
    ('CRITICAL ALERT: Earthquake tremor felt on campus. Evacuate all buildings immediately.', 'critical'),

    # ── HIGH (55 samples) ─────────────────────────────────────────────────────
    ('Power outage affecting the entire campus. Generator backup active for essentials.', 'high'),
    ('Security breach at the main gate. Unknown individuals on campus. Stay indoors.', 'high'),
    ('Flood warning: Heavy rainfall causing flooding near Hall D. Avoid low-lying areas.', 'high'),
    ('Gas leak reported in the engineering block. Hazmat team notified. Stay away.', 'high'),
    ('Student injured in road accident near the campus gate. Ambulance dispatched.', 'high'),
    ('Police presence on campus. An arrest has been made. Situation under control.', 'high'),
    ('Water supply contamination suspected. Do not drink tap water until further notice.', 'high'),
    ('Major security incident at the male hostel. All students restrict movement.', 'high'),
    ('Dangerous suspect sighted near the sports complex. Avoid the area.', 'high'),
    ('Medical alert: Multiple students reported injured after a laboratory accident.', 'high'),
    ('Total power failure across campus. Backup generators running for critical services only.', 'high'),
    ('Large tree fallen across the road between the hostels and lecture halls. Use alternate route.', 'high'),
    ('Security patrol has been doubled following a theft incident at the bookshop.', 'high'),
    ('Heavy rainfall has caused structural damage to the roof of Block F. Residents must relocate.', 'high'),
    ('Water main burst near the Faculty of Management Sciences. Road is impassable.', 'high'),
    ('Unidentified person seen climbing the perimeter fence near the female hostel. Security alerted.', 'high'),
    ('Food poisoning suspected among students who ate from the roadside vendor near the gate.', 'high'),
    ('Electrical fault caused partial blackout in the ICT centre and adjacent buildings.', 'high'),
    ('Ambulance on campus for student with severe allergic reaction. Keep route to gate clear.', 'high'),
    ('Campus clinic is overwhelmed. Minor cases should use the external clinic until further notice.', 'high'),
    ('Widespread internet outage caused by fibre cut. No ETA for restoration. Use mobile data.', 'high'),
    ('Multiple thefts reported in the male hostel last night. Secure all valuables immediately.', 'high'),
    ('Flash flood alert issued for areas near the river on the eastern campus boundary.', 'high'),
    ('Construction equipment failure near the new chapel building. Area cordoned off for safety.', 'high'),
    ('Suspicious package found near the admin block. Security team investigating. Avoid the area.', 'high'),
    ('Fever and respiratory illness spreading in Block C. Clinic advises students to report symptoms.', 'high'),
    ('Major accident on the campus access road. Do not use the main gate until police clear the scene.', 'high'),
    ('Power surge damaged equipment in three lecture halls. IT team assessing damage.', 'high'),
    ('Heavy smoke from bush burning near the campus perimeter. Respiratory hazard. Stay indoors.', 'high'),
    ('Gas supply disrupted to all hostels. No cooking gas until the line is repaired.', 'high'),
    ('Aggressive stray dogs reported near the sports complex. Avoid the area after dark.', 'high'),
    ('Storm damaged the roof of the female hostel common room. Room closed for repairs.', 'high'),
    ('University health centre reports a rise in malaria cases. Students must use nets and repellents.', 'high'),
    ('Unmarked chemical container found in the biology lab. Lab closed pending hazmat inspection.', 'high'),
    ('Large number of students reporting symptoms of food poisoning after dining at the cafeteria.', 'high'),
    ('Water supply to female hostel cut off due to pipe burst. Emergency bowsers deployed.', 'high'),
    ('Unknown car has been parked near the security office for three days. Report any suspicious activity.', 'high'),
    ('Electrical wiring fault causing intermittent shocks in hostel Block B bathrooms. Report to maintenance.', 'high'),
    ('Strong winds caused damage to building roof near the lecture theatre complex.', 'high'),
    ('Medical evacuation of two students with severe symptoms. Clinic requests non-emergency visits be deferred.', 'high'),
    ('Police checkpoint set up on the campus access road. Allow extra travel time.', 'high'),
    ('Generator fuel shortage. Power rotation will apply from 6pm tonight until supply is restored.', 'high'),
    ('Reported case of meningitis being investigated. Students with symptoms should isolate and visit clinic.', 'high'),
    ('Security cameras detected forced entry attempt at the computer science lab overnight.', 'high'),
    ('Flooding in the ground floor of Block A. Affected students moved to overflow accommodation.', 'high'),
    ('Campus under curfew from 10pm tonight following an external security threat. All must be indoors.', 'high'),
    ('Burst pipe flooding the sports complex changing rooms. Facility temporarily closed.', 'high'),
    ('Power restoration delayed until midnight. Hostel generators running on low fuel.', 'high'),
    ('Medical team on site at the chapel following a student collapsing during service.', 'high'),
    ('Chemical smell reported in the postgraduate hostel. Ventilation engineers called in.', 'high'),
    ('Road accident involving a university bus near the campus junction. Three students injured.', 'high'),
    ('Security dogs deployed following repeated perimeter breach attempts in the past 48 hours.', 'high'),
    ('Petrol generator spill near Block D creates fire risk. Area temporarily off limits.', 'high'),
    ('Student hospitalised after consuming medication without prescription. Report self-medication to clinic.', 'high'),
    ('Transformer fire at the substation affects power to the entire south campus.', 'high'),

    # ── MEDIUM (55 samples) ───────────────────────────────────────────────────
    ('Chapel service cancelled today due to health advisory from the university clinic.', 'medium'),
    ('Second semester exams rescheduled. New timetable on the student portal.', 'medium'),
    ('Health advisory: Reported cases of malaria in Hall F. Visit clinic if unwell.', 'medium'),
    ('Disruption: Road works near main entrance. Use the back gate until further notice.', 'medium'),
    ('Caution: Slippery surfaces near the library walkway. Exercise care.', 'medium'),
    ('University health centre closed tomorrow. Seek alternative medical care.', 'medium'),
    ('Internet services disrupted 10pm to 2am for scheduled maintenance.', 'medium'),
    ('Advisory: Do not consume food from unauthorised vendors on campus.', 'medium'),
    ('Notice: The library will close early today due to a staff function.', 'medium'),
    ('Caution: Unverified reports of theft in the male hostel. Secure valuables.', 'medium'),
    ('The compulsory chapel service tomorrow has been rescheduled from 8am to 10am.', 'medium'),
    ('Exam postponed: The Economics paper scheduled for Tuesday is moved to Thursday.', 'medium'),
    ('Notice: Water supply will be off from 6am to 12pm tomorrow for pipe maintenance.', 'medium'),
    ('Advisory: Avoid purchasing food from vendors outside the main gate this week.', 'medium'),
    ('Disruption: Lift in the academic block is out of service. Use the staircase.', 'medium'),
    ('The clinic will be closed this Saturday. Students requiring urgent care should go to the general hospital.', 'medium'),
    ('Notice: Network maintenance will disrupt Wi-Fi in all hostels from 1am to 4am.', 'medium'),
    ('The cafeteria in the male hostel area will be closed for three days for renovation.', 'medium'),
    ('Advisory: A number of students are experiencing flu-like symptoms. Practise good hygiene.', 'medium'),
    ('Road construction at the back gate means longer delays. Allow extra time when leaving campus.', 'medium'),
    ('Lecture halls in Block B will be without power tomorrow from 9am due to maintenance.', 'medium'),
    ('The academic registry will be closed this afternoon for an internal audit.', 'medium'),
    ('Notice: Some hostels will experience reduced water pressure this week due to ongoing repairs.', 'medium'),
    ('Students are advised to stay inside during the heavy rainfall expected this afternoon.', 'medium'),
    ('Advisory: Mosquito breeding has been detected in drains near Hall C. Take precautions.', 'medium'),
    ('The management meeting will cause disruptions to parking near the admin block today.', 'medium'),
    ('Exam timetable adjustment: Management Science students should check the updated schedule.', 'medium'),
    ('Caution: Loose tiles on the path near the Faculty of Law. Walk carefully.', 'medium'),
    ('Notice: The bookshop will not accept payments by transfer today. Cash only.', 'medium'),
    ('Advisory: Students with dietary allergies should note a menu change in the cafeteria this week.', 'medium'),
    ('Medical notice: Skin rash cases rising. Students are advised to report to the clinic early.', 'medium'),
    ('Generator servicing will cause power interruptions in Blocks C and D from 10am to 2pm.', 'medium'),
    ('The Sunday chapel service will be held outside on the main lawn due to hall renovation.', 'medium'),
    ('Bus service to the off-campus shopping area is suspended this weekend.', 'medium'),
    ('Disruption: Construction noise near the postgraduate quarters may affect study. Plan accordingly.', 'medium'),
    ('Health advisory: High humidity levels this week increase risk of fungal infections. Keep rooms dry.', 'medium'),
    ('Notice: Laboratory sessions for all Year 3 chemistry students are postponed by one week.', 'medium'),
    ('Advisory: Be cautious of fake student portal links circulating on WhatsApp. Use only the official site.', 'medium'),
    ('The faculty of engineering orientation has been moved from Monday to Wednesday.', 'medium'),
    ('Notice: Photocopying services near the library will be unavailable for two days.', 'medium'),
    ('Caution: A minor electrical fault in Block A bathrooms has been reported. Use Block B bathrooms temporarily.', 'medium'),
    ('School fees portal will be down for maintenance from midnight to 6am tomorrow.', 'medium'),
    ('The campus bank branch will close at 2pm today instead of the usual 4pm.', 'medium'),
    ('Hostel internet will be throttled tonight between 11pm and 6am for network reconfiguration.', 'medium'),
    ('Notice: The visa and documentation office is temporarily relocated to Room 201, Admin Block B.', 'medium'),
    ('Advisory: Cases of conjunctivitis reported in female hostel. Avoid sharing towels or eye drops.', 'medium'),
    ('All Thursday afternoon lectures have been rescheduled to Friday due to a faculty seminar.', 'medium'),
    ('The student ID card printing service is temporarily suspended. Cards to be ready by end of next week.', 'medium'),
    ('Notice: Diesel supply for generators is delayed. Some buildings may lose power this evening.', 'medium'),
    ('Medical notice: Students returning from off-campus trips should monitor for typhoid symptoms.', 'medium'),
    ('Caution: Uneven flooring in the engineering lab corridor. Maintenance has been notified.', 'medium'),
    ('Advisory: A series of phone snatching incidents have been reported off campus near the junction.', 'medium'),
    ('The vice chancellor\'s address originally scheduled for Friday has been moved to Monday.', 'medium'),
    ('Notice: The laundry room in female hostel Block B is temporarily closed for repairs.', 'medium'),
    ('Caution: Wet paint in the corridors of the administration block. Please avoid contact.', 'medium'),

    # ── LOW (55 samples) ──────────────────────────────────────────────────────
    ('Reminder: CU Talent Hunt registration closes Friday. Submit at the SUB.', 'low'),
    ('The vice chancellor will address students at Freedom Square this Friday.', 'low'),
    ('Hall dues payment deadline extended to end of the month.', 'low'),
    ('New library hours: 7am to 10pm weekdays, 8am to 6pm weekends.', 'low'),
    ('All student government executives report to the DSA office by 3pm.', 'low'),
    ('Inter-hall football championship starts next week. Register your team today.', 'low'),
    ('Midweek chapel service holds tomorrow at 6:30am. Attendance expected.', 'low'),
    ('Semester break begins after the last examination. Check the academic calendar.', 'low'),
    ('The campus bookshop will be closed on Monday for stocktaking.', 'low'),
    ('Convocation ceremony rehearsal is mandatory for all graduating students.', 'low'),
    ('Announcement: The annual CU cultural day is scheduled for next Saturday.', 'low'),
    ('Reminder: Submit your hostel room swap request before end of week.', 'low'),
    ('The faculty of social sciences is hosting a career fair next Tuesday in the auditorium.', 'low'),
    ('Students are invited to attend the alumni networking dinner on Saturday evening.', 'low'),
    ('New semester academic calendar is now available on the student portal.', 'low'),
    ('Chapel attendance records will be updated on Monday. Ensure your card was scanned.', 'low'),
    ('Registration for the entrepreneurship workshop closes tomorrow. Seats are limited.', 'low'),
    ('Reminder: Tuition balance for returning students must be cleared before exam week.', 'low'),
    ('The photography club is holding a free portrait session on the lawns this Friday.', 'low'),
    ('Sports day is scheduled for next Saturday at the sports complex. All are welcome.', 'low'),
    ('Notice: Library catalogue has been updated with new journals. Log in to access them.', 'low'),
    ('Graduation gown fittings will hold every Tuesday and Thursday in the sports hall.', 'low'),
    ('The drama society is auditioning for their annual production. Visit the Arts complex.', 'low'),
    ('Scholarship application for the next session closes at the end of this month.', 'low'),
    ('The student union organises a free movie night this Friday at the amphitheatre.', 'low'),
    ('Announcement: The best graduating student award nominations are now open.', 'low'),
    ('Reminder: Return all borrowed textbooks before the deadline to avoid fines.', 'low'),
    ('The music department presents a classical concert this Sunday at 5pm in the chapel.', 'low'),
    ('Clearance forms for outgoing students are now available at the registry office.', 'low'),
    ('Students who completed community service should submit their forms to the DSA office.', 'low'),
    ('The university swimming pool will be open for recreational use this weekend.', 'low'),
    ('Notice: Chapel choir auditions will hold this Wednesday after the morning service.', 'low'),
    ('Reminder: The hostel allocation for new students is available on the student portal.', 'low'),
    ('The debate society is recruiting new members. Meeting is every Thursday at 5pm.', 'low'),
    ('Announcement: Covenant University ranked among top universities in Africa this year.', 'low'),
    ('The academic advising office will operate extended hours this week for course registration.', 'low'),
    ('Convocation rehearsal schedule has been released. Check the notice board in your faculty.', 'low'),
    ('Campus café now offers extended breakfast hours from 6am to 10am on weekdays.', 'low'),
    ('The students association invites all members to the end-of-semester dinner on Saturday.', 'low'),
    ('Reminder: Feedback forms for lecturers must be completed online before the semester ends.', 'low'),
    ('The latest edition of the campus magazine is now available at the student union building.', 'low'),
    ('Notice: The university gym schedule has been updated. New sessions added on weekends.', 'low'),
    ('Registration for the national mathematics olympiad is open. Contact your department for details.', 'low'),
    ('The international students association is hosting a cultural exhibition this Friday.', 'low'),
    ('Reminder: ID card renewal for all year-two students begins on Monday.', 'low'),
    ('The postgraduate association holds its general meeting every last Thursday of the month.', 'low'),
    ('New vending machines have been installed in the hostel lobbies. Card payments accepted.', 'low'),
    ('Announcement: A blood donation drive will take place at the clinic this Thursday.', 'low'),
    ('The student welfare office is distributing free sanitary kits to female students this week.', 'low'),
    ('Reminder: All final-year students must submit their project titles to the department by Friday.', 'low'),
    ('The campus Wi-Fi password has been updated. Collect the new password from the ICT helpdesk.', 'low'),
    ('Notice: Outdoor exercise equipment near Block E has been repaired and is now available.', 'low'),
    ('The university will observe a public holiday on Monday. All offices will be closed.', 'low'),
    ('Chapel notice: The visiting minister for Sunday service is Reverend Dr. Emmanuel Okon.', 'low'),
    ('Reminder: Semester registration closes at the end of next week. Avoid late fees.', 'low'),
]


def clean_text(text: str) -> str:
    """
    Normalises raw text for TF-IDF vectorization.
    Removes URLs, mentions, hashtags, non-alpha characters, and extra whitespace.
    """
    if not isinstance(text, str):
        return ''
    text = text.lower()
    text = re.sub(r'http\S+|www\S+', '', text)
    text = re.sub(r'@\w+', '', text)
    text = re.sub(r'#\w+', '', text)
    text = re.sub(r'[^a-z\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def load_crisislex(path: Path) -> pd.DataFrame:
    """
    Loads and relabels the CrisisLex dataset to CampusAlert urgency classes.

    Args:
        path: Path to the CrisisLex CSV.

    Returns:
        DataFrame with columns: text, urgency.
    """
    logger.info('Loading CrisisLex from %s', path)
    df = pd.read_csv(path, encoding='utf-8', on_bad_lines='skip')

    col_map = {'tweet_text': 'text', 'category': 'raw_label', 'label': 'raw_label'}
    df = df.rename(columns={c: col_map[c] for c in col_map if c in df.columns})

    if 'text' not in df.columns or 'raw_label' not in df.columns:
        logger.warning('CrisisLex CSV missing expected columns. Skipping.')
        return pd.DataFrame(columns=['text', 'urgency'])

    label_map = {
        'deaths_reports': 'critical',
        'injured_or_dead_people': 'critical',
        'missing_trapped_or_found_people': 'critical',
        'displaced_people_and_evacuations': 'critical',
        'infrastructure_and_utilities_damage': 'critical',
        'rescue_volunteering_or_donation_effort': 'high',
        'requests_or_urgent_needs': 'high',
        'sympathy_and_support': 'high',
        'affected_individuals': 'high',
        'caution_and_advice': 'medium',
        'not_humanitarian': 'medium',
        'other_useful_information': 'low',
        'not_related_or_irrelevant': 'low',
    }
    df['raw_label'] = df['raw_label'].str.lower().str.strip()
    df['urgency'] = df['raw_label'].map(label_map)
    df = df.dropna(subset=['urgency', 'text'])
    logger.info('CrisisLex: %d usable samples.', len(df))
    return df[['text', 'urgency']]


def load_humaid(path: Path) -> pd.DataFrame:
    """
    Loads and relabels the HumAID dataset to CampusAlert urgency classes.

    Args:
        path: Path to the HumAID CSV.

    Returns:
        DataFrame with columns: text, urgency.
    """
    logger.info('Loading HumAID from %s', path)
    df = pd.read_csv(path, encoding='utf-8', on_bad_lines='skip')

    col_map = {'tweet_text': 'text', 'label': 'raw_label'}
    df = df.rename(columns={c: col_map[c] for c in col_map if c in df.columns})

    if 'text' not in df.columns or 'raw_label' not in df.columns:
        logger.warning('HumAID CSV missing expected columns. Skipping.')
        return pd.DataFrame(columns=['text', 'urgency'])

    label_map = {
        'deaths_and_casualties': 'critical',
        'injured_or_dead_people': 'critical',
        'missing_and_found_people': 'critical',
        'displaced_people_and_evacuations': 'critical',
        'infrastructure_and_utility_damage': 'high',
        'rescue_volunteering_or_donation_effort': 'high',
        'requests_or_urgent_needs': 'high',
        'caution_and_advice': 'medium',
        'sympathy_and_support': 'low',
        'other_useful_information': 'low',
        'not_humanitarian': 'low',
    }
    df['raw_label'] = df['raw_label'].str.lower().str.strip()
    df['urgency'] = df['raw_label'].map(label_map)
    df = df.dropna(subset=['urgency', 'text'])
    logger.info('HumAID: %d usable samples.', len(df))
    return df[['text', 'urgency']]


def train(data_path: Optional[Path], output_dir: Path) -> None:
    """
    Full training pipeline from raw data to saved model artefacts.

    Args:
        data_path: Optional path to CrisisLex or HumAID CSV.
        output_dir: Directory where model.pkl and vectorizer.pkl are written.
    """
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
    from sklearn.model_selection import train_test_split
    from sklearn.utils.class_weight import compute_sample_weight
    from xgboost import XGBClassifier

    try:
        from imblearn.over_sampling import SMOTE
        smote_available = True
    except ImportError:
        smote_available = False
        logger.warning('imbalanced-learn not installed — SMOTE skipped. pip install imbalanced-learn')

    # ── 1. Load and merge all data sources ────────────────────────────────────
    frames = [pd.DataFrame(SYNTHETIC_SAMPLES, columns=['text', 'urgency'])]
    logger.info('Synthetic samples: %d', len(frames[0]))

    if data_path and data_path.exists():
        name = data_path.name.lower()
        if 'humaid' in name:
            frames.append(load_humaid(data_path))
        else:
            frames.append(load_crisislex(data_path))
    else:
        logger.info(
            'No external dataset provided. Training on %d synthetic samples. '
            'For higher accuracy, download CrisisLex: https://crisislex.org/',
            len(frames[0]),
        )

    df = pd.concat(frames, ignore_index=True)
    logger.info('Combined dataset: %d samples', len(df))

    # ── 2. Clean text ──────────────────────────────────────────────────────────
    df['text'] = df['text'].apply(clean_text)
    df = df[df['text'].str.len() > 5].reset_index(drop=True)
    logger.info('After cleaning: %d samples', len(df))

    # ── 3. Encode labels ───────────────────────────────────────────────────────
    df['label'] = df['urgency'].map(URGENCY_TO_LABEL)
    df = df.dropna(subset=['label'])
    df['label'] = df['label'].astype(int)

    logger.info('Class distribution:')
    for urgency, count in df['urgency'].value_counts().items():
        pct = count / len(df) * 100
        logger.info('  %-10s %d samples (%.1f%%)', urgency, count, pct)

    # ── 4. Train/test split (stratified 80/20) ────────────────────────────────
    X_raw = df['text'].values
    y = df['label'].values
    X_train_raw, X_test_raw, y_train, y_test = train_test_split(
        X_raw, y, test_size=0.20, random_state=42, stratify=y
    )
    logger.info('Train: %d | Test: %d', len(X_train_raw), len(X_test_raw))

    # ── 5. TF-IDF vectorization ────────────────────────────────────────────────
    # Unigrams + bigrams: bigrams capture phrases like "gas leak", "power outage"
    # sublinear_tf: dampens extreme term frequencies (reduces noise from repetition)
    # min_df=1 here because our dataset is small — raise to 2 when using CrisisLex
    vectorizer = TfidfVectorizer(
        max_features=5000,
        ngram_range=(1, 2),
        sublinear_tf=True,
        min_df=1,                    # min_df=2 once you have CrisisLex/HumAID data
        strip_accents='unicode',
        analyzer='word',
        token_pattern=r'\b[a-z]{2,}\b',
    )
    X_train = vectorizer.fit_transform(X_train_raw)
    X_test = vectorizer.transform(X_test_raw)
    logger.info('TF-IDF vocabulary: %d features', len(vectorizer.vocabulary_))

    # ── 6. SMOTE balancing ────────────────────────────────────────────────────
    # Critical and High alerts are naturally underrepresented in any real dataset.
    # SMOTE generates synthetic minority examples so the model is not biased
    # towards predicting Low for everything.
    if smote_available:
        counts = np.bincount(y_train)
        min_count = int(counts.min())
        # k_neighbors must be < min class count; cap at 5
        k = min(5, min_count - 1)
        if k >= 1:
            smote = SMOTE(random_state=42, k_neighbors=k)
            X_train, y_train = smote.fit_resample(X_train, y_train)
            logger.info('After SMOTE: %d training samples', len(y_train))
        else:
            logger.warning('Insufficient samples for SMOTE (min class has %d samples).', min_count)

    # ── 7. Train XGBoost ──────────────────────────────────────────────────────
    # With a small synthetic-only dataset, fewer estimators and shallower trees
    # reduce overfitting. Raise n_estimators to 300-400 when using CrisisLex data.
    sample_weights = compute_sample_weight(class_weight='balanced', y=y_train)

    model = XGBClassifier(
        n_estimators=300,
        max_depth=4,                 # Shallower trees prevent overfitting on small data
        learning_rate=0.05,          # Slower learning rate for better generalisation
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=2,          # Require at least 2 samples per leaf
        reg_alpha=0.1,               # L1 regularisation
        reg_lambda=1.0,              # L2 regularisation
        objective='multi:softprob',
        num_class=4,
        eval_metric='mlogloss',
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )

    logger.info('Training XGBoost (300 estimators, max_depth=4)...')
    model.fit(
        X_train,
        y_train,
        sample_weight=sample_weights,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )
    logger.info('Training complete.')

    # ── 8. Evaluate ───────────────────────────────────────────────────────────
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)

    # PRD false alarm rate: non-urgent (low/medium) misclassified as critical/high
    non_urgent_mask = y_test <= 1
    false_alarm_count = int(np.sum(y_pred[non_urgent_mask] >= 2))
    non_urgent_total = int(np.sum(non_urgent_mask))
    false_alarm_rate = false_alarm_count / max(non_urgent_total, 1)

    logger.info('=' * 60)
    logger.info('EVALUATION RESULTS')
    logger.info('=' * 60)
    logger.info('Overall Accuracy : %.2f%%', accuracy * 100)
    logger.info('False Alarm Rate : %.2f%% (%d/%d non-urgent misclassified)',
                false_alarm_rate * 100, false_alarm_count, non_urgent_total)
    logger.info('')

    target_names = [LABEL_TO_URGENCY[i] for i in range(4)]
    print(classification_report(y_test, y_pred, target_names=target_names, digits=3))

    cm = confusion_matrix(y_test, y_pred)
    logger.info('Confusion matrix (rows=actual, cols=predicted):')
    logger.info('Labels: %s', target_names)
    for i, row in enumerate(cm):
        logger.info('  %-10s %s', target_names[i], list(row))

    logger.info('=' * 60)

    # ── PRD gate ───────────────────────────────────────────────────────────────
    meets_accuracy = accuracy >= 0.80
    meets_false_alarm = false_alarm_rate < 0.05

    if not meets_accuracy:
        logger.warning(
            'Accuracy %.2f%% is below the PRD target of 80%%. '
            'Add more training data from CrisisLex or HumAID.',
            accuracy * 100,
        )
    if not meets_false_alarm:
        logger.warning(
            'False alarm rate %.2f%% exceeds the PRD limit of 5%%. '
            'Expand the keyword override list and/or add more low/medium training samples.',
            false_alarm_rate * 100,
        )
    if meets_accuracy and meets_false_alarm:
        logger.info('All PRD targets met. Model is ready for deployment.')

    # ── 9. Save artefacts ─────────────────────────────────────────────────────
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / 'model.pkl'
    vectorizer_path = output_dir / 'vectorizer.pkl'

    joblib.dump(model, model_path, compress=3)
    joblib.dump(vectorizer, vectorizer_path, compress=3)

    metadata = {
        'accuracy': round(float(accuracy), 4),
        'false_alarm_rate': round(float(false_alarm_rate), 4),
        'n_train': int(len(y_train)),
        'n_test': int(len(y_test)),
        'n_features': int(len(vectorizer.vocabulary_)),
        'label_encoding': LABEL_TO_URGENCY,
        'prd_targets_met': meets_accuracy and meets_false_alarm,
    }
    metadata_path = output_dir / 'metadata.json'
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    logger.info('Saved: %s', model_path)
    logger.info('Saved: %s', vectorizer_path)
    logger.info('Saved: %s', metadata_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Train the CampusAlert XGBoost urgency classifier.',
    )
    parser.add_argument(
        '--data-path',
        type=Path,
        default=None,
        help='Path to CrisisLex or HumAID CSV file.',
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path(__file__).parent,
        help='Output directory for model.pkl, vectorizer.pkl, metadata.json.',
    )
    args = parser.parse_args()
    train(data_path=args.data_path, output_dir=args.output_dir)

