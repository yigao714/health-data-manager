import unittest
from health_data_schema import PersonProfile, DailyHealthData, HealthDataStore
from report_generator import _calc_scores

# Python implementations of Phase 2 alerts for testing purposes
def calculate_ttr(profile: PersonProfile, records: list[DailyHealthData]) -> tuple[float, bool]:
    """
    Calculate TTR (Time in Target Range) for heart rate.
    Returns (ttr_percentage, should_alert).
    """
    has_hypertension_or_chd = any(
        any(kw in c for kw in ['高血压', '冠心病']) 
        for c in profile.conditions
    )
    is_beta_blocker = profile.has_beta_blocker
    
    if not (has_hypertension_or_chd and is_beta_blocker):
        return 0.0, False
        
    rest_hr_records = [r for r in records if r.resting_heart_rate is not None]
    if not rest_hr_records:
        return 0.0, False
        
    target_hr_days = sum(
        1 for r in rest_hr_records 
        if 55 <= r.resting_heart_rate <= 65
    )
    ttr = (target_hr_days / len(rest_hr_records)) * 100
    should_alert = ttr < 60
    return ttr, should_alert

def check_sedentary_max_hr(profile: PersonProfile, records: list[DailyHealthData]) -> tuple[bool, float, float]:
    """
    Check if safe max heart rate is breached during sedentary days.
    Returns (should_alert, max_limit, warning_limit).
    """
    if not profile.age:
        return False, 0.0, 0.0
        
    hr_max_limit = 207 - 0.7 * profile.age
    warn_limit = hr_max_limit * 0.85
    
    for r in records:
        if r.heart_rate_max is not None and r.heart_rate_max >= warn_limit:
            steps_low = (r.steps is None or r.steps < 1000)
            exercise_none = (r.exercise_minutes is None or r.exercise_minutes == 0)
            if steps_low and exercise_none:
                return True, hr_max_limit, warn_limit
                
    return False, hr_max_limit, warn_limit


class TestClinicalLogic(unittest.TestCase):
    def test_ttr_drug_controlled_heart_rate(self):
        # Case 1: Not applicable (no beta-blocker, no hypertension)
        profile_normal = PersonProfile(age=45, conditions=[], medications=[])
        records = [
            DailyHealthData(date="2026-06-01", resting_heart_rate=70),
            DailyHealthData(date="2026-06-02", resting_heart_rate=58),
        ]
        ttr, should_alert = calculate_ttr(profile_normal, records)
        self.assertFalse(should_alert)

        # Case 2: Applicable, high TTR (no alert)
        profile_patient = PersonProfile(
            age=65, 
            conditions=["高血压"], 
            medications=["琥珀酸美托洛尔缓释片"]
        )
        self.assertTrue(profile_patient.has_beta_blocker)
        
        records_good = [
            DailyHealthData(date="2026-06-01", resting_heart_rate=60), # In target
            DailyHealthData(date="2026-06-02", resting_heart_rate=58), # In target
            DailyHealthData(date="2026-06-03", resting_heart_rate=64), # In target
            DailyHealthData(date="2026-06-04", resting_heart_rate=68), # Out of target
            DailyHealthData(date="2026-06-05", resting_heart_rate=62), # In target
        ] # 4 out of 5 in target -> 80%
        ttr, should_alert = calculate_ttr(profile_patient, records_good)
        self.assertAlmostEqual(ttr, 80.0)
        self.assertFalse(should_alert)

        # Case 3: Applicable, low TTR (alert)
        records_bad = [
            DailyHealthData(date="2026-06-01", resting_heart_rate=50), # Out (low)
            DailyHealthData(date="2026-06-02", resting_heart_rate=54), # Out (low)
            DailyHealthData(date="2026-06-03", resting_heart_rate=60), # In target
            DailyHealthData(date="2026-06-04", resting_heart_rate=68), # Out (high)
            DailyHealthData(date="2026-06-05", resting_heart_rate=48), # Out (low)
        ] # 1 out of 5 in target -> 20%
        ttr, should_alert = calculate_ttr(profile_patient, records_bad)
        self.assertAlmostEqual(ttr, 20.0)
        self.assertTrue(should_alert)

    def test_sedentary_max_hr_alert(self):
        # Age 79 patient: max HR limit = 207 - 0.7 * 79 = 151.7. Warning limit (85%) = 128.945.
        profile = PersonProfile(age=79)
        
        # Case 1: High heart rate during exercise -> No sedentary warning
        records_exercise = [
            DailyHealthData(date="2026-06-01", heart_rate_max=135, steps=5000, exercise_minutes=30)
        ]
        should_alert, _, _ = check_sedentary_max_hr(profile, records_exercise)
        self.assertFalse(should_alert)
        
        # Case 2: High heart rate when sedentary (steps < 1000, exercise_minutes = 0) -> Warning
        records_sedentary = [
            DailyHealthData(date="2026-06-01", heart_rate_max=130, steps=500, exercise_minutes=0)
        ]
        should_alert, max_limit, warn_limit = check_sedentary_max_hr(profile, records_sedentary)
        self.assertTrue(should_alert)
        self.assertAlmostEqual(max_limit, 151.7)
        self.assertAlmostEqual(warn_limit, 128.945)

    def test_copd_spo2_regression_protection_f15(self):
        """
        F15 Protection: Simulate a COPD patient with persistent 88-89% SpO2.
        For a COPD patient, danger threshold is 88% (F12: raw value, no subtraction).
        Warning threshold is 92% - 2% (precision) = 90%.
        Thus, 88-89% should trigger '留意' (warning/warning level) but NOT '需关注' (danger level).
        """
        copd_profile = PersonProfile(
            age=75,
            conditions=["慢阻肺(COPD)"]
        )
        self.assertTrue(copd_profile.has_copd)
        
        # SpO2 minimums: 89, 88, 89. These are >= 88 (danger), but < 90 (warning).
        records = [
            DailyHealthData(date="2026-06-01", spo2_min=89, steps=3000, resting_heart_rate=60, sleep_hours=7.0, sleep_score=80),
            DailyHealthData(date="2026-06-02", spo2_min=88, steps=3000, resting_heart_rate=60, sleep_hours=7.0, sleep_score=80),
            DailyHealthData(date="2026-06-03", spo2_min=89, steps=3000, resting_heart_rate=60, sleep_hours=7.0, sleep_score=80),
        ]
        
        scores = _calc_scores(records, copd_profile)
        # Check that level is '留意' (warning) and not '需关注' (danger)
        self.assertEqual(scores["spo2_level"], "留意")
        self.assertTrue("SpO2<90%" in scores["spo2_text"])
        
        # If SpO2 drops to 87% (below 88% danger limit), it should trigger '需关注'
        records_danger = [
            DailyHealthData(date="2026-06-01", spo2_min=87, steps=3000, resting_heart_rate=60, sleep_hours=7.0, sleep_score=80)
        ]
        scores_danger = _calc_scores(records_danger, copd_profile)
        self.assertEqual(scores_danger["spo2_level"], "需关注")

if __name__ == "__main__":
    unittest.main()
