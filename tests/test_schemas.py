import unittest
from datetime import datetime
from health_data_schema import PersonProfile, DailyHealthData, HealthDataStore

class TestHealthDataSchema(unittest.TestCase):
    def test_clean_none_strings(self):
        # Test cleaning of various representations of "None" or "null" with/without units
        data = DailyHealthData(
            date="2026-06-01",
            steps="None",
            distance_km="null",
            exercise_minutes="nan",
            calories="",
            resting_heart_rate="--",
            spo2_min="暂无",
            sleep_hours="无",
            sleep_score="undefined"
        )
        self.assertIsNone(data.steps)
        self.assertIsNone(data.distance_km)
        self.assertIsNone(data.exercise_minutes)
        self.assertIsNone(data.calories)
        self.assertIsNone(data.resting_heart_rate)
        self.assertIsNone(data.spo2_min)
        self.assertIsNone(data.sleep_hours)
        self.assertIsNone(data.sleep_score)

    def test_unit_stripping_and_coercion(self):
        # Test unit suffix removal and coercion to numbers
        data = DailyHealthData(
            date="2026-06-01",
            steps="5432步",
            distance_km="3.21km",
            exercise_minutes="45min",
            resting_heart_rate="65bpm",
            spo2_min="95%",
            sleep_hours="7.5h",
            avg_heart_rate="72次/分"
        )
        self.assertEqual(data.steps, 5432)
        self.assertAlmostEqual(data.distance_km, 3.21)
        self.assertEqual(data.exercise_minutes, 45)
        self.assertEqual(data.resting_heart_rate, 65)
        self.assertEqual(data.spo2_min, 95)
        self.assertAlmostEqual(data.sleep_hours, 7.5)
        self.assertEqual(data.avg_heart_rate, 72)

    def test_date_validation(self):
        # Correct format
        data = DailyHealthData(date="2026-06-01")
        self.assertEqual(data.date, "2026-06-01")
        
        # Incorrect format should raise ValueError
        with self.assertRaises(ValueError):
            DailyHealthData(date="2026/06/01")
            
        with self.assertRaises(ValueError):
            DailyHealthData(date="06-01-2026")

    def test_boundary_validators(self):
        # Test steps boundary [0, 200000]
        with self.assertRaises(ValueError):
            DailyHealthData(date="2026-06-01", steps=-1)
        with self.assertRaises(ValueError):
            DailyHealthData(date="2026-06-01", steps=200001)

        # Test resting heart rate boundary [30, 150]
        with self.assertRaises(ValueError):
            DailyHealthData(date="2026-06-01", resting_heart_rate=29)
        with self.assertRaises(ValueError):
            DailyHealthData(date="2026-06-01", resting_heart_rate=151)

        # Test sleep score boundary [0, 100]
        with self.assertRaises(ValueError):
            DailyHealthData(date="2026-06-01", sleep_score=-5)
        with self.assertRaises(ValueError):
            DailyHealthData(date="2026-06-01", sleep_score=105)

    def test_adaptive_thresholds_copd(self):
        # COPD profile: thresholds for SpO2 should be relaxed (GOLD/BTS guidelines)
        copd_profile = PersonProfile(
            age=50,
            conditions=["慢性阻塞性肺疾病", "高血压"]
        )
        self.assertTrue(copd_profile.has_copd)
        
        thr = copd_profile.get_thresholds()
        self.assertEqual(thr["spo2_danger"], 88)
        self.assertEqual(thr["spo2_warning"], 92)

        # Non-COPD profile (or Asthma only, which is excluded by F13)
        asthma_profile = PersonProfile(
            age=50,
            conditions=["支气管哮喘", "高血压"]
        )
        self.assertFalse(asthma_profile.has_copd)
        
        thr_asthma = asthma_profile.get_thresholds()
        self.assertEqual(thr_asthma["spo2_danger"], 90)
        self.assertEqual(thr_asthma["spo2_warning"], 95)

    def test_adaptive_thresholds_elderly_and_beta_blocker(self):
        # Elderly (>=65) sleep thresholds lower limit relaxed
        elderly_profile = PersonProfile(age=70)
        thr = elderly_profile.get_thresholds()
        self.assertEqual(thr["sleep_low"], 5.5)
        self.assertEqual(thr["sleep_high"], 8.0)

        # Adult (<65) sleep thresholds
        adult_profile = PersonProfile(age=40)
        thr_adult = adult_profile.get_thresholds()
        self.assertEqual(thr_adult["sleep_low"], 6.0)
        self.assertEqual(thr_adult["sleep_high"], 9.0)

        # Beta-blocker resting HR threshold relaxed to 45
        bb_profile = PersonProfile(medications=["美托洛尔缓释片"])
        self.assertTrue(bb_profile.has_beta_blocker)
        thr_bb = bb_profile.get_thresholds()
        self.assertEqual(thr_bb["rhr_low"], 45)

        # Non-beta-blocker resting HR threshold remains 50
        no_bb_profile = PersonProfile(medications=["阿司匹林"])
        self.assertFalse(no_bb_profile.has_beta_blocker)
        thr_no_bb = no_bb_profile.get_thresholds()
        self.assertEqual(thr_no_bb["rhr_low"], 50)

if __name__ == "__main__":
    unittest.main()
