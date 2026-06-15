import unittest
import os
from health_data_schema import DailyHealthData
# Ensure we mock the DASHSCOPE_API_KEY before importing QwenVLExtractor
os.environ["DASHSCOPE_API_KEY"] = "sk-mockkeyforvalidationtests"
from extract_health_data import QwenVLExtractor, check_cross_day_consistency

class TestValidators(unittest.TestCase):
    def setUp(self):
        self.extractor = QwenVLExtractor()

    def test_validate_extraction_normal(self):
        # Normal data should have no warnings
        data = DailyHealthData(
            date="2026-06-01",
            steps=8000,
            resting_heart_rate=65,
            heart_rate_min=60,
            heart_rate_max=120,
            spo2_min=95,
            sleep_hours=7.5,
            sleep_score=80
        )
        warnings = self.extractor.validate_extraction(data)
        self.assertEqual(len(warnings), 0)

    def test_validate_extraction_anomalies(self):
        # Steps too high
        data = DailyHealthData(date="2026-06-01", steps=60000)
        warnings = self.extractor.validate_extraction(data)
        self.assertTrue(any("步数异常偏高" in w for w in warnings))

        # Heart rate range invalid (min >= max)
        data = DailyHealthData(date="2026-06-01", heart_rate_min=90, heart_rate_max=85)
        warnings = self.extractor.validate_extraction(data)
        self.assertTrue(any("心率范围异常" in w for w in warnings))

        # Resting heart rate anomaly
        data = DailyHealthData(date="2026-06-01", resting_heart_rate=35)
        warnings = self.extractor.validate_extraction(data)
        self.assertTrue(any("静息心率异常" in w for w in warnings))

        # SpO2 anomaly
        data = DailyHealthData(date="2026-06-01", spo2_min=65)
        warnings = self.extractor.validate_extraction(data)
        self.assertTrue(any("血氧下限异常" in w for w in warnings))

    def test_check_cross_day_consistency(self):
        # Create stable history
        history = [
            DailyHealthData(date=f"2026-05-{i:02d}", steps=5000, resting_heart_rate=60, spo2_min=98, sleep_hours=7.0)
            for i in range(1, 10)
        ]

        # Scenario 1: Consistent new day
        new_data_ok = DailyHealthData(date="2026-05-10", steps=5500, resting_heart_rate=62, spo2_min=97, sleep_hours=7.2)
        warnings = check_cross_day_consistency(new_data_ok, history)
        self.assertEqual(len(warnings), 0)

        # Scenario 2: Steps mutation (> 3.0 sigma)
        # All history steps are 5000. mean = 5000, std = 0.
        # Wait, if std is 0, the function check_cross_day_consistency skips checking standard deviation!
        # Let's verify: `if mean is None or std is None or std == 0: continue`
        # So we must introduce some variation in history to have std > 0
        history_var = [
            DailyHealthData(date="2026-05-01", steps=5000, resting_heart_rate=60, spo2_min=98, sleep_hours=7.0),
            DailyHealthData(date="2026-05-02", steps=5200, resting_heart_rate=61, spo2_min=97, sleep_hours=6.8),
            DailyHealthData(date="2026-05-03", steps=4800, resting_heart_rate=59, spo2_min=99, sleep_hours=7.2),
        ]
        # Steps: mean = 5000, std = sqrt((0 + 40000 + 40000)/3) = 163.3
        # RHR: mean = 60, std = sqrt((0 + 1 + 1)/3) = 0.816
        # SpO2: mean = 98, std = 0.816
        # Sleep: mean = 7.0, std = 0.163

        # New data with massive steps mutation: 9000 steps (deviation = (9000-5000)/163.3 = 24.5 sigma > 3.0)
        new_data_mut = DailyHealthData(date="2026-05-04", steps=9000)
        warnings = check_cross_day_consistency(new_data_mut, history_var)
        self.assertTrue(any("步数突变" in w for w in warnings))

        # New data with massive RHR mutation: 75 bpm (deviation = (75-60)/0.816 = 18.3 sigma > 3.0)
        new_data_mut_rhr = DailyHealthData(date="2026-05-04", resting_heart_rate=75)
        warnings = check_cross_day_consistency(new_data_mut_rhr, history_var)
        self.assertTrue(any("静息心率突变" in w for w in warnings))

if __name__ == "__main__":
    unittest.main()
