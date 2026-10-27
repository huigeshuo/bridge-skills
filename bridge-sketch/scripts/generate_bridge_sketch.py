#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
斜拉桥立面草图生成器 (Cable-Stayed Bridge Elevation Sketch Generator)

根据跨径、索塔上拉索布置间距、梁上拉索布置间距等参数，
生成斜拉桥立面布置草图 (SVG格式)。

用法:
    # 命令行参数
    python generate_bridge_sketch.py --main-span 430 --side-span 180 --d-tower 2.5 --d-deck 8 --output bridge.svg

    # JSON文件
    python generate_bridge_sketch.py --json params.json --output bridge.svg

    # JSON字符串
    python generate_bridge_sketch.py --json-str '{"main_span":430,"side_span":180,"d_tower":2.5,"d_deck":8}' --output bridge.svg
"""

import argparse
import json
import sys
import math
import os

# ================================================================
#  实桥预设
# ================================================================
PRESETS = {
    # 重庆东水门长江大桥主桥 (双塔单索面部分斜拉、公轨两用钢桁梁、稀索体系)
    # 参数来源：招商局重庆交科院报告 + 主桥立面布置图量测
    'dongshuimen': {
        'main_span': 445, 'side_span_left': 222.5, 'side_span_right': 190.5,
        # 梁上索距模式: 塔根 54.5 m 起, 8×16 m, 最外索距跨端 40 m
        # => 塔处无索区 109 m, 跨中无索区 80 m
        'deck_main_pattern': '54.5+8*16+40',
        'deck_side_pattern': '54.5+8*16+40',
        'n_side_left': 9, 'n_side_right': 9,
        'tower_height': 106.5,        # 南塔桥面以上塔高 (总高 172.61 m)
        'd_tower': 3.7,                # 塔上索距 (据布置图量测)
        'd_deck': 16, 'd_deck_side': 16,
        'tower_width': 6, 'pier_height': 20,
        'dims_top': True, 'show_tower_h_dim': False,
        'deck_mode': 'truss', 'truss_panels': 8, 'deck_thickness': 11.74,
        'river': True, 'water_depth': 37, 'water_from': 50, 'water_to': 745,
        'bed_profile': [[50, 45], [118, 65], [180, 78], [250, 80], [330, 85],
                        [420, 90], [500, 88], [580, 82], [660, 70], [745, 45]],
        'pier_base_depth': 66,
        'end_labels': ['南岸区', '渝中区'],
        'title': '重庆东水门长江大桥 主桥立面布置草图',
        'notes': ['双塔单索面部分斜拉桥', '钢桁梁 桁高11.74m', '每塔9对索 全桥36根',
                  '主跨跨中无索区80m', '桥塔处无索区109m', '南塔总高172.61m'],
    },
}


class CableStayedBridge:
    """斜拉桥参数计算与立面SVG生成"""

    def __init__(self, **kw):
        # ---- 结构形式 ----
        self.single_tower = bool(kw.get('single_tower', False))
        # 独塔模式下主跨位置: 'left'=主跨在左/边跨在右(默认), 'right'=主跨在右/边跨在左
        self.main_side = str(kw.get('main_side', 'left')).lower()
        if self.main_side not in ('left', 'right'):
            self.main_side = 'left'

        # ---- 跨径布置 (m) ----
        self.main_span = float(kw.get('main_span', 300))
        sl = kw.get('side_span', kw.get('side_span_left', 120))
        sr = kw.get('side_span_right', sl)
        self.side_span_left = float(sl)
        self.side_span_right = float(sr)

        # ---- 索塔 ----
        th = kw.get('tower_height', None)
        self.tower_height = float(th) if th is not None else None
        self.tower_width = float(kw.get('tower_width', 3.0))

        # ---- 拉索布置 ----
        self.d_tower = float(kw.get('d_tower', kw.get('cable_spacing_tower', 2.0)))
        dm = kw.get('d_deck', kw.get('d_deck_main', kw.get('cable_spacing_deck', 8.0)))
        ds = kw.get('d_deck_side', dm)
        self.d_deck_main = float(dm)
        self.d_deck_side = float(ds)
        # 塔上索距渐变 (顶部 d_tower_max -> 底部 d_tower_min), 默认恒定
        self.d_tower_min = float(kw.get('d_tower_min', self.d_tower))
        self.d_tower_max = float(kw.get('d_tower_max', self.d_tower))
        # 边跨梁上变距: 近塔段索距/索对数 + 远端索距 (默认不变距)
        self.d_deck_side_near = float(kw.get('d_deck_side_near', self.d_deck_side))
        self.d_deck_side_near_count = int(kw.get('d_deck_side_near_count', 0))
        # 可直接指定索数 (覆盖自动计算)
        self.n_main_override = kw.get('n_main', None)
        self.n_side_right_override = kw.get('n_side_right', None)
        self.arrangement = kw.get('arrangement', 'semi-fan')
        # 梁上索距模式 (字符串: "offset+n1*s1+n2*s2+...+end_gap")
        # 例: "16+25*8+16" -> 26根索, 距塔[16,24,...,216]
        # 例: "15+11*5+14*4+4" -> 26根索, 距塔[15,20,...,70,74,...,126]
        self.deck_main_pattern = kw.get('deck_main_pattern', None)
        self.deck_side_pattern = kw.get('deck_side_pattern', None)

        # ---- 边跨索数(左)覆盖: 双塔不对称、左右边跨索数不同或需精确匹配图纸时使用 ----
        self.n_side_left_override = kw.get('n_side_left', None)

        # ---- 主梁形式 ----
        # deck_mode: 'line' 单线粗线(默认) | 'truss' 桁梁(上下弦+竖杆+斜腹杆)
        dm_ = kw.get('deck_mode', None)
        if dm_ is None:
            dm_ = 'truss' if kw.get('truss') else 'line'
        self.deck_mode = str(dm_).lower()
        self.truss_panels = float(kw.get('truss_panels', 8.0))       # 桁架节间长度 (m)
        self.truss_verticals = bool(kw.get('truss_verticals', True))  # 是否画竖杆

        # ---- 河流 (水面线 + 河床曲线), 开启后替代地面线 ----
        self.river = bool(kw.get('river', False))
        self.water_depth = float(kw.get('water_depth', 30.0))   # 水面在桥面以下深度 (m)
        self.water_from = kw.get('water_from', None)            # 水面线起点绝对x (m)
        self.water_to = kw.get('water_to', None)                # 水面线终点绝对x (m)
        # 河床控制点 [(绝对x, 桥面以下深度), ...]; 不传则按 water_depth 自动生成
        self.bed_profile = kw.get('bed_profile', None)
        self.river_labels = bool(kw.get('river_labels', True))
        self.pier_cap = bool(kw.get('pier_cap', True))          # 承台+桩基
        # 塔/墩基础底面深度 (桥面以下, m); None = 落在河床上
        pbd = kw.get('pier_base_depth', None)
        self.pier_base_depth = float(pbd) if pbd is not None else None

        # ---- 说明条附加内容 ----
        self.notes = kw.get('notes', None)
        if isinstance(self.notes, str):
            self.notes = [t for t in self.notes.split(';') if t.strip()]

        # ---- 两端地名标注 (分号分隔两个, 箭头朝外) ----
        self.end_labels = kw.get('end_labels', None)
        if isinstance(self.end_labels, str):
            self.end_labels = [t for t in self.end_labels.split(';') if t.strip()]

        # ---- 辅助墩 ----
        # aux_piers: 绝对x坐标列表 (m); aux_pier_spans: 独塔边跨分段 [70,40,20] -> 墩在 70,110 处
        self.aux_pier_spans = kw.get('aux_pier_spans', None)
        aux = kw.get('aux_piers', None)
        if aux is None and self.aux_pier_spans is not None:
            spans = [float(s) for s in self.aux_pier_spans]
            offsets = []
            acc = 0.0
            for s in spans[:-1]:
                acc += s
                offsets.append(acc)
            if self.main_side == 'right':
                # 主跨在右: 边跨在左, 辅助墩从塔向左布置 (距塔 offset)
                aux = [self.side_span_left - o for o in offsets]
            else:
                # 主跨在左: 边跨在右, 辅助墩从塔向右布置 (距塔 offset)
                aux = [self.main_span + o for o in offsets]
        self.aux_piers = [float(x) for x in aux] if aux else []
        self.aux_pier_width = float(kw.get('aux_pier_width', 2.5))

        # ---- 视觉参数 ----
        self.deck_thickness = float(kw.get('deck_thickness', 1.5))
        self.pier_height = float(kw.get('pier_height', 12.0))
        self.title = kw.get('title', '斜拉桥立面草图')
        self.show_grid = kw.get('show_grid', False)
        self.show_dimensions = kw.get('show_dimensions', True)
        self.show_cable_count = kw.get('show_cable_count', True)
        # 尺寸标注细项控制: 塔高标注 / 索距标注(塔上+梁上)
        self.show_tower_h_dim = kw.get('show_tower_h_dim', True)
        self.show_spacing_dims = kw.get('show_spacing_dims', True)
        # 跨径标注位置: 默认在桥面下方; True = 置于图幅顶部(塔顶以上), 与原图排版一致
        self.dims_top = bool(kw.get('dims_top', False))

        # ---- 计算派生参数 ----
        self._calculate()

    # ================================================================
    #  参数计算
    # ================================================================

    def _calculate(self):
        """计算拉索数量、塔高、锚点坐标等派生参数"""

        # 每塔主跨侧拉索数量
        if self.n_main_override is not None:
            self.n_main = int(self.n_main_override)
        elif self.single_tower:
            # 独塔模式: 整个主跨位于塔一侧
            self.n_main = max(1, int(self.main_span / self.d_deck_main))
        else:
            # 双塔模式: 每塔承担主跨的一半
            self.n_main = max(1, int(self.main_span / 2.0 / self.d_deck_main))

        # 解析梁上索距模式 (如果提供, 覆盖自动计算的索数和间距)
        self.main_deck_dists = None
        self.side_deck_dists = None
        if self.deck_main_pattern:
            self.main_deck_dists = self._parse_deck_pattern(self.deck_main_pattern)
            self.n_main = len(self.main_deck_dists)

        if self.single_tower:
            # ---- 独塔模式 ----
            # 主跨位置: 'left'=左主跨右边跨(默认), 'right'=左边跨右主跨
            if self.main_side == 'right':
                side_span_used = self.side_span_left
                dir_main, dir_side = +1, -1   # 主跨索向右, 边跨索向左
            else:
                side_span_used = self.side_span_right
                dir_main, dir_side = -1, +1   # 主跨索向左, 边跨索向右
            self.n_side_left = 0
            self.n_side_right = self._calc_side_cable_count(side_span_used)
            if self.deck_side_pattern:
                self.side_deck_dists = self._parse_deck_pattern(self.deck_side_pattern)
                self.n_side_right = len(self.side_deck_dists)
            if self.main_side == 'right':
                self.total_length = self.side_span_left + self.main_span
                self.tower_x = self.side_span_left
            else:
                self.total_length = self.main_span + self.side_span_right
                self.tower_x = self.main_span
            self.tower_left_x = None
            self.tower_right_x = None

            if self.tower_height is None:
                n_max = max(self.n_main, self.n_side_right)
                self.tower_height = (n_max + 1) * self.d_tower_max
            else:
                self.tower_height = float(self.tower_height)

            cables_main = self._calc_tower_cables(
                self.tower_x, self.n_main, 0, dir_main=dir_main, dir_side=dir_side, side_kind='main')
            cables_side = self._calc_tower_cables(
                self.tower_x, 0, self.n_side_right, dir_main=dir_main, dir_side=dir_side, side_kind='side')
            self.cables_left = cables_main + cables_side
            self.cables_right = []
            self.n_cables_left = max(self.n_main, self.n_side_right)
            self.n_cables_right = 0
            self.towers = [{'x': self.tower_x, 'cables': self.cables_left}]
        else:
            # ---- 双塔模式 ----
            # 边跨索距模式 (双塔同样支持, 用于稀疏索 / 带无索区的实桥)
            if self.deck_side_pattern and self.side_deck_dists is None:
                self.side_deck_dists = self._parse_deck_pattern(self.deck_side_pattern)

            def _n_side(span, override):
                if override is not None:
                    return int(override)
                if self.side_deck_dists:
                    return len(self.side_deck_dists)
                return max(1, int(span / self.d_deck_side))

            self.n_side_left = _n_side(self.side_span_left, self.n_side_left_override)
            self.n_side_right = _n_side(self.side_span_right, self.n_side_right_override)

            # 每塔索对数 (主跨索与边跨索配对在同一高度)
            self.n_cables_left = max(self.n_main, self.n_side_left)
            self.n_cables_right = max(self.n_main, self.n_side_right)

            # 索塔高度 (未指定时自动计算: 索数×塔上索距 + 顶部余量)
            if self.tower_height is None:
                n_max = max(self.n_cables_left, self.n_cables_right)
                self.tower_height = (n_max + 1) * self.d_tower_max
            else:
                self.tower_height = float(self.tower_height)

            # 桥梁总长
            self.total_length = self.side_span_left + self.main_span + self.side_span_right

            # 索塔位置 (x坐标)
            self.tower_left_x = self.side_span_left
            self.tower_right_x = self.side_span_left + self.main_span
            self.tower_x = None

            # 拉索锚点坐标
            self.cables_left = self._calc_tower_cables(
                self.tower_left_x, self.n_main, self.n_side_left,
                dir_main=+1, dir_side=-1, side_kind=None
            )
            self.cables_right = self._calc_tower_cables(
                self.tower_right_x, self.n_main, self.n_side_right,
                dir_main=-1, dir_side=+1, side_kind=None
            )
            self.towers = [
                {'x': self.tower_left_x, 'cables': self.cables_left},
                {'x': self.tower_right_x, 'cables': self.cables_right},
            ]

        # 合理性校验
        self._warnings = []
        if self.single_tower:
            # 独塔: 主跨索覆盖整个主跨
            if self.main_deck_dists:
                if self.main_deck_dists[-1] > self.main_span + 0.01:
                    self._warnings.append(
                        "主跨侧: 末端锚点 %.1fm 超过主跨 = %.1fm"
                        % (self.main_deck_dists[-1], self.main_span)
                    )
            elif self.n_main * self.d_deck_main > self.main_span + 0.01:
                self._warnings.append(
                    "主跨侧: %d x %.1fm = %.1fm 超过主跨 = %.1fm"
                    % (self.n_main, self.d_deck_main,
                       self.n_main * self.d_deck_main, self.main_span)
                )
        else:
            if self.n_main * self.d_deck_main > self.main_span / 2.0 + 0.01:
                self._warnings.append(
                    "主跨侧: %d x %.1fm = %.1fm 超过主跨/2 = %.1fm, 拉索可能在中跨重叠"
                    % (self.n_main, self.d_deck_main,
                       self.n_main * self.d_deck_main, self.main_span / 2.0)
                )
        if self.single_tower:
            side_span_chk = self.side_span_left if self.main_side == 'right' else self.side_span_right
            side_dists = self._side_deck_distances(self.n_side_right)
            if side_dists and side_dists[-1] > side_span_chk + 0.01:
                self._warnings.append(
                    "边跨: 末端锚点 %.1fm 超过边跨 = %.1fm"
                    % (side_dists[-1], side_span_chk)
                )
        else:
            if self.n_side_left * self.d_deck_side > self.side_span_left + 0.01:
                self._warnings.append(
                    "左边跨: %d x %.1fm = %.1fm 超过边跨 = %.1fm"
                    % (self.n_side_left, self.d_deck_side,
                       self.n_side_left * self.d_deck_side, self.side_span_left)
                )
            if self.n_side_right * self.d_deck_side > self.side_span_right + 0.01:
                self._warnings.append(
                    "右边跨: %d x %.1fm = %.1fm 超过边跨 = %.1fm"
                    % (self.n_side_right, self.d_deck_side,
                       self.n_side_right * self.d_deck_side, self.side_span_right)
                )
        n_max = max(self.n_cables_left, self.n_cables_right)
        if n_max * self.d_tower_max > self.tower_height + 0.01:
            self._warnings.append(
                "塔上: %d x %.1fm = %.1fm 超过塔高 = %.1fm, 锚点可能超出塔顶"
                % (n_max, self.d_tower_max, n_max * self.d_tower_max, self.tower_height)
            )
        # 辅助墩位置校验
        for x in self.aux_piers:
            if x <= 0.01 or x >= self.total_length - 0.01:
                self._warnings.append(
                    "辅助墩 x=%.1fm 不在桥长范围内 (0 ~ %.1fm)" % (x, self.total_length)
                )
            if self.single_tower and abs(x - self.tower_x) < 1.0:
                self._warnings.append(
                    "辅助墩 x=%.1fm 与索塔 x=%.1fm 重叠" % (x, self.tower_x)
                )
            elif (not self.single_tower and
                  (abs(x - self.tower_left_x) < 1.0 or abs(x - self.tower_right_x) < 1.0)):
                self._warnings.append(
                    "辅助墩 x=%.1fm 与索塔位置重叠" % x
                )
        if self.aux_pier_spans is not None and self.single_tower:
            total_seg = sum(float(s) for s in self.aux_pier_spans)
            side_span_chk = self.side_span_left if self.main_side == 'right' else self.side_span_right
            if abs(total_seg - side_span_chk) > 0.01:
                self._warnings.append(
                    "边跨分段合计 %.1fm, 与边跨跨径 %.1fm 不一致 (总长 %.1fm)"
                    % (total_seg, side_span_chk, self.total_length)
                )

        # 梁上锚点覆盖范围校验 (稀疏索 / 带无索区时才是有效校核)
        if self.main_deck_dists:
            if self.main_deck_dists[-1] > self.main_span / 2.0 + 0.01:
                self._warnings.append(
                    "主跨侧: 最外索距塔 %.1fm 超过主跨/2 = %.1fm"
                    % (self.main_deck_dists[-1], self.main_span / 2.0)
                )
            self._no_cable_mid = self.main_span - 2.0 * self.main_deck_dists[-1]
            if self._no_cable_mid < 0:
                self._no_cable_mid = 0.0
        if self.side_deck_dists:
            if self.side_deck_dists[-1] > self.side_span_right + 0.01:
                self._warnings.append(
                    "右(边跨): 最外索距塔 %.1fm 超过边跨 = %.1fm"
                    % (self.side_deck_dists[-1], self.side_span_right)
                )

        # ---- 竖向总深 (画布比例用) ----
        self.bottom_depth = max(self.pier_height,
                                self.water_depth if self.river else 0.0)
        if self.river:
            self.bottom_depth = max(self.bottom_depth,
                                    max(d for _, d in self._bed_profile_pts()))
        if self.pier_base_depth is not None:
            self.bottom_depth = max(self.bottom_depth, float(self.pier_base_depth))

    # ----------------------------------------------------------------
    #  河床剖面
    # ----------------------------------------------------------------

    def _bed_profile_pts(self):
        """河床控制点 [(x, 深度), ...], 未给定时按水面深度自动生成"""
        if self.bed_profile:
            return [(float(a), float(b)) for a, b in self.bed_profile]
        L = self.total_length
        x0 = self.water_from if self.water_from is not None else L * 0.06
        x1 = self.water_to if self.water_to is not None else L * 0.87
        w = self.water_depth
        return [
            (x0, w + 5.0),
            (L * 0.20, w + 26.0),
            (L * 0.33, w + 40.0),
            (L * 0.49, w + 52.0),
            (L * 0.62, w + 47.0),
            (L * 0.73, w + 38.0),
            (x1, w + 5.0),
        ]

    def _bed_depth_at(self, x):
        """任意 x 处的河床深度 (Catmull-Rom 平滑插值)"""
        pts = self._bed_profile_pts()
        if x <= pts[0][0]:
            return pts[0][1]
        if x >= pts[-1][0]:
            return pts[-1][1]
        for i in range(len(pts) - 1):
            if pts[i][0] <= x <= pts[i + 1][0]:
                p0 = pts[max(i - 1, 0)]
                p1 = pts[i]
                p2 = pts[i + 1]
                p3 = pts[min(i + 2, len(pts) - 1)]
                t = (x - p1[0]) / (p2[0] - p1[0]) if p2[0] > p1[0] else 0.0
                t2, t3 = t * t, t * t * t
                v = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                           + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                           + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
                return v
        return pts[-1][1]

    def _calc_side_cable_count(self, span):
        """计算边跨拉索数量 (支持近塔段变距)"""
        if self.n_side_right_override is not None:
            return int(self.n_side_right_override)
        if self.d_deck_side_near_count <= 0:
            return max(1, int(span / self.d_deck_side))
        near_len = self.d_deck_side_near * self.d_deck_side_near_count
        if near_len >= span:
            return max(1, int(span / self.d_deck_side_near))
        rest = span - near_len
        return self.d_deck_side_near_count + max(1, int(rest / self.d_deck_side))

    @staticmethod
    def _parse_deck_pattern(pattern):
        """
        解析梁上索距模式字符串, 返回锚点距塔距离列表 (从近到远)。

        格式: "offset+n1*s1+n2*s2+...+end_gap"
        - offset: 塔根到第一根索的距离
        - n_i*s_i: 第i段, n_i个间距, 每个间距s_i米 (相邻段共用边界锚点)
        - end_gap: 最末索到跨端的距离

        例: "16+25*8+16" -> 26个锚点, 距塔 [16, 24, ..., 216]
        例: "15+11*5+14*4+4" -> 26个锚点, 距塔 [15, 20, ..., 70, 74, ..., 126]
        """
        s = pattern.replace(' ', '').replace('\u00d7', '*').replace('\uff0a', '*')
        parts = s.split('+')
        zones = []
        scalars = []
        for part in parts:
            if '*' in part:
                n_str, sp_str = part.split('*')
                zones.append((int(n_str), float(sp_str)))
            else:
                scalars.append(float(part))
        offset = scalars[0] if scalars else 0.0
        dists = []
        pos = offset
        for i, (n_int, sp) in enumerate(zones):
            if i == 0:
                for j in range(n_int + 1):
                    dists.append(offset + j * sp)
                pos = offset + n_int * sp
            else:
                for j in range(1, n_int + 1):
                    dists.append(pos + j * sp)
                pos = pos + n_int * sp
        return dists

    def _side_deck_distances(self, n_side):
        """边跨梁上锚点距塔距离列表 (从近到远)"""
        if self.side_deck_dists is not None:
            return self.side_deck_dists[:n_side]
        dists = []
        nc = self.d_deck_side_near_count
        for k in range(1, n_side + 1):
            if nc > 0 and k <= nc:
                d = k * self.d_deck_side_near
            else:
                d = nc * self.d_deck_side_near + (k - nc) * self.d_deck_side
            dists.append(d)
        return dists

    def _tower_anchor_ys(self, n):
        """塔上锚点高度列表 (从塔顶向下, 支持渐变索距), 返回 (y列表, 塔上索距列表)"""
        ys, ds = [], []
        y = self.tower_height
        for i in range(n):
            if n == 1:
                td = self.d_tower_max
            else:
                td = self.d_tower_max - (self.d_tower_max - self.d_tower_min) * i / (n - 1)
            y -= td
            if y <= 0:
                break
            ys.append(y)
            ds.append(td)
        return ys, ds

    def _calc_tower_cables(self, tower_x, n_main, n_side, dir_main, dir_side, side_kind=None):
        """
        计算一座索塔两侧所有拉索的锚点坐标。

        布置规则 (半扇形 semi-fan):
          - 第 i 根索 (i=0 最外/最长) 塔上锚点高度 = H - sum(d_tower(j)), 塔上索距可渐变
          - 主跨侧: 梁上锚点 = tower_x + dir_main * (n_main - i) * d_deck_main
          - 边跨侧: 梁上锚点按 _side_deck_distances (支持近塔段变距)
          - 最长索在塔顶, 最短索在塔底 (符合扇形布置规律)

        返回: [{'x1':deck_x, 'y1':deck_y, 'x2':tower_x, 'y2':tower_y, 'side':'main'/'side'}, ...]
        """
        cables = []
        n = max(n_main, n_side)
        anchor_ys, _ = self._tower_anchor_ys(n)
        side_dists = self._side_deck_distances(n_side)  # 从近到远, len=n_side
        for i, y_tower in enumerate(anchor_ys):
            # 主跨侧拉索
            if i < n_main:
                if self.main_deck_dists:
                    dist = self.main_deck_dists[n_main - 1 - i]  # i=0(塔顶)->最远索
                else:
                    dist = (n_main - i) * self.d_deck_main
                x_deck = tower_x + dir_main * dist
                cables.append({
                    'x1': x_deck, 'y1': 0.0,
                    'x2': tower_x, 'y2': y_tower,
                    'side': 'main'
                })

            # 边跨侧拉索
            if i < n_side:
                dist = side_dists[n_side - 1 - i]  # i=0(塔顶) 对应最远索
                x_deck = tower_x + dir_side * dist
                cables.append({
                    'x1': x_deck, 'y1': 0.0,
                    'x2': tower_x, 'y2': y_tower,
                    'side': side_kind if side_kind else 'side'
                })
        return cables

    # ================================================================
    #  汇总信息
    # ================================================================

    def get_summary(self):
        """返回桥梁参数汇总字典"""
        total_cables = len(self.cables_left) + len(self.cables_right)
        return {
            'single_tower': self.single_tower,
            'main_span': self.main_span,
            'side_span_left': self.side_span_left,
            'side_span_right': self.side_span_right,
            'total_length': self.total_length,
            'tower_height': round(self.tower_height, 2),
            'd_tower': self.d_tower,
            'd_tower_min': self.d_tower_min,
            'd_tower_max': self.d_tower_max,
            'd_deck_main': self.d_deck_main,
            'd_deck_side': self.d_deck_side,
            'd_deck_side_near': self.d_deck_side_near,
            'd_deck_side_near_count': self.d_deck_side_near_count,
            'n_main_per_tower': self.n_main,
            'n_side_left': self.n_side_left,
            'n_side_right': self.n_side_right,
            'total_cables': total_cables,
            'aux_piers': self.aux_piers,
            'warnings': self._warnings,
        }

    def _span_arrangement_text(self, s):
        """跨径布置文本: 独塔带辅助墩时 232+70+40+20"""
        def fmt(v):
            return "%.0f" % v if abs(v - round(v)) < 1e-6 else "%.1f" % v
        if self.single_tower:
            if self.aux_piers:
                xs = sorted([0.0, self.tower_x, self.total_length] + list(self.aux_piers))
                segs = []
                for i in range(len(xs) - 1):
                    if xs[i + 1] - xs[i] > 1e-6:
                        segs.append(fmt(xs[i + 1] - xs[i]))
                return "+".join(segs) + " = %.0f m" % self.total_length
            if self.main_side == 'right':
                return "%s + %s = %.0f m" % (fmt(self.side_span_left), fmt(self.main_span), self.total_length)
            return "%s + %s = %.0f m" % (fmt(self.main_span), fmt(self.side_span_right), self.total_length)
        return "%s + %s + %s = %.0f m" % (
            fmt(self.side_span_left), fmt(self.main_span), fmt(self.side_span_right), self.total_length)

    def get_summary_text(self):
        """返回可读的参数汇总文本"""
        s = self.get_summary()
        lines = [
            "===== 斜拉桥参数汇总 =====",
        ]
        if s['single_tower']:
            side_desc = "主跨右侧" if self.main_side == 'right' else "主跨左侧"
            lines += [
                "结构形式:       独塔斜拉桥",
                "跨径布置:       %s (%s)" % (self._span_arrangement_text(s), side_desc),
                "桥梁总长:       %.1f m" % s['total_length'],
                "索塔高度:       %.1f m (桥面以上)" % s['tower_height'],
            ]
        else:
            lines += [
                "结构形式:       双塔斜拉桥",
                "跨径布置:       %s" % self._span_arrangement_text(s),
                "桥梁总长:       %.1f m" % s['total_length'],
                "索塔高度:       %.1f m" % s['tower_height'],
            ]
        if s['aux_piers']:
            lines.append(
                "辅助墩位置:     %s (x=%.0f~%.0fm, 共%d座)"
                % (", ".join("x=%.1fm" % x for x in s['aux_piers']),
                   s['aux_piers'][0], s['aux_piers'][-1], len(s['aux_piers']))
            )
        tower_spacing = "%.2f m" % s['d_tower']
        if s['d_tower_min'] != s['d_tower_max']:
            tower_spacing = "%.2f ~ %.2f m (顶~底渐变)" % (s['d_tower_max'], s['d_tower_min'])
        lines += [
            "塔上索距:       %s" % tower_spacing,
        ]
        if self.deck_main_pattern:
            lines.append("梁上索距(主跨): %s (模式)" % self.deck_main_pattern)
        else:
            lines.append("梁上索距(主跨): %.2f m" % s['d_deck_main'])
        if self.deck_side_pattern:
            lines.append("梁上索距(边跨): %s (模式)" % self.deck_side_pattern)
        elif s['d_deck_side_near_count'] > 0:
            lines.append(
                "梁上索距(边跨): 近塔段%.0f对 x %.2fm, 其余 %.2f m"
                % (s['d_deck_side_near_count'], s['d_deck_side_near'], s['d_deck_side'])
            )
        else:
            lines.append("梁上索距(边跨): %.2f m" % s['d_deck_side'])
        if s['single_tower']:
            lines += [
                "主跨侧索数:     %d" % s['n_main_per_tower'],
                "边跨侧索数:     %d" % s['n_side_right'],
            ]
        else:
            lines += [
                "每塔主跨侧索数: %d" % s['n_main_per_tower'],
                "左塔边跨侧索数: %d" % s['n_side_left'],
                "右塔边跨侧索数: %d" % s['n_side_right'],
            ]
        lines.append("拉索总数:       %d" % s['total_cables'])
        if s['warnings']:
            lines.append("")
            lines.append("----- 校验警告 -----")
            for w in s['warnings']:
                lines.append("  * %s" % w)
        return "\n".join(lines)

    # ================================================================
    #  SVG 生成
    # ================================================================

    def generate_svg(self, output_path=None):
        """生成SVG字符串, 可选保存到文件"""

        # ---- 画布尺寸与缩放 ----
        margin_l = 90
        # 有索距模式时右边距加宽以容纳长字符串
        margin_r = 160 if (self.deck_main_pattern or self.deck_side_pattern) else 90
        if self.notes:
            mx = max(len(str(t)) for t in self.notes)
            margin_r = max(margin_r, int(mx * 12) + 40)
        margin_t, margin_b = 50, 110
        if self.dims_top:
            margin_t = 112          # 顶部留出跨径标注空间
        target_w, target_h = 1200, 700

        avail_w = target_w - margin_l - margin_r
        avail_h = target_h - margin_t - margin_b

        bridge_w = self.total_length
        # 竖向总高 = 塔高(桥面以上) + 桥面以下最大深度(墩/基础/河床)
        below = getattr(self, 'bottom_depth', self.pier_height)
        bridge_h = self.tower_height + below

        scale = min(avail_w / bridge_w, avail_h / bridge_h)

        svg_w = margin_l + bridge_w * scale + margin_r
        svg_h = margin_t + bridge_h * scale + margin_b

        # 桥面在SVG中的y坐标
        deck_y_svg = margin_t + self.tower_height * scale

        def tx(x):
            """桥梁x坐标 -> SVG x坐标"""
            return margin_l + x * scale

        def ty(y):
            """桥梁y坐标(向上为正) -> SVG y坐标(向下为正)"""
            return deck_y_svg - y * scale

        parts = []

        # ---- SVG 头 ----
        parts.append('<?xml version="1.0" encoding="UTF-8"?>')
        parts.append(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="%d" height="%d" viewBox="0 0 %d %d">'
            % (svg_w, svg_h, svg_w, svg_h)
        )

        # ---- defs: 箭头标记 ----
        parts.append('<defs>')
        parts.append(
            '<marker id="arr-e" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">'
            '<polygon points="0 0,8 3,0 6" fill="#3b82f6"/></marker>'
        )
        parts.append(
            '<marker id="arr-s" markerWidth="8" markerHeight="6" refX="1" refY="3" orient="auto">'
            '<polygon points="8 0,0 3,8 6" fill="#3b82f6"/></marker>'
        )
        parts.append(
            '<marker id="arr-k" markerWidth="7" markerHeight="5" refX="6" refY="2.5" orient="auto">'
            '<polygon points="0 0,7 2.5,0 5" fill="#1e293b"/></marker>'
        )
        parts.append('</defs>')

        # ---- 背景 ----
        parts.append('<rect width="%d" height="%d" fill="#ffffff"/>' % (svg_w, svg_h))

        # ---- 标题 ----
        parts.append(
            '<text x="%.0f" y="%d" text-anchor="middle" '
            'font-family="SimSun,SimHei,serif" font-size="18" font-weight="bold" fill="#1e293b">'
            '%s</text>' % (svg_w / 2, 22 if self.dims_top else 28, self.title)
        )

        # ---- 网格 (可选) ----
        if self.show_grid:
            grid_step = 10  # m
            n_steps = int(bridge_w / grid_step) + 1
            for i in range(n_steps + 1):
                gx = tx(i * grid_step)
                parts.append(
                    '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                    'stroke="#f1f5f9" stroke-width="0.5"/>' % (gx, margin_t, gx, svg_h - margin_b)
                )

        # ---- 基本线宽 ----
        lw_deck = max(2.0, scale * self.deck_thickness)
        lw_tower = max(3.0, scale * self.tower_width / 1.5)
        lw_cable = 0.9

        # 桁梁时以梁底(下弦)为墩顶起点, 单线时为桥面
        h_girder = self.deck_thickness if self.deck_mode == 'truss' else 0.0

        # ---- 地面线 / 河流 ----
        if self.river:
            self._svg_river(parts, scale, tx, ty)
        else:
            ground_y = ty(-self.pier_height)
            parts.append(
                '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                'stroke="#cbd5e1" stroke-width="1" stroke-dasharray="6,4"/>'
                % (tx(-5), ground_y, tx(self.total_length + 5), ground_y)
            )
            # 地面剖面线 (按像素间距自适应)
            hatch_px = 25  # 每隔约25像素一根
            n_hatch = int((tx(self.total_length) - tx(0)) / hatch_px) + 2
            for i in range(n_hatch):
                x_start = tx(0) + i * hatch_px
                parts.append(
                    '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                    'stroke="#cbd5e1" stroke-width="0.5"/>'
                    % (x_start, ground_y, x_start - 4, ground_y + 4)
                )

        # ---- 桥墩与桥台 ----
        pier_fill = '#e2e8f0'
        pier_stroke = '#94a3b8'

        def base_depth(x):
            """墩/基础底面深度: 指定则用指定值, 否则落在河床(或 pier_height)上"""
            if self.pier_base_depth is not None:
                return self.pier_base_depth
            if self.river:
                return max(self._bed_depth_at(x), self.water_depth + 2.0) + 6.0
            return self.pier_height

        # 塔墩 (独塔1座, 双塔2座)
        for t in self.towers:
            d = base_depth(t['x'])
            self._svg_pier(parts, t['x'], d, self.tower_width, scale, tx, ty,
                           pier_fill, pier_stroke, top_y=-h_girder,
                           cap=self.pier_cap and self.river)
        # 辅助墩 (边跨内)
        for ax in self.aux_piers:
            self._svg_pier(parts, ax, self.pier_height,
                           self.aux_pier_width, scale, tx, ty, pier_fill, pier_stroke,
                           top_y=-h_girder)
        # 桥台 (两端)
        self._svg_abutment(parts, 0, self.pier_height, scale, tx, ty, pier_fill, pier_stroke)
        self._svg_abutment(parts, self.total_length, self.pier_height, scale, tx, ty, pier_fill, pier_stroke)

        # ---- 桥面 (主梁) ----
        y_deck = ty(0)
        if self.deck_mode == 'truss':
            self._svg_truss(parts, scale, tx, ty, h_girder)
        else:
            parts.append(
                '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                'stroke="#1e293b" stroke-width="%.1f" stroke-linecap="round"/>'
                % (tx(0), y_deck, tx(self.total_length), y_deck, lw_deck)
            )

        # ---- 拉索 ----
        # 两端地名标注 (先画, 避免压住索)
        if self.end_labels:
            ly_txt = ty(0) - 30
            ly_ln = ty(0) - 16
            n_lab = len(self.end_labels)
            if n_lab >= 1 and self.end_labels[0]:
                x0 = tx(0)
                parts.append(
                    '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#1e293b" '
                    'stroke-width="1" marker-end="url(#arr-k)"/>' % (x0 + 74, ly_ln, x0 + 8, ly_ln)
                )
                parts.append(
                    '<text x="%.1f" y="%.1f" text-anchor="start" '
                    'font-family="SimSun,SimHei,serif" font-size="13" font-weight="bold" '
                    'fill="#334155">%s</text>' % (x0 + 8, ly_txt, self.end_labels[0])
                )
            if n_lab >= 2 and self.end_labels[1]:
                x1 = tx(self.total_length)
                parts.append(
                    '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#1e293b" '
                    'stroke-width="1" marker-end="url(#arr-k)"/>' % (x1 - 74, ly_ln, x1 - 8, ly_ln)
                )
                parts.append(
                    '<text x="%.1f" y="%.1f" text-anchor="end" '
                    'font-family="SimSun,SimHei,serif" font-size="13" font-weight="bold" '
                    'fill="#334155">%s</text>' % (x1 - 8, ly_txt, self.end_labels[1])
                )

        for t in self.towers:
            for c in t['cables']:
                x1, y1 = tx(c['x1']), ty(c['y1'])
                x2, y2 = tx(c['x2']), ty(c['y2'])
                color = '#64748b' if c['side'] == 'main' else '#94a3b8'
                parts.append(
                    '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                    'stroke="%s" stroke-width="%.1f"/>'
                    % (x1, y1, x2, y2, color, lw_cable)
                )
                # 锚点圆点
                parts.append('<circle cx="%.1f" cy="%.1f" r="2.5" fill="#475569"/>' % (x1, y1))
                parts.append('<circle cx="%.1f" cy="%.1f" r="2.5" fill="#475569"/>' % (x2, y2))

        # ---- 索塔 ----
        for t in self.towers:
            tower_x = t['x']
            x_bot, y_bot = tx(tower_x), ty(0)
            x_top, y_top = tx(tower_x), ty(self.tower_height)
            # 塔身
            parts.append(
                '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                'stroke="#1e293b" stroke-width="%.1f" stroke-linecap="round"/>'
                % (x_bot, y_bot, x_top, y_top, lw_tower)
            )
            # 塔顶标记
            parts.append('<circle cx="%.1f" cy="%.1f" r="3" fill="#1e293b"/>' % (x_top, y_top))
            # 塔底横梁 (与主梁的连接)
            cw = self.tower_width * scale * 0.8
            parts.append(
                '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                'stroke="#1e293b" stroke-width="2"/>'
                % (x_bot - cw / 2, y_bot, x_bot + cw / 2, y_bot)
            )

        # ---- 尺寸标注 ----
        if self.show_dimensions:
            self._add_dimensions(parts, tx, ty, scale, y_deck, svg_w, svg_h)

        # ---- 索数标注 ----
        if self.show_cable_count:
            if self.single_tower:
                parts.append(
                    '<text x="%.1f" y="%.1f" text-anchor="middle" '
                    'font-family="SimSun,SimHei,serif" font-size="11" fill="#64748b">'
                    '索塔: 主跨侧%d / 边跨侧%d'
                    '</text>' % (
                        tx(self.tower_x),
                        ty(self.tower_height) - 12,
                        self.n_main, self.n_side_right
                    )
                )
            else:
                parts.append(
                    '<text x="%.1f" y="%.1f" text-anchor="middle" '
                    'font-family="SimSun,SimHei,serif" font-size="11" fill="#64748b">'
                    '左塔: 主跨%d / 边跨%d'
                    '</text>' % (
                        tx(self.tower_left_x),
                        ty(self.tower_height) - 12,
                        self.n_main, self.n_side_left
                    )
                )
                parts.append(
                    '<text x="%.1f" y="%.1f" text-anchor="middle" '
                    'font-family="SimSun,SimHei,serif" font-size="11" fill="#64748b">'
                    '右塔: 主跨%d / 边跨%d'
                    '</text>' % (
                        tx(self.tower_right_x),
                        ty(self.tower_height) - 12,
                        self.n_main, self.n_side_right
                    )
                )

        # ---- 参数信息框 (右上角) ----
        tower_spacing = "%.1f" % self.d_tower
        if self.d_tower_min != self.d_tower_max:
            tower_spacing = "%.1f~%.1f" % (self.d_tower_max, self.d_tower_min)
        if self.aux_piers:
            info_span = self._span_arrangement_text(self.get_summary())
        elif self.single_tower:
            info_span = ("%.0f + %.0f m" % (self.side_span_left, self.main_span)
                         if self.main_side == 'right'
                         else "%.0f + %.0f m" % (self.main_span, self.side_span_right))
        else:
            info_span = "%.0f + %.0f + %.0f m" % (self.side_span_left, self.main_span, self.side_span_right)
        info_lines = [
            "跨径: %s" % info_span,
            "塔高: %.1fm" % self.tower_height,
            "塔上索距: %sm" % tower_spacing,
        ]
        if self.deck_main_pattern:
            info_lines.append("主跨索距: %sm" % self.deck_main_pattern)
        else:
            info_lines.append("主跨索距: %.1fm" % self.d_deck_main)
        if self.deck_side_pattern:
            info_lines.append("边跨索距: %sm" % self.deck_side_pattern)
        elif self.d_deck_side_near_count > 0:
            info_lines.append("边跨索距: %.0f×%d+%.1fm" % (
                self.d_deck_side_near, self.d_deck_side_near_count, self.d_deck_side))
        else:
            info_lines.append("边跨索距: %.1fm" % self.d_deck_side)
        info_lines.append("总索数: %d" % (len(self.cables_left) + len(self.cables_right)))
        if self.notes:
            info_lines += list(self.notes)
        box_x = svg_w - margin_r + 12
        box_y = margin_t + 5
        box_w = margin_r - 20
        box_h = len(info_lines) * 16 + 10
        # 背景框
        parts.append(
            '<rect x="%.1f" y="%.1f" width="%d" height="%d" '
            'fill="#f8fafc" stroke="#e2e8f0" stroke-width="0.5" rx="3"/>'
            % (box_x, box_y, box_w, box_h)
        )
        for idx, line in enumerate(info_lines):
            parts.append(
                '<text x="%.1f" y="%.1f" '
                'font-family="SimSun,SimHei,serif" font-size="11" fill="#475569">'
                '%s</text>' % (box_x + 6, box_y + 16 + idx * 16, line)
            )

        parts.append('</svg>')

        svg_str = '\n'.join(parts)

        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(svg_str)

        return svg_str

    # ================================================================
    #  SVG 辅助方法
    # ================================================================

    def _svg_pier(self, parts, center_x, height, width, scale, tx, ty, fill, stroke,
                  top_y=0.0, cap=False):
        """绘制桥墩 (top_y: 墩顶相对桥面的标高, 桁梁取 -梁高)"""
        x1 = tx(center_x - width / 2)
        x2 = tx(center_x + width / 2)
        y_top = ty(top_y)          # 墩顶 (y较小)
        y_bot = ty(top_y - height)  # 墩底 (y较大)
        h = y_bot - y_top           # 正值
        parts.append(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
            'fill="%s" stroke="%s" stroke-width="1" rx="1"/>'
            % (x1, y_top, x2 - x1, h, fill, stroke)
        )
        # 墩底扩展 (承台)
        parts.append(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="4" '
            'fill="%s" stroke="%s" stroke-width="1"/>'
            % (x1 - 2, y_bot - 4, x2 - x1 + 4, fill, stroke)
        )
        if cap:
            # 承台 + 桩基 (水中基础)
            cw = max(x2 - x1, 14.0) * 1.9
            ch = max(9.0, 4.0 * scale)
            cx = (x1 + x2) / 2
            parts.append(
                '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                'fill="#dbe4ee" stroke="%s" stroke-width="1"/>'
                % (cx - cw / 2, y_bot, cw, ch, stroke)
            )
            n_p = 4
            pw = cw / (2.0 * n_p)
            for i in range(n_p):
                px = cx - cw / 2 + cw * (2 * i + 1) / (2.0 * n_p)
                parts.append(
                    '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                    'fill="#eef2f7" stroke="%s" stroke-width="0.8"/>'
                    % (px - pw / 2, y_bot + ch, pw, max(8.0, 3.5 * scale), stroke)
                )

    def _svg_truss(self, parts, scale, tx, ty, h):
        """桁梁: 上弦 + 下弦 + 竖杆 + 交替斜腹杆"""
        L = self.total_length
        y_ut = ty(0)
        y_lb = ty(-h)
        ch_w = max(1.4, 0.9 * scale)      # 弦杆粗线宽
        web_w = max(0.7, 0.45 * scale)    # 腹杆线宽
        parts.append(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#1e293b" '
            'stroke-width="%.1f" stroke-linecap="round"/>'
            % (tx(0), y_ut, tx(L), y_ut, ch_w)
        )
        parts.append(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#1e293b" '
            'stroke-width="%.1f" stroke-linecap="round"/>'
            % (tx(0), y_lb, tx(L), y_lb, ch_w)
        )
        p = self.truss_panels
        if p <= 0:
            return
        n = int(round(L / p))
        for i in range(n + 1):
            x = i * p
            if i < n:
                # 斜腹杆 (交替方向)
                xa, xb = x, x + p
                if i % 2 == 0:
                    x1, y1, x2, y2 = tx(xa), y_ut, tx(xb), y_lb
                else:
                    x1, y1, x2, y2 = tx(xa), y_lb, tx(xb), y_ut
                parts.append(
                    '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#64748b" '
                    'stroke-width="%.1f"/>' % (x1, y1, x2, y2, web_w)
                )
            if self.truss_verticals and i <= n:
                parts.append(
                    '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#94a3b8" '
                    'stroke-width="%.1f"/>' % (tx(x), y_ut, tx(x), y_lb, web_w)
                )

    def _svg_river(self, parts, scale, tx, ty):
        """水面线 + 河床曲线 (+ 名称标注)"""
        L = self.total_length
        x0 = self.water_from if self.water_from is not None else L * 0.06
        x1 = self.water_to if self.water_to is not None else L * 0.87

        # 河床曲线
        pts = self._bed_profile_pts()
        xs0, xs1 = max(0.0, pts[0][0] - L * 0.04), min(L, pts[-1][0] + L * 0.04)
        n = 80
        poly = []
        for i in range(n + 1):
            x = xs0 + (xs1 - xs0) * i / n
            poly.append("%.1f,%.1f" % (tx(x), ty(-self._bed_depth_at(x))))
        parts.append(
            '<polyline points="%s" fill="none" stroke="#94a3b8" '
            'stroke-width="1.1"/>' % " ".join(poly)
        )
        # 河床下填充 (极浅灰)
        fill_poly = list(poly) + ["%.1f,%.1f" % (tx(xs1), ty(-self.bottom_depth)),
                                  "%.1f,%.1f" % (tx(xs0), ty(-self.bottom_depth))]
        parts.append(
            '<polygon points="%s" fill="#f8fafc" stroke="none"/>' % " ".join(fill_poly)
        )

        # 水面线
        wy = ty(-self.water_depth)
        parts.append(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#38bdf8" '
            'stroke-width="1.4" stroke-dasharray="14,4,3,4"/>'
            % (tx(x0), wy, tx(x1), wy)
        )
        if self.river_labels:
            parts.append(
                '<text x="%.1f" y="%.1f" font-family="SimSun,SimHei,serif" '
                'font-size="11" fill="#0284c7">水面</text>' % (tx(x1) + 6, wy + 4)
            )
            xm = self._bed_profile_pts()[len(self._bed_profile_pts()) // 2][0]
            parts.append(
                '<text x="%.1f" y="%.1f" font-family="SimSun,SimHei,serif" '
                'font-size="11" fill="#64748b">河床</text>'
                % (tx(xm), ty(-self._bed_depth_at(xm)) + 14)
            )

    def _svg_abutment(self, parts, x, height, scale, tx, ty, fill, stroke):
        """绘制桥台"""
        w = 4 * scale
        cx = tx(x)
        y_top = ty(0)
        y_bot = ty(-height)
        h = y_bot - y_top
        parts.append(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
            'fill="%s" stroke="%s" stroke-width="1"/>'
            % (cx - w / 2, y_top, w, h, fill, stroke)
        )

    def _add_dimensions(self, parts, tx, ty, scale, y_deck, svg_w, svg_h):
        """添加尺寸标注"""

        dim_color = '#3b82f6'
        txt_color = '#1d4ed8'
        if self.dims_top:
            # 标注置于图幅顶部 (塔顶以上), 与原图排版一致
            dim_y1 = 68            # 分跨标注线
            dim_y2 = 40            # 主桥全长标注线
            ext_top = 30           # 延伸线上端
            ext_bot = y_deck + 5   # 延伸线下端 (到桥面)
        else:
            dim_y1 = y_deck + 30   # 跨径标注线y
            dim_y2 = y_deck + 55   # 总长标注线y
            ext_top = y_deck + 5   # 延伸线起点
            ext_bot = y_deck + 60  # 延伸线终点

        # 延伸线 (各跨分界点: 端点/索塔/辅助墩)
        boundary_xs = [0, self.total_length]
        if self.single_tower:
            boundary_xs.append(self.tower_x)
        else:
            boundary_xs += [self.tower_left_x, self.tower_right_x]
        boundary_xs += self.aux_piers
        boundary_xs = sorted(set(round(x, 6) for x in boundary_xs))
        for x in boundary_xs:
            parts.append(
                '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                'stroke="%s" stroke-width="0.5" stroke-dasharray="3,2"/>'
                % (tx(x), ext_top, tx(x), ext_bot, dim_color)
            )

        # 各跨尺寸 (相邻分界点之间)
        for i in range(len(boundary_xs) - 1):
            xa, xb = boundary_xs[i], boundary_xs[i + 1]
            if xb - xa < 1e-6:
                continue
            seg = xb - xa
            label = "%.0f" % seg if abs(seg - round(seg)) < 1e-6 else "%.1f" % seg
            self._dim_h(parts, tx(xa), dim_y1, tx(xb), dim_y1,
                         label, dim_color, txt_color)
        # 总长
        self._dim_h(parts, tx(0), dim_y2, tx(self.total_length), dim_y2,
                     "L = %.0f m" % self.total_length, dim_color, txt_color)

        # 索塔x坐标 (塔高/索距标注共用)
        tower_x = self.tower_x if self.single_tower else self.tower_left_x

        # 塔高标注 (塔左侧)
        if self.show_tower_h_dim:
            dim_x = tx(tower_x) - 35
            parts.append(
                '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                'stroke="%s" stroke-width="0.5" stroke-dasharray="3,2"/>'
                % (dim_x, ty(0), dim_x, ty(self.tower_height), dim_color)
            )
            self._dim_v(parts, dim_x, ty(self.tower_height), dim_x, ty(0),
                         "H = %.1f m" % self.tower_height, dim_color, txt_color)

        # 塔上索距标注 (取最上方两根索的锚点间距, 支持渐变)
        if self.show_spacing_dims:
            n_max = max(self.n_cables_left, self.n_cables_right)
            if n_max >= 2:
                anchor_ys, anchor_ds = self._tower_anchor_ys(n_max)
                if len(anchor_ds) >= 2:
                    y_a = ty(anchor_ys[0])
                    y_b = ty(anchor_ys[1])
                    dx = tx(tower_x) + 25
                    label = "%.1f" % anchor_ds[0]
                    if self.d_tower_min != self.d_tower_max:
                        label = "%.1f~%.1f" % (self.d_tower_max, self.d_tower_min)
                    self._dim_v(parts, dx, y_a, dx, y_b, label, dim_color, txt_color, small=True)

            # 梁上索距标注 (主跨, 塔侧最近两根索之间)
            if self.n_main >= 2:
                if self.single_tower:
                    sign = +1 if self.main_side == 'right' else -1
                else:
                    sign = +1   # 双塔: 左塔的主跨侧在其右侧
                if self.main_deck_dists:
                    d0 = self.main_deck_dists[0]
                    d1 = self.main_deck_dists[1]
                    xa = tx(tower_x + sign * d0)
                    xb = tx(tower_x + sign * d1)
                    label = "%.1f" % (d1 - d0)
                else:
                    xa = tx(tower_x + sign * 2 * self.d_deck_main)
                    xb = tx(tower_x + sign * self.d_deck_main)
                    label = "%.1f" % self.d_deck_main
                dy = y_deck - 12
                self._dim_h(parts, xa, dy, xb, dy,
                             label, dim_color, txt_color, small=True)

    def _dim_h(self, parts, x1, y, x2, y2, text, color, txt_color, small=False):
        """水平尺寸标注"""
        parts.append(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
            'stroke="%s" stroke-width="0.8" '
            'marker-start="url(#arr-s)" marker-end="url(#arr-e)"/>'
            % (x1, y, x2, y2, color)
        )
        fs = 9 if small else 11
        parts.append(
            '<text x="%.1f" y="%.1f" text-anchor="middle" '
            'font-family="SimSun,SimHei,serif" font-size="%d" fill="%s">%s</text>'
            % ((x1 + x2) / 2, y - 4, fs, txt_color, text)
        )

    def _dim_v(self, parts, x, y1, x2, y2, text, color, txt_color, small=False):
        """垂直尺寸标注"""
        parts.append(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
            'stroke="%s" stroke-width="0.8" '
            'marker-start="url(#arr-s)" marker-end="url(#arr-e)"/>'
            % (x, y1, x, y2, color)
        )
        fs = 9 if small else 11
        parts.append(
            '<text x="%.1f" y="%.1f" text-anchor="end" '
            'font-family="SimSun,SimHei,serif" font-size="%d" fill="%s" '
            'transform="rotate(-90 %.1f %.1f)">%s</text>'
            % (x - 4, (y1 + y2) / 2, fs, txt_color, x - 4, (y1 + y2) / 2, text)
        )


# ================================================================
#  命令行入口
# ================================================================

def main():
    parser = argparse.ArgumentParser(
        description='斜拉桥立面草图生成器 - 根据跨径和拉索间距生成SVG草图'
    )
    parser.add_argument('--main-span', type=float, default=None,
                        help='主跨跨径 (m)')
    parser.add_argument('--side-span', type=float, default=None,
                        help='边跨跨径 (m), 左右对称时使用')
    parser.add_argument('--side-span-left', type=float, default=None,
                        help='左边跨跨径 (m)')
    parser.add_argument('--side-span-right', type=float, default=None,
                        help='右边跨跨径 (m)')
    parser.add_argument('--tower-height', type=float, default=None,
                        help='索塔高度 (m), 不指定则自动计算')
    parser.add_argument('--d-tower', type=float, default=None,
                        help='塔上拉索间距 (m)')
    parser.add_argument('--d-tower-min', type=float, default=None,
                        help='塔上拉索间距下限(底部), 与--d-tower-max配合实现渐变 (m)')
    parser.add_argument('--d-tower-max', type=float, default=None,
                        help='塔上拉索间距上限(顶部) (m)')
    parser.add_argument('--d-deck', type=float, default=None,
                        help='梁上拉索间距 (m), 主跨边跨相同时使用')
    parser.add_argument('--d-deck-main', type=float, default=None,
                        help='主跨梁上拉索间距 (m)')
    parser.add_argument('--d-deck-side', type=float, default=None,
                        help='边跨梁上拉索间距 (m)')
    parser.add_argument('--d-deck-side-near', type=float, default=None,
                        help='边跨近塔段梁上拉索间距 (m)')
    parser.add_argument('--d-deck-side-near-count', type=int, default=None,
                        help='边跨近塔段索对数 (与--d-deck-side-near配合实现变距)')
    parser.add_argument('--deck-main-pattern', type=str, default=None,
                        help='主跨梁上索距模式, 如 "16+25*8+16" (offset+间距数*间距+末端)')
    parser.add_argument('--deck-side-pattern', type=str, default=None,
                        help='边跨梁上索距模式, 如 "15+11*5+14*4+4"')
    parser.add_argument('--n-main', type=int, default=None,
                        help='主跨侧拉索数量 (覆盖自动计算)')
    parser.add_argument('--n-side-right', type=int, default=None,
                        help='边跨侧拉索数量 (覆盖自动计算, 独塔模式右侧)')
    parser.add_argument('--n-side-left', type=int, default=None,
                        help='左边跨侧拉索数量 (覆盖自动计算, 双塔模式)')
    parser.add_argument('--deck-mode', type=str, default=None, choices=['line', 'truss'],
                        help='主梁形式: line=单线粗线(默认), truss=桁梁(上下弦+腹杆)')
    parser.add_argument('--truss', action='store_true',
                        help='等价于 --deck-mode truss')
    parser.add_argument('--truss-panels', type=float, default=None,
                        help='桁架节间长度 (m), 默认8.0')
    parser.add_argument('--deck-thickness', type=float, default=None,
                        help='主梁高度 (m): 单线模式=粗线宽, 桁梁模式=桁高')
    parser.add_argument('--river', action='store_true',
                        help='画水面线 + 河床曲线 (替代地面线)')
    parser.add_argument('--water-depth', type=float, default=None,
                        help='水面在桥面以下深度 (m)')
    parser.add_argument('--water-from', type=float, default=None,
                        help='水面线起点绝对x (m)')
    parser.add_argument('--water-to', type=float, default=None,
                        help='水面线终点绝对x (m)')
    parser.add_argument('--bed-profile', type=str, default=None,
                        help='河床控制点 "x1:d1,x2:d2,..." (绝对x:桥面以下深度 m)')
    parser.add_argument('--pier-base-depth', type=float, default=None,
                        help='塔/墩基础底面深度 (桥面以下 m), 默认落在河床上')
    parser.add_argument('--no-pier-cap', action='store_true',
                        help='不画承台与桩基')
    parser.add_argument('--notes', type=str, default=None,
                        help='说明条附加文字, 分号分隔')
    parser.add_argument('--end-labels', type=str, default=None,
                        help='两端地名标注, 分号分隔两个 (如 "南岸区;渝中区")')
    parser.add_argument('--aux-piers', type=str, default=None,
                        help='辅助墩绝对x坐标, 逗号分隔, 如 "302,342"')
    parser.add_argument('--aux-pier-spans', type=str, default=None,
                        help='独塔模式边跨分段跨径(从塔向外), 逗号分隔, 如 "70,40,20" (自动换算墩位)')
    parser.add_argument('--aux-pier-width', type=float, default=2.5,
                        help='辅助墩显示宽度 (m), 默认2.5')
    parser.add_argument('--single-tower', action='store_true',
                        help='独塔模式: 塔位于主跨与边跨交界')
    parser.add_argument('--main-side', type=str, default=None, choices=['left', 'right'],
                        help='独塔模式主跨位置: left=主跨在左/边跨在右(默认), right=主跨在右/边跨在左')
    parser.add_argument('--tower-width', type=float, default=3.0,
                        help='塔身宽度 (m), 默认3.0')
    parser.add_argument('--pier-height', type=float, default=12.0,
                        help='桥墩高度 (m), 默认12.0')
    parser.add_argument('--title', type=str, default=None,
                        help='图纸标题')
    parser.add_argument('--preset', type=str, default=None,
                        help='实桥预设: %s' % '/'.join(sorted(PRESETS)))
    parser.add_argument('--show-grid', action='store_true',
                        help='显示网格')
    parser.add_argument('--no-tower-h-dim', action='store_true',
                        help='取消塔高标注')
    parser.add_argument('--no-spacing-dims', action='store_true',
                        help='取消索距标注 (塔上/梁上)')
    parser.add_argument('--dims-top', action='store_true',
                        help='跨径/全长标注置于图幅顶部 (塔顶以上), 原图排版')
    parser.add_argument('--output', '-o', type=str, default='bridge_sketch.svg',
                        help='输出SVG文件路径')
    parser.add_argument('--json', type=str, default=None,
                        help='从JSON文件读取参数')
    parser.add_argument('--json-str', type=str, default=None,
                        help='从JSON字符串读取参数')
    parser.add_argument('--stdin', action='store_true',
                        help='从标准输入读取JSON参数')

    args = parser.parse_args()

    # 收集参数
    if args.json:
        with open(args.json, 'r', encoding='utf-8') as f:
            params = json.load(f)
    elif args.json_str:
        params = json.loads(args.json_str)
    elif args.stdin:
        params = json.loads(sys.stdin.read())
    else:
        if args.preset:
            if args.preset not in PRESETS:
                print('未知预设: %s, 可用预设: %s' % (args.preset, ', '.join(sorted(PRESETS))))
                sys.exit(1)
            params = json.loads(json.dumps(PRESETS[args.preset]))
        else:
            params = {}
        if args.main_span is not None:
            params['main_span'] = args.main_span
        if args.side_span is not None:
            params['side_span'] = args.side_span
        if args.side_span_left is not None:
            params['side_span_left'] = args.side_span_left
        if args.side_span_right is not None:
            params['side_span_right'] = args.side_span_right
        if args.tower_height is not None:
            params['tower_height'] = args.tower_height
        if args.d_tower is not None:
            params['d_tower'] = args.d_tower
        if args.d_tower_min is not None:
            params['d_tower_min'] = args.d_tower_min
        if args.d_tower_max is not None:
            params['d_tower_max'] = args.d_tower_max
        if args.d_deck is not None:
            params['d_deck'] = args.d_deck
        if args.d_deck_main is not None:
            params['d_deck_main'] = args.d_deck_main
        if args.d_deck_side is not None:
            params['d_deck_side'] = args.d_deck_side
        if args.d_deck_side_near is not None:
            params['d_deck_side_near'] = args.d_deck_side_near
        if args.d_deck_side_near_count is not None:
            params['d_deck_side_near_count'] = args.d_deck_side_near_count
        if args.deck_main_pattern is not None:
            params['deck_main_pattern'] = args.deck_main_pattern
        if args.deck_side_pattern is not None:
            params['deck_side_pattern'] = args.deck_side_pattern
        if args.n_main is not None:
            params['n_main'] = args.n_main
        if args.n_side_right is not None:
            params['n_side_right'] = args.n_side_right
        if args.n_side_left is not None:
            params['n_side_left'] = args.n_side_left
        if args.deck_mode is not None:
            params['deck_mode'] = args.deck_mode
        if args.truss:
            params['deck_mode'] = 'truss'
        if args.truss_panels is not None:
            params['truss_panels'] = args.truss_panels
        if args.deck_thickness is not None:
            params['deck_thickness'] = args.deck_thickness
        if args.river:
            params['river'] = True
        if args.water_depth is not None:
            params['water_depth'] = args.water_depth
        if args.water_from is not None:
            params['water_from'] = args.water_from
        if args.water_to is not None:
            params['water_to'] = args.water_to
        if args.bed_profile:
            pts = []
            for seg in args.bed_profile.split(','):
                if not seg.strip():
                    continue
                a, b = seg.split(':')
                pts.append([float(a), float(b)])
            params['bed_profile'] = pts
        if args.pier_base_depth is not None:
            params['pier_base_depth'] = args.pier_base_depth
        if args.no_pier_cap:
            params['pier_cap'] = False
        if args.notes:
            params['notes'] = [t for t in args.notes.split(';') if t.strip()]
        if args.end_labels:
            params['end_labels'] = [t for t in args.end_labels.split(';') if t.strip()]
        if args.aux_piers is not None:
            params['aux_piers'] = [float(v) for v in args.aux_piers.split(',') if v.strip()]
        if args.aux_pier_spans is not None:
            params['aux_pier_spans'] = [float(v) for v in args.aux_pier_spans.split(',') if v.strip()]
        if args.aux_pier_width != 2.5:
            params['aux_pier_width'] = args.aux_pier_width
        if args.single_tower:
            params['single_tower'] = True
        if args.main_side:
            params['main_side'] = args.main_side
        if args.tower_width != 3.0:
            params['tower_width'] = args.tower_width
        if args.pier_height != 12.0:
            params['pier_height'] = args.pier_height
        if args.title:
            params['title'] = args.title
        if args.show_grid:
            params['show_grid'] = True
        if args.no_tower_h_dim:
            params['show_tower_h_dim'] = False
        if args.no_spacing_dims:
            params['show_spacing_dims'] = False
        if args.dims_top:
            params['dims_top'] = True

    if not params:
        parser.print_help()
        sys.exit(1)

    # 创建桥梁对象
    bridge = CableStayedBridge(**params)

    # 输出汇总
    print(bridge.get_summary_text())
    print()

    # 生成SVG
    svg_path = args.output
    bridge.generate_svg(output_path=svg_path)
    print("SVG已生成: %s" % os.path.abspath(svg_path))


if __name__ == '__main__':
    main()
