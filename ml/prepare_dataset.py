# campusalert/ml/prepare_dataset.py

"""
Phase 2 — Dataset Preparation Script.

Converts public crisis/emergency text datasets (CrisisLex, HumAID)
into the four-class format expected by train.py:
    critical, high, medium, low

Usage:
    # Synthetic only (no downloads needed):
    python ml/prepare_dataset.py --source synthetic --output ml/data/crisis_dataset.csv

    # HumAID PSV files:
    python ml/prepare_dataset.py --source humaid --input ml/data/ --output ml/data/crisis_dataset.csv

    # CrisisLex CSV files:
    python ml/prepare_dataset.py --source crisislex --input ml/data/ --output ml/data/crisis_dataset.csv

    # All combined (recommended):
    python ml/prepare_dataset.py --source combined --input ml/data/ --output ml/data/crisis_dataset.csv

    Then train:
    python ml/train.py --dataset ml/data/crisis_dataset.csv

Real file format notes:
    HumAID:    .psv files (pipe-separated: tweet_id|tweet_text|class_label)
               Also supports .tsv and .csv as fallbacks.
    CrisisLex: .csv files per event folder (tweet_id, tweet_text, label/category/informativeness).
               Column names vary slightly across CrisisLex-T6 and CrisisLex-T26 releases.
"""

import argparse
import logging
import random
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s — %(message)s',
)
logger = logging.getLogger('campusalert.ml.prepare')

random.seed(42)

# ─── HumAID class_label → CampusAlert urgency ────────────────────────────────
# HumAID provides fine-grained event types. We collapse them into 4 urgency tiers.
HUMAID_TO_URGENCY = {
    'injured_or_dead_people': 'critical',
    'missing_trapped_or_found_people': 'critical',
    'displaced_people_and_evacuations': 'critical',
    'rescue_volunteering_or_donation_effort': 'high',
    'infrastructure_and_utility_damage': 'high',
    'affected_individuals': 'high',
    'requests_or_urgent_needs': 'high',
    'caution_and_advice': 'medium',
    'sympathy_and_support': 'low',
    'other_useful_information': 'low',
    'not_humanitarian': 'low',
}

# ─── CrisisLex informativeness / category → CampusAlert urgency ──────────────
# CrisisLex-T6: labels are "on-topic" / "off-topic" (informativeness column).
# CrisisLex-T26: labels are fine-grained categories (information_type column).
CRISISLEX_INFORMATIVENESS_TO_URGENCY = {
    'on-topic': 'high',    # Crisis-related; we default to high and refine via category
    'off-topic': 'low',
}

CRISISLEX_CATEGORY_TO_URGENCY = {
    # Deaths / direct casualties → critical
    'deaths_reports': 'critical',
    'injured_or_dead_people': 'critical',
    'missing_trapped_or_found_people': 'critical',
    'displaced_people_and_evacuations': 'critical',
    # Infrastructure damage and response → high
    'infrastructure_and_utilities_damage': 'high',
    'rescue_volunteering_or_donation_effort': 'high',
    'requests_or_urgent_needs': 'high',
    'affected_individuals': 'high',
    'sympathy_and_support': 'high',
    # Advice / information → medium
    'caution_and_advice': 'medium',
    'not_humanitarian': 'medium',
    # Irrelevant → low
    'other_useful_information': 'low',
    'not_related_or_irrelevant': 'low',
}

