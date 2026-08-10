# -*- coding: utf-8 -*-
"""label_boxes 的 YOLO txt 行解析/序列化:加 player 类后,类别必须往返保真。
(风险:旧版 save 写死 '0 ',重存一次会把人工标好的 player 全改回 mob。)"""
import unittest

from scripts.label_boxes import format_label_line, parse_label_line


class TestLabelLines(unittest.TestCase):

    def test_round_trip_preserves_class(self):
        for cls in (0, 1):
            line = format_label_line([cls, 0.5, 0.25, 0.1, 0.2])
            self.assertEqual(parse_label_line(line)[0], cls)

    def test_parse_legacy_mob_line(self):
        # 现存 270 帧标注全是 0 开头的旧行,必须原样读回
        self.assertEqual(parse_label_line('0 0.500000 0.250000 0.100000 0.200000'),
                         [0, 0.5, 0.25, 0.1, 0.2])

    def test_parse_rejects_malformed(self):
        self.assertIsNone(parse_label_line(''))
        self.assertIsNone(parse_label_line('0 0.5 0.25'))

    def test_format_normalized_six_decimals(self):
        self.assertEqual(format_label_line([1, 0.5, 0.25, 0.1, 0.2]),
                         '1 0.500000 0.250000 0.100000 0.200000')


if __name__ == '__main__':
    unittest.main()
