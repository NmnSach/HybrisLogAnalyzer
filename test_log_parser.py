import unittest
from datetime import datetime

from log_parser import cluster_errors, filter_by_window, parse_log


class LogParserTests(unittest.TestCase):
    def test_log4j_timestamp_with_dot_and_error_level_is_detected(self):
        text = (
            "2026-07-20 14:32:10.123 ERROR [http-nio-9002-exec-3] "
            "de.hybris.platform.servicelayer.search.exceptions.FlexibleSearchException: query failed\n"
            "    at de.hybris.platform.servicelayer.search.impl.DefaultFlexibleSearchService.search(DefaultFlexibleSearchService.java:101)\n"
        )

        entries = parse_log(text)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].timestamp, datetime(2026, 7, 20, 14, 32, 10, 123000))
        self.assertTrue(entries[0].is_error)

    def test_wrapper_log_with_embedded_warn_is_grouped(self):
        text = (
            "INFO   | jvm 1    | main    | 2026/07/20 09:12:10.287 | WARN  [hybrisHTTP24] [CatalogVersionSyncJob] Sync is taking unusually long for job 12345\n"
        )

        entries = parse_log(text)
        groups = cluster_errors(entries)

        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].is_warning)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].severity, "warning")

    def test_window_filter_keeps_detected_issue(self):
        text = (
            "2026-07-20 14:32:10,123 WARN [http-nio-9002-exec-3] CacheRegion : backend unavailable\n"
            "2026-07-20 14:40:10,123 INFO [http-nio-9002-exec-3] Startup complete\n"
        )

        entries = parse_log(text)
        windowed = filter_by_window(
            entries,
            datetime(2026, 7, 20, 14, 30),
            datetime(2026, 7, 20, 14, 35),
        )
        groups = cluster_errors(windowed)

        self.assertEqual(len(windowed), 1)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].message, "[http-nio-9002-exec-3] CacheRegion : backend unavailable")


if __name__ == "__main__":
    unittest.main()