# ─── Synthetic campus alert examples ─────────────────────────────────────────
SYNTHETIC_EXAMPLES = [
    # ── Critical ──────────────────────────────────────────────────────────────
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

    # ── High ──────────────────────────────────────────────────────────────────
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

    # ── Medium ────────────────────────────────────────────────────────────────
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
    ("The vice chancellor's address originally scheduled for Friday has been moved to Monday.", 'medium'),
    ('Notice: The laundry room in female hostel Block B is temporarily closed for repairs.', 'medium'),
    ('Caution: Wet paint in the corridors of the administration block. Please avoid contact.', 'medium'),

    # ── Low ───────────────────────────────────────────────────────────────────
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


def build_synthetic_dataframe() -> pd.DataFrame:
    """Returns a DataFrame of curated synthetic campus alert examples."""
    texts, labels = zip(*SYNTHETIC_EXAMPLES)
    df = pd.DataFrame({'text': list(texts), 'label': list(labels)})
    logger.info('Synthetic examples: %d total.', len(df))
    return df


def _read_tabular(path: Path) -> pd.DataFrame | None:
    """
    Tries to read a delimited file by probing the most common separators.
    HumAID uses pipe (|). CrisisLex uses comma. Some releases use tab.

    Args:
        path: File path to read.

    Returns:
        DataFrame or None if all separator attempts fail.
    """
    separators = ['|', '\t', ',']
    for sep in separators:
        try:
            df = pd.read_csv(path, sep=sep, encoding='utf-8', on_bad_lines='skip')
            # Need at least 2 columns to be a valid data file
            if df.shape[1] >= 2:
                return df
        except Exception:
            continue
    return None


def load_humaid(input_dir: str) -> pd.DataFrame:
    """
    Loads HumAID dataset from a directory containing .psv, .tsv, or .csv files.

    HumAID real format (pipe-separated):
        tweet_id | tweet_text | class_label

    The script recurses into subdirectories, so you can point it at the top-level
    unzipped HumAID folder and it will find all event files.

    Args:
        input_dir: Root directory containing HumAID files (nested OK).

    Returns:
        DataFrame with columns: text, label.
    """
    rows = []
    input_path = Path(input_dir)

    # HumAID uses .psv extension; also accept .tsv and .csv for flexibility
    found_files = (
        list(input_path.rglob('*.psv'))
        + list(input_path.rglob('*.tsv'))
        + [f for f in input_path.rglob('*.csv') if 'humaid' in f.stem.lower() or 'humaid' in f.parent.name.lower()]
    )

    if not found_files:
        logger.warning(
            'No HumAID files (.psv / .tsv) found under %s. '
            'Expected pipe-separated files with columns: tweet_id, tweet_text, class_label.',
            input_dir,
        )
        return pd.DataFrame(columns=['text', 'label'])

    logger.info('Found %d HumAID file(s) under %s.', len(found_files), input_dir)

    for file_path in found_files:
        df = _read_tabular(file_path)
        if df is None:
            logger.warning('Could not parse %s — skipping.', file_path.name)
            continue

        # Normalise column names to lowercase
        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]

        # Find the text column (tweet_text or text)
        text_col = next(
            (c for c in df.columns if c in ('tweet_text', 'text', 'tweet')),
            None,
        )
        # Find the label column (class_label, label, category)
        label_col = next(
            (c for c in df.columns if c in ('class_label', 'label', 'category', 'event_type')),
            None,
        )

        if text_col is None or label_col is None:
            logger.warning(
                'Cannot identify text/label columns in %s (found: %s) — skipping.',
                file_path.name, list(df.columns),
            )
            continue

        df = df.rename(columns={text_col: 'text', label_col: 'raw_label'})
        df['raw_label'] = df['raw_label'].astype(str).str.strip().str.lower()
        df['label'] = df['raw_label'].map(HUMAID_TO_URGENCY)
        df = df.dropna(subset=['label', 'text'])
        rows.append(df[['text', 'label']])

        logger.info(
            '  %s → %d usable samples (columns used: text=%s, label=%s)',
            file_path.name, len(df), text_col, label_col,
        )

    if not rows:
        logger.warning('No usable HumAID samples extracted.')
        return pd.DataFrame(columns=['text', 'label'])

    combined = pd.concat(rows, ignore_index=True)
    logger.info('HumAID total: %d samples.', len(combined))
    return combined


def load_crisislex(input_dir: str) -> pd.DataFrame:
    """
    Loads CrisisLex dataset from a directory of event folders.

    CrisisLex-T26 / CrisisLex-T6 real structure:
        <event_name>/
            <event_name>-tweets_labeled.csv   (comma-separated)

    CSV columns (vary across releases — all handled):
        tweet_id, tweet_text, label             (CrisisLex-T6, on-topic/off-topic)
        tweet_id, tweet_text, informativeness   (alternate name)
        tweet_id, tweet_text, information_type  (CrisisLex-T26 fine-grained category)
        tweet_id, tweet_text, category          (another variant)

    Priority: use fine-grained category mapping first; fall back to
    informativeness (on-topic/off-topic) if category is absent.

    Args:
        input_dir: Root directory containing CrisisLex event folders.

    Returns:
        DataFrame with columns: text, label.
    """
    rows = []
    input_path = Path(input_dir)

    # Exclude files that look like HumAID to avoid double-loading in combined mode
    csv_files = [
        f for f in input_path.rglob('*.csv')
        if 'humaid' not in f.stem.lower() and 'humaid' not in f.parent.name.lower()
        and 'crisis_dataset' not in f.stem.lower()  # don't read our own output
    ]

    if not csv_files:
        logger.warning('No CrisisLex CSV files found under %s.', input_dir)
        return pd.DataFrame(columns=['text', 'label'])

    logger.info('Found %d CrisisLex CSV file(s) under %s.', len(csv_files), input_dir)

    for csv_path in csv_files:
        df = _read_tabular(csv_path)
        if df is None:
            logger.warning('Could not parse %s — skipping.', csv_path.name)
            continue

        # Normalise column names
        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]

        # Find tweet text column
        text_col = next(
            (c for c in df.columns if 'text' in c or 'tweet' in c),
            None,
        )
        if text_col is None:
            logger.warning(
                'No text column found in %s (columns: %s) — skipping.',
                csv_path.name, list(df.columns),
            )
            continue

        df = df.rename(columns={text_col: 'text'})

        # ── Try fine-grained category mapping first ─────────────────────────
        category_col = next(
            (c for c in df.columns if c in ('information_type', 'category', 'class_label')),
            None,
        )
        if category_col:
            df['label'] = (
                df[category_col]
                .astype(str).str.strip().str.lower()
                .map(CRISISLEX_CATEGORY_TO_URGENCY)
            )
            usable = df.dropna(subset=['label', 'text'])
            if len(usable) > 0:
                rows.append(usable[['text', 'label']])
                logger.info(
                    '  %s → %d samples via category mapping (col: %s)',
                    csv_path.name, len(usable), category_col,
                )
                continue

        # ── Fall back to informativeness (on-topic / off-topic) ────────────
        info_col = next(
            (c for c in df.columns if c in ('informativeness', 'label', 'class', 'relevant')),
            None,
        )
        if info_col:
            df['label'] = (
                df[info_col]
                .astype(str).str.strip().str.lower()
                .map(CRISISLEX_INFORMATIVENESS_TO_URGENCY)
            )
            usable = df.dropna(subset=['label', 'text'])
            if len(usable) > 0:
                rows.append(usable[['text', 'label']])
                logger.info(
                    '  %s → %d samples via informativeness mapping (col: %s)',
                    csv_path.name, len(usable), info_col,
                )
                continue

        logger.warning(
            'Could not find a usable label column in %s (columns: %s) — skipping.',
            csv_path.name, list(df.columns),
        )

    if not rows:
        logger.warning('No usable CrisisLex samples extracted.')
        return pd.DataFrame(columns=['text', 'label'])

    combined = pd.concat(rows, ignore_index=True)
    logger.info('CrisisLex total: %d samples.', len(combined))
    return combined


def prepare(source: str, input_dir: str, output_path: str) -> None:
    """
    Orchestrates dataset preparation and writes the final CSV.

    Args:
        source:      One of: humaid, crisislex, synthetic, combined.
        input_dir:   Directory with raw dataset files.
        output_path: Path to write the prepared CSV (text, label).
    """
    frames = []

    if source in ('synthetic', 'combined'):
        frames.append(build_synthetic_dataframe())

    if source in ('humaid', 'combined'):
        frames.append(load_humaid(input_dir))

    if source in ('crisislex', 'combined'):
        frames.append(load_crisislex(input_dir))

    if not frames:
        logger.error('No data loaded for source: %s', source)
        return

    combined = pd.concat(frames, ignore_index=True)

    # Clean
    combined['text'] = combined['text'].astype(str).str.strip()
    combined['label'] = combined['label'].str.strip().str.lower()
    combined = combined[combined['text'].str.len() > 10]
    combined = combined.drop_duplicates(subset=['text'])

    valid_labels = {'critical', 'high', 'medium', 'low'}
    combined = combined[combined['label'].isin(valid_labels)]

    logger.info('\n── Final dataset: %d samples ─────────────────────────', len(combined))
    dist = combined['label'].value_counts()
    for label_name, count in dist.items():
        pct = count / len(combined) * 100
        logger.info('  %-10s: %d (%.1f%%)', label_name, count, pct)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    combined[['text', 'label']].to_csv(output_path, index=False)
    logger.info('\nDataset saved → %s', output_path)
    logger.info('Next step:')
    logger.info('  python ml/train.py --dataset %s', output_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Prepare CampusAlert training dataset from real crisis datasets.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quickstart — synthetic only:
  python ml/prepare_dataset.py --source synthetic --output ml/data/crisis_dataset.csv

  # HumAID PSV files (point at the unzipped folder):
  python ml/prepare_dataset.py --source humaid --input ml/data/HumAID_data_en_labels/ --output ml/data/crisis_dataset.csv

  # CrisisLex CSV folders:
  python ml/prepare_dataset.py --source crisislex --input ml/data/CrisisLexT26/ --output ml/data/crisis_dataset.csv

  # All combined (best accuracy):
  python ml/prepare_dataset.py --source combined --input ml/data/ --output ml/data/crisis_dataset.csv
        """,
    )
    parser.add_argument(
        '--source',
        choices=['humaid', 'crisislex', 'synthetic', 'combined'],
        default='synthetic',
        help='Dataset source (default: synthetic).',
    )
    parser.add_argument(
        '--input',
        default='ml/data/',
        help='Root directory containing raw dataset files.',
    )
    parser.add_argument(
        '--output',
        default='ml/data/crisis_dataset.csv',
        help='Output path for the prepared CSV.',
    )
    args = parser.parse_args()
    prepare(source=args.source, input_dir=args.input, output_path=args.output)

